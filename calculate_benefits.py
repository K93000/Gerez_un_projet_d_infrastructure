import json
import os

import pandas as pd
import psycopg2
from sqlalchemy import create_engine

from commute_validator import (
    get_commute_distance,
    init_distance_cache_table,
    normalize_transport_mode,
)
from config import Config


# ============================================================
# 1. INITIALISATION ET CONNEXIONS À LA BASE DE DONNÉES
# ============================================================

print("🔌 Connexion à PostgreSQL...")

# Connexion Psycopg2 pour les opérations DDL / DML directes
conn = psycopg2.connect(**Config.get_db_params())
init_distance_cache_table(conn)

# Moteur SQLAlchemy pour la lecture fluide avec Pandas
db_url = f"postgresql://{Config.DB_USER}:{Config.DB_PASSWORD}@{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
engine = create_engine(db_url)

print("✅ Connexion PostgreSQL réussie.")


# ============================================================
# 2. CHARGEMENT ET VERSIONING DES RÈGLES MÉTIER
# ============================================================

print("📋 Chargement des règles métier...")

with conn.cursor() as cur:

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dim_business_rules (
            rule_id SERIAL PRIMARY KEY,
            version VARCHAR(10) NOT NULL,
            prime_rate NUMERIC(4,3) NOT NULL,
            min_activities_wellness INT NOT NULL,
            wellness_days INT NOT NULL,
            max_walk_dist_km NUMERIC(4,1) NOT NULL,
            max_bike_dist_km NUMERIC(4,1) NOT NULL,
            valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE
        );
        """
    )

    cur.execute(
        """
        SELECT COUNT(*)
        FROM dim_business_rules;
        """
    )

    rules_count = cur.fetchone()[0]

    if rules_count == 0:

        cur.execute(
            """
            INSERT INTO dim_business_rules (
                version,
                prime_rate,
                min_activities_wellness,
                wellness_days,
                max_walk_dist_km,
                max_bike_dist_km
            )
            VALUES (
                'v1.0',
                0.050,
                15,
                5,
                15.0,
                25.0
            );
            """
        )

    conn.commit()


df_rules = pd.read_sql(
    """
    SELECT *
    FROM dim_business_rules
    WHERE is_active = TRUE
    ORDER BY rule_id DESC
    LIMIT 1;
    """,
    engine,
)

if df_rules.empty:
    raise RuntimeError(
        "❌ Aucune règle métier active dans dim_business_rules."
    )

active_rule = df_rules.iloc[0]

RULE_ID = int(active_rule["rule_id"])
RULE_VERSION = active_rule["version"]
PRIME_RATE = float(active_rule["prime_rate"])
MIN_ACTIVITIES = int(active_rule["min_activities_wellness"])
WELLNESS_DAYS = int(active_rule["wellness_days"])
MAX_WALK_KM = float(active_rule["max_walk_dist_km"])
MAX_BIKE_KM = float(active_rule["max_bike_dist_km"])

print(f"✅ Règles actives : {RULE_VERSION}")


# Prise en compte de la boîte de dialogue Kestra si renseignée
# (surcharge en mémoire uniquement, pour les scénarios de démo :
# la règle versionnée en base reste inchangée tant qu'on ne fait
# pas un nouvel INSERT explicite dans dim_business_rules)
override_rate = os.getenv("OVERRIDE_PRIME_RATE")
if override_rate:
    PRIME_RATE = float(override_rate)
    print(f"⚡ Taux de prime surchargé depuis Kestra UI : {PRIME_RATE * 100:.1f}%")


# ============================================================
# 3. EXTRACTION DES DONNÉES RH
# ============================================================

print("📥 Chargement des données RH...")

df_rh = pd.read_excel(Config.RH_FILE_PATH)

df_rh.columns = df_rh.columns.str.strip()

required_rh_columns = [
    "ID salarié",
    "Prénom",
    "Nom",
    "Salaire brut",
    "Moyen de déplacement",
    "Adresse du domicile",
]

missing_columns = [
    column
    for column in required_rh_columns
    if column not in df_rh.columns
]

if missing_columns:
    raise RuntimeError(
        "❌ Colonnes RH manquantes : "
        + ", ".join(missing_columns)
    )

df_rh["moyen_deplacement_canonique"] = (
    df_rh["Moyen de déplacement"]
    .apply(normalize_transport_mode)
)

print(f"✅ {len(df_rh)} salariés chargés.")


# ============================================================
# 4. EXTRACTION DES ACTIVITÉS SPORTIVES
# ============================================================

print("🏃 Chargement des activités sportives...")

df_activities = pd.read_sql(
    """
    SELECT
        employee_id,
        start_date,
        sport_type,
        distance_m,
        elapsed_time_s
    FROM strava_activities
    WHERE start_date >= CURRENT_TIMESTAMP - INTERVAL '12 months';
    """,
    engine,
)

print(f"✅ {len(df_activities)} activités sportives chargées.")


# ============================================================
# 5. CALCUL DU NOMBRE D'ACTIVITÉS PAR SALARIÉ
# ============================================================

activity_counts = (
    df_activities
    .groupby("employee_id")
    .size()
    .reset_index(name="nb_activites")
)

df = df_rh.merge(
    activity_counts,
    left_on="ID salarié",
    right_on="employee_id",
    how="left",
)

df["nb_activites"] = (
    df["nb_activites"]
    .fillna(0)
    .astype(int)
)


# ============================================================
# 6. CALCUL DES JOURS BIEN-ÊTRE
# ============================================================

df["eligible_jours_bien_etre"] = (
    df["nb_activites"] >= MIN_ACTIVITIES
)

df["jours_bien_etre"] = (
    df["eligible_jours_bien_etre"]
    .apply(
        lambda eligible: WELLNESS_DAYS
        if eligible
        else 0
    )
)


# ============================================================
# 7. AUDIT DES DÉPLACEMENTS ET CALCUL DE LA PRIME
# ============================================================

print("🚗 Audit des distances domicile-travail...")

audit_results = []

for _, row in df.iterrows():

    employee_id = row["ID salarié"]

    transport_mode = row[
        "moyen_deplacement_canonique"
    ]

    address = row[
        "Adresse du domicile"
    ]

    max_allowed_distance = (
        MAX_WALK_KM
        if transport_mode == "Marche/running"
        else (
            MAX_BIKE_KM
            if transport_mode == "Vélo/Trottinette/Autres"
            else None
        )
    )

    # Mode de transport non éligible à la prime
    if max_allowed_distance is None:

        audit_results.append(
            {
                "employee_id": employee_id,
                "distance_km": None,
                "distance_max_km": None,
                "distance_valid": False,
                "eligible_prime": False,
                "anomaly_reason": (
                    "Mode de transport non éligible"
                ),
            }
        )

        continue

    distance_km = get_commute_distance(
        conn,
        address,
        transport_mode,
    )

    # Distance impossible à calculer
    if distance_km is None:

        audit_results.append(
            {
                "employee_id": employee_id,
                "distance_km": None,
                "distance_max_km": max_allowed_distance,
                "distance_valid": False,
                "eligible_prime": False,
                "anomaly_reason": (
                    "Distance non vérifiée "
                    "(erreur API ou adresse invalide)"
                ),
            }
        )

    # Distance conforme
    elif distance_km <= max_allowed_distance:

        audit_results.append(
            {
                "employee_id": employee_id,
                "distance_km": distance_km,
                "distance_max_km": max_allowed_distance,
                "distance_valid": True,
                "eligible_prime": True,
                "anomaly_reason": None,
            }
        )

    # Distance supérieure au seuil
    else:

        audit_results.append(
            {
                "employee_id": employee_id,
                "distance_km": distance_km,
                "distance_max_km": max_allowed_distance,
                "distance_valid": False,
                "eligible_prime": False,
                "anomaly_reason": (
                    f"Distance ({distance_km:.1f} km) "
                    f"> seuil maximum "
                    f"({max_allowed_distance:.1f} km)"
                ),
            }
        )


df_audit = pd.DataFrame(audit_results)

df = df.merge(
    df_audit,
    left_on="ID salarié",
    right_on="employee_id",
    how="left",
)


# ============================================================
# 8. CALCUL DU COÛT DE LA PRIME
# ============================================================

salary_column = "Salaire brut"

df[salary_column] = pd.to_numeric(
    df[salary_column],
    errors="coerce",
).fillna(0)

df["cout_prime"] = (
    df[salary_column]
    * PRIME_RATE
    * df["eligible_prime"].fillna(False)
)


# ============================================================
# 9. CRÉATION DE LA TABLE DES BÉNÉFICES
# ============================================================

print("💾 Synchronisation de la table employee_benefits...")

with conn.cursor() as cur:

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_benefits (
            employee_id INT,
            rule_id INT,
            rule_version VARCHAR(10),
            prenom VARCHAR(100),
            nom VARCHAR(100),
            salaire_annuel NUMERIC,
            moyen_deplacement VARCHAR(100),
            distance_km NUMERIC,
            distance_max_km NUMERIC,
            distance_valid BOOLEAN,
            anomaly_reason TEXT,
            nb_activites INT,
            eligible_prime BOOLEAN,
            cout_prime NUMERIC,
            eligible_jours_bien_etre BOOLEAN,
            jours_bien_etre INT,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (employee_id, rule_version)
        );
        """
    )

    upsert_query = """
        INSERT INTO employee_benefits (
            employee_id,
            rule_id,
            rule_version,
            prenom,
            nom,
            salaire_annuel,
            moyen_deplacement,
            distance_km,
            distance_max_km,
            distance_valid,
            anomaly_reason,
            nb_activites,
            eligible_prime,
            cout_prime,
            eligible_jours_bien_etre,
            jours_bien_etre
        )
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (
            employee_id,
            rule_version
        )
        DO UPDATE SET
            rule_id = EXCLUDED.rule_id,
            prenom = EXCLUDED.prenom,
            nom = EXCLUDED.nom,
            salaire_annuel = EXCLUDED.salaire_annuel,
            moyen_deplacement = EXCLUDED.moyen_deplacement,
            distance_km = EXCLUDED.distance_km,
            distance_max_km = EXCLUDED.distance_max_km,
            distance_valid = EXCLUDED.distance_valid,
            anomaly_reason = EXCLUDED.anomaly_reason,
            nb_activites = EXCLUDED.nb_activites,
            eligible_prime = EXCLUDED.eligible_prime,
            cout_prime = EXCLUDED.cout_prime,
            eligible_jours_bien_etre = EXCLUDED.eligible_jours_bien_etre,
            jours_bien_etre = EXCLUDED.jours_bien_etre,
            calculated_at = CURRENT_TIMESTAMP;
    """

    for _, row in df.iterrows():

        cur.execute(
            upsert_query,
            (
                int(row["ID salarié"]),
                RULE_ID,
                RULE_VERSION,
                row["Prénom"],
                row["Nom"],
                float(row[salary_column]),
                row["moyen_deplacement_canonique"],
                (
                    float(row["distance_km"])
                    if pd.notna(row["distance_km"])
                    else None
                ),
                (
                    float(row["distance_max_km"])
                    if pd.notna(row["distance_max_km"])
                    else None
                ),
                bool(row["distance_valid"]),
                row["anomaly_reason"],
                int(row["nb_activites"]),
                bool(row["eligible_prime"]),
                float(row["cout_prime"]),
                bool(row["eligible_jours_bien_etre"]),
                int(row["jours_bien_etre"]),
            ),
        )

    conn.commit()


# ============================================================
# 10. FERMETURE DE LA CONNEXION
# ============================================================

conn.close()


# ============================================================
# 11. RAPPORT FINAL
# ============================================================

print()
print("=" * 65)
print(
    f"📊 RAPPORT FINANCIER POC "
    f"(Règles {RULE_VERSION} / ID {RULE_ID})"
)
print("=" * 65)

print(
    f"👥 Effectif total : {len(df)}"
)

print(
    f"🏃 Salariés éligibles à la prime "
    f"({int(PRIME_RATE * 100)} %) : "
    f"{int(df['eligible_prime'].sum())}"
)

print(
    f"💶 Coût total des primes : "
    f"{df['cout_prime'].sum():,.2f} €"
)

print(
    "🧘 Salariés éligibles aux jours bien-être : "
    f"{int(df['eligible_jours_bien_etre'].sum())}"
)

print(
    "📅 Total des jours bien-être accordés : "
    f"{int(df['jours_bien_etre'].sum())} jours"
)

print("=" * 65)

print(
    "✅ Table PostgreSQL "
    "'employee_benefits' synchronisée."
)

print(
    "✅ L'historique est conservé grâce à la clé "
    "(employee_id, rule_version)."
)


# ============================================================
# 12. SORTIE KESTRA — DERNIÈRE ACTIVITÉ DÉTECTÉE
# ============================================================
# Utilisé par la tâche notify_slack_success pour afficher le nom
# du salarié et la distance de la dernière activité insérée
# (démo "nouvelle course" -> Slack + Power BI).

# Libellés français pour les types de sport Strava les plus courants
SPORT_LABELS_FR = {
    "Run": "Course à pied",
    "Ride": "Vélo",
    "Walk": "Marche",
    "Swim": "Natation",
    "Hike": "Randonnée",
}

if not df_activities.empty:

    latest_run = df_activities.sort_values(
        "start_date", ascending=False
    ).iloc[0]

    target_id = latest_run["employee_id"]

    sport_label = SPORT_LABELS_FR.get(
        latest_run["sport_type"], latest_run["sport_type"]
    )
    duration_min = int(round(latest_run["elapsed_time_s"] / 60))

    # Normalisation des types pour éviter tout faux-négatif de
    # comparaison (ex. "ID salarié" lu comme texte par Excel/pandas
    # alors que employee_id vient de PostgreSQL en entier).
    df["ID salarié"] = pd.to_numeric(
        df["ID salarié"], errors="coerce"
    )
    target_id = pd.to_numeric(
        pd.Series([target_id]), errors="coerce"
    ).iloc[0]

    matches = df[df["ID salarié"] == target_id]

    if matches.empty:
        print(
            f"⚠️ Aucun salarié RH trouvé pour "
            f"employee_id={target_id!r} — vérifiez que cet ID "
            f"existe bien dans le fichier RH."
        )
        kestra_outputs = {
            "last_athlete": "Inconnu",
            "last_distance": f"{latest_run['distance_m'] / 1000:.1f}",
            "last_sport": sport_label,
            "last_duration": duration_min,
        }
    else:
        latest_emp = matches.iloc[0]
        kestra_outputs = {
            "last_athlete": f"{latest_emp['Prénom']} {latest_emp['Nom']}",
            "last_distance": f"{latest_run['distance_m'] / 1000:.1f}",
            "last_sport": sport_label,
            "last_duration": duration_min,
        }

    print(f"::{json.dumps({'outputs': kestra_outputs})}::")

else:

    print("⚠️ Aucune activité sportive trouvée sur les 12 derniers mois.")
    print(
        f"::{json.dumps({'outputs': {'last_athlete': 'Aucune', 'last_distance': '0', 'last_sport': 'sport', 'last_duration': 0}})}::"
    )
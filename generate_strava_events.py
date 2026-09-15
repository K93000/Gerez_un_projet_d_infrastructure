import random
from datetime import datetime, timedelta
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from config import Config

# Connection PostgreSQL sécurisée via Config
conn = psycopg2.connect(**Config.get_db_params())
cur = conn.cursor()

cur.execute("TRUNCATE TABLE strava_activities RESTART IDENTITY;")

# Chargement des référentiels via les chemins centralisés
rh_df = pd.read_excel(Config.RH_FILE_PATH)
sport_df = pd.read_excel(Config.SPORT_FILE_PATH)

rh_df.columns = rh_df.columns.str.strip()
sport_df.columns = sport_df.columns.str.strip()

df_employees = pd.merge(rh_df, sport_df, on="ID salarié", how="left")

COMMENTS = [
    "Reprise du sport :)",
    "Sélection pour le marathon en vue !",
    "Petite sortie matinale avant le bureau.",
    "Forme olympique aujourd'hui !",
    "Séance intense, besoin de récupération.",
    "Randonnée sympa ce week-end !",
    "Séance au top avec les collègues.",
    None,
]

SPORT_SPECS = {
    "Runing": {"dist": (3000, 15000), "speed_m_s": 3.0, "has_dist": True, "clean_name": "Course à pied"},
    "Running": {"dist": (3000, 15000), "speed_m_s": 3.0, "has_dist": True, "clean_name": "Course à pied"},
    "Course à pied": {"dist": (3000, 15000), "speed_m_s": 3.0, "has_dist": True, "clean_name": "Course à pied"},
    "Randonnée": {"dist": (5000, 25000), "speed_m_s": 1.2, "has_dist": True, "clean_name": "Randonnée"},
    "Tennis": {"dist": None, "duration_s": (3600, 7200), "has_dist": False, "clean_name": "Tennis"},
    "Natation": {"dist": (1000, 3000), "speed_m_s": 0.8, "has_dist": True, "clean_name": "Natation"},
    "Football": {"dist": (4000, 8000), "speed_m_s": 2.0, "has_dist": True, "clean_name": "Football"},
    "Rugby": {"dist": (3000, 7000), "speed_m_s": 1.8, "has_dist": True, "clean_name": "Rugby"},
    "Badminton": {"dist": None, "duration_s": (2700, 5400), "has_dist": False, "clean_name": "Badminton"},
    "Voile": {"dist": (5000, 30000), "speed_m_s": 4.0, "has_dist": True, "clean_name": "Voile"},
    "Judo": {"dist": None, "duration_s": (3600, 5400), "has_dist": False, "clean_name": "Judo"},
    "Boxe": {"dist": None, "duration_s": (3600, 5400), "has_dist": False, "clean_name": "Boxe"},
    "Escalade": {"dist": None, "duration_s": (3600, 7200), "has_dist": False, "clean_name": "Escalade"},
    "Triathlon": {"dist": (15000, 40000), "speed_m_s": 6.0, "has_dist": True, "clean_name": "Triathlon"},
    "Équitation": {"dist": None, "duration_s": (3600, 7200), "has_dist": False, "clean_name": "Équitation"},
    "Tennis de table": {"dist": None, "duration_s": (2700, 5400), "has_dist": False, "clean_name": "Tennis de table"},
    "Basketball": {"dist": None, "duration_s": (3600, 5400), "has_dist": False, "clean_name": "Basketball"},
}

DEFAULT_SPORTS = ["Course à pied", "Randonnée", "Natation"]

data_to_insert = []
now = datetime.now()
start_history = now - timedelta(days=365)

print("🏃 Generation des activités Strava simulees...")

for _, emp in df_employees.iterrows():
    emp_id = int(emp["ID salarié"])
    declared_sport = emp["Pratique d'un sport"]

    if pd.isna(declared_sport):
        num_activities = random.randint(2, 10) if random.random() > 0.5 else random.randint(0, 3)
        sports_pool = DEFAULT_SPORTS
    else:
        num_activities = random.randint(16, 45)
        sports_pool = [declared_sport]

    for _ in range(num_activities):
        sport_raw = random.choice(sports_pool)
        spec = SPORT_SPECS.get(sport_raw, SPORT_SPECS["Course à pied"])
        sport_clean = spec["clean_name"]

        random_days = random.randint(0, 364)
        random_hours = random.randint(6, 20)
        start_date = start_history + timedelta(days=random_days, hours=random_hours, minutes=random.randint(0, 59))

        if spec["has_dist"]:
            distance_m = float(random.randint(spec["dist"][0], spec["dist"][1]))
            elapsed_time_s = int(distance_m / spec["speed_m_s"] * random.uniform(0.9, 1.1))
        else:
            distance_m = None
            elapsed_time_s = random.randint(spec["duration_s"][0], spec["duration_s"][1])

        end_date = start_date + timedelta(seconds=elapsed_time_s)
        comment = random.choice(COMMENTS)

        data_to_insert.append((emp_id, start_date, sport_clean, distance_m, elapsed_time_s, end_date, comment))

insert_query = """
    INSERT INTO strava_activities 
    (employee_id, start_date, sport_type, distance_m, elapsed_time_s, end_date, comment)
    VALUES %s
"""

print(f"📥 Insertion de {len(data_to_insert)} lignes dans PostgreSQL...")
execute_values(cur, insert_query, data_to_insert)

conn.commit()
cur.close()
conn.close()

print("✅ Base de données alimentée avec succès !")
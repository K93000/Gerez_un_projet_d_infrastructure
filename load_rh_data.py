import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from config import Config

# Connexion à PostgreSQL
conn = psycopg2.connect(**Config.get_db_params())
cur = conn.cursor()

# 1. Lecture du fichier Excel RH
df_rh = pd.read_excel(Config.RH_FILE_PATH)
df_rh.columns = df_rh.columns.str.strip()

# 2. Préparation des tuples pour insertion
data_to_insert = [
    (
        int(row['ID salarié']),
        str(row['Prénom']),
        str(row['Nom']),
        str(row['Adresse du domicile']),
        str(row['Moyen de déplacement']),
        float(row['Salaire brut'])
    )
    for _, row in df_rh.iterrows()
]

# 3. Requête d'insertion / mise à jour (Upsert)
insert_query = """
    INSERT INTO employees (employee_id, prenom, nom, adresse_domicile, moyen_deplacement, salaire_brut)
    VALUES %s
    ON CONFLICT (employee_id) DO UPDATE SET
        prenom = EXCLUDED.prenom,
        nom = EXCLUDED.nom,
        adresse_domicile = EXCLUDED.adresse_domicile,
        moyen_deplacement = EXCLUDED.moyen_deplacement,
        salaire_brut = EXCLUDED.salaire_brut;
"""

execute_values(cur, insert_query, data_to_insert)
conn.commit()

cur.close()
conn.close()

print("✅ Données RH chargées dans PostgreSQL avec succès !")
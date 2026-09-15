import os


class Config:
    # Hôte PostgreSQL (fallback sur le nom de service Docker Compose 'postgres')
    DB_HOST = os.environ.get("DB_HOST", "postgres")
    DB_PORT = int(os.environ.get("DB_PORT", 5432))
    DB_NAME = os.environ.get("POSTGRES_DB", "sport_data_db")
    DB_USER = os.environ.get("POSTGRES_USER", "sds_user")
    DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "sds_password")

    # Nom exact du fichier RH monté dans /project ou récupéré via Namespace Files
    RH_FILE_PATH = os.environ.get("RH_FILE_PATH", "Donnees_RH.xlsx")

    # Webhook Slack pour les notifications temps réel (slack_notifier.py)
    # Jamais de valeur en dur ici : vient de la variable d'environnement du
    # conteneur, elle-même définie via secret / .env — jamais committée.
    SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

    @classmethod
    def get_db_params(cls):
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "dbname": cls.DB_NAME,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
        }
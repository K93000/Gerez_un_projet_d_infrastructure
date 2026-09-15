import json
import os
import requests
import psycopg2
from kafka import KafkaConsumer
from config import Config

def get_employee_name(employee_id):
    """Récupère le prénom et le nom du salarié depuis PostgreSQL."""
    try:
        conn = psycopg2.connect(**Config.get_db_params())
        cur = conn.cursor()
        cur.execute("SELECT prenom, nom FROM employees WHERE employee_id = %s;", (employee_id,))
        res = cur.fetchone()
        cur.close()
        conn.close()
        if res:
            return res[0], res[1]
    except Exception as e:
        print(f"⚠️ Erreur BDD : {e}")
    return "Salarié", f"#{employee_id}"

def send_slack_notification(
    prenom,
    nom,
    sport_type,
    distance_m,
    elapsed_time_s,
    comment
):
    """Envoie les informations de l'activité sur Slack."""

    distance_km = round(float(distance_m) / 1000, 1) if distance_m else 0
    duration_min = int(elapsed_time_s / 60) if elapsed_time_s else 0

    text = (
        f"🏃 Nouvelle activité sportive !\n"
        f"👤 Salarié : {prenom} {nom}\n"
        f"🏅 Sport : {sport_type}\n"
        f"📏 Distance : {distance_km} km\n"
        f"⏱️ Durée : {duration_min} min\n"
        f"💬 Commentaire : {comment or 'Aucun commentaire'}"
    )

    payload = {"text": text}

    response = requests.post(
        Config.SLACK_WEBHOOK_URL,
        json=payload
    )

    if response.status_code == 200:
        print(
            f"✅ Notification Slack envoyée avec succès "
            f"pour {prenom} {nom} !"
        )
    else:
        print(
            f"❌ Erreur Slack ({response.status_code}) : "
            f"{response.text}"
        )

def main():
    print("🚀 Slack Notifier Service démarré ! En attente de nouvelles activités...\n")

    if not Config.SLACK_WEBHOOK_URL:
        raise RuntimeError(
            "❌ SLACK_WEBHOOK_URL n'est pas défini — vérifiez la variable "
            "d'environnement du service slack_notifier dans docker-compose.yml."
        )

    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")

    consumer = KafkaConsumer(
        'sds.public.strava_activities',
        bootstrap_servers=[kafka_bootstrap],
        auto_offset_reset='latest',
        # Version fixée explicitement pour éviter le sondage automatique
        # ("check_version") de kafka-python, qui échoue souvent face à
        # Redpanda et lève NoBrokersAvailable même quand la connexion
        # réseau fonctionne (cause fréquente et bien documentée).
        api_version=(2, 5, 0),
        value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None
    )

    for message in consumer:
        if not message.value:
            continue
            
        payload = message.value.get('payload', {})
        op = payload.get('op')
        after = payload.get('after')
        
        # Seulement les nouvelles insertions ("c" = create) : on ignore
        # "r" (lignes déjà existantes renvoyées par un snapshot Debezium)
        # et "u" (modifications d'une ligne déjà notifiée).
        if op == 'c' and after:
            emp_id = after.get('employee_id')
            sport = after.get('sport_type')
            dist = after.get('distance_m')
            duration = after.get('elapsed_time_s')
            comment = after.get('comment', '')
            
            prenom, nom = get_employee_name(emp_id)
            
            send_slack_notification(prenom, nom, sport, dist, duration, comment)

if __name__ == "__main__":
    main()
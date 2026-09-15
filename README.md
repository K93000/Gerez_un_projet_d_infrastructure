# Sport Data Solution — POC Avantages Sportifs (P12)

POC de pipeline de données de bout en bout pour calculer et diffuser deux avantages salariés liés à la pratique sportive : une prime de mobilité douce et des jours de bien-être, avec qualité des données, notification Slack temps réel, et reporting Power BI.

Projet réalisé dans le cadre d'une mission chez **Sport Data Solution**, à la demande de Juliette (cofondatrice).

## Sommaire
- [Contexte](#contexte)
- [Architecture](#architecture)
- [Structure du projet](#structure-du-projet)
- [Prérequis](#prérequis)
- [Installation et démarrage](#installation-et-démarrage)
- [Utilisation](#utilisation)
- [Limites connues du POC](#limites-connues-du-poc)

## Contexte

Deux avantages à calculer pour chaque salarié :

- **Prime de mobilité** : 5 % du salaire annuel brut pour un salarié venant au travail en mode actif (marche, vélo, trottinette), sous un seuil de distance domicile-travail.
- **Jours bien-être** : 5 jours par an pour les salariés ayant une pratique sportive régulière (nombre minimum d'activités sur 12 mois glissants).

Objectifs du POC : valider la faisabilité technique, identifier les données à collecter, chiffrer l'impact financier, et permettre de rejouer l'historique des indicateurs si un taux ou une donnée source change.

## Architecture

Deux circuits distincts, pour deux usages différents :

**Circuit batch (calcul + reporting)**
```
Données RH (Excel) + Strava (PostgreSQL)
        │
        ▼
  Qualité des données (Soda Core)
        │
        ▼
  Calcul métier (calculate_benefits.py, orchestré par Kestra)
        │
        ▼
  Table employee_benefits (PostgreSQL, versionnée par règle métier)
        │
        ▼
  Power BI (reporting, rafraîchissement à la demande)
```

**Circuit temps réel (notification Slack)**
```
Nouvelle activité insérée dans PostgreSQL
        │
        ▼
  Debezium (Change Data Capture)
        │
        ▼
  Kafka / Redpanda
        │
        ▼
  slack_notifier (service Python, écoute en continu)
        │
        ▼
  Notification Slack (quelques secondes)
```

Les deux circuits sont indépendants : une exécution du pipeline Kestra ne déclenche pas la notification Slack temps réel, et inversement.

## Structure du projet

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | Infrastructure locale : PostgreSQL, Redpanda (Kafka), Debezium, Kestra, service `slack_notifier` |
| `sport_data_pipeline.yml` | Flow Kestra : qualité → calcul → notification, avec paramètre de taux de prime |
| `calculate_benefits.py` | Calcul des primes et jours bien-être, règles métier versionnées |
| `commute_validator.py` | Calcul et cache des distances domicile-travail |
| `config.py` | Configuration centralisée (variables d'environnement) |
| `checks.yml` / `configuration.yml` | Contrôles qualité Soda Core |
| `load_rh_data.py` | Charge le RH Excel dans la table `employees` (utilisée par `slack_notifier`) |
| `generate_strava_events.py` | Génère un historique d'activités simulées pour la démo |
| `slack_notifier.py` | Service temps réel : écoute Kafka, notifie Slack à chaque nouvelle activité |
| `slack_notifier_service/Dockerfile` | Image du service `slack_notifier` |
| `register-postgres.json` | Configuration du connecteur Debezium (CDC sur `strava_activities`) |
| `register_connector.sh` | Script d'enregistrement du connecteur (Linux/Mac) |
| `demo_passage_v2.sql` | Script de changement de taux de prime versionné (démo : 5 % → 7 %) |
| `Donnees_RH.xlsx` / `Donnees_Sportive.xlsx` | Données sources de démo |
| `power_bi.pbix` | Rapport Power BI connecté à `employee_benefits` |
| `.env.example` | Modèle des variables d'environnement à définir |

## Prérequis

- Docker Desktop (avec le moteur démarré)
- Un webhook Slack entrant configuré sur votre workspace
- Power BI Desktop (pour ouvrir `power_bi.pbix`)

## Installation et démarrage

1. Copier `.env.example` en `.env` et renseigner les deux variables Slack (voir commentaires dans le fichier — attention, ce sont deux formats différents : URL en clair pour `slack_notifier`, encodée en base64 pour Kestra).

2. Démarrer l'infrastructure :
   ```
   docker compose up -d --build
   ```

3. Enregistrer le connecteur Debezium (Windows / PowerShell) :
   ```
   curl.exe -X POST -H "Content-Type: application/json" http://localhost:8083/connectors/ -d "@register-postgres.json"
   ```
   (Linux/Mac : `./register_connector.sh`)

4. Vérifier que le connecteur tourne :
   ```
   curl.exe http://localhost:8083/connectors/sds-postgres-connector/status
   ```
   Les deux `state` doivent afficher `RUNNING`.

5. Charger les données RH dans PostgreSQL :
   ```
   python load_rh_data.py
   ```

6. (Optionnel, pour peupler un historique de démo) :
   ```
   python generate_strava_events.py
   ```

## Utilisation

**Lancer le pipeline de calcul** : dans l'interface Kestra (`localhost:8080`), exécuter le flow `sport_data_pipeline`, en choisissant le taux de prime souhaité dans la fenêtre de paramètres (test ponctuel, non persisté).

**Changer durablement le taux de prime** : exécuter `demo_passage_v2.sql` sur la base — crée une nouvelle version versionnée dans `dim_business_rules`, sans écraser l'historique.

**Simuler une nouvelle activité sportive** (déclenche une notification Slack en quelques secondes, indépendamment de Kestra) :
```
docker exec -it sds_postgres psql -U sds_user -d sport_data_db -c "INSERT INTO strava_activities (employee_id, start_date, end_date, sport_type, distance_m, elapsed_time_s, comment) VALUES (<ID_EXISTANT>, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '1800 seconds', 'Course à pied', 5000, 1800, 'Test');"
```
Remplacer `<ID_EXISTANT>` par un `employee_id` réellement présent dans la table `employees`.

**Consulter le reporting** : ouvrir `power_bi.pbix` dans Power BI Desktop, vérifier la connexion PostgreSQL, puis actualiser.

## Limites connues du POC

- Les données RH existent en deux endroits (fichier Excel lu directement par `calculate_benefits.py`, et table `employees` utilisée par `slack_notifier`) — à unifier avant un passage en production.
- Les identifiants de connexion sont en clair dans `docker-compose.yml` et `register-postgres.json`, acceptable pour un environnement local mais à externaliser via secrets pour un déploiement réel.
- L'ingestion Strava est simulée (`generate_strava_events.py`) plutôt que connectée à l'API Strava réelle.
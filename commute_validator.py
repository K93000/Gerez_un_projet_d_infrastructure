import hashlib
from config import Config
import pandas as pd
import psycopg2
import requests


def normalize_transport_mode(mode: str) -> str:
  """Normalise les chaînes saisies pour éviter les rejets injustifiés."""
  if pd.isna(mode) or not mode:
    return "Inconnu"

  normalized = str(mode).strip().lower()

  mapping = {
      "marche/running": "Marche/running",
      "marche / running": "Marche/running",
      "marche": "Marche/running",
      "running": "Marche/running",
      "vélo/trottinette/autres": "Vélo/Trottinette/Autres",
      "velo/trottinette/autres": "Vélo/Trottinette/Autres",
      "vélo": "Vélo/Trottinette/Autres",
      "velo": "Vélo/Trottinette/Autres",
      "trottinette": "Vélo/Trottinette/Autres",
      "transports en commun": "Transports en commun",
      "véhicule thermique/électrique": "Véhicule thermique/électrique",
  }

  return mapping.get(normalized, mode.strip())


def get_cache_key(address: str, canonical_mode: str) -> str:
  """Génère une clé SHA256 pour le cache des adresses."""
  raw_str = f"{address.strip().lower()}_{canonical_mode.strip().lower()}"
  return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def init_distance_cache_table(conn):
  """Initialise la table de cache d'adresses si elle n'existe pas."""
  with conn.cursor() as cur:
    cur.execute("""
            CREATE TABLE IF NOT EXISTS dim_address_distance (
                cache_key VARCHAR(64) PRIMARY KEY,
                address_raw TEXT NOT NULL,
                transport_mode VARCHAR(50) NOT NULL,
                distance_km NUMERIC(5, 2),
                api_status VARCHAR(20) NOT NULL,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
  conn.commit()


def get_distance_from_google_maps(
    origin_address: str, google_mode: str
) -> float:
  """Effectue la requête réseau Google Maps Matrix API."""
  if not Config.GOOGLE_API_KEY:
    return None

  url = "https://maps.googleapis.com/maps/api/distancematrix/json"
  params = {
      "origins": str(origin_address).strip(),
      "destinations": Config.COMPANY_ADDRESS,
      "mode": google_mode,
      "key": Config.GOOGLE_API_KEY,
  }

  try:
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "OK":
      element = data["rows"][0]["elements"][0]
      if element.get("status") == "OK":
        return round(element["distance"]["value"] / 1000.0, 2)
  except Exception as e:
    print(f"⚠️ Erreur Google Maps API ({origin_address}) : {e}")

  return None


def get_commute_distance(
    conn, origin_address: str, canonical_mode: str
) -> float:
  """Récupère la distance depuis le cache SQL, ou appelle l'API si absente."""
  if pd.isna(origin_address):
    return None

  google_mode_map = {
      "Marche/running": "walking",
      "Vélo/Trottinette/Autres": "bicycling",
  }
  google_mode = google_mode_map.get(canonical_mode)
  if not google_mode:
    return None

  cache_key = get_cache_key(origin_address, canonical_mode)

  # 1. Vérification dans le cache SQL
  with conn.cursor() as cur:
    cur.execute(
        "SELECT distance_km FROM dim_address_distance WHERE cache_key = %s;",
        (cache_key,),
    )
    result = cur.fetchone()
    if result is not None:
      return float(result[0]) if result[0] is not None else None

  # 2. Appel de l'API externe si non présent en cache
  dist_km = get_distance_from_google_maps(origin_address, google_mode)
  status = "OK" if dist_km is not None else "ERROR"

  # 3. Sauvegarde en cache SQL
  with conn.cursor() as cur:
    cur.execute(
        """
            INSERT INTO dim_address_distance (cache_key, address_raw, transport_mode, distance_km, api_status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cache_key) DO NOTHING;
        """,
        (cache_key, origin_address, canonical_mode, dist_km, status),
    )
  conn.commit()

  return dist_km
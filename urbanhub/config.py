"""Configuration centrale du projet.

Toutes les valeurs sont surchargeables par variables d'environnement (ou fichier .env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


# --------------------------------------------------------------------------- #
# Infrastructure
# --------------------------------------------------------------------------- #
MINIO_ENDPOINT = _env("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = _env("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = _env("MINIO_SECRET_KEY", "minioadmin123")
MINIO_BUCKET = _env("MINIO_BUCKET", "urbanhub")

POSTGRES_HOST = _env("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(_env("POSTGRES_PORT", "5432"))
POSTGRES_DB = _env("POSTGRES_DB", "mydatabase")
POSTGRES_USER = _env("POSTGRES_USER", "myuser")
POSTGRES_PASSWORD = _env("POSTGRES_PASSWORD", "mypassword")
POSTGRES_SCHEMA = _env("POSTGRES_SCHEMA", "urbanhub")

LOCAL_TZ = "Europe/Paris"

# --------------------------------------------------------------------------- #
# Villes étudiées (centre-ville + réseau CityBikes associé)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    bike_network: str | None


CITIES: dict[str, City] = {
    c.name: c
    for c in [
        City("Paris", 48.8566, 2.3522, "velib"),
        City("Marseille", 43.2965, 5.3698, "le-velo"),
        City("Lyon", 45.7640, 4.8357, "velov"),
        City("Toulouse", 43.6047, 1.4442, "velo"),
        City("Nice", 43.7102, 7.2620, None),
        City("Nantes", 47.2184, -1.5536, "bicloo"),
        City("Montpellier", 43.6119, 3.8772, "velomagg"),
        City("Strasbourg", 48.5734, 7.7521, "velhop"),
        City("Bordeaux", 44.8378, -0.5792, "v3-bordeaux"),
        City("Lille", 50.6292, 3.0573, "vlille"),
        City("Rennes", 48.1173, -1.6778, "le-velo-star"),
    ]
}

# Rayon (km) pour rattacher une station météo / un capteur à une ville
CITY_RADIUS_KM = 30.0

# Boîte englobante de la France métropolitaine (Corse incluse)
FRANCE_BBOX = {"lat_min": 41.0, "lat_max": 51.5, "lon_min": -5.5, "lon_max": 10.0}

# --------------------------------------------------------------------------- #
# Partie 1 - Batch NOAA
# --------------------------------------------------------------------------- #
# L'index https://www.ncei.noaa.gov/data/global-hourly/access/ redirige désormais
# vers le bucket S3 public de la NOAA (même arborescence : {année}/{station}.csv).
NOAA_BASE_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com"
NOAA_STATIONS_URL = "https://noaa-isd-pds.s3.amazonaws.com/isd-history.csv"
NOAA_YEARS = int(_env("NOAA_YEARS", "5"))
NOAA_WORKERS = int(_env("NOAA_WORKERS", "16"))

# --------------------------------------------------------------------------- #
# Partie 2 - Streaming CityBikes
# --------------------------------------------------------------------------- #
CITYBIKES_BASE_URL = "https://api.citybik.es/v2"
BIKES_INTERVAL_SECONDS = int(_env("BIKES_INTERVAL_SECONDS", "150"))  # 2 min 30

# --------------------------------------------------------------------------- #
# Partie 3 - IoT OpenAQ
# --------------------------------------------------------------------------- #
OPENAQ_BASE_URL = "https://api.openaq.org/v3"
OPENAQ_API_KEY = _env("OPENAQ_API_KEY", "")
AIR_INTERVAL_SECONDS = int(_env("AIR_INTERVAL_SECONDS", "900"))  # 15 min
# Limite gratuite OpenAQ : 60 requêtes / minute -> on reste en dessous
OPENAQ_MIN_DELAY_SECONDS = 1.1

# Polluants demandés (nom OpenAQ -> libellé)
POLLUTANTS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO2", "o3": "O3", "co": "CO"}

# Seuils journaliers OMS 2021 (µg/m³) - utilisés pour comparer les polluants entre eux
WHO_DAILY_GUIDELINES = {"pm25": 15.0, "pm10": 45.0, "no2": 25.0, "o3": 100.0, "co": 4000.0}

# --------------------------------------------------------------------------- #
# Météo récente (complément pour l'analyse croisée)
# --------------------------------------------------------------------------- #
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

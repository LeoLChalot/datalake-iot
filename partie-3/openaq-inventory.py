"""Inventaire des capteurs OpenAQ des principales villes françaises.

Interroge l'API OpenAQ v3 (stations de la France), garde les stations actives qui
mesurent au moins un des 5 polluants étudiés et situées à moins de 20 km d'une grande
ville, puis dépose dans le bucket MinIO datalake-openaq :
  - inventory/sensors.csv    : un capteur par ligne (sensor_id, pollutant, unit, lat, lon, city...)
  - inventory/locations.txt  : la liste des location_id (utilisée par openaq-download.sh)

Usage : python partie-3/openaq-inventory.py   (clé API dans .env : OPENAQ_API_KEY=...)
"""

import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

# --- CONFIGURATION ---
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

OPENAQ_URL = "https://api.openaq.org/v3"
OPENAQ_API_KEY = os.environ["OPENAQ_API_KEY"]
FRANCE_ID = 22

MINIO_ENDPOINT = "http://127.0.0.1:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin123"
BUCKET_NAME = "datalake-openaq"

POLLUTANTS = {"pm25", "pm10", "no2", "o3", "co"}
RADIUS_KM = 20
ACTIVE_DAYS = 7  # une station sans mesure depuis 7 jours est considérée inactive

CITIES = {
    "Paris": (48.8566, 2.3522),
    "Marseille": (43.2965, 5.3698),
    "Lyon": (45.7640, 4.8357),
    "Toulouse": (43.6047, 1.4442),
    "Nice": (43.7102, 7.2620),
    "Nantes": (47.2184, -1.5536),
    "Montpellier": (43.6119, 3.8772),
    "Strasbourg": (48.5734, 7.7521),
    "Bordeaux": (44.8378, -0.5792),
    "Lille": (50.6292, 3.0573),
    "Rennes": (48.1173, -1.6778),
}

COLUMNS = ["sensor_id", "location_id", "location_name", "pollutant", "unit", "latitude",
           "longitude", "city", "distance_km", "provider", "is_monitor", "datetime_first",
           "datetime_last"]


def api_get(path):
    req = urllib.request.Request(f"{OPENAQ_URL}{path}", headers={"X-API-Key": OPENAQ_API_KEY})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def distance_km(lat1, lon1, lat2, lon2):
    """Distance approchée (projection équirectangulaire), suffisante à l'échelle d'une ville."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371 * math.hypot(x, y)


def nearest_city(lat, lon):
    city, dist = min(((c, distance_km(lat, lon, *pos)) for c, pos in CITIES.items()), key=lambda t: t[1])
    return (city, dist) if dist <= RADIUS_KM else (None, dist)


def get_france_locations():
    locations, page = [], 1
    while True:
        results = api_get(f"/locations?countries_id={FRANCE_ID}&limit=1000&page={page}")["results"]
        if not results:
            return locations
        locations += results
        page += 1


def to_rows(location):
    coords = location.get("coordinates") or {}
    if not coords:
        return []
    city, dist = nearest_city(coords["latitude"], coords["longitude"])
    if city is None:
        return []
    return [
        {
            "sensor_id": sensor["id"],
            "location_id": location["id"],
            "location_name": location["name"],
            "pollutant": sensor["parameter"]["name"],
            "unit": sensor["parameter"]["units"],
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
            "city": city,
            "distance_km": round(dist, 2),
            "provider": (location.get("provider") or {}).get("name"),
            "is_monitor": location["isMonitor"],
            "datetime_first": (location.get("datetimeFirst") or {}).get("utc"),
            "datetime_last": (location.get("datetimeLast") or {}).get("utc"),
        }
        for sensor in location["sensors"]
        if sensor["parameter"]["name"] in POLLUTANTS
    ]


locations = get_france_locations()
active_since = (datetime.now(timezone.utc) - timedelta(days=ACTIVE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
active = [l for l in locations if ((l.get("datetimeLast") or {}).get("utc") or "") >= active_since]
rows = [row for location in active for row in to_rows(location)]
location_ids = sorted({row["location_id"] for row in rows})

print(f"{len(locations)} stations en France, {len(active)} actives")
print(f"{len(location_ids)} stations et {len(rows)} capteurs retenus dans les grandes villes :")
for city in CITIES:
    n = len({r["location_id"] for r in rows if r["city"] == city})
    print(f"  {city:<12} {n} stations")

s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT, aws_access_key_id=MINIO_ACCESS_KEY,
                  aws_secret_access_key=MINIO_SECRET_KEY)
if BUCKET_NAME not in [b["Name"] for b in s3.list_buckets()["Buckets"]]:
    s3.create_bucket(Bucket=BUCKET_NAME)

buf = io.StringIO()
writer = csv.DictWriter(buf, fieldnames=COLUMNS)
writer.writeheader()
writer.writerows(rows)
s3.put_object(Bucket=BUCKET_NAME, Key="inventory/sensors.csv", Body=buf.getvalue().encode("utf-8"))
s3.put_object(Bucket=BUCKET_NAME, Key="inventory/locations.txt",
              Body="\n".join(map(str, location_ids)).encode("utf-8") + b"\n")
print(f"Inventaire déposé dans {BUCKET_NAME}/inventory/")

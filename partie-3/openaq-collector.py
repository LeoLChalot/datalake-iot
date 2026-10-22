"""Flux IoT simulé : interroge toutes les 15 min les dernières mesures des capteurs OpenAQ
des grandes villes françaises et dépose les nouvelles mesures dans le bucket MinIO
datalake-openaq, comme le ferait une passerelle IoT (un message JSON par mesure).

Seules les mesures nouvelles depuis le cycle précédent sont émises.
Fichiers produits : datalake-openaq/stream/<YYYY-MM-DD>/<HHMMSS>.jsonl

Usage : python partie-3/openaq-collector.py   (Ctrl+C pour arrêter)
Prérequis : python partie-3/openaq-inventory.py (liste des capteurs)
"""

import csv
import io
import json
import os
import time
import urllib.error
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

MINIO_ENDPOINT = "http://127.0.0.1:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin123"
BUCKET_NAME = "datalake-openaq"

INTERVAL = 15 * 60  # secondes ; les capteurs publient une mesure par heure
API_DELAY = 1.1  # plan gratuit OpenAQ : 60 requêtes / minute
MAX_AGE_HOURS = 24  # mesures plus anciennes ignorées

s3 = boto3.client("s3", endpoint_url=MINIO_ENDPOINT, aws_access_key_id=MINIO_ACCESS_KEY,
                  aws_secret_access_key=MINIO_SECRET_KEY)


def api_get(path):
    req = urllib.request.Request(f"{OPENAQ_URL}{path}", headers={"X-API-Key": OPENAQ_API_KEY})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            # Quota dépassé : on attend la remise à zéro indiquée par l'API
            time.sleep(int(e.headers.get("x-ratelimit-reset", 60)) + 1)
    raise RuntimeError(f"quota OpenAQ toujours dépassé : {path}")


def load_inventory():
    body = s3.get_object(Bucket=BUCKET_NAME, Key="inventory/sensors.csv")["Body"].read().decode("utf-8")
    return {int(row["sensor_id"]): row for row in csv.DictReader(io.StringIO(body))}


def to_message(measure, sensor):
    return {
        "sensor_id": measure["sensorsId"],
        "pollutant": sensor["pollutant"],
        "timestamp": measure["datetime"]["utc"],
        "latitude": measure["coordinates"]["latitude"],
        "longitude": measure["coordinates"]["longitude"],
        "value": measure["value"],
        "unit": sensor["unit"],
        "location_id": measure["locationsId"],
        "city": sensor["city"],
    }


sensors = load_inventory()
location_ids = sorted({int(s["location_id"]) for s in sensors.values()})
last_seen = {}  # sensor_id -> timestamp de la dernière mesure émise
pending = []  # messages pas encore déposés dans MinIO (renvoyés au cycle suivant)
print(f"{len(sensors)} capteurs sur {len(location_ids)} stations")

while True:
    start = time.time()
    now = datetime.now(timezone.utc)
    oldest = (now - timedelta(hours=MAX_AGE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== Collecte {now:%Y-%m-%d %H:%M:%S} UTC ===")

    messages = []
    for location_id in location_ids:
        try:
            for measure in api_get(f"/locations/{location_id}/latest")["results"]:
                sensor = sensors.get(measure["sensorsId"])
                ts = measure["datetime"]["utc"]
                # Un capteur en panne renvoie sa dernière mesure, parfois vieille de plusieurs années
                if ts < oldest:
                    continue
                if sensor and last_seen.get(measure["sensorsId"]) != ts:
                    last_seen[measure["sensorsId"]] = ts
                    messages.append(to_message(measure, sensor))
        except Exception as e:
            print(f"  station {location_id} ÉCHEC : {e}")
        time.sleep(API_DELAY)

    print(f"  {len(messages)} nouvelles mesures en {time.time() - start:.0f} s")

    pending += messages
    if pending:
        body = "\n".join(json.dumps(m, ensure_ascii=False) for m in pending) + "\n"
        try:
            s3.put_object(Bucket=BUCKET_NAME, Key=f"stream/{now:%Y-%m-%d}/{now:%H%M%S}.jsonl",
                          Body=body.encode("utf-8"))
            pending = []
        except Exception as e:
            # MinIO indisponible (ou horloge Docker décalée après une mise en veille)
            print(f"  ÉCHEC du dépôt MinIO, {len(pending)} mesures gardées pour le cycle suivant : {e}")

    time.sleep(max(0, INTERVAL - (time.time() - start)))

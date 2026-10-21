"""Récupère toutes les 150 s les stations de vélos des grandes villes françaises
(CityBikes API) et dépose un CSV par ville dans le bucket MinIO datalake-citybikes.

Usage : python partie-2/citybikes-collector.py   (Ctrl+C pour arrêter)
"""

import csv
import io
import json
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

MINIO_URL = "http://localhost:9000/datalake-citybikes"
INTERVAL = 150  # secondes

NETWORKS = {
    "velib": "Paris",
    "velov": "Lyon",
    "le-velo": "Marseille",
    "velo": "Toulouse",
    "bicloo": "Nantes",
    "v3-bordeaux": "Bordeaux",
    "vlille": "Lille",
    "velhop": "Strasbourg",
    "velomagg": "Montpellier",
    "le-velo-star": "Rennes",
}

COLUMNS = ["station_id", "station_name", "timestamp", "latitude", "longitude",
           "free_slots", "bikes_available", "city"]


def get_stations(network):
    url = f"https://api.citybik.es/v2/networks/{network}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)["network"]["stations"]


def to_row(station, city):
    return {
        "station_id": station["id"],
        "station_name": station["name"].strip(),
        "timestamp": station["timestamp"][:19] + "Z",  # ex : 2026-10-21T15:01:21Z
        "latitude": station["latitude"],
        "longitude": station["longitude"],
        "free_slots": station["empty_slots"],
        "bikes_available": station["free_bikes"],
        "city": city,
    }


def upload_csv(path, rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    subprocess.run(
        ["curl", "-s", "-f", "-X", "PUT", "--data-binary", "@-", f"{MINIO_URL}/{path}"],
        input=buf.getvalue().encode("utf-8"),
        check=True,
    )


while True:
    now = datetime.now(timezone.utc)
    print(f"=== Collecte {now:%Y-%m-%d %H:%M:%S} UTC ===")

    for network, city in NETWORKS.items():
        try:
            rows = [to_row(s, city) for s in get_stations(network)]
            upload_csv(f"{network}/{now:%Y-%m-%d}/{now:%H%M%S}.csv", rows)
            print(f"  {city:<12} {len(rows)} stations")
        except Exception as e:
            print(f"  {city:<12} ÉCHEC : {e}")

    time.sleep(INTERVAL)

"""Ingestion régulière simulant un flux IoT.

Toutes les AIR_INTERVAL_SECONDS (15 min par défaut), le collecteur interroge la dernière
mesure de chaque capteur des grandes villes. Chaque mesure est traitée comme un message
capteur indépendant (comme sur un bus MQTT / Kafka) :

    {"sensor_id": 1234, "pollutant": "no2", "timestamp": "...", "latitude": ..,
     "longitude": .., "value": 21.4, "unit": "µg/m³"}

Les messages d'un cycle sont archivés en JSON Lines dans bronze/openaq/stream/ puis
insérés dans PostgreSQL (les doublons d'un cycle à l'autre sont ignorés).

Usage :
    python -m urbanhub air              # boucle infinie
    python -m urbanhub air --once       # un seul cycle
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from urbanhub import config
from urbanhub.iot.inventory import refresh_inventory
from urbanhub.iot.openaq_client import OpenAQClient
from urbanhub.iot.transform import parse_latest
from urbanhub.storage import DataLake, Warehouse

log = logging.getLogger(__name__)


def to_messages(df: pd.DataFrame) -> list[dict]:
    """Mesures -> messages capteurs avec les variables demandées par le sujet."""
    msgs = df.rename(columns={"ts": "timestamp"})[
        ["sensor_id", "pollutant", "timestamp", "latitude", "longitude", "value", "unit"]
    ].copy()
    msgs["timestamp"] = msgs["timestamp"].map(lambda t: t.isoformat())
    return msgs.to_dict(orient="records")


def collect_once(client: OpenAQClient, lake: DataLake, wh: Warehouse,
                 locations: pd.DataFrame, sensors: pd.DataFrame) -> int:
    now = datetime.now(timezone.utc)
    frames = []
    for _, loc in locations.iterrows():
        try:
            frames.append(parse_latest(client.latest(int(loc["location_id"])), sensors, loc))
        except Exception as exc:
            log.warning("Station %s ignorée : %s", loc["location_id"], exc)
    batch = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if batch.empty:
        return 0

    lines = "\n".join(json.dumps(m, ensure_ascii=False) for m in to_messages(batch))
    lake.put_bytes(f"bronze/openaq/stream/date={now:%Y-%m-%d}/{now:%H%M%S}.jsonl", lines.encode("utf-8"),
                   compress=True)
    return wh.upsert(batch, "air_measurement", ["sensor_id", "ts"], update=False)


def run(interval: int = config.AIR_INTERVAL_SECONDS, once: bool = False, duration_min: float | None = None) -> None:
    client, lake, wh = OpenAQClient(), DataLake(), Warehouse()
    lake.ensure_bucket()
    wh.init_schema()
    locations, sensors = refresh_inventory(client, lake, wh)

    deadline = time.time() + duration_min * 60 if duration_min else None
    cycle = 0
    while True:
        start = time.time()
        cycle += 1
        try:
            n = collect_once(client, lake, wh, locations, sensors)
            log.info("Cycle %d : %d nouvelles mesures en %.0f s", cycle, n, time.time() - start)
        except Exception:
            log.exception("Cycle %d en échec", cycle)
        if once or (deadline and time.time() >= deadline):
            break
        time.sleep(max(0.0, interval - (time.time() - start)))

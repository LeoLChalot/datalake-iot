"""Historique horaire OpenAQ des capteurs des grandes villes.

Le flux IoT ne commence qu'au lancement du collecteur ; ce backfill fournit l'historique
nécessaire aux analyses (variations journalières, épisodes, croisement avec la météo NOAA).

Usage :
    python -m urbanhub air-backfill --days 60
    python -m urbanhub air-backfill --since 2024-01-01   # recouvre la période NOAA (plus long)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from urbanhub.iot.inventory import refresh_inventory
from urbanhub.iot.openaq_client import OpenAQClient
from urbanhub.iot.transform import parse_hours
from urbanhub.storage import DataLake, Warehouse

log = logging.getLogger(__name__)


def run(days: int = 60, since: str | None = None) -> None:
    client, lake, wh = OpenAQClient(), DataLake(), Warehouse()
    lake.ensure_bucket()
    wh.init_schema()

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = datetime.fromisoformat(since).replace(tzinfo=timezone.utc) if since else end - timedelta(days=days)
    active_days = (end - start).days + 1
    locations, sensors = refresh_inventory(client, lake, wh, active_since_days=active_days)
    loc_by_id = locations.set_index("location_id")

    log.info("Backfill de %d capteurs du %s au %s", len(sensors), start.date(), end.date())
    total = 0
    for i, sensor in enumerate(sensors.itertuples(index=False), 1):
        try:
            results = client.sensor_hours(sensor.sensor_id, start.isoformat(), end.isoformat())
        except Exception as exc:
            log.warning("Capteur %s ignoré : %s", sensor.sensor_id, exc)
            continue
        lake.put_json(f"bronze/openaq/hours/sensor={sensor.sensor_id}/{start:%Y%m%d}-{end:%Y%m%d}.json", results)
        df = parse_hours(results, sensor.sensor_id, sensors, loc_by_id.loc[sensor.location_id])
        total += wh.upsert(df, "air_measurement", ["sensor_id", "ts"], update=False)
        log.info("[%d/%d] capteur %s (%s) : %d heures", i, len(sensors), sensor.sensor_id, sensor.pollutant, len(df))
    log.info("Backfill terminé : %d mesures insérées", total)

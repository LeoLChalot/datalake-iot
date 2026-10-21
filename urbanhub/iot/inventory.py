"""Inventaire des capteurs OpenAQ en France (stations + capteurs des polluants étudiés)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from urbanhub.iot.openaq_client import OpenAQClient
from urbanhub.iot.transform import parse_locations
from urbanhub.storage import DataLake, Warehouse

log = logging.getLogger(__name__)


def refresh_inventory(
    client: OpenAQClient, lake: DataLake, wh: Warehouse, active_since_days: int | None = 30
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Met à jour air_location / air_sensor et renvoie les stations des grandes villes à suivre."""
    raw = client.locations(iso="FR")
    now = datetime.now(timezone.utc)
    lake.put_json(f"bronze/openaq/locations/date={now:%Y-%m-%d}/{now:%H%M%S}.json", raw)

    locations, sensors = parse_locations(raw)
    wh.upsert(locations.drop(columns=["last_update"]), "air_location", ["location_id"])
    wh.upsert(sensors, "air_sensor", ["sensor_id"])
    log.info("Inventaire OpenAQ France : %d stations, %d capteurs", len(locations), len(sensors))

    tracked = locations[locations["city"].notna()]
    if active_since_days is not None:
        tracked = tracked[tracked["last_update"] >= now - timedelta(days=active_since_days)]
    log.info("%d stations actives dans les grandes villes : %s", len(tracked),
             tracked["city"].value_counts().to_dict())
    return tracked.reset_index(drop=True), sensors[sensors["location_id"].isin(tracked["location_id"])]

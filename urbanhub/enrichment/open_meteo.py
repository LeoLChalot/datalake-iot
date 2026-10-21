"""Météo horaire récente par ville via Open-Meteo (sans clé API).

Pourquoi ? L'archive publique NOAA Global Hourly s'arrête en 2025 alors que les flux
vélos et pollution sont collectés aujourd'hui. Pour croiser météo x mobilité x air sur
la période de collecte, on complète la NOAA avec Open-Meteo (mêmes variables, mêmes
unités). La vue v_weather_city_hourly fusionne les deux sources.

Usage :
    python -m urbanhub weather-recent --past-days 92
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from urbanhub import config
from urbanhub.storage import DataLake, Warehouse

log = logging.getLogger(__name__)

VARIABLES = {
    "temperature_2m": "temperature",
    "wind_speed_10m": "wind_speed",
    "wind_direction_10m": "wind_direction",
    "visibility": "visibility",
    "pressure_msl": "pressure",
    "precipitation": "precipitation",
}


def fetch_city(city: config.City, past_days: int) -> dict:
    resp = requests.get(config.OPEN_METEO_URL, params={
        "latitude": city.lat,
        "longitude": city.lon,
        "hourly": ",".join(VARIABLES),
        "past_days": past_days,
        "forecast_days": 1,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }, timeout=60)
    resp.raise_for_status()
    return resp.json()


def parse(city: str, payload: dict) -> pd.DataFrame:
    df = pd.DataFrame(payload["hourly"]).rename(columns={"time": "ts", **VARIABLES})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["visibility"] = df["visibility"] / 1000  # m -> km (même unité que la NOAA)
    df.insert(0, "city", city)
    df = df[df["ts"] <= datetime.now(timezone.utc)]  # pas de prévisions
    return df.dropna(subset=["temperature"])


def run(past_days: int = 92) -> None:
    lake, wh = DataLake(), Warehouse()
    lake.ensure_bucket()
    wh.init_schema()
    now = datetime.now(timezone.utc)
    total = 0
    for city in config.CITIES.values():
        payload = fetch_city(city, past_days)
        lake.put_json(f"bronze/open-meteo/date={now:%Y-%m-%d}/{city.name}.json", payload)
        total += wh.upsert(parse(city.name, payload), "weather_recent", ["city", "ts"])
    log.info("Open-Meteo : %d heures chargées pour %d villes", total, len(config.CITIES))

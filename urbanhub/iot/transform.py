"""Mise en forme des réponses OpenAQ : référentiel capteurs et mesures normalisées."""
from __future__ import annotations

import pandas as pd

from urbanhub import config
from urbanhub.geo import nearest_city

# Masse molaire (g/mol) pour convertir ppm/ppb en µg/m³ (25 °C, 1 atm : volume molaire 24,45 L)
MOLAR_MASS = {"no2": 46.01, "o3": 48.00, "co": 28.01}
MOLAR_VOLUME = 24.45

MEASUREMENT_COLS = ["sensor_id", "ts", "pollutant", "value", "unit", "value_ugm3", "latitude", "longitude", "source"]


def to_ugm3(value: pd.Series, unit: pd.Series, pollutant: pd.Series) -> pd.Series:
    """Ramène toutes les concentrations en µg/m³ pour pouvoir les comparer."""
    unit = unit.str.lower().str.replace("³", "3").str.replace("μ", "µ")
    mass = pollutant.map(MOLAR_MASS)
    factor = pd.Series(float("nan"), index=value.index)
    factor[unit.isin(["µg/m3", "ug/m3"])] = 1.0
    factor[unit == "mg/m3"] = 1000.0
    factor[unit == "ppb"] = mass / MOLAR_VOLUME
    factor[unit == "ppm"] = mass * 1000 / MOLAR_VOLUME
    return (value * factor).round(2)


def parse_locations(locations: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(stations, capteurs) en ne gardant que les polluants étudiés."""
    loc_rows, sensor_rows = [], []
    for loc in locations:
        coords = loc.get("coordinates") or {}
        loc_rows.append({
            "location_id": loc["id"],
            "name": loc.get("name"),
            "locality": loc.get("locality"),
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
            "provider": (loc.get("provider") or {}).get("name"),
            "last_update": (loc.get("datetimeLast") or {}).get("utc"),
        })
        for s in loc.get("sensors", []):
            param = s.get("parameter") or {}
            if param.get("name") in config.POLLUTANTS:
                sensor_rows.append({
                    "sensor_id": s["id"],
                    "location_id": loc["id"],
                    "pollutant": param["name"],
                    "unit": param.get("units"),
                })

    locs = pd.DataFrame(loc_rows)
    sensors = pd.DataFrame(sensor_rows, columns=["sensor_id", "location_id", "pollutant", "unit"])
    if locs.empty:
        return locs, sensors
    locs["city"] = nearest_city(locs["latitude"], locs["longitude"]).values
    locs["last_update"] = pd.to_datetime(locs["last_update"], utc=True, errors="coerce")
    # On ne garde que les stations qui mesurent au moins un polluant étudié
    locs = locs[locs["location_id"].isin(sensors["location_id"])]
    return locs.reset_index(drop=True), sensors


def _finalize(df: pd.DataFrame, sensors: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=MEASUREMENT_COLS)
    df = df.merge(sensors[["sensor_id", "pollutant", "unit"]], on="sensor_id", how="inner",
                  suffixes=("", "_sensor"))
    if "unit_sensor" in df:
        df["unit"] = df["unit"].fillna(df.pop("unit_sensor"))
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[df["value"].notna() & (df["value"] >= 0)].dropna(subset=["ts"])  # -999 = capteur en défaut
    df["value_ugm3"] = to_ugm3(df["value"], df["unit"], df["pollutant"])
    df["source"] = source
    return df[MEASUREMENT_COLS]


def parse_latest(results: list[dict], sensors: pd.DataFrame, location: pd.Series) -> pd.DataFrame:
    """Réponse /locations/{id}/latest -> mesures (une ligne par capteur)."""
    rows = [{
        "sensor_id": r["sensorsId"],
        "ts": (r.get("datetime") or {}).get("utc"),
        "value": r.get("value"),
        "unit": None,
        "latitude": (r.get("coordinates") or {}).get("latitude", location["latitude"]),
        "longitude": (r.get("coordinates") or {}).get("longitude", location["longitude"]),
    } for r in results]
    return _finalize(pd.DataFrame(rows), sensors, "stream")


def parse_hours(results: list[dict], sensor_id: int, sensors: pd.DataFrame, location: pd.Series) -> pd.DataFrame:
    """Réponse /sensors/{id}/hours -> mesures horaires."""
    rows = [{
        "sensor_id": sensor_id,
        "ts": ((r.get("period") or {}).get("datetimeTo") or {}).get("utc"),
        "value": r.get("value"),
        "unit": (r.get("parameter") or {}).get("units"),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
    } for r in results]
    return _finalize(pd.DataFrame(rows), sensors, "backfill")

"""Transformation d'une réponse CityBikes en tables `bike_station` et `bike_status`."""
from __future__ import annotations

import pandas as pd


def fix_encoding(text: str | None) -> str | None:
    """Certains noms arrivent doublement encodés (ex. « ChÃ¢teau » au lieu de « Château »)."""
    if not text or "Ã" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_timestamp(values: pd.Series) -> pd.Series:
    # L'API renvoie parfois « ...+00:00Z » (double indication de fuseau)
    cleaned = values.astype(str).str.replace(r"(\+00:00)Z$", r"\1", regex=True)
    return pd.to_datetime(cleaned, utc=True, format="ISO8601", errors="coerce").dt.floor("s")


def parse_network(network: dict, city: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Retourne (référentiel des stations, statut instantané des stations)."""
    stations = network.get("stations", [])
    if not stations:
        empty = pd.DataFrame()
        return empty, empty

    df = pd.json_normalize(stations)
    get = lambda col: df[col] if col in df else pd.Series([None] * len(df))  # noqa: E731

    bikes = pd.to_numeric(df["free_bikes"], errors="coerce")
    slots = pd.to_numeric(df["empty_slots"], errors="coerce")
    capacity = pd.to_numeric(get("extra.slots"), errors="coerce").fillna(bikes + slots)
    ts = parse_timestamp(df["timestamp"])

    ref = pd.DataFrame({
        "station_id": df["id"],
        "network_id": network["id"],
        "city": city,
        "station_name": df["name"].map(fix_encoding),
        "latitude": df["latitude"],
        "longitude": df["longitude"],
        "capacity": capacity.round().astype("Int64"),
        "last_seen": ts,
    })
    status = pd.DataFrame({
        "station_id": df["id"],
        "ts": ts,
        "bikes_available": bikes.astype("Int64"),
        "free_slots": slots.astype("Int64"),
        "ebikes": pd.to_numeric(get("extra.ebikes"), errors="coerce").astype("Int64"),
    }).dropna(subset=["ts"])
    return ref, status

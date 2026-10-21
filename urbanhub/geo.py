"""Outils géographiques : distances et rattachement aux villes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from urbanhub.config import CITIES, CITY_RADIUS_KM, FRANCE_BBOX

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance orthodromique (km), vectorisée numpy."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def nearest_city(lat: pd.Series, lon: pd.Series, radius_km: float = CITY_RADIUS_KM) -> pd.Series:
    """Retourne la ville principale la plus proche (ou None au-delà du rayon)."""
    lat = pd.to_numeric(lat, errors="coerce").to_numpy()
    lon = pd.to_numeric(lon, errors="coerce").to_numpy()
    names = list(CITIES)
    dists = np.column_stack([haversine_km(lat, lon, c.lat, c.lon) for c in CITIES.values()])
    best = np.nanargmin(np.where(np.isnan(dists), np.inf, dists), axis=1)
    best_dist = dists[np.arange(len(best)), best]
    result = np.where(best_dist <= radius_km, np.array(names, dtype=object)[best], None)
    return pd.Series(result, dtype="object")


def in_france(lat: pd.Series, lon: pd.Series) -> pd.Series:
    b = FRANCE_BBOX
    return lat.between(b["lat_min"], b["lat_max"]) & lon.between(b["lon_min"], b["lon_max"])

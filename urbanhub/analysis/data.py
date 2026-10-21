"""Chargement des données depuis l'entrepôt (couche gold) pour les analyses."""
from __future__ import annotations

import pandas as pd

from urbanhub import config
from urbanhub.storage import Warehouse

_wh = Warehouse()


def _local(df: pd.DataFrame, col: str = "ts") -> pd.DataFrame:
    if not df.empty:
        df[col] = pd.to_datetime(df[col], utc=True)
        df["ts_local"] = df[col].dt.tz_convert(config.LOCAL_TZ)
    return df


# ------------------------------------------------------------------------ météo
def weather_city_daily() -> pd.DataFrame:
    df = _wh.read_sql("SELECT * FROM {schema}.v_weather_city_daily ORDER BY city, day")
    df["day"] = pd.to_datetime(df["day"])
    return df


def weather_france_daily() -> pd.DataFrame:
    """Moyenne journalière sur toutes les stations françaises chargées."""
    df = _wh.read_sql(
        """
        SELECT day, AVG(t_mean) AS t_mean, AVG(t_min) AS t_min, AVG(t_max) AS t_max,
               AVG(wind_mean) AS wind_mean, AVG(precipitation) AS precipitation,
               COUNT(*) AS n_stations
        FROM {schema}.weather_daily GROUP BY day ORDER BY day
        """
    )
    df["day"] = pd.to_datetime(df["day"])
    return df


def weather_city_hourly(start=None, end=None, source: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM {schema}.v_weather_city_hourly WHERE TRUE"
    params = {}
    if start is not None:
        sql += " AND ts >= :start"
        params["start"] = pd.Timestamp(start).floor("h")
    if end is not None:
        sql += " AND ts <= :end"
        params["end"] = pd.Timestamp(end)
    if source:
        sql += " AND source = :source"
        params["source"] = source
    df = _wh.read_sql(sql + " ORDER BY city, ts", **params)
    for col in ("wind_direction",):
        df[col] = pd.to_numeric(df[col])
    return _local(df)


def weather_station_hourly_sample(station_ids: list[str] | None = None, max_rows: int = 2_000_000) -> pd.DataFrame:
    """Données horaires station par station (pour la corrélation visibilité)."""
    sql = "SELECT * FROM {schema}.weather_hourly"
    params = {}
    if station_ids:
        sql += " WHERE station_id = ANY(:ids)"
        params["ids"] = station_ids
    df = _wh.read_sql(sql + f" LIMIT {max_rows}", **params)
    return _local(df)


def weather_stations() -> pd.DataFrame:
    return _wh.read_sql("SELECT * FROM {schema}.weather_station")


# ------------------------------------------------------------------------ vélos
def bike_status(since=None, cities: list[str] | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM {schema}.v_bike_status WHERE TRUE"
    params = {}
    if since is not None:
        sql += " AND ts >= :since"
        params["since"] = pd.Timestamp(since)
    if cities:
        sql += " AND city = ANY(:cities)"
        params["cities"] = cities
    return _local(_wh.read_sql(sql + " ORDER BY station_id, ts", **params))


# ---------------------------------------------------------------------- pollution
def air_measurements(since=None) -> pd.DataFrame:
    sql = "SELECT * FROM {schema}.v_air_measurement WHERE value_ugm3 IS NOT NULL"
    params = {}
    if since is not None:
        sql += " AND ts >= :since"
        params["since"] = pd.Timestamp(since)
    return _local(_wh.read_sql(sql + " ORDER BY sensor_id, ts", **params))


def air_city_hourly() -> pd.DataFrame:
    return _local(_wh.read_sql("SELECT * FROM {schema}.v_air_city_hourly ORDER BY city, ts"))

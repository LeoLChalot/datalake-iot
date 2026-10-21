"""Pipeline batch NOAA : inventaire -> téléchargement parallèle -> bronze -> nettoyage -> silver -> PostgreSQL.

Usage :
    python -m urbanhub batch                     # 5 dernières années, toutes les stations FR
    python -m urbanhub batch --cities-only       # uniquement les stations des grandes villes
    python -m urbanhub batch --max-stations 10   # échantillon rapide pour tester
"""
from __future__ import annotations

import logging

import pandas as pd

from urbanhub import config
from urbanhub.batch import noaa_stations
from urbanhub.batch.noaa_clean import clean_noaa_csv
from urbanhub.batch.noaa_download import NoaaFile, download_parallel
from urbanhub.storage import DataLake, Warehouse

log = logging.getLogger(__name__)

DAILY_SQL = """
INSERT INTO {schema}.weather_daily
SELECT station_id,
       (ts AT TIME ZONE 'Europe/Paris')::date AS day,
       AVG(temperature), MIN(temperature), MAX(temperature),
       AVG(wind_speed), MAX(wind_speed),
       AVG(visibility), MIN(visibility),
       AVG(pressure),
       AVG(precipitation) * 24,          -- taux moyen (mm/h) -> cumul journalier estimé
       COUNT(*)
FROM {schema}.weather_hourly
WHERE station_id = ANY(:station_ids)
GROUP BY station_id, day
HAVING COUNT(*) >= 12                    -- au moins 12 heures observées dans la journée
ON CONFLICT (station_id, day) DO UPDATE SET
    t_mean = EXCLUDED.t_mean, t_min = EXCLUDED.t_min, t_max = EXCLUDED.t_max,
    wind_mean = EXCLUDED.wind_mean, wind_max = EXCLUDED.wind_max,
    visibility_mean = EXCLUDED.visibility_mean, visibility_min = EXCLUDED.visibility_min,
    pressure_mean = EXCLUDED.pressure_mean, precipitation = EXCLUDED.precipitation,
    n_hours = EXCLUDED.n_hours
"""


def bronze_key(f: NoaaFile) -> str:
    return f"bronze/noaa/year={f.year}/{f.station_id}.csv.gz"


def silver_key(f: NoaaFile) -> str:
    return f"silver/weather_hourly/year={f.year}/{f.station_id}.parquet"


def run(
    n_years: int = config.NOAA_YEARS,
    workers: int = config.NOAA_WORKERS,
    cities_only: bool = False,
    max_stations: int | None = None,
    force: bool = False,
) -> None:
    lake, wh = DataLake(), Warehouse()
    lake.ensure_bucket()
    wh.init_schema()

    # 1. Inventaire des stations françaises
    stations = noaa_stations.france_stations()
    if cities_only:
        stations = stations[stations["city"].notna()]
    if max_stations:
        # Échantillon : on garde en priorité les stations rattachées à une grande ville
        stations = stations.sort_values("city", na_position="last").head(max_stations)
    wh.upsert(stations, "weather_station", ["station_id"])
    log.info("%d stations françaises retenues", len(stations))

    # 2. Liste des fichiers existants sur les n dernières années disponibles
    years = noaa_stations.available_years(n_years)
    log.info("Années disponibles retenues : %s", years)
    ids = set(stations["station_id"])
    files = [NoaaFile(y, sid) for y in years for sid in noaa_stations.files_for_year(y, ids)]
    if not force:
        done = {k for y in years for k in lake.list_keys(f"silver/weather_hourly/year={y}/")}
        files = [f for f in files if silver_key(f) not in done]
    log.info("%d fichiers à télécharger en parallèle (%d threads)", len(files), workers)

    # 3. Pour chaque fichier (dans les threads) : bronze -> nettoyage -> silver
    def process(f: NoaaFile, raw: bytes) -> pd.DataFrame:
        lake.put_bytes(bronze_key(f), raw, compress=True)
        hourly = clean_noaa_csv(raw)
        lake.put_parquet(silver_key(f), hourly)
        return hourly

    # 4. Chargement dans PostgreSQL au fil de l'eau
    loaded_rows, failures = 0, 0
    for f, result in download_parallel(files, process, workers):
        if isinstance(result, Exception):
            failures += 1
            continue
        loaded_rows += wh.upsert(result, "weather_hourly", ["station_id", "ts"])

    # 5. Agrégats journaliers (couche gold), calculés directement en SQL
    wh.execute(DAILY_SQL, station_ids=list(ids))
    log.info("Batch terminé : %d lignes horaires chargées, %d échecs", loaded_rows, failures)

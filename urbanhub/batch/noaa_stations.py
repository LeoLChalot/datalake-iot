"""Inventaire des stations météo NOAA situées en France et des fichiers disponibles."""
from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from urbanhub import config
from urbanhub.geo import in_france, nearest_city

log = logging.getLogger(__name__)

S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def france_stations() -> pd.DataFrame:
    """Stations du fichier isd-history.csv situées en France métropolitaine."""
    resp = requests.get(config.NOAA_STATIONS_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.BytesIO(resp.content), dtype=str)
    df = df[df["CTRY"] == "FR"].copy()
    df["latitude"] = pd.to_numeric(df["LAT"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["LON"], errors="coerce")
    df = df[in_france(df["latitude"], df["longitude"])]

    out = pd.DataFrame({
        "station_id": df["USAF"] + df["WBAN"],
        "name": df["STATION NAME"].str.title(),
        "latitude": df["latitude"],
        "longitude": df["longitude"],
        "elevation": pd.to_numeric(df["ELEV(M)"], errors="coerce"),
    }).drop_duplicates("station_id")
    out["city"] = nearest_city(out["latitude"], out["longitude"]).values
    return out.reset_index(drop=True)


def _list_s3(prefix: str, delimiter: str | None = None) -> tuple[list[str], list[str]]:
    """Liste (clés, sous-dossiers) du bucket public NOAA via l'API S3 REST."""
    keys, prefixes, token = [], [], None
    while True:
        params = {"list-type": "2", "prefix": prefix}
        if delimiter:
            params["delimiter"] = delimiter
        if token:
            params["continuation-token"] = token
        resp = requests.get(config.NOAA_BASE_URL + "/", params=params, timeout=60)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        keys += [e.text for e in root.findall("s3:Contents/s3:Key", S3_NS)]
        prefixes += [e.text for e in root.findall("s3:CommonPrefixes/s3:Prefix", S3_NS)]
        token_el = root.find("s3:NextContinuationToken", S3_NS)
        if token_el is None:
            return keys, prefixes
        token = token_el.text


def available_years(n_years: int = config.NOAA_YEARS) -> list[int]:
    """Les n dernières années réellement publiées par la NOAA.

    Remarque : l'archive publique s'arrête actuellement à 2025 ; on prend donc les
    5 dernières années *disponibles* plutôt que les 5 dernières années civiles.
    """
    _, prefixes = _list_s3("", delimiter="/")
    years = sorted((int(p.strip("/")) for p in prefixes if p.strip("/").isdigit()), reverse=True)
    selected: list[int] = []
    for year in years:  # du plus récent au plus ancien, on s'arrête dès qu'on en a assez
        if _has_files(f"{year}/07"):  # 07xxxx = bloc OMM de la France métropolitaine
            selected.append(year)
        if len(selected) == n_years:
            break
    return sorted(selected)


def _has_files(prefix: str) -> bool:
    resp = requests.get(config.NOAA_BASE_URL + "/", params={"list-type": "2", "prefix": prefix, "max-keys": "1"},
                        timeout=60)
    resp.raise_for_status()
    return ET.fromstring(resp.content).find("s3:Contents", S3_NS) is not None


def files_for_year(year: int, station_ids: set[str]) -> list[str]:
    """Identifiants de stations françaises ayant un fichier pour l'année donnée."""
    first_digits = sorted({sid[:2] for sid in station_ids})
    found: set[str] = set()
    for digits in first_digits:
        keys, _ = _list_s3(f"{year}/{digits}")
        found |= {k.split("/")[-1].removesuffix(".csv") for k in keys}
    return sorted(found & station_ids)

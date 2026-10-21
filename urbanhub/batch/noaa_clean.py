"""Décodage et nettoyage d'un fichier NOAA Global Hourly (format ISD en CSV).

Chaque variable est encodée dans une colonne « valeur,qualité,... » avec des valeurs
sentinelles pour les données manquantes et des facteurs d'échelle :

    TMP  "+0038,1"            température en °C x10          (manquant : +9999)
    WND  "210,1,N,0057,1"     direction °, type, vitesse m/s x10 (manquant : 999 / 9999)
    VIS  "003600,1,9,9"       visibilité en mètres            (manquant : 999999)
    SLP  "10278,1"            pression niveau mer en hPa x10  (manquant : 99999)
    MA1  "10270,1,99999,9"    QNH des METAR en hPa x10, utilisé quand SLP manque
    AA1  "03,0000,9,1"        période (h), hauteur de pluie mm x10 (manquant : 99 / 9999)

Documentation : https://www.ncei.noaa.gov/data/global-hourly/doc/isd-format-document.pdf
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

# Codes qualité acceptés (2, 3, 6, 7 = suspect ou erroné)
GOOD_QUALITY = set("01459ACIMPRU")

# Rapports de synthèse journaliers / mensuels à exclure (ce ne sont pas des observations)
EXCLUDED_REPORT_TYPES = {"SOD", "SOM"}

# Bornes physiquement plausibles après conversion
VALID_RANGES = {
    "temperature": (-50, 50),       # °C
    "wind_speed": (0, 60),          # m/s
    "visibility": (0.01, 100),      # km (0 m exactement = capteur en défaut)
    "pressure": (900, 1080),        # hPa
    "precipitation": (0, 150),      # mm/h
}

USECOLS = ["STATION", "DATE", "REPORT_TYPE", "WND", "VIS", "TMP", "SLP", "MA1", "AA1", "AA2"]
OUTPUT_COLS = ["station_id", "ts", "temperature", "wind_speed", "wind_direction",
               "visibility", "pressure", "precipitation"]


def _parts(series: pd.Series, n: int) -> pd.DataFrame:
    return series.fillna("").str.split(",", expand=True).reindex(columns=range(n))


def _decode(value: pd.Series, quality: pd.Series, missing: float, scale: float) -> pd.Series:
    num = pd.to_numeric(value, errors="coerce")
    ok = quality.isin(GOOD_QUALITY) & (num.abs() != missing)
    return num.where(ok) / scale


def _precipitation_rate(aa: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(période en heures, taux en mm/h) pour un groupe AAx."""
    p = _parts(aa, 4)
    period = pd.to_numeric(p[0], errors="coerce")
    depth = _decode(p[1], p[3], 9999, 10)
    period = period.where(period.between(1, 24))
    return period, depth / period


def decode_observations(raw: pd.DataFrame) -> pd.DataFrame:
    """Observations brutes -> une ligne par observation, unités SI, valeurs invalides à NaN."""
    df = raw.copy()
    for col in USECOLS:
        if col not in df:
            df[col] = np.nan
    df = df[~df["REPORT_TYPE"].fillna("").str.strip().isin(EXCLUDED_REPORT_TYPES)]

    out = pd.DataFrame({"station_id": df["STATION"].astype(str).str.zfill(11),
                        "ts": pd.to_datetime(df["DATE"], utc=True, errors="coerce")})

    tmp = _parts(df["TMP"], 2)
    out["temperature"] = _decode(tmp[0], tmp[1], 9999, 10)

    wnd = _parts(df["WND"], 5)
    out["wind_speed"] = _decode(wnd[3], wnd[4], 9999, 10)
    direction = _decode(wnd[0], wnd[1], 999, 1)
    calm = wnd[2] == "C"
    out["wind_direction"] = direction.where(~calm)
    out.loc[calm & out["wind_speed"].isna(), "wind_speed"] = 0.0

    vis = _parts(df["VIS"], 4)
    out["visibility"] = _decode(vis[0], vis[1], 999999, 1000)  # m -> km

    # Pression au niveau de la mer : SLP (messages SYNOP), à défaut le QNH des METAR (MA1)
    slp = _parts(df["SLP"], 2)
    ma1 = _parts(df["MA1"], 4)
    out["pressure"] = _decode(slp[0], slp[1], 99999, 10).fillna(_decode(ma1[0], ma1[1], 99999, 10))

    # On privilégie le cumul sur la période la plus courte (AA1 ou AA2)
    p1, r1 = _precipitation_rate(df["AA1"])
    p2, r2 = _precipitation_rate(df["AA2"])
    use_second = r1.isna() | (p2 < p1)
    out["precipitation"] = r1.where(~use_second, r2)

    for col, (lo, hi) in VALID_RANGES.items():
        out[col] = out[col].where(out[col].between(lo, hi))
    out.loc[~out["wind_direction"].between(0, 360), "wind_direction"] = np.nan

    return out.dropna(subset=["ts"])


def to_hourly(obs: pd.DataFrame) -> pd.DataFrame:
    """Agrège les observations (SYNOP, METAR, SPECI...) en une ligne par heure."""
    if obs.empty:
        return pd.DataFrame(columns=OUTPUT_COLS)
    station_id = obs["station_id"].iloc[0]
    obs = obs.assign(hour=obs["ts"].dt.floor("h"))

    rad = np.radians(obs["wind_direction"])
    obs = obs.assign(_sin=np.sin(rad), _cos=np.cos(rad))
    hourly = obs.groupby("hour").agg(
        temperature=("temperature", "mean"),
        wind_speed=("wind_speed", "mean"),
        visibility=("visibility", "mean"),
        pressure=("pressure", "mean"),
        precipitation=("precipitation", "mean"),
        _sin=("_sin", "mean"),
        _cos=("_cos", "mean"),
    )
    hourly["wind_direction"] = np.degrees(np.arctan2(hourly["_sin"], hourly["_cos"])) % 360

    # Série horaire complète puis interpolation des trous courts (<= 3 h)
    full_index = pd.date_range(hourly.index.min(), hourly.index.max(), freq="h")
    hourly = hourly.reindex(full_index)
    for col in ("temperature", "pressure"):
        hourly[col] = hourly[col].interpolate(limit=3, limit_area="inside")

    hourly = hourly.drop(columns=["_sin", "_cos"]).dropna(how="all")
    hourly = hourly.rename_axis("ts").reset_index()
    hourly.insert(0, "station_id", station_id)
    return hourly[OUTPUT_COLS].round(2)


def clean_noaa_csv(raw_csv: bytes) -> pd.DataFrame:
    """Pipeline complet : CSV brut NOAA -> DataFrame horaire propre."""
    raw = pd.read_csv(io.BytesIO(raw_csv), usecols=lambda c: c in USECOLS, dtype=str, low_memory=False)
    obs = decode_observations(raw).drop_duplicates()
    return to_hourly(obs)

"""Partie 3 - Questions métier sur la pollution de l'air (OpenAQ).

Les concentrations sont comparées en µg/m³ ; pour comparer des polluants entre eux, on
les rapporte aux valeurs guides journalières de l'OMS (2021) : un indice de 1 signifie
« au niveau du seuil OMS ».
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from urbanhub.config import POLLUTANTS, WHO_DAILY_GUIDELINES


def _who_index(df: pd.DataFrame, col: str = "value_ugm3") -> pd.Series:
    return df[col] / df["pollutant"].map(WHO_DAILY_GUIDELINES)


# --------------------------------------------------------------------------- Q1
def levels_by_location(df: pd.DataFrame) -> pd.DataFrame:
    """Concentration moyenne par station et polluant, rapportée au seuil OMS."""
    out = df.groupby(["city", "location_id", "location_name", "pollutant"]).agg(
        moyenne_ugm3=("value_ugm3", "mean"), p95_ugm3=("value_ugm3", lambda v: v.quantile(0.95)),
        n=("value_ugm3", "size"), latitude=("latitude", "first"), longitude=("longitude", "first"),
    ).reset_index()
    out["indice_oms"] = out["moyenne_ugm3"] / out["pollutant"].map(WHO_DAILY_GUIDELINES)
    return out.sort_values("indice_oms", ascending=False).reset_index(drop=True)


def levels_by_city(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau ville x polluant des concentrations moyennes (µg/m³)."""
    return df.pivot_table(index="city", columns="pollutant", values="value_ugm3", aggfunc="mean").round(1)


# --------------------------------------------------------------------------- Q2
def daily_cycle(df: pd.DataFrame) -> pd.DataFrame:
    """Profil horaire moyen (heure locale), normalisé par la moyenne de chaque polluant."""
    d = df.assign(hour=df["ts_local"].dt.hour)
    prof = d.groupby(["pollutant", "hour"])["value_ugm3"].mean().unstack("pollutant")
    return prof / prof.mean()


def daily_cycle_amplitude(df: pd.DataFrame) -> pd.DataFrame:
    """Heure du pic, heure du creux et amplitude relative (max/min) par polluant."""
    prof = df.assign(hour=df["ts_local"].dt.hour).groupby(["pollutant", "hour"])["value_ugm3"].mean().unstack()
    return pd.DataFrame({
        "heure_pic": prof.idxmax(axis=1), "heure_creux": prof.idxmin(axis=1),
        "ratio_pic_creux": (prof.max(axis=1) / prof.min(axis=1)).round(2),
    })


# --------------------------------------------------------------------------- Q3
def dominant_pollutants(df: pd.DataFrame) -> pd.DataFrame:
    """Polluant dominant par ville = indice OMS moyen le plus élevé."""
    d = df.assign(indice=_who_index(df))
    idx = d.pivot_table(index="city", columns="pollutant", values="indice", aggfunc="mean")
    out = idx.round(2)
    out["dominant"] = idx.idxmax(axis=1).map(lambda p: POLLUTANTS.get(p, p))
    return out


# --------------------------------------------------------------------------- Q4
def daily_means(df: pd.DataFrame) -> pd.DataFrame:
    d = df.assign(day=df["ts_local"].dt.tz_localize(None).dt.floor("D"))
    return d.groupby(["city", "pollutant", "day"])["value_ugm3"].agg(["mean", "size"]).reset_index()


def pollution_episodes(df: pd.DataFrame, z_threshold: float = 3.5) -> pd.DataFrame:
    """Jours anormaux : moyenne journalière au-dessus du seuil OMS et/ou z-score robuste élevé.

    Le z-score robuste utilise la médiane et l'écart absolu médian (MAD), peu sensibles
    aux épisodes eux-mêmes : z = 0,6745 x (x - médiane) / MAD.
    """
    daily = daily_means(df)
    daily = daily[daily["size"] >= 12]  # au moins 12 h de mesures dans la journée
    grp = daily.groupby(["city", "pollutant"])["mean"]
    median = grp.transform("median")
    mad = grp.transform(lambda v: (v - v.median()).abs().median()).replace(0, np.nan)
    daily["z_robuste"] = 0.6745 * (daily["mean"] - median) / mad
    daily["seuil_oms"] = daily["pollutant"].map(WHO_DAILY_GUIDELINES)
    daily["depasse_oms"] = daily["mean"] > daily["seuil_oms"]
    daily["anomalie_stat"] = daily["z_robuste"] > z_threshold
    episodes = daily[daily["depasse_oms"] | daily["anomalie_stat"]]
    return episodes.rename(columns={"mean": "moyenne_jour_ugm3"}).drop(columns="size").sort_values(
        ["z_robuste"], ascending=False).reset_index(drop=True)


def hourly_anomalies(df: pd.DataFrame, z_threshold: float = 5.0) -> pd.DataFrame:
    """Pics horaires isolés par capteur (z-score robuste)."""
    g = df.groupby("sensor_id")["value_ugm3"]
    med = g.transform("median")
    mad = g.transform(lambda v: (v - v.median()).abs().median()).replace(0, np.nan)
    z = 0.6745 * (df["value_ugm3"] - med) / mad
    return df.assign(z_robuste=z)[z > z_threshold].sort_values("z_robuste", ascending=False)

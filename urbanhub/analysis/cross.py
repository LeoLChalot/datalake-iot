"""Partie 4 - Analyse croisée Météo x Mobilité x Pollution.

Toutes les sources sont ramenées au même grain : (ville, heure UTC).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WEATHER_COLS = ["temperature", "wind_speed", "precipitation", "pressure", "visibility"]


def _hour(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.floor("h")


def air_wide(air_city_hourly: pd.DataFrame) -> pd.DataFrame:
    """(ville, heure) x polluants en colonnes."""
    df = air_city_hourly.assign(ts=_hour(air_city_hourly["ts"]))
    return df.pivot_table(index=["city", "ts"], columns="pollutant", values="value_ugm3").reset_index()


def bike_hourly(activity: pd.DataFrame) -> pd.DataFrame:
    """Activité vélo horaire par ville + indice d'usage corrigé du cycle journalier.

    indice = activité observée / activité moyenne à la même heure (et même type de jour).
    Un indice de 1,2 signifie « 20 % d'usage en plus que d'habitude à cette heure-là » :
    cela neutralise l'effet heure de pointe pour isoler l'effet météo.
    """
    a = activity.assign(ts=_hour(activity["slot"].dt.tz_convert("UTC")))
    h = a.groupby(["city", "ts"]).agg(movements=("movements", "sum"), hours=("hours", "sum")).reset_index()
    h["activite"] = h["movements"] / h["hours"].replace(0, np.nan)
    local = h["ts"].dt.tz_convert("Europe/Paris")
    h["hour"] = local.dt.hour
    h["weekend"] = local.dt.dayofweek >= 5
    ref = h.groupby(["city", "hour", "weekend"])["activite"].transform("mean")
    h["indice_usage"] = h["activite"] / ref.replace(0, np.nan)
    return h


def merge_sources(weather: pd.DataFrame, bikes: pd.DataFrame | None = None, air: pd.DataFrame | None = None) -> pd.DataFrame:
    w = weather.assign(ts=_hour(weather["ts"]))[["city", "ts", *WEATHER_COLS]]
    out = w
    for other in (bikes, air):
        if other is not None and not other.empty:
            out = out.merge(other, on=["city", "ts"], how="inner")
    return out


# --------------------------------------------------------------------------- Q1
def weather_pollution_correlations(merged: pd.DataFrame, pollutants: list[str]) -> pd.DataFrame:
    """Matrice de corrélation de Spearman météo (lignes) x polluants (colonnes)."""
    cols = [p for p in pollutants if p in merged]
    corr = merged[WEATHER_COLS + cols].corr(method="spearman")
    return corr.loc[WEATHER_COLS, cols].round(2)


def pollution_by_wind(merged: pd.DataFrame, pollutants: list[str]) -> pd.DataFrame:
    bins = pd.cut(merged["wind_speed"], [-0.1, 2, 4, 6, 8, np.inf], labels=["<2", "2-4", "4-6", "6-8", ">8 m/s"])
    cols = [p for p in pollutants if p in merged]
    return merged.groupby(bins, observed=True)[cols].mean().round(1)


def pollution_by_temperature(merged: pd.DataFrame, pollutants: list[str]) -> pd.DataFrame:
    bins = pd.cut(merged["temperature"], [-50, 0, 5, 10, 15, 20, 25, 30, 60])
    cols = [p for p in pollutants if p in merged]
    return merged.groupby(bins, observed=True)[cols].mean().round(1)


# --------------------------------------------------------------------------- Q2
def weather_bike_effects(merged: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Indice d'usage moyen selon pluie, température et vent."""
    d = merged.dropna(subset=["indice_usage"]).copy()
    d["pluie"] = np.where(d["precipitation"] > 0.1, "pluie", "sec")
    d["temperature_classe"] = pd.cut(d["temperature"], [-50, 5, 10, 15, 20, 25, 60],
                                     labels=["<5°C", "5-10", "10-15", "15-20", "20-25", ">25°C"])
    d["vent_classe"] = pd.cut(d["wind_speed"], [-0.1, 3, 6, 9, np.inf], labels=["<3", "3-6", "6-9", ">9 m/s"])
    out = {}
    for col in ("pluie", "temperature_classe", "vent_classe"):
        out[col] = d.groupby(col, observed=True)["indice_usage"].agg(["mean", "size"]).round(3)
    out["correlations"] = d[["indice_usage", *WEATHER_COLS]].corr(method="spearman")[["indice_usage"]].drop(
        "indice_usage").round(2)
    return out


# --------------------------------------------------------------------------- Q3
def favorable_conditions(merged: pd.DataFrame, min_hours: int = 3) -> pd.DataFrame:
    """Combinaisons (température, pluie, vent) classées par indice d'usage moyen."""
    d = merged.dropna(subset=["indice_usage"]).copy()
    d["temperature"] = pd.cut(d["temperature"], [-50, 5, 10, 15, 20, 25, 60],
                              labels=["<5°C", "5-10", "10-15", "15-20", "20-25", ">25°C"])
    d["pluie"] = np.where(d["precipitation"] > 0.1, "pluie", "sec")
    d["vent"] = np.where(d["wind_speed"] > 6, "venteux", "calme")
    res = d.groupby(["temperature", "pluie", "vent"], observed=True)["indice_usage"].agg(["mean", "size"])
    res = res[res["size"] >= min_hours].sort_values("mean", ascending=False)
    res["favorable"] = res["mean"] > 1
    return res.round(3)


# --------------------------------------------------------------------------- Q4
def daily_interactions(merged: pd.DataFrame, pollutant: str = "no2") -> pd.DataFrame:
    """Par ville et par jour : z-scores de l'usage vélo, de la pollution et de la météo.

    Une journée « d'interaction forte » combine des écarts importants (|z| >= 1) sur
    les trois dimensions en même temps.
    """
    d = merged.assign(day=merged["ts"].dt.tz_convert("Europe/Paris").dt.date)
    agg = {"indice_usage": "mean", "temperature": "mean", "wind_speed": "mean", "precipitation": "sum"}
    if pollutant in d:
        agg[pollutant] = "mean"
    daily = d.groupby(["city", "day"]).agg(agg).reset_index()

    def z(col):
        g = daily.groupby("city")[col]
        return (daily[col] - g.transform("mean")) / g.transform("std").replace(0, np.nan)

    daily["z_usage"] = z("indice_usage")
    daily["z_meteo"] = z("temperature")
    if pollutant in daily:
        daily["z_pollution"] = z(pollutant)
        daily["interaction_forte"] = (daily[["z_usage", "z_meteo", "z_pollution"]].abs() >= 1).all(axis=1)
    return daily


def hourly_interaction_matrix(merged: pd.DataFrame, pollutants: list[str]) -> pd.DataFrame:
    cols = ["indice_usage", *WEATHER_COLS, *[p for p in pollutants if p in merged]]
    return merged[cols].corr(method="spearman").round(2)

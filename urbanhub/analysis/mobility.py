"""Partie 2 - Questions métier sur les vélos en libre-service (CityBikes).

L'API ne fournit pas les trajets, seulement l'état des stations. On en déduit l'activité :
entre deux relevés successifs d'une station, |Δ vélos disponibles| est le nombre minimal
de vélos empruntés ou rendus (« mouvements »). C'est une borne basse de l'usage réel
(un emprunt compensé par un retour entre deux relevés est invisible).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from urbanhub import config
from urbanhub.geo import haversine_km

MAX_GAP = pd.Timedelta(minutes=10)  # au-delà, le Δ n'est pas attribuable à un intervalle court


def network_quality(status: pd.DataFrame) -> pd.DataFrame:
    """Contrôle qualité par réseau : un flux où aucune station n'a jamais de vélo est défaillant
    (c'est le cas de certains réseaux dont l'API amont renvoie 0 partout)."""
    q = status.groupby("city").agg(
        stations=("station_id", "nunique"), releves=("ts", "size"),
        debut=("ts", "min"), fin=("ts", "max"),
        velos_moy=("bikes_available", "mean"),
        part_stations_jamais_vides=("bikes_available", lambda b: (b.groupby(status.loc[b.index, "station_id"]).max() > 0).mean()),
    )
    q["flux_suspect"] = q["velos_moy"] < 0.1
    return q.round(3)


def drop_broken_networks(status: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    q = network_quality(status)
    broken = q.index[q["flux_suspect"]].tolist()
    return status[~status["city"].isin(broken)], broken


def prepare(status: pd.DataFrame) -> pd.DataFrame:
    """Ajoute mouvements, taux de remplissage et indicateurs vide/pleine à chaque relevé."""
    df = status.sort_values(["station_id", "ts"]).copy()
    df = df[(df["bikes_available"] + df["free_slots"]) > 0]  # station hors service (0 vélo, 0 place)
    df["capacity"] = df["capacity"].where(df["capacity"] > 0, df["bikes_available"] + df["free_slots"])
    df["occupancy"] = df["bikes_available"] / (df["bikes_available"] + df["free_slots"]).replace(0, np.nan)

    g = df.groupby("station_id")
    gap = g["ts"].diff()
    delta = g["bikes_available"].diff()
    df["movements"] = delta.abs().where(gap <= MAX_GAP)
    df["interval_h"] = (gap.dt.total_seconds() / 3600).where(gap <= MAX_GAP)

    df["empty"] = df["bikes_available"] == 0
    df["full"] = df["free_slots"] == 0
    df["hour"] = df["ts_local"].dt.hour
    df["weekend"] = df["ts_local"].dt.dayofweek >= 5
    df["slot"] = df["ts_local"].dt.floor("15min")
    return df


# --------------------------------------------------------------------------- Q1
def station_usage(df: pd.DataFrame, min_hours: float = 1.0) -> pd.DataFrame:
    """Taux d'utilisation = mouvements par point d'attache et par jour (rotations)."""
    agg = df.groupby(["station_id", "station_name", "city"]).agg(
        capacity=("capacity", "max"),
        movements=("movements", "sum"),
        observed_h=("interval_h", "sum"),
        occupancy=("occupancy", "mean"),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
    ).reset_index()
    agg = agg[(agg["observed_h"] >= min_hours) & (agg["capacity"] > 0)]
    agg["mouvements_par_heure"] = agg["movements"] / agg["observed_h"]
    agg["rotations_par_borne_jour"] = agg["mouvements_par_heure"] * 24 / agg["capacity"]
    return agg.sort_values("rotations_par_borne_jour", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- Q2
def supply_gaps(df: pd.DataFrame, cell_deg: float = 0.01, empty_threshold: float = 0.25) -> pd.DataFrame:
    """Zones (mailles d'environ 1 km) où les vélos manquent souvent.

    Une zone est « en sous-offre » si ses stations sont vides plus de 25 % du temps
    ou si elle offre en moyenne moins de 2 vélos par station.
    """
    d = df.assign(
        cell_lat=(df["latitude"] / cell_deg).round() * cell_deg,
        cell_lon=(df["longitude"] / cell_deg).round() * cell_deg,
    )
    per_station = d.groupby(["city", "cell_lat", "cell_lon", "station_id"]).agg(
        bikes=("bikes_available", "mean"), empty=("empty", "mean"), capacity=("capacity", "max")
    ).reset_index()
    zones = per_station.groupby(["city", "cell_lat", "cell_lon"]).agg(
        stations=("station_id", "nunique"), capacite=("capacity", "sum"),
        velos_moy_par_station=("bikes", "mean"), part_temps_vide=("empty", "mean"),
    ).reset_index()
    zones["sous_offre"] = (zones["part_temps_vide"] > empty_threshold) | (zones["velos_moy_par_station"] < 2)
    return zones.sort_values("part_temps_vide", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- Q3
def network_activity(df: pd.DataFrame) -> pd.DataFrame:
    """Activité du réseau par quart d'heure et par ville (mouvements / station / heure)."""
    act = df.groupby(["city", "slot"]).agg(
        movements=("movements", "sum"), hours=("interval_h", "sum"),
        bikes_available=("bikes_available", "sum"), stations=("station_id", "nunique"),
    ).reset_index()
    act["activite"] = act["movements"] / act["hours"].replace(0, np.nan)  # mouvements par station-heure
    return act


def hourly_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Profil journalier moyen : activité par heure locale, semaine vs week-end."""
    prof = df.groupby(["city", "weekend", "hour"]).agg(movements=("movements", "sum"), hours=("interval_h", "sum"))
    prof["activite"] = prof["movements"] / prof["hours"].replace(0, np.nan)
    return prof.reset_index()


def peak_hours(profile: pd.DataFrame, top: int = 3) -> pd.DataFrame:
    return (profile.dropna(subset=["activite"]).sort_values("activite", ascending=False)
            .groupby(["city", "weekend"]).head(top).sort_values(["city", "weekend", "activite"],
                                                               ascending=[True, True, False]))


# --------------------------------------------------------------------------- Q4
def geographic_balance(df: pd.DataFrame) -> pd.DataFrame:
    """Taux de remplissage moyen selon l'éloignement du centre-ville et le moment de la journée."""
    centers = {c.name: (c.lat, c.lon) for c in config.CITIES.values()}
    lat_c = df["city"].map(lambda c: centers[c][0])
    lon_c = df["city"].map(lambda c: centers[c][1])
    d = df.assign(dist_km=haversine_km(df["latitude"], df["longitude"], lat_c, lon_c))
    d["anneau"] = pd.cut(d["dist_km"], [0, 1.5, 4, 8, np.inf], labels=["hyper-centre <1,5 km", "centre 1,5-4 km",
                                                                         "périphérie 4-8 km", "banlieue >8 km"])
    d["moment"] = pd.cut(d["hour"], [-1, 6, 10, 16, 20, 24], labels=["nuit", "matin 7-10h", "journée",
                                                                      "soir 17-20h", "nuit "])
    d["moment"] = d["moment"].astype(str).str.strip()
    return d.pivot_table(index=["city", "anneau"], columns="moment", values="occupancy", aggfunc="mean",
                         observed=True).round(3)


def station_balance(df: pd.DataFrame) -> pd.DataFrame:
    """Remplissage moyen par station (pour la carte des déséquilibres)."""
    return df.groupby(["station_id", "station_name", "city"]).agg(
        latitude=("latitude", "first"), longitude=("longitude", "first"),
        occupancy=("occupancy", "mean"), capacity=("capacity", "max"),
    ).reset_index()


# --------------------------------------------------------------------------- Q5
def critical_stations(df: pd.DataFrame, threshold: float = 0.2, target: float = 0.5) -> pd.DataFrame:
    """Stations vides ou pleines plus de `threshold` du temps, avec le nombre de vélos à déplacer
    pour revenir à un taux de remplissage cible de 50 %."""
    s = df.groupby(["station_id", "station_name", "city"]).agg(
        capacity=("capacity", "max"), bikes_moy=("bikes_available", "mean"),
        part_vide=("empty", "mean"), part_pleine=("full", "mean"), releves=("ts", "size"),
        latitude=("latitude", "first"), longitude=("longitude", "first"),
    ).reset_index()
    s = s[s["releves"] >= 5]
    s["probleme"] = np.select(
        [s["part_vide"] >= threshold, s["part_pleine"] >= threshold], ["vide (à réapprovisionner)", "pleine (à délester)"],
        default="",
    )
    s = s[s["probleme"] != ""].copy()
    s["velos_a_deplacer"] = (target * s["capacity"] - s["bikes_moy"]).round().astype(int)
    s["priorite"] = (s[["part_vide", "part_pleine"]].max(axis=1) * s["capacity"]).round(1)
    return s.sort_values("priorite", ascending=False).reset_index(drop=True)

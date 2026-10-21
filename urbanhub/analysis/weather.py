"""Partie 1 - Questions métier sur la météo (NOAA)."""
from __future__ import annotations

import numpy as np
import pandas as pd

WEATHER_VARS = ["temperature", "wind_speed", "pressure", "precipitation", "visibility"]

# Seuils des journées extrêmes (inspirés des vigilances Météo-France)
EXTREME_THRESHOLDS = {
    "canicule": ("t_max", ">=", 35.0),          # °C
    "grand_froid": ("t_min", "<=", -7.0),       # °C
    "vent_violent": ("wind_max", ">=", 15.0),   # m/s en moyenne horaire (~54 km/h, rafales bien plus fortes)
    "fortes_pluies": ("precipitation", ">=", 30.0),  # mm/jour
    "brouillard_dense": ("visibility_min", "<=", 0.2),  # km
}


# --------------------------------------------------------------------------- Q1
def daily_anomalies(daily: pd.DataFrame, value: str = "t_mean", group: str = "city") -> pd.DataFrame:
    """Écart de chaque jour à la « normale » du même jour de l'année (z-score).

    La normale est la moyenne sur toutes les années disponibles, lissée sur 31 jours
    pour ne pas dépendre du bruit d'une date particulière.
    """
    df = daily[[group, "day", value]].dropna().copy()
    df["doy"] = df["day"].dt.dayofyear.clip(upper=365)

    def climatology(g: pd.DataFrame) -> pd.DataFrame:
        clim = g.groupby("doy")[value].agg(["mean", "std"]).reindex(range(1, 366)).interpolate(limit_direction="both")
        # Lissage circulaire (le 31 décembre est voisin du 1er janvier)
        padded = pd.concat([clim.iloc[-15:], clim, clim.iloc[:15]])
        smooth = padded.rolling(31, center=True, min_periods=1).mean().iloc[15:-15]
        return smooth.rename(columns={"mean": "normal", "std": "normal_std"})

    clims = df.groupby(group, group_keys=True).apply(climatology, include_groups=False).reset_index()
    out = df.merge(clims, on=[group, "doy"])
    out["anomaly"] = out[value] - out["normal"]
    out["z"] = out["anomaly"] / out["normal_std"]
    return out.sort_values([group, "day"]).reset_index(drop=True)


def anomalous_periods(anom: pd.DataFrame, z_threshold: float = 1.5, min_days: int = 3, group: str = "city") -> pd.DataFrame:
    """Séquences d'au moins `min_days` jours consécutifs anormalement chauds ou froids."""
    rows = []
    for key, g in anom.groupby(group):
        g = g.set_index("day").asfreq("D")
        state = np.select([g["z"] >= z_threshold, g["z"] <= -z_threshold], ["chaud", "froid"], default="")
        run_id = (pd.Series(state, index=g.index) != pd.Series(state, index=g.index).shift()).cumsum()
        for _, block in g.assign(state=state, run=run_id.values).groupby("run"):
            kind = block["state"].iloc[0]
            if kind and len(block) >= min_days:
                rows.append({
                    group: key, "type": kind, "debut": block.index[0].date(), "fin": block.index[-1].date(),
                    "jours": len(block), "anomalie_moy_C": round(block["anomaly"].mean(), 1),
                    "z_max": round(block["z"].abs().max(), 1),
                })
    cols = [group, "type", "debut", "fin", "jours", "anomalie_moy_C", "z_max"]
    return pd.DataFrame(rows, columns=cols).sort_values(["jours", "z_max"], ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- Q2
def visibility_correlations(hourly: pd.DataFrame) -> pd.Series:
    """Corrélation de Spearman (robuste aux relations non linéaires) avec la visibilité."""
    cols = [c for c in WEATHER_VARS if c in hourly]
    corr = hourly[cols].corr(method="spearman")["visibility"].drop("visibility")
    return corr.sort_values()


def visibility_by_condition(hourly: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Visibilité moyenne par classe de pluie, de vent et de pression."""
    df = hourly.dropna(subset=["visibility"]).copy()
    df["pluie"] = pd.cut(df["precipitation"], [-0.01, 0.0, 1, 4, np.inf],
                         labels=["sèche", "faible (<1 mm/h)", "modérée (1-4)", "forte (>4)"])
    df["vent"] = pd.cut(df["wind_speed"], [-0.1, 2, 5, 10, np.inf], labels=["calme <2", "2-5", "5-10", ">10 m/s"])
    df["pression"] = pd.cut(df["pressure"], [0, 1005, 1015, 1025, 2000],
                            labels=["<1005 (dépression)", "1005-1015", "1015-1025", ">1025 (anticyclone)"])
    df["mois"] = df["ts_local"].dt.month
    out = {}
    for col in ("pluie", "vent", "pression", "mois"):
        out[col] = df.groupby(col, observed=True)["visibility"].agg(
            visibilite_moy_km="mean", part_brouillard=lambda v: (v < 1).mean(), n="size"
        ).round(3)
    return out


# --------------------------------------------------------------------------- Q3
def seasonal_profile(daily: pd.DataFrame, group: str | None = "city") -> pd.DataFrame:
    """Température moyenne mensuelle (série chronologique)."""
    keys = ([group] if group else []) + [pd.Grouper(key="day", freq="MS")]
    return daily.groupby(keys)["t_mean"].mean().reset_index().rename(columns={"day": "month"})


def monthly_climatology(daily: pd.DataFrame, group: str = "city") -> pd.DataFrame:
    """Normale mensuelle par ville : lignes = mois (1-12), colonnes = villes."""
    df = daily.assign(mois=daily["day"].dt.month)
    return df.pivot_table(index="mois", columns=group, values="t_mean", aggfunc="mean").round(1)


def seasonal_amplitude(daily: pd.DataFrame, group: str = "city") -> pd.DataFrame:
    clim = monthly_climatology(daily, group)
    return pd.DataFrame({
        "mois_le_plus_froid_C": clim.min(), "mois_le_plus_chaud_C": clim.max(),
        "amplitude_C": clim.max() - clim.min(),
    }).sort_values("amplitude_C", ascending=False)


def yearly_trend(daily: pd.DataFrame, group: str = "city") -> pd.DataFrame:
    """Température moyenne annuelle (années complètes uniquement)."""
    df = daily.assign(annee=daily["day"].dt.year)
    counts = df.groupby([group, "annee"])["day"].transform("size")
    return df[counts >= 330].pivot_table(index="annee", columns=group, values="t_mean").round(2)


# --------------------------------------------------------------------------- Q4
def extreme_days(daily: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par (ville, jour) présentant au moins une condition extrême."""
    df = daily.copy()
    flags = []
    for name, (col, op, thr) in EXTREME_THRESHOLDS.items():
        if col in df:
            df[name] = df[col] >= thr if op == ">=" else df[col] <= thr
            flags.append(name)
    df["n_conditions"] = df[flags].sum(axis=1)
    df["conditions"] = df[flags].apply(lambda r: ", ".join(f for f in flags if r[f]), axis=1)
    keep = ["city", "day", "conditions", "n_conditions", "t_min", "t_max", "wind_max", "precipitation", "visibility_min"]
    keep = [c for c in keep if c in df]
    return df.loc[df["n_conditions"] > 0, keep].sort_values(["n_conditions", "day"], ascending=[False, True])


def extreme_summary(extremes: pd.DataFrame) -> pd.DataFrame:
    """Nombre de jours extrêmes par ville et par type."""
    exploded = extremes.assign(condition=extremes["conditions"].str.split(", ")).explode("condition")
    return exploded.pivot_table(index="city", columns="condition", values="day", aggfunc="count", fill_value=0)

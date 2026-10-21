"""Helpers graphiques communs au notebook (matplotlib uniquement)."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PALETTE = {"batch": "#2563eb", "streaming": "#059669", "iot": "#ea580c", "cross": "#7c3aed"}


def setup() -> None:
    plt.rcParams.update({
        "figure.figsize": (11, 4.5),
        "figure.dpi": 100,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "legend.frameon": False,
    })


def geo_scatter(ax, df: pd.DataFrame, value: str, cmap: str = "RdYlGn", size=None, vmin=None, vmax=None,
                title: str = "", label: str = ""):
    """Carte simple lat/lon (projection équirectangulaire corrigée de la latitude)."""
    sc = ax.scatter(df["longitude"], df["latitude"], c=df[value], cmap=cmap, s=size if size is not None else 12,
                    vmin=vmin, vmax=vmax, alpha=0.85, edgecolors="none")
    ax.set_aspect(1 / np.cos(np.radians(df["latitude"].mean())))
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    plt.colorbar(sc, ax=ax, shrink=0.8, label=label)
    return sc


def heatmap(ax, table: pd.DataFrame, cmap: str = "RdBu_r", center: float | None = 0, fmt: str = "{:.2f}",
            title: str = ""):
    values = table.to_numpy(dtype=float)
    if center is not None:
        lim = np.nanmax(np.abs(values - center))
        im = ax.imshow(values, cmap=cmap, vmin=center - lim, vmax=center + lim, aspect="auto")
    else:
        im = ax.imshow(values, cmap=cmap, aspect="auto")
    ax.set_xticks(range(table.shape[1]), [str(c) for c in table.columns], rotation=45, ha="right")
    ax.set_yticks(range(table.shape[0]), [str(i) for i in table.index])
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            if not np.isnan(values[i, j]):
                ax.text(j, i, fmt.format(values[i, j]), ha="center", va="center", fontsize=8)
    ax.grid(False)
    ax.set_title(title)
    plt.colorbar(im, ax=ax, shrink=0.8)
    return im


def no_data(message: str) -> None:
    print(f"⚠️  Pas encore de données : {message}")

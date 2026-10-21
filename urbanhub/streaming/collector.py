"""Collecteur temps réel CityBikes : interroge les réseaux des grandes villes toutes les 2-3 minutes.

Chaque cycle :
    1. récupère en parallèle l'état de tous les réseaux suivis ;
    2. archive la réponse brute dans le Data Lake (bronze/citybikes/...) ;
    3. met à jour le référentiel des stations et ajoute les statuts dans PostgreSQL.

Usage :
    python -m urbanhub bikes                    # boucle infinie, toutes les 150 s
    python -m urbanhub bikes --once             # un seul cycle (test)
    python -m urbanhub bikes --duration 120     # tourne pendant 2 heures
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from urbanhub import config
from urbanhub.storage import DataLake, Warehouse
from urbanhub.streaming.citybikes_client import CityBikesClient
from urbanhub.streaming.transform import parse_network

log = logging.getLogger(__name__)


def tracked_networks() -> dict[str, str]:
    """{network_id: ville} pour les grandes villes configurées."""
    return {c.bike_network: c.name for c in config.CITIES.values() if c.bike_network}


def collect_once(client: CityBikesClient, lake: DataLake, wh: Warehouse, networks: dict[str, str]) -> int:
    now = datetime.now(timezone.utc)

    def fetch(network_id: str):
        try:
            return network_id, client.network(network_id)
        except Exception as exc:
            log.warning("Réseau %s indisponible : %s", network_id, exc)
            return network_id, None

    with ThreadPoolExecutor(max_workers=len(networks)) as pool:
        responses = list(pool.map(fetch, networks))

    total = 0
    for network_id, data in responses:
        if data is None:
            continue
        lake.put_json(f"bronze/citybikes/network={network_id}/date={now:%Y-%m-%d}/{now:%H%M%S}.json", data)
        ref, status = parse_network(data, networks[network_id])
        wh.upsert(ref, "bike_station", ["station_id"])
        total += wh.upsert(status, "bike_status", ["station_id", "ts"], update=False)
    return total


def run(interval: int = config.BIKES_INTERVAL_SECONDS, once: bool = False, duration_min: float | None = None) -> None:
    client, lake, wh = CityBikesClient(), DataLake(), Warehouse()
    lake.ensure_bucket()
    wh.init_schema()
    networks = tracked_networks()
    log.info("Suivi de %d réseaux : %s", len(networks), ", ".join(networks))

    deadline = time.time() + duration_min * 60 if duration_min else None
    cycle = 0
    while True:
        start = time.time()
        cycle += 1
        try:
            n = collect_once(client, lake, wh, networks)
            log.info("Cycle %d : %d nouveaux statuts en %.1f s", cycle, n, time.time() - start)
        except Exception:
            log.exception("Cycle %d en échec, nouvel essai au prochain intervalle", cycle)
        if once or (deadline and time.time() >= deadline):
            break
        time.sleep(max(0.0, interval - (time.time() - start)))

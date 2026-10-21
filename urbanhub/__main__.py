"""Point d'entrée unique : `python -m urbanhub <commande>`.

Commandes :
    init            crée le bucket MinIO et le schéma PostgreSQL
    batch           Partie 1 - téléchargement parallèle + nettoyage NOAA
    bikes           Partie 2 - collecteur CityBikes (toutes les 2-3 min)
    air             Partie 3 - collecteur IoT OpenAQ (flux régulier)
    air-backfill    Partie 3 - historique horaire OpenAQ
    weather-recent  météo récente Open-Meteo (pour l'analyse croisée)
    status          état du Data Lake et de l'entrepôt
"""
from __future__ import annotations

import argparse
import logging

from urbanhub import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="urbanhub", description="Plateforme UrbanHub")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialise MinIO et PostgreSQL")

    p = sub.add_parser("batch", help="Partie 1 : NOAA Global Hourly")
    p.add_argument("--years", type=int, default=config.NOAA_YEARS)
    p.add_argument("--workers", type=int, default=config.NOAA_WORKERS)
    p.add_argument("--cities-only", action="store_true", help="seulement les stations des grandes villes")
    p.add_argument("--max-stations", type=int, help="limite le nombre de stations (test)")
    p.add_argument("--force", action="store_true", help="retélécharge les fichiers déjà traités")

    for name, interval in (("bikes", config.BIKES_INTERVAL_SECONDS), ("air", config.AIR_INTERVAL_SECONDS)):
        p = sub.add_parser(name, help=f"collecteur {name}")
        p.add_argument("--interval", type=int, default=interval, help="secondes entre deux cycles")
        p.add_argument("--once", action="store_true", help="un seul cycle")
        p.add_argument("--duration", type=float, help="durée maximale en minutes")

    p = sub.add_parser("air-backfill", help="historique OpenAQ")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--since", help="date de début AAAA-MM-JJ (prioritaire sur --days)")

    p = sub.add_parser("weather-recent", help="météo récente Open-Meteo")
    p.add_argument("--past-days", type=int, default=92)

    sub.add_parser("status", help="volumes stockés")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.command == "init":
        from urbanhub.storage import DataLake, Warehouse
        DataLake().ensure_bucket()
        Warehouse().init_schema()
    elif args.command == "batch":
        from urbanhub.batch import pipeline
        pipeline.run(args.years, args.workers, args.cities_only, args.max_stations, args.force)
    elif args.command == "bikes":
        from urbanhub.streaming import collector
        collector.run(args.interval, args.once, args.duration)
    elif args.command == "air":
        from urbanhub.iot import collector
        collector.run(args.interval, args.once, args.duration)
    elif args.command == "air-backfill":
        from urbanhub.iot import backfill
        backfill.run(args.days, args.since)
    elif args.command == "weather-recent":
        from urbanhub.enrichment import open_meteo
        open_meteo.run(args.past_days)
    elif args.command == "status":
        from urbanhub.storage import DataLake, Warehouse
        print("Data Lake (MinIO)\n", DataLake().summary().to_string(index=False))
        print("\nEntrepôt (PostgreSQL)\n", Warehouse().table_counts().to_string(index=False))


if __name__ == "__main__":
    main()

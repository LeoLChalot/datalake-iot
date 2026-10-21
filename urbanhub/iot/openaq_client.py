"""Client de l'API OpenAQ v3 (https://docs.openaq.org/), avec limitation de débit.

Une clé API gratuite est nécessaire (variable OPENAQ_API_KEY).
Limite du plan gratuit : 60 requêtes / minute et 2 000 / heure.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterator

import requests

from urbanhub import config

log = logging.getLogger(__name__)


class OpenAQError(RuntimeError):
    pass


class OpenAQClient:
    def __init__(self, api_key: str = config.OPENAQ_API_KEY, min_delay: float = config.OPENAQ_MIN_DELAY_SECONDS):
        if not api_key:
            raise OpenAQError(
                "OPENAQ_API_KEY manquante : créez une clé gratuite sur https://explore.openaq.org/register "
                "puis ajoutez-la au fichier .env"
            )
        self.session = requests.Session()
        self.session.headers["X-API-Key"] = api_key
        self.min_delay = min_delay
        self._last_call = 0.0
        self._lock = threading.Lock()

    def _get(self, path: str, **params) -> dict:
        for attempt in range(6):
            with self._lock:  # au plus une requête toutes les `min_delay` secondes
                wait = self.min_delay - (time.time() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
                self._last_call = time.time()
            resp = self.session.get(f"{config.OPENAQ_BASE_URL}{path}", params=params, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("x-ratelimit-reset", 0) or 0) or 5 * (attempt + 1)
                log.warning("OpenAQ %s (%s), nouvel essai dans %.0f s", resp.status_code, path, delay)
                time.sleep(delay)
                continue
            if resp.status_code == 401:
                raise OpenAQError("Clé OpenAQ refusée (401)")
            resp.raise_for_status()
            return resp.json()
        raise OpenAQError(f"Échec répété sur {path}")

    def _paginate(self, path: str, limit: int = 1000, **params) -> Iterator[dict]:
        page = 1
        while True:
            results = self._get(path, limit=limit, page=page, **params).get("results", [])
            yield from results
            if len(results) < limit:
                return
            page += 1

    # ------------------------------------------------------------------ endpoints
    def locations(self, iso: str = "FR") -> list[dict]:
        """Toutes les stations de mesure d'un pays."""
        return list(self._paginate("/locations", iso=iso))

    def latest(self, location_id: int) -> list[dict]:
        """Dernière valeur de chaque capteur d'une station."""
        return self._get(f"/locations/{location_id}/latest").get("results", [])

    def sensor_hours(self, sensor_id: int, date_from: str, date_to: str) -> list[dict]:
        """Moyennes horaires d'un capteur sur une période (ISO 8601)."""
        return list(self._paginate(f"/sensors/{sensor_id}/hours", datetime_from=date_from, datetime_to=date_to))

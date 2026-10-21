"""Client minimal de l'API CityBikes v2 (https://api.citybik.es/v2/)."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from urbanhub import config


class CityBikesClient:
    def __init__(self, base_url: str = config.CITYBIKES_BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, path: str, **params) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def networks(self, country: str = "FR") -> list[dict]:
        nets = self._get("/networks")["networks"]
        return [n for n in nets if n["location"]["country"] == country]

    def network(self, network_id: str) -> dict:
        """Réseau complet avec la liste de ses stations et leur état courant."""
        return self._get(f"/networks/{network_id}", fields="id,name,location,stations")["network"]

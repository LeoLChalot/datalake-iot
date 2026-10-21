"""Téléchargement PARALLÈLE des fichiers NOAA (un fichier = une station x une année)."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from urbanhub import config

log = logging.getLogger(__name__)

_local = threading.local()


@dataclass(frozen=True)
class NoaaFile:
    year: int
    station_id: str

    @property
    def url(self) -> str:
        return f"{config.NOAA_BASE_URL}/{self.year}/{self.station_id}.csv"


def _session() -> requests.Session:
    """Une session HTTP par thread (réutilisation des connexions + retries)."""
    if not hasattr(_local, "session"):
        s = requests.Session()
        retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=4))
        _local.session = s
    return _local.session


def download(file: NoaaFile) -> bytes:
    resp = _session().get(file.url, timeout=120)
    resp.raise_for_status()
    return resp.content


def download_parallel(
    files: Iterable[NoaaFile],
    process: Callable[[NoaaFile, bytes], object],
    workers: int = config.NOAA_WORKERS,
) -> Iterator[tuple[NoaaFile, object | Exception]]:
    """Télécharge les fichiers sur `workers` threads et applique `process` à chacun.

    Les résultats sont restitués au fil de l'eau (as_completed), ce qui permet au
    consommateur de charger la base pendant que les téléchargements continuent.
    """
    files = list(files)
    start = time.time()

    def task(f: NoaaFile):
        return process(f, download(f))

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="noaa") as pool:
        futures = {pool.submit(task, f): f for f in files}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # un fichier en échec ne bloque pas le batch
                log.warning("Échec %s : %s", f.url, exc)
                result = exc
            if i % 25 == 0 or i == len(files):
                log.info("%d/%d fichiers traités (%.0f s)", i, len(files), time.time() - start)
            yield f, result

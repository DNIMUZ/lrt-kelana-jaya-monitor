from __future__ import annotations

from pathlib import Path

import requests

from ..models import OfficialFact

PRASARANA_GTFS_URL = "https://api.data.gov.my/gtfs-static/prasarana"


def download_prasarana_gtfs(
    destination: str | Path,
    category: str = "rapid-rail-kl",
    timeout: int = 30,
) -> Path:
    """Download the documented Prasarana GTFS static ZIP feed."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        PRASARANA_GTFS_URL,
        params={"category": category},
        timeout=timeout,
    )
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def fetch_official_fact() -> OfficialFact:
    """Return a safe placeholder until an approved official feed is configured."""
    return OfficialFact()

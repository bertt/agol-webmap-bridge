"""GeoNode API v2 client."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class GeoNodeError(Exception):
    """Raised when a GeoNode API call fails."""


def fetch_datasets(geonode_url: str) -> list[dict]:
    """Fetch all datasets from a GeoNode instance (handles pagination).

    Args:
        geonode_url: Base URL of the GeoNode instance, e.g. ``https://example.com``.

    Returns:
        Flat list of dataset dicts from the GeoNode API.

    Raises:
        GeoNodeError: On HTTP error or non-JSON response.
    """
    geonode_url = geonode_url.rstrip("/")
    url = f"{geonode_url}/api/v2/datasets/"
    datasets: list[dict] = []
    page = 1

    while url:
        logger.debug("Fetching datasets page %d from %s", page, url)
        try:
            response = requests.get(url, params={"page_size": 100}, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise GeoNodeError(f"Failed to fetch datasets from '{geonode_url}': {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise GeoNodeError(f"Invalid JSON from GeoNode at '{url}'") from exc

        datasets.extend(data.get("datasets", []))
        url = data.get("links", {}).get("next")
        page += 1

    logger.info("Fetched %d datasets from %s", len(datasets), geonode_url)
    return datasets

"""ArcGIS Online REST API client."""

from __future__ import annotations

import requests


AGOL_BASE_URL = "https://www.arcgis.com/sharing/rest/content/items"


class AGOLError(Exception):
    """Raised when the AGOL API call fails."""


def fetch_webmap(guid: str) -> dict:
    """Fetch webmap JSON from ArcGIS Online.

    Args:
        guid: The item GUID of the webmap.

    Returns:
        Parsed webmap JSON as a dict.

    Raises:
        AGOLError: On HTTP error or non-JSON response.
    """
    url = f"{AGOL_BASE_URL}/{guid}/data"
    try:
        response = requests.get(url, params={"f": "json"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AGOLError(f"Failed to fetch webmap '{guid}': {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise AGOLError(f"Invalid JSON returned for webmap '{guid}'") from exc

    if "error" in data:
        raise AGOLError(f"AGOL error for webmap '{guid}': {data['error']}")

    return data

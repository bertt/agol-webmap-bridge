"""ArcGIS Online REST API client."""

from __future__ import annotations

import requests


AGOL_BASE_URL = "https://www.arcgis.com/sharing/rest/content/items"


class AGOLError(Exception):
    """Raised when the AGOL API call fails."""


def _fetch_item_data(guid: str) -> dict:
    """Fetch and parse the /data JSON for any AGOL item GUID."""
    url = f"{AGOL_BASE_URL}/{guid}/data"
    try:
        response = requests.get(url, params={"f": "json"}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AGOLError(f"Failed to fetch item '{guid}': {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise AGOLError(f"Invalid JSON returned for item '{guid}'") from exc

    if "error" in data:
        raise AGOLError(f"AGOL error for item '{guid}': {data['error']}")

    return data


def fetch_app_configuration(guid: str) -> tuple[str, str]:
    """Fetch an AppConfiguration item and extract the webmap title and GUID.

    Args:
        guid: The item GUID of the AppConfiguration.

    Returns:
        A tuple of (webmap_title, webmap_guid).

    Raises:
        AGOLError: If the item cannot be fetched, is not a webmap app, or
                   required fields are missing.
    """
    data = _fetch_item_data(guid)

    values: dict = data.get("values", {})

    if values.get("type") != "webmap":
        raise AGOLError(
            f"Item '{guid}' is not a webmap AppConfiguration "
            f"(values.type={values.get('type')!r}). Stopping."
        )

    title: str = values.get("title", "")
    if not title:
        raise AGOLError(f"AppConfiguration '{guid}' has no 'title' field in values.")

    webmap_guid: str = values.get("webmap", "")
    if not webmap_guid:
        raise AGOLError(f"AppConfiguration '{guid}' has no 'webmap' field in values.")

    return title, webmap_guid


def fetch_webmap(guid: str) -> dict:
    """Fetch webmap JSON from ArcGIS Online.

    Args:
        guid: The item GUID of the webmap.

    Returns:
        Parsed webmap JSON as a dict.

    Raises:
        AGOLError: On HTTP error or non-JSON response.
    """
    return _fetch_item_data(guid)

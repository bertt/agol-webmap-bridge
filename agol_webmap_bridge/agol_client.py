"""ArcGIS Online REST API client."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

AGOL_BASE_URL = "https://www.arcgis.com/sharing/rest/content/items"


class AGOLError(Exception):
    """Raised when the AGOL API call fails."""


def fetch_layer_name(url: str) -> str:
    """Fetch the layer name from an ArcGIS REST service endpoint.

    Calls ``GET <url>?f=json`` and returns the ``name`` field from the
    response.  Returns an empty string when the URL is blank, the request
    fails, or the response contains no ``name`` field.

    Args:
        url: Full URL of an ArcGIS REST layer or service endpoint.

    Returns:
        The ``name`` value reported by the service, or ``""`` on any error.
    """
    if not url:
        return ""
    try:
        response = requests.get(url, params={"f": "json"}, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get("name", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch layer name from '%s': %s", url, exc)
        return ""


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


def detect_and_fetch_webmap(guid: str) -> tuple[str, str, dict]:
    """Auto-detect whether *guid* is a webmap or an AppConfiguration and fetch accordingly.

    Detection rules:
    - If the returned JSON contains ``operationalLayers`` it is treated as a
      direct webmap GUID.
    - If the returned JSON contains ``values.type == "webmap"`` it is treated
      as an AppConfiguration GUID; the webmap GUID is extracted and fetched.
    - Otherwise an :class:`AGOLError` is raised.

    Args:
        guid: An AGOL item GUID — either a webmap or an AppConfiguration.

    Returns:
        A tuple of (guid_type, webmap_title, webmap_data) where *guid_type* is
        ``"webmap"`` or ``"appconfiguration"``.

    Raises:
        AGOLError: If the item cannot be fetched or is neither a webmap nor a
                   supported AppConfiguration.
    """
    data = _fetch_item_data(guid)

    # Direct webmap: has operationalLayers at the top level
    if "operationalLayers" in data:
        title: str = data.get("title", "") or guid
        return "webmap", title, data

    # AppConfiguration: has values.type == "webmap"
    values: dict = data.get("values", {})
    if values.get("type") == "webmap":
        title = values.get("title", "")
        if not title:
            raise AGOLError(f"AppConfiguration '{guid}' has no 'title' field in values.")
        webmap_guid: str = values.get("webmap", "")
        if not webmap_guid:
            raise AGOLError(f"AppConfiguration '{guid}' has no 'webmap' field in values.")
        webmap_data = fetch_webmap(webmap_guid)
        return "appconfiguration", title, webmap_data

    raise AGOLError(
        f"Item '{guid}' is neither a webmap (no 'operationalLayers') nor a "
        f"supported AppConfiguration (values.type={values.get('type')!r})."
    )

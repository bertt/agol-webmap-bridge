"""Tests for agol_client."""

import pytest
import requests

from agol_webmap_bridge.agol_client import AGOLError, fetch_webmap


GUID = "8a9a419b704e4e03bb98d9f14226a743"
SAMPLE_DATA = {"operationalLayers": [], "version": "2.27"}


def test_fetch_webmap_success(requests_mock):
    url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(url, json=SAMPLE_DATA)

    result = fetch_webmap(GUID)
    assert result == SAMPLE_DATA


def test_fetch_webmap_http_error(requests_mock):
    url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(url, status_code=404)

    with pytest.raises(AGOLError, match=GUID):
        fetch_webmap(GUID)


def test_fetch_webmap_agol_error_in_response(requests_mock):
    url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(url, json={"error": {"code": 400, "message": "Item not found"}})

    with pytest.raises(AGOLError, match="AGOL error"):
        fetch_webmap(GUID)


def test_fetch_webmap_invalid_json(requests_mock):
    url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(url, text="not-json", headers={"Content-Type": "text/html"})

    with pytest.raises(AGOLError):
        fetch_webmap(GUID)

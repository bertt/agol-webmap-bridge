"""Tests for agol_client — including auto-detection logic."""

from __future__ import annotations

import pytest
import requests_mock as requests_mock_module

from agol_webmap_bridge.agol_client import (
    AGOLError,
    AGOL_BASE_URL,
    detect_and_fetch_webmap,
    fetch_app_configuration,
    fetch_webmap,
)

WEBMAP_GUID = "d0b3a31896d84b0592a32a61c1334532"
APPCFG_GUID = "2b214417eea74ae9a56119c251ffa960"

WEBMAP_DATA = {
    "title": "My Webmap",
    "operationalLayers": [
        {"id": "layer1", "title": "Layer 1", "layerType": "ArcGISFeatureLayer"},
    ],
    "spatialReference": {"wkid": 4326},
}

APPCFG_DATA = {
    "values": {
        "type": "webmap",
        "title": "My App Config",
        "webmap": WEBMAP_GUID,
    }
}

UNKNOWN_DATA = {
    "values": {
        "type": "dashboard",
    }
}


# ---------------------------------------------------------------------------
# detect_and_fetch_webmap — direct webmap GUID
# ---------------------------------------------------------------------------

def test_detect_direct_webmap(requests_mock):
    requests_mock.get(
        f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data",
        json=WEBMAP_DATA,
    )
    guid_type, title, data = detect_and_fetch_webmap(WEBMAP_GUID)
    assert guid_type == "webmap"
    assert title == "My Webmap"
    assert data["operationalLayers"][0]["title"] == "Layer 1"


def test_detect_direct_webmap_uses_guid_as_title_when_missing(requests_mock):
    webmap_no_title = {**WEBMAP_DATA}
    del webmap_no_title["title"]
    requests_mock.get(
        f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data",
        json=webmap_no_title,
    )
    _, title, _ = detect_and_fetch_webmap(WEBMAP_GUID)
    assert title == WEBMAP_GUID


# ---------------------------------------------------------------------------
# detect_and_fetch_webmap — AppConfiguration GUID
# ---------------------------------------------------------------------------

def test_detect_appconfiguration(requests_mock):
    requests_mock.get(
        f"{AGOL_BASE_URL}/{APPCFG_GUID}/data",
        json=APPCFG_DATA,
    )
    requests_mock.get(
        f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data",
        json=WEBMAP_DATA,
    )
    guid_type, title, data = detect_and_fetch_webmap(APPCFG_GUID)
    assert guid_type == "appconfiguration"
    assert title == "My App Config"
    assert "operationalLayers" in data


def test_detect_appconfiguration_missing_title_raises(requests_mock):
    bad_cfg = {"values": {"type": "webmap", "webmap": WEBMAP_GUID}}
    requests_mock.get(f"{AGOL_BASE_URL}/{APPCFG_GUID}/data", json=bad_cfg)
    with pytest.raises(AGOLError, match="no 'title'"):
        detect_and_fetch_webmap(APPCFG_GUID)


def test_detect_appconfiguration_missing_webmap_field_raises(requests_mock):
    bad_cfg = {"values": {"type": "webmap", "title": "No Webmap Field"}}
    requests_mock.get(f"{AGOL_BASE_URL}/{APPCFG_GUID}/data", json=bad_cfg)
    with pytest.raises(AGOLError, match="no 'webmap'"):
        detect_and_fetch_webmap(APPCFG_GUID)


# ---------------------------------------------------------------------------
# detect_and_fetch_webmap — unknown type raises
# ---------------------------------------------------------------------------

def test_detect_unknown_type_raises(requests_mock):
    requests_mock.get(f"{AGOL_BASE_URL}/{APPCFG_GUID}/data", json=UNKNOWN_DATA)
    with pytest.raises(AGOLError, match="neither a webmap"):
        detect_and_fetch_webmap(APPCFG_GUID)


# ---------------------------------------------------------------------------
# HTTP / API error handling
# ---------------------------------------------------------------------------

def test_detect_http_error_raises(requests_mock):
    requests_mock.get(
        f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data",
        status_code=500,
    )
    with pytest.raises(AGOLError):
        detect_and_fetch_webmap(WEBMAP_GUID)


def test_detect_agol_error_in_response_raises(requests_mock):
    requests_mock.get(
        f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data",
        json={"error": {"code": 400, "message": "Invalid parameter"}},
    )
    with pytest.raises(AGOLError, match="AGOL error"):
        detect_and_fetch_webmap(WEBMAP_GUID)


# ---------------------------------------------------------------------------
# fetch_app_configuration (legacy)
# ---------------------------------------------------------------------------

def test_fetch_app_configuration_success(requests_mock):
    requests_mock.get(f"{AGOL_BASE_URL}/{APPCFG_GUID}/data", json=APPCFG_DATA)
    title, webmap_guid = fetch_app_configuration(APPCFG_GUID)
    assert title == "My App Config"
    assert webmap_guid == WEBMAP_GUID


def test_fetch_app_configuration_wrong_type_raises(requests_mock):
    requests_mock.get(f"{AGOL_BASE_URL}/{APPCFG_GUID}/data", json=UNKNOWN_DATA)
    with pytest.raises(AGOLError, match="not a webmap AppConfiguration"):
        fetch_app_configuration(APPCFG_GUID)


# ---------------------------------------------------------------------------
# fetch_webmap (legacy)
# ---------------------------------------------------------------------------

def test_fetch_webmap_success(requests_mock):
    requests_mock.get(f"{AGOL_BASE_URL}/{WEBMAP_GUID}/data", json=WEBMAP_DATA)
    data = fetch_webmap(WEBMAP_GUID)
    assert data["title"] == "My Webmap"

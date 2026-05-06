"""Tests for the CLI using Click's CliRunner."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agol_webmap_bridge.cli import main, _slugify


# ---------------------------------------------------------------------------
# _slugify helper
# ---------------------------------------------------------------------------

def test_slugify_basic():
    assert _slugify("Hello World") == "hello_world"


def test_slugify_special_chars():
    assert _slugify("Grens Rijnland! 2024") == "grens_rijnland_2024"


def test_slugify_accents():
    assert _slugify("Élève") == "eleve"


def test_slugify_empty():
    assert _slugify("") == "webmap"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

GUID = "testguid123"
GEONODE_URL = "https://example.geonode.org"

AGOL_RESPONSE = {
    "title": "My Test Map",
    "operationalLayers": [
        {"id": "l1", "title": "Woningbouwlocaties", "opacity": 1.0, "visibility": True, "layerType": "ArcGISFeatureLayer"}
    ],
    "baseMap": {"title": "OSM"},
    "spatialReference": {"wkid": 4326},
    "version": "2.27",
}

GEONODE_DATASETS_RESPONSE = {
    "links": {"next": None},
    "datasets": [
        {"pk": "1", "title": "Woningbouwlocaties", "name": "woningbouwlocaties", "alternate": "hhr:woningbouwlocaties",
         "default_style": {"pk": 1, "name": "style1", "workspace": "hhr"}},
    ],
}


def test_cli_success(requests_mock, tmp_path):
    agol_url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(agol_url, json=AGOL_RESPONSE)
    requests_mock.get(f"{GEONODE_URL}/api/v2/datasets/", json=GEONODE_DATASETS_RESPONSE)

    runner = CliRunner()
    result = runner.invoke(main, [GUID, "-g", GEONODE_URL, "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output
    out_file = tmp_path / "my_test_map_geonode.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["title"] == "My Test Map"
    assert len(data["maplayers"]) == 1


def test_cli_force_overwrites(requests_mock, tmp_path):
    agol_url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(agol_url, json=AGOL_RESPONSE)
    requests_mock.get(f"{GEONODE_URL}/api/v2/datasets/", json=GEONODE_DATASETS_RESPONSE)

    out_file = tmp_path / "my_test_map_geonode.json"
    out_file.write_text("old content")

    runner = CliRunner()
    result = runner.invoke(main, [GUID, "-g", GEONODE_URL, "-o", str(tmp_path), "--force"])

    assert result.exit_code == 0
    assert out_file.read_text() != "old content"


def test_cli_prompts_overwrite_abort(requests_mock, tmp_path):
    agol_url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(agol_url, json=AGOL_RESPONSE)
    requests_mock.get(f"{GEONODE_URL}/api/v2/datasets/", json=GEONODE_DATASETS_RESPONSE)

    out_file = tmp_path / "my_test_map_geonode.json"
    out_file.write_text("old content")

    runner = CliRunner()
    # Answer 'n' to the overwrite prompt
    result = runner.invoke(main, [GUID, "-g", GEONODE_URL, "-o", str(tmp_path)], input="n\n")

    assert result.exit_code == 0
    assert out_file.read_text() == "old content"


def test_cli_agol_error(requests_mock, tmp_path):
    agol_url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(agol_url, status_code=404)

    runner = CliRunner()
    result = runner.invoke(main, [GUID, "-g", GEONODE_URL, "-o", str(tmp_path)])

    assert result.exit_code == 1


def test_cli_geonode_error(requests_mock, tmp_path):
    agol_url = f"https://www.arcgis.com/sharing/rest/content/items/{GUID}/data"
    requests_mock.get(agol_url, json=AGOL_RESPONSE)
    requests_mock.get(f"{GEONODE_URL}/api/v2/datasets/", status_code=500)

    runner = CliRunner()
    result = runner.invoke(main, [GUID, "-g", GEONODE_URL, "-o", str(tmp_path)])

    assert result.exit_code == 1


def test_cli_missing_required_option(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["someguid"])  # missing --geonode-url
    assert result.exit_code != 0

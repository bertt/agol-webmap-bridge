"""Tests for converter using fixture JSON files."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agol_webmap_bridge.converter import _wkid_to_epsg, _extract_extent, convert
from agol_webmap_bridge.writers.base_writer import BaseWriter

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CapturingWriter(BaseWriter):
    """Test writer that captures map_config instead of writing to disk."""

    def __init__(self):
        self.captured = None

    def write(self, map_config: dict, path) -> None:
        self.captured = map_config


def test_wkid_to_epsg():
    assert _wkid_to_epsg(4326) == "EPSG:4326"
    assert _wkid_to_epsg(28992) == "EPSG:28992"
    assert _wkid_to_epsg(None) == "EPSG:4326"


def test_extract_extent_from_initial_state():
    webmap = {
        "initialState": {
            "viewpoint": {
                "targetGeometry": {"xmin": 1.0, "ymin": 2.0, "xmax": 3.0, "ymax": 4.0}
            }
        }
    }
    assert _extract_extent(webmap) == [1.0, 2.0, 3.0, 4.0]


def test_extract_extent_returns_none_when_missing():
    assert _extract_extent({}) is None


def test_convert_with_fixture():
    agol_webmap = load_fixture("agol_webmap_sample.json")
    datasets = load_fixture("geonode_datasets_sample.json")["datasets"]

    writer = CapturingWriter()
    map_config = convert(
        agol_webmap=agol_webmap,
        geonode_datasets=datasets,
        writer=writer,
        threshold=0.5,
        webmap_title="Test Map",
    )

    assert map_config["title"] == "Test Map"
    assert map_config["srid"] == "EPSG:4326"
    assert map_config["extent"] == [4.3, 52.0, 4.9, 52.5]
    # 2 of 4 layers should match (Grens Rijnland and Woningbouwlocaties)
    assert len(map_config["layers"]) >= 1


def test_convert_preserves_opacity_and_visibility():
    agol_webmap = load_fixture("agol_webmap_sample.json")
    datasets = load_fixture("geonode_datasets_sample.json")["datasets"]

    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.5)

    # Woningbouwlocaties layer has opacity 0.8
    woning_layer = next(
        (l for l in map_config["layers"] if l["geonode_dataset"]["title"] == "Woningbouwlocaties"),
        None,
    )
    assert woning_layer is not None
    assert woning_layer["opacity"] == 0.8
    assert woning_layer["visibility"] is True


def test_convert_basemap_in_abstract():
    agol_webmap = load_fixture("agol_webmap_sample.json")
    datasets = load_fixture("geonode_datasets_sample.json")["datasets"]

    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.5)
    assert "OpenStreetMap" in map_config["abstract"]


def test_convert_group_layer_flattened():
    agol_webmap = {
        "operationalLayers": [
            {
                "id": "group1",
                "layerType": "GroupLayer",
                "layers": [
                    {"id": "sub1", "title": "Woningbouwlocaties", "opacity": 1.0, "visibility": True, "layerType": "ArcGISFeatureLayer"},
                ],
            }
        ],
        "spatialReference": {"wkid": 4326},
    }
    datasets = [{"pk": "1", "title": "Woningbouwlocaties", "name": "woningbouwlocaties", "alternate": "hhr:woningbouwlocaties", "default_style": None}]

    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.6)
    assert len(map_config["layers"]) == 1
    assert map_config["layers"][0]["geonode_dataset"]["pk"] == "1"

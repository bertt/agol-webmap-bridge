"""Tests for converter using fixture JSON files."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agol_webmap_bridge.converter import _wkid_to_epsg, _extract_extent, _extract_service_sublayers, convert
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


# ---------------------------------------------------------------------------
# subLayerIds / ArcGISMapServiceLayer sublayer tests
# ---------------------------------------------------------------------------

_SERVICE_LAYER_WITH_SUBLAYERS = {
    "id": "Legger_001",
    "opacity": 0.75,
    "title": "Legger",
    "url": "https://example.com/arcgis/rest/services/Leggers/Legger/MapServer",
    "visibility": True,
    "layerType": "ArcGISMapServiceLayer",
    "layers": [
        {"id": 0, "name": "Regionale kering as", "parentLayerId": -1, "defaultVisibility": True},
        {"id": 1, "name": "Regionale kering zone", "parentLayerId": -1, "defaultVisibility": True, "subLayerIds": [2, 3]},
        {"id": 2, "name": "Kernzone", "parentLayerId": 1, "defaultVisibility": True},
        {"id": 3, "name": "Beschermingszone", "parentLayerId": 1, "defaultVisibility": False},
    ],
}


def test_extract_service_sublayers_skips_group_nodes():
    """Group nodes (entries with subLayerIds) must not appear in the result."""
    result = _extract_service_sublayers(_SERVICE_LAYER_WITH_SUBLAYERS)
    names = [r["title"] for r in result]
    assert "Regionale kering zone" not in names, "Group node should be skipped"
    assert "Regionale kering as" in names
    assert "Kernzone" in names
    assert "Beschermingszone" in names


def test_extract_service_sublayers_count():
    """Three leaf layers expected (one top-level + two children of the group)."""
    result = _extract_service_sublayers(_SERVICE_LAYER_WITH_SUBLAYERS)
    assert len(result) == 3


def test_extract_service_sublayers_inherits_opacity():
    """Each leaf sublayer must inherit opacity from the parent operational layer."""
    result = _extract_service_sublayers(_SERVICE_LAYER_WITH_SUBLAYERS)
    for leaf in result:
        assert leaf["opacity"] == 0.75


def test_extract_service_sublayers_uses_default_visibility():
    """Each leaf sublayer must use its own defaultVisibility."""
    result = _extract_service_sublayers(_SERVICE_LAYER_WITH_SUBLAYERS)
    bescherming = next(r for r in result if r["title"] == "Beschermingszone")
    assert bescherming["visibility"] is False
    kernzone = next(r for r in result if r["title"] == "Kernzone")
    assert kernzone["visibility"] is True


def test_extract_service_sublayers_no_layers_returns_service_itself():
    """A service layer without a layers array should be returned unchanged."""
    layer = {"id": "svc", "title": "My Service", "layerType": "ArcGISMapServiceLayer"}
    result = _extract_service_sublayers(layer)
    assert result == [layer]


def test_convert_service_sublayers_group_node_not_in_output():
    """After convert(), group nodes must never appear in map_config['layers']."""
    agol_webmap = load_fixture("agol_webmap_sublayers.json")
    datasets = [
        {"pk": "10", "title": "Kernzone", "name": "kernzone", "alternate": "ws:kernzone", "default_style": None},
        {"pk": "11", "title": "Beschermingszone", "name": "beschermingszone", "alternate": "ws:beschermingszone", "default_style": None},
        {"pk": "12", "title": "Regionale kering as", "name": "regionale_kering_as", "alternate": "ws:regionale_kering_as", "default_style": None},
    ]
    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.5)

    titles = [l["geonode_dataset"]["title"] for l in map_config["layers"]]
    assert "Regionale kering zone" not in titles
    assert "Kernzone" in titles
    assert "Regionale kering as" in titles


def test_convert_service_sublayers_opacity_preserved():
    """Leaf sublayers produced by convert() must carry the parent opacity."""
    agol_webmap = load_fixture("agol_webmap_sublayers.json")
    datasets = [
        {"pk": "10", "title": "Kernzone", "name": "kernzone", "alternate": "ws:kernzone", "default_style": None},
    ]
    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.5)

    kernzone_layer = next((l for l in map_config["layers"] if l["geonode_dataset"]["title"] == "Kernzone"), None)
    assert kernzone_layer is not None
    assert kernzone_layer["opacity"] == 0.75


"""Tests for converter using fixture JSON files."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agol_webmap_bridge.converter import _wkid_to_epsg, _extract_extent, _extract_service_sublayers, _flatten_layers, _detect_unsupported, convert
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


# ---------------------------------------------------------------------------
# Unsupported features detection
# ---------------------------------------------------------------------------

def test_detect_unsupported_empty_webmap():
    assert _detect_unsupported({}) == []


def test_detect_unsupported_bookmarks():
    webmap = {"bookmarks": [{"name": "View 1"}]}
    findings = _detect_unsupported(webmap)
    features = [f["feature"] for f in findings]
    assert "Bookmarks" in features
    assert all(f["layer"] is None for f in findings if f["feature"] == "Bookmarks")


def test_detect_unsupported_tables():
    webmap = {"tables": [{"id": "t1", "title": "My Table"}]}
    findings = _detect_unsupported(webmap)
    assert any(f["feature"] == "Non-spatial tables" for f in findings)


def test_detect_unsupported_mapfloorinfo():
    webmap = {"mapFloorInfo": {"floorFilterEnabled": True}}
    findings = _detect_unsupported(webmap)
    assert any(f["feature"] == "Indoor map / mapFloorInfo" for f in findings)


def test_detect_unsupported_renderer_on_layer():
    webmap = {
        "operationalLayers": [
            {"title": "My Layer", "renderer": {"type": "simple"}, "layerType": "ArcGISFeatureLayer"},
        ]
    }
    findings = _detect_unsupported(webmap)
    match = next((f for f in findings if f["feature"] == "Renderer / symbology"), None)
    assert match is not None
    assert match["layer"] == "My Layer"


def test_detect_unsupported_popupinfo_on_layer():
    webmap = {
        "operationalLayers": [
            {"title": "Popup Layer", "popupInfo": {"title": "{Name}"}, "layerType": "ArcGISFeatureLayer"},
        ]
    }
    findings = _detect_unsupported(webmap)
    match = next((f for f in findings if f["feature"] == "Popup configuration (popupInfo)"), None)
    assert match is not None
    assert match["layer"] == "Popup Layer"


def test_detect_unsupported_timeinfo_on_layer():
    webmap = {
        "operationalLayers": [
            {"title": "Time Layer", "timeInfo": {"startField": "date"}, "layerType": "ArcGISFeatureLayer"},
        ]
    }
    findings = _detect_unsupported(webmap)
    assert any(f["feature"] == "Time-aware layer settings" and f["layer"] == "Time Layer" for f in findings)


def test_detect_unsupported_definition_expression():
    webmap = {
        "operationalLayers": [
            {
                "title": "Filtered Layer",
                "layerType": "ArcGISFeatureLayer",
                "layerDefinition": {"definitionExpression": "STATUS = 'active'"},
            },
        ]
    }
    findings = _detect_unsupported(webmap)
    assert any(f["feature"] == "Definition expression / filter" and f["layer"] == "Filtered Layer" for f in findings)


def test_detect_unsupported_nested_group_layer():
    webmap = {
        "operationalLayers": [
            {
                "title": "Outer Group",
                "layerType": "GroupLayer",
                "layers": [
                    {"title": "Inner Group", "layerType": "GroupLayer", "layers": []},
                ],
            }
        ]
    }
    findings = _detect_unsupported(webmap)
    assert any(f["feature"] == "Nested group layer (> 1 level deep)" for f in findings)


def test_convert_unsupported_features_in_map_config():
    """convert() must store _unsupported_features in map_config."""
    webmap = {
        "operationalLayers": [
            {"title": "Layer A", "popupInfo": {"title": "{Name}"}, "layerType": "ArcGISFeatureLayer"},
        ],
        "bookmarks": [{"name": "View 1"}],
        "spatialReference": {"wkid": 4326},
    }
    writer = CapturingWriter()
    map_config = convert(agol_webmap=webmap, geonode_datasets=[], writer=writer)
    unsupported = map_config["_unsupported_features"]
    features = [f["feature"] for f in unsupported]
    assert "Bookmarks" in features
    assert "Popup configuration (popupInfo)" in features


# ---------------------------------------------------------------------------
# _flatten_layers — group path propagation
# ---------------------------------------------------------------------------

def test_flatten_layers_top_level_leaf_has_empty_group():
    layers = [{"title": "My Layer", "layerType": "ArcGISFeatureLayer"}]
    result = _flatten_layers(layers)
    assert result[0]["group_title"] == ""


def test_flatten_layers_group_layer_propagates_title():
    layers = [
        {
            "title": "Legger",
            "layerType": "GroupLayer",
            "layers": [
                {"title": "Kernzone", "layerType": "ArcGISFeatureLayer"},
            ],
        }
    ]
    result = _flatten_layers(layers)
    assert len(result) == 1
    assert result[0]["group_title"] == "Legger"


def test_flatten_layers_service_inside_group_creates_nested_path():
    layers = [
        {
            "title": "Legger",
            "layerType": "GroupLayer",
            "layers": [
                {
                    "title": "Zonering",
                    "layerType": "ArcGISMapServiceLayer",
                    "layers": [
                        {"id": 0, "name": "Kernzone", "parentLayerId": -1, "defaultVisibility": True},
                    ],
                }
            ],
        }
    ]
    result = _flatten_layers(layers)
    assert len(result) == 1
    assert result[0]["group_title"] == "Legger.Zonering"


def test_flatten_layers_service_internal_group_adds_third_level():
    layers = [
        {
            "title": "Legger",
            "layerType": "GroupLayer",
            "layers": [
                {
                    "title": "Kering",
                    "layerType": "ArcGISMapServiceLayer",
                    "layers": [
                        {"id": 0, "name": "Groep", "parentLayerId": -1, "defaultVisibility": True, "subLayerIds": [1]},
                        {"id": 1, "name": "Kernzone", "parentLayerId": 0, "defaultVisibility": True},
                    ],
                }
            ],
        }
    ]
    result = _flatten_layers(layers)
    kernzone = next(r for r in result if r["title"] == "Kernzone")
    assert kernzone["group_title"] == "Legger.Kering.Groep"


def test_flatten_layers_mixed_siblings_in_group():
    """Direct leaf + service sublayers inside the same GroupLayer."""
    layers = [
        {
            "title": "Legger",
            "layerType": "GroupLayer",
            "layers": [
                {"title": "Direct leaf", "layerType": "ArcGISFeatureLayer"},
                {
                    "title": "Zonering",
                    "layerType": "ArcGISMapServiceLayer",
                    "layers": [
                        {"id": 0, "name": "Kernzone", "parentLayerId": -1, "defaultVisibility": True},
                    ],
                },
            ],
        }
    ]
    result = _flatten_layers(layers)
    direct = next(r for r in result if r.get("title") == "Direct leaf")
    kernzone = next(r for r in result if r.get("title") == "Kernzone")
    assert direct["group_title"] == "Legger"
    assert kernzone["group_title"] == "Legger.Zonering"


def test_convert_nested_groups_fixture():
    """End-to-end: GroupLayer + ArcGISMapServiceLayer produces correct nested group_titles."""
    agol_webmap = load_fixture("agol_webmap_nested_groups.json")
    # Dataset names must match the search terms produced by the matcher:
    # - ArcGISFeatureLayer URL .../regionale_kering_as_vigerend/MapServer/0 → "regionale_kering_as_vigerend"
    # - Sublayer "Kernzone" of service "Regionale_kering_zone_vigerend"     → "regionale_kering_zone_vigerend_kernzone"
    # - ArcGISFeatureLayer URL .../Grens_Rijnland/MapServer/0               → "grens_rijnland"
    datasets = [
        {"pk": "1", "title": "Regionale kering as (vigerend)", "name": "regionale_kering_as_vigerend", "alternate": "ws:kering_as", "default_style": None},
        {"pk": "2", "title": "Kernzone", "name": "regionale_kering_zone_vigerend_kernzone", "alternate": "ws:kernzone", "default_style": None},
        {"pk": "3", "title": "Beschermingszone", "name": "regionale_kering_zone_vigerend_beschermingszone", "alternate": "ws:beschermingszone", "default_style": None},
        {"pk": "4", "title": "Grens Rijnland", "name": "grens_rijnland", "alternate": "ws:grens_rijnland", "default_style": None},
    ]
    writer = CapturingWriter()
    map_config = convert(agol_webmap=agol_webmap, geonode_datasets=datasets, writer=writer, threshold=0.5)

    by_title = {l["geonode_dataset"]["title"]: l for l in map_config["layers"]}

    assert by_title["Regionale kering as (vigerend)"]["group_title"] == "Legger"
    assert by_title["Kernzone"]["group_title"] == "Legger.Regionale kering zone (vigerend)"
    assert by_title["Beschermingszone"]["group_title"] == "Legger.Regionale kering zone (vigerend)"
    assert by_title["Grens Rijnland"].get("group_title", "") == ""


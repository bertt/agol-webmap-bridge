"""Tests for GeoNodeWriter output format."""

import json
from pathlib import Path

import pytest

from agol_webmap_bridge.writers.geonode_writer import GeoNodeWriter


def _make_dataset(pk: str, title: str, alternate: str = "", style: str = "") -> dict:
    return {
        "pk": pk,
        "title": title,
        "alternate": alternate or f"ws:{title.lower()}",
        "default_style": {"name": style} if style else None,
    }


def _make_layer(pk: str, title: str, group_title: str = "", opacity: float = 1.0,
                visibility: bool = True, style: str = "") -> dict:
    layer: dict = {
        "geonode_dataset": _make_dataset(pk, title, style=style),
        "opacity": opacity,
        "visibility": visibility,
    }
    if group_title:
        layer["group_title"] = group_title
    return layer


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

def test_writer_produces_data_map_structure(tmp_path):
    map_config = {
        "title": "Test Map",
        "abstract": "Basemap: Topo",
        "srid": "EPSG:28992",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter(geonode_url="https://example.com")
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert result["title"] == "Test Map"
    assert result["abstract"] == "Basemap: Topo"
    assert "data" in result
    assert "map" in result["data"]
    map_ = result["data"]["map"]
    assert map_["projection"] == "EPSG:3857"
    assert map_["units"] == "m"
    assert "zoom" in map_
    assert "center" in map_
    assert "layers" in map_


def test_writer_osm_layer_always_first(tmp_path):
    map_config = {
        "title": "T",
        "abstract": "",
        "srid": "EPSG:3857",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    layers = json.loads(out.read_text())["data"]["map"]["layers"]

    assert layers[0]["type"] == "osm"
    assert layers[0]["name"] == "mapnik"
    # OSM must be in the background group so it appears in the basemap switcher,
    # not the main layers TOC, keeping "Default" clean.
    assert layers[0]["group"] == "background"


def test_writer_wms_layer_fields(tmp_path):
    map_config = {
        "title": "T",
        "abstract": "",
        "srid": "EPSG:28992",
        "layers": [_make_layer("1", "My Layer", opacity=0.5, visibility=False, style="my_style")],
    }
    writer = GeoNodeWriter(geonode_url="https://geonode.example.com")
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert wms["type"] == "wms"
    assert wms["url"] == "https://geonode.example.com/geoserver/ows"
    assert wms["name"] == "ws:my layer"
    assert wms["title"] == "My Layer"
    assert wms["opacity"] == 0.5
    assert wms["visibility"] is False
    assert wms["format"] == "image/png"
    assert wms["singleTile"] is False
    assert wms["styles"] == ["my_style"]


def test_writer_no_style_empty_styles_list(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert wms["styles"] == []


# ---------------------------------------------------------------------------
# CQL_FILTER / definitionExpression
# ---------------------------------------------------------------------------

def test_writer_cql_filter_added_when_definition_expression_present(tmp_path):
    layer = _make_layer("1", "Filtered Layer")
    layer["definition_expression"] = "MIJLPAAL = 'Afgerond'"
    map_config = {"title": "T", "abstract": "", "srid": "EPSG:4326", "layers": [layer]}
    writer = GeoNodeWriter(geonode_url="https://geonode.example.com")
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert "params" in wms
    assert wms["params"]["CQL_FILTER"] == "MIJLPAAL = 'Afgerond'"


def test_writer_no_params_when_no_definition_expression(tmp_path):
    map_config = {"title": "T", "abstract": "", "srid": "EPSG:4326", "layers": [_make_layer("1", "Plain Layer")]}
    writer = GeoNodeWriter(geonode_url="https://geonode.example.com")
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert "params" not in wms

def test_writer_group_title_used_as_group(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A", group_title="Keringen")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert wms["group"] == "Keringen"


def test_writer_no_group_title_defaults_to_default_group(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert wms["group"] == "Default"


def test_writer_multiple_layers(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Layer A"),
            _make_layer("2", "Layer B", group_title="Groep X"),
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    all_layers = json.loads(out.read_text())["data"]["map"]["layers"]

    # OSM + 2 WMS layers
    assert len(all_layers) == 3
    # WMS layers are reversed so the first AGOL layer appears last in the array
    # (MapStore2 displays layers from the end of the array to the top of the TOC)
    names = [l["name"] for l in all_layers]
    assert names[0] == "mapnik"          # OSM always first
    assert "ws:layer a" in names
    assert "ws:layer b" in names
    layer_b = next(l for l in all_layers if l["name"] == "ws:layer b")
    assert layer_b["group"] == "Groep X"


# ---------------------------------------------------------------------------
# Center / extent
# ---------------------------------------------------------------------------

def test_writer_center_computed_from_extent(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:28992",
        "extent": [100000, 400000, 200000, 500000],
        "layers": [],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    map_ = json.loads(out.read_text())["data"]["map"]

    # Coordinates are reprojected from EPSG:28992 to EPSG:3857
    assert map_["projection"] == "EPSG:3857"
    assert map_["center"]["crs"] == "EPSG:3857"
    assert abs(map_["center"]["x"] - 591588.612) < 1
    assert abs(map_["center"]["y"] - 6807054.577) < 1
    assert abs(map_["maxExtent"][0] - 511356.799) < 1
    assert abs(map_["maxExtent"][1] - 6725651.376) < 1
    assert abs(map_["maxExtent"][2] - 673448.634) < 1
    assert abs(map_["maxExtent"][3] - 6888457.163) < 1


def test_writer_default_center_when_no_extent(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:3857",
        "layers": [],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    map_ = json.loads(out.read_text())["data"]["map"]

    assert map_["center"]["x"] == 0.0
    assert map_["center"]["y"] == 0.0


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def test_writer_groups_written_to_map(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Layer A", group_title="Keringen"),
            _make_layer("2", "Layer B", group_title="Keringen"),
            _make_layer("3", "Layer C"),
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    map_ = json.loads(out.read_text())["data"]["map"]

    groups = map_["groups"]
    group_ids = [g["id"] for g in groups]
    assert "Keringen" in group_ids
    # "Default" is MapStore2 built-in — must NOT appear as a custom group
    assert "Default" not in group_ids
    assert "overlay" not in group_ids
    # No duplicates
    assert len(group_ids) == len(set(group_ids))


def test_writer_groups_have_required_fields(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A", group_title="MyGroup")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    groups = json.loads(out.read_text())["data"]["map"]["groups"]

    my_group = next(g for g in groups if g["id"] == "MyGroup")
    assert my_group["title"] == "MyGroup"
    assert my_group["expanded"] is True


def test_writer_nested_groups_tree(tmp_path):
    """Dot-notation group IDs must produce a nested groups tree."""
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Direct", group_title="Legger"),
            _make_layer("2", "Kernzone", group_title="Legger.Zonering"),
            _make_layer("3", "Other"),  # no group → "Default" (built-in, not in groups array)
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    map_ = json.loads(out.read_text())["data"]["map"]

    top_ids = [g["id"] for g in map_["groups"]]
    assert "Legger" in top_ids
    # "Default" is MapStore2 built-in — must not appear as a custom group
    assert "Default" not in top_ids
    assert "overlay" not in top_ids
    # "Legger.Zonering" must NOT be at the top level — it lives inside Legger.nodes
    assert "Legger.Zonering" not in top_ids

    legger = next(g for g in map_["groups"] if g["id"] == "Legger")
    child_ids = [n["id"] for n in legger["nodes"]]
    assert "Legger.Zonering" in child_ids
    zonering = next(n for n in legger["nodes"] if n["id"] == "Legger.Zonering")
    assert zonering["title"] == "Zonering"


def test_writer_nested_groups_ancestor_auto_created(tmp_path):
    """If a layer references a nested group whose parent was not explicitly used,
    the parent group must still be created in the tree."""
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Kernzone", group_title="Legger.Zonering"),
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    map_ = json.loads(out.read_text())["data"]["map"]

    top_ids = [g["id"] for g in map_["groups"]]
    assert "Legger" in top_ids
    legger = next(g for g in map_["groups"] if g["id"] == "Legger")
    assert any(n["id"] == "Legger.Zonering" for n in legger["nodes"])


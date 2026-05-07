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
    assert map_["projection"] == "EPSG:28992"
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
# Group handling
# ---------------------------------------------------------------------------

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


def test_writer_no_group_title_defaults_to_overlay(tmp_path):
    map_config = {
        "title": "T", "abstract": "", "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    wms = json.loads(out.read_text())["data"]["map"]["layers"][1]

    assert wms["group"] == "overlay"


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
    assert all_layers[1]["name"] == "ws:layer a"
    assert all_layers[2]["group"] == "Groep X"


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

    assert map_["center"]["x"] == 150000.0
    assert map_["center"]["y"] == 450000.0
    assert map_["maxExtent"] == [100000, 400000, 200000, 500000]


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


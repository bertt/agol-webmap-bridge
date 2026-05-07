"""Tests for GeoNodeWriter group handling."""

import json
from pathlib import Path

import pytest

from agol_webmap_bridge.writers.geonode_writer import GeoNodeWriter


def _make_dataset(pk: str, title: str) -> dict:
    return {"pk": pk, "title": title, "alternate": f"ws:{title.lower()}", "default_style": None}


def _make_layer(pk: str, title: str, group_title: str = "", opacity: float = 1.0, visibility: bool = True) -> dict:
    layer = {
        "geonode_dataset": _make_dataset(pk, title),
        "opacity": opacity,
        "visibility": visibility,
    }
    if group_title:
        layer["group_title"] = group_title
    return layer


def test_writer_no_group_extra_params_empty(tmp_path):
    map_config = {
        "title": "Test",
        "abstract": "",
        "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert result["maplayers"][0]["extra_params"] == {}
    assert "groups" not in result


def test_writer_group_in_extra_params(tmp_path):
    map_config = {
        "title": "Test",
        "abstract": "",
        "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A", group_title="Groep A")],
        "groups": [{"title": "Groep A", "visibility": True, "layers": []}],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert result["maplayers"][0]["extra_params"]["group"] == "Groep A"


def test_writer_multiple_groups_in_output(tmp_path):
    map_config = {
        "title": "Test",
        "abstract": "",
        "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Layer A", group_title="Groep A"),
            _make_layer("2", "Layer B", group_title="Groep B"),
        ],
        "groups": [
            {"title": "Groep A", "visibility": True, "layers": []},
            {"title": "Groep B", "visibility": False, "layers": []},
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert len(result["groups"]) == 2
    assert result["groups"][0]["title"] == "Groep A"
    assert result["groups"][1]["title"] == "Groep B"
    assert result["groups"][1]["visibility"] is False
    assert result["maplayers"][0]["extra_params"]["group"] == "Groep A"
    assert result["maplayers"][1]["extra_params"]["group"] == "Groep B"


def test_writer_ungrouped_layer_no_group_key(tmp_path):
    """Layers without a group_title must not have 'group' in extra_params."""
    map_config = {
        "title": "Test",
        "abstract": "",
        "srid": "EPSG:4326",
        "layers": [_make_layer("1", "Layer A")],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert "group" not in result["maplayers"][0]["extra_params"]


def test_writer_mixed_grouped_and_ungrouped(tmp_path):
    map_config = {
        "title": "Test",
        "abstract": "",
        "srid": "EPSG:4326",
        "layers": [
            _make_layer("1", "Ungrouped Layer"),
            _make_layer("2", "Grouped Layer", group_title="My Group"),
        ],
        "groups": [
            {"title": "My Group", "visibility": True, "layers": []},
        ],
    }
    writer = GeoNodeWriter()
    out = tmp_path / "out.json"
    writer.write(map_config, out)
    result = json.loads(out.read_text(encoding="utf-8"))

    assert "group" not in result["maplayers"][0]["extra_params"]
    assert result["maplayers"][1]["extra_params"]["group"] == "My Group"
    assert len(result["groups"]) == 1

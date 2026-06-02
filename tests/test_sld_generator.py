"""Tests for agol_webmap_bridge.sld_generator."""

from __future__ import annotations

import pytest

from agol_webmap_bridge.sld_generator import SLDGenerator

_GEN = SLDGenerator()

# ---------------------------------------------------------------------------
# Simple renderer — polygon (esriSFS)
# ---------------------------------------------------------------------------

SIMPLE_POLYGON_RENDERER = {
    "type": "simple",
    "symbol": {
        "type": "esriSFS",
        "color": [71, 69, 69, 255],
        "outline": {
            "type": "esriSLS",
            "color": [0, 0, 0, 0],
            "width": 2.25,
            "style": "esriSLSSolid",
        },
        "style": "esriSFSSolid",
    },
}


def test_simple_polygon_produces_sld():
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "my_layer", geometry_type="Polygon")
    assert sld is not None
    assert "PolygonSymbolizer" in sld
    assert "my_layer" in sld


def test_simple_polygon_fill_color():
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "my_layer")
    assert "#474545" in sld  # RGB(71, 69, 69)


def test_simple_polygon_outline_transparency():
    """Alpha=0 on outline → stroke-opacity 0 element present."""
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "my_layer")
    assert "stroke-opacity" in sld


# ---------------------------------------------------------------------------
# Simple renderer — line (esriSLS)
# ---------------------------------------------------------------------------

SIMPLE_LINE_RENDERER = {
    "type": "simple",
    "symbol": {
        "type": "esriSLS",
        "color": [255, 0, 0, 255],
        "width": 2.0,
        "style": "esriSLSSolid",
    },
}


def test_simple_line_produces_sld():
    sld = _GEN.generate_sld(SIMPLE_LINE_RENDERER, "roads", geometry_type="Line")
    assert sld is not None
    assert "LineSymbolizer" in sld


def test_simple_line_color():
    sld = _GEN.generate_sld(SIMPLE_LINE_RENDERER, "roads")
    assert "#ff0000" in sld


def test_simple_line_dash_style():
    renderer = {
        "type": "simple",
        "symbol": {
            "type": "esriSLS",
            "color": [0, 0, 255, 255],
            "width": 2.0,
            "style": "esriSLSDash",
        },
    }
    sld = _GEN.generate_sld(renderer, "dash_layer")
    assert "stroke-dasharray" in sld


# ---------------------------------------------------------------------------
# Simple renderer — point (esriSMS)
# ---------------------------------------------------------------------------

SIMPLE_POINT_RENDERER = {
    "type": "simple",
    "symbol": {
        "type": "esriSMS",
        "color": [0, 92, 230, 255],
        "size": 8,
        "style": "esriSMSCircle",
    },
}


def test_simple_point_produces_sld():
    sld = _GEN.generate_sld(SIMPLE_POINT_RENDERER, "points", geometry_type="Point")
    assert sld is not None
    assert "PointSymbolizer" in sld


def test_simple_point_color():
    sld = _GEN.generate_sld(SIMPLE_POINT_RENDERER, "points")
    assert "#005ce6" in sld


# ---------------------------------------------------------------------------
# Simple renderer — picture marker (esriPMS) falls back to circle
# ---------------------------------------------------------------------------

def test_picture_marker_fallback_to_circle():
    renderer = {
        "type": "simple",
        "symbol": {
            "type": "esriPMS",
            "width": 16,
            "height": 16,
            "color": [200, 0, 0, 255],
        },
    }
    sld = _GEN.generate_sld(renderer, "markers")
    assert sld is not None
    assert "PointSymbolizer" in sld
    assert "circle" in sld


# ---------------------------------------------------------------------------
# uniqueValue renderer
# ---------------------------------------------------------------------------

UNIQUE_VALUE_RENDERER = {
    "type": "uniqueValue",
    "field1": "STATUS",
    "uniqueValueInfos": [
        {
            "value": "Active",
            "label": "Active",
            "symbol": {"type": "esriSFS", "color": [0, 200, 0, 255], "style": "esriSFSSolid"},
        },
        {
            "value": "Inactive",
            "label": "Inactive",
            "symbol": {"type": "esriSFS", "color": [200, 0, 0, 255], "style": "esriSFSSolid"},
        },
    ],
}


def test_unique_value_produces_sld():
    sld = _GEN.generate_sld(UNIQUE_VALUE_RENDERER, "parcels")
    assert sld is not None
    assert "Active" in sld
    assert "Inactive" in sld


def test_unique_value_has_ogc_filters():
    sld = _GEN.generate_sld(UNIQUE_VALUE_RENDERER, "parcels")
    assert "PropertyIsEqualTo" in sld
    assert "status" in sld.lower()


def test_unique_value_multiple_rules():
    sld = _GEN.generate_sld(UNIQUE_VALUE_RENDERER, "parcels")
    assert sld.count("<Rule>") == 2


def test_unique_value_default_symbol():
    renderer = dict(UNIQUE_VALUE_RENDERER)
    renderer["defaultSymbol"] = {"type": "esriSFS", "color": [128, 128, 128, 255], "style": "esriSFSSolid"}
    renderer["defaultLabel"] = "Unknown"
    sld = _GEN.generate_sld(renderer, "parcels")
    assert "ElseFilter" in sld
    assert "Unknown" in sld


# ---------------------------------------------------------------------------
# classBreaks renderer
# ---------------------------------------------------------------------------

CLASS_BREAKS_RENDERER = {
    "type": "classBreaks",
    "field": "POPULATION",
    "minValue": 0,
    "classBreakInfos": [
        {
            "classMaxValue": 1000,
            "label": "Low",
            "symbol": {"type": "esriSFS", "color": [255, 255, 0, 255], "style": "esriSFSSolid"},
        },
        {
            "classMaxValue": 10000,
            "label": "Medium",
            "symbol": {"type": "esriSFS", "color": [255, 165, 0, 255], "style": "esriSFSSolid"},
        },
    ],
}


def test_class_breaks_produces_sld():
    sld = _GEN.generate_sld(CLASS_BREAKS_RENDERER, "census")
    assert sld is not None
    assert "Low" in sld
    assert "Medium" in sld


def test_class_breaks_has_range_filters():
    sld = _GEN.generate_sld(CLASS_BREAKS_RENDERER, "census")
    assert "PropertyIsLessThanOrEqualTo" in sld
    assert "population" in sld.lower()


def test_class_breaks_multiple_rules():
    sld = _GEN.generate_sld(CLASS_BREAKS_RENDERER, "census")
    assert sld.count("<Rule>") == 2


# ---------------------------------------------------------------------------
# Unknown renderer type → None
# ---------------------------------------------------------------------------

def test_unknown_renderer_returns_none():
    renderer = {"type": "heatmap", "symbol": {}}
    result = _GEN.generate_sld(renderer, "layer")
    assert result is None


def test_missing_renderer_type_returns_none():
    result = _GEN.generate_sld({}, "layer")
    assert result is None


# ---------------------------------------------------------------------------
# RGBA → hex color conversion
# ---------------------------------------------------------------------------

def test_color_conversion():
    assert _GEN._esri_color_to_hex([71, 69, 69, 255]) == "#474545"
    assert _GEN._esri_color_to_hex([0, 0, 0, 255]) == "#000000"
    assert _GEN._esri_color_to_hex([255, 255, 255, 255]) == "#ffffff"


# ---------------------------------------------------------------------------
# Opacity — alpha < 255 → opacity CSS parameter present
# ---------------------------------------------------------------------------

def test_semi_transparent_fill_opacity():
    renderer = {
        "type": "simple",
        "symbol": {
            "type": "esriSFS",
            "color": [71, 69, 69, 128],  # alpha = 128 → ~0.502
            "style": "esriSFSSolid",
        },
    }
    sld = _GEN.generate_sld(renderer, "layer")
    assert "fill-opacity" in sld


def test_fully_opaque_no_opacity_element():
    renderer = {
        "type": "simple",
        "symbol": {
            "type": "esriSFS",
            "color": [71, 69, 69, 255],
            "style": "esriSFSSolid",
        },
    }
    sld = _GEN.generate_sld(renderer, "layer")
    assert "fill-opacity" not in sld


# ---------------------------------------------------------------------------
# SLD XML structure — well-formed header / named layer
# ---------------------------------------------------------------------------

def test_sld_has_xml_declaration():
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "test_layer")
    assert sld.startswith('<?xml version="1.0"')


def test_sld_named_layer():
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "my:cool_layer")
    assert "<Name>my:cool_layer</Name>" in sld


def test_style_name_in_title():
    sld = _GEN.generate_sld(SIMPLE_POLYGON_RENDERER, "layer", style_name="my_custom_style")
    assert "<Title>my_custom_style</Title>" in sld

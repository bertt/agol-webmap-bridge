"""SLD (Styled Layer Descriptor) generator from ESRI renderer JSON.

Adapted from an external reference implementation.  Supports the three
main ArcGIS renderer types (simple, uniqueValue, classBreaks) and all
common ESRI symbol types for vector geometry.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class SLDGenerator:
    """Generate SLD XML strings from ESRI renderer JSON dicts."""

    _POINTS_TO_PIXELS = 96.0 / 72.0

    _FONT_FAMILY_ALIASES: Dict[str, str] = {
        "arial": "Liberation Sans",
        "arial black": "Liberation Sans",
        "arial unicode ms": "Liberation Sans",
        "calibri": "Liberation Sans",
        "candara": "Liberation Sans",
        "century gothic": "Liberation Sans",
        "corbel": "Liberation Sans",
        "franklin gothic medium": "Liberation Sans",
        "geneva": "Liberation Sans",
        "helvetica": "Liberation Sans",
        "segoe ui": "Liberation Sans",
        "tahoma": "Liberation Sans",
        "trebuchet ms": "Liberation Sans",
        "verdana": "Liberation Sans",
        "cambria": "Liberation Serif",
        "constantia": "Liberation Serif",
        "georgia": "Liberation Serif",
        "times": "Liberation Serif",
        "times new roman": "Liberation Serif",
        "courier": "Liberation Mono",
        "courier new": "Liberation Mono",
        "consolas": "Liberation Mono",
        "lucida console": "Liberation Mono",
        "lucida sans typewriter": "Liberation Mono",
    }

    def generate_sld(
        self,
        renderer: dict,
        layer_name: str,
        geometry_type: Optional[str] = None,
        style_name: Optional[str] = None,
        min_scale: int = 0,
        max_scale: int = 0,
    ) -> Optional[str]:
        """Generate SLD XML from an ESRI renderer dict.

        Args:
            renderer: ESRI renderer dictionary (``drawingInfo.renderer``).
            layer_name: Layer name used in SLD ``<NamedLayer><Name>``.
            geometry_type: ``"Point"``, ``"Line"``, or ``"Polygon"``.  When
                ``None`` the generator infers it from the symbol type.
            style_name: Human-readable style title.  Defaults to *layer_name*.
            min_scale: ArcGIS ``minScale`` (0 = unconstrained).
            max_scale: ArcGIS ``maxScale`` (0 = unconstrained).

        Returns:
            SLD XML string, or ``None`` when the renderer type is not
            supported or the renderer contains no usable symbol.
        """
        renderer_type = renderer.get("type")
        if not renderer_type:
            return None

        style_name = style_name or layer_name

        if renderer_type == "simple":
            return self._create_simple_sld(
                renderer, layer_name, style_name, geometry_type, min_scale, max_scale
            )
        if renderer_type == "uniqueValue":
            return self._create_unique_value_sld(
                renderer, layer_name, style_name, geometry_type, min_scale, max_scale
            )
        if renderer_type == "classBreaks":
            return self._create_class_breaks_sld(
                renderer, layer_name, style_name, geometry_type, min_scale, max_scale
            )
        return None

    # ------------------------------------------------------------------
    # Renderer → SLD document builders
    # ------------------------------------------------------------------

    def _create_simple_sld(
        self,
        renderer: dict,
        layer_name: str,
        style_name: str,
        geometry_type: Optional[str],
        min_scale: int,
        max_scale: int,
    ) -> Optional[str]:
        symbol = renderer.get("symbol", {}).copy()
        if not symbol:
            return None

        symbol = self._scale_symbol_size(symbol)
        symbolizer_xml = self._create_symbolizer(symbol, geometry_type, renderer=renderer)
        if not symbolizer_xml:
            return None

        scale_xml = self._create_scale_denominators(min_scale, max_scale)
        label_fts_xml = self._create_label_feature_type_style(renderer, min_scale, max_scale)
        escaped_layer = self._xml_escape(layer_name)
        escaped_style = self._xml_escape(style_name)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>{escaped_layer}</Name>
    <UserStyle>
      <Title>{escaped_style}</Title>
      <FeatureTypeStyle>
        <Rule>
{scale_xml}
{symbolizer_xml}
        </Rule>
      </FeatureTypeStyle>
{label_fts_xml}
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>"""

    def _create_unique_value_sld(
        self,
        renderer: dict,
        layer_name: str,
        style_name: str,
        geometry_type: Optional[str],
        min_scale: int,
        max_scale: int,
    ) -> Optional[str]:
        fields: List[str] = []
        for i in range(1, 4):
            field = renderer.get(f"field{i}")
            if field:
                fields.append(field)

        if not fields:
            return None

        field_delimiter = renderer.get("fieldDelimiter", ",")
        unique_value_infos = renderer.get("uniqueValueInfos", [])
        default_symbol = renderer.get("defaultSymbol")
        default_label = renderer.get("defaultLabel", "Other")

        if not unique_value_infos:
            return None

        ramp_colors = self._get_color_ramp_colors(renderer)
        use_ramp_colors = self._should_use_ramp_colors(unique_value_infos, ramp_colors)

        scale_xml = self._create_scale_denominators(min_scale, max_scale)
        sld_rules: List[str] = []

        for idx, info in enumerate(unique_value_infos):
            symbol = info.get("symbol", {}).copy()
            value = info.get("value", "")
            label = info.get("label", f"Class {idx + 1}")

            if use_ramp_colors and idx < len(ramp_colors):
                symbol["color"] = ramp_colors[idx]

            symbol = self._scale_symbol_size(symbol)
            filter_xml = self._create_ogc_filter(fields, value, field_delimiter)
            symbolizer_xml = self._create_symbolizer(symbol, geometry_type, renderer=renderer)

            if symbolizer_xml:
                escaped_label = self._xml_escape(label)
                sld_rules.append(
                    f"""        <Rule>
          <Name>{escaped_label}</Name>
          <Title>{escaped_label}</Title>
{scale_xml}
{filter_xml}
{symbolizer_xml}
        </Rule>"""
                )

        if default_symbol:
            ds = default_symbol.copy()
            ds = self._scale_symbol_size(ds)
            sym_xml = self._create_symbolizer(ds, geometry_type, renderer=renderer)
            if sym_xml:
                sld_rules.append(
                    f"""        <Rule>
          <Name>default_else_filter</Name>
          <Title>{self._xml_escape(default_label)}</Title>
{scale_xml}
          <ElseFilter/>
{sym_xml}
        </Rule>"""
                )

        if not sld_rules:
            return None

        escaped_layer = self._xml_escape(layer_name)
        escaped_style = self._xml_escape(style_name)
        label_fts_xml = self._create_label_feature_type_style(renderer, min_scale, max_scale)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>{escaped_layer}</Name>
    <UserStyle>
      <Title>{escaped_style}</Title>
      <FeatureTypeStyle>
{chr(10).join(sld_rules)}
      </FeatureTypeStyle>
{label_fts_xml}
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>"""

    def _create_class_breaks_sld(
        self,
        renderer: dict,
        layer_name: str,
        style_name: str,
        geometry_type: Optional[str],
        min_scale: int,
        max_scale: int,
    ) -> Optional[str]:
        field = renderer.get("field", "").lower()
        if not field:
            return None

        class_break_infos = renderer.get("classBreakInfos", [])
        if not class_break_infos:
            return None

        min_value = renderer.get("minValue")
        default_symbol = renderer.get("defaultSymbol")
        default_label = renderer.get("defaultLabel", "Other")
        scale_xml = self._create_scale_denominators(min_scale, max_scale)
        escaped_field = self._xml_escape(field)
        sld_rules: List[str] = []
        prev_max = min_value

        for idx, info in enumerate(class_break_infos):
            symbol = info.get("symbol", {}).copy()
            class_max = info.get("classMaxValue")
            label = info.get("label", f"Class {idx + 1}")

            symbol = self._scale_symbol_size(symbol)
            symbolizer_xml = self._create_symbolizer(symbol, geometry_type, renderer=renderer)
            if not symbolizer_xml:
                prev_max = class_max
                continue

            filter_parts: List[str] = []
            if prev_max is not None:
                op = "PropertyIsGreaterThan" if idx > 0 else "PropertyIsGreaterThanOrEqualTo"
                filter_parts.append(
                    f"""            <ogc:{op}>
              <ogc:PropertyName>{escaped_field}</ogc:PropertyName>
              <ogc:Literal>{prev_max}</ogc:Literal>
            </ogc:{op}>"""
                )
            if class_max is not None:
                filter_parts.append(
                    f"""            <ogc:PropertyIsLessThanOrEqualTo>
              <ogc:PropertyName>{escaped_field}</ogc:PropertyName>
              <ogc:Literal>{class_max}</ogc:Literal>
            </ogc:PropertyIsLessThanOrEqualTo>"""
                )

            if len(filter_parts) == 1:
                filter_xml = f"          <ogc:Filter>\n{filter_parts[0]}\n          </ogc:Filter>"
            elif len(filter_parts) > 1:
                filter_xml = (
                    "          <ogc:Filter>\n"
                    "            <ogc:And>\n"
                    + "\n".join(filter_parts)
                    + "\n            </ogc:And>\n"
                    "          </ogc:Filter>"
                )
            else:
                filter_xml = ""

            escaped_label = self._xml_escape(label)
            sld_rules.append(
                f"""        <Rule>
          <Name>{escaped_label}</Name>
          <Title>{escaped_label}</Title>
{scale_xml}
{filter_xml}
{symbolizer_xml}
        </Rule>"""
            )
            prev_max = class_max

        if default_symbol:
            ds = default_symbol.copy()
            ds = self._scale_symbol_size(ds)
            sym_xml = self._create_symbolizer(ds, geometry_type, renderer=renderer)
            if sym_xml:
                sld_rules.append(
                    f"""        <Rule>
          <Name>default_else_filter</Name>
          <Title>{self._xml_escape(default_label)}</Title>
{scale_xml}
          <ElseFilter/>
{sym_xml}
        </Rule>"""
                )

        if not sld_rules:
            return None

        escaped_layer = self._xml_escape(layer_name)
        escaped_style = self._xml_escape(style_name)
        label_fts_xml = self._create_label_feature_type_style(renderer, min_scale, max_scale)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0"
    xmlns="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <NamedLayer>
    <Name>{escaped_layer}</Name>
    <UserStyle>
      <Title>{escaped_style}</Title>
      <FeatureTypeStyle>
{chr(10).join(sld_rules)}
      </FeatureTypeStyle>
{label_fts_xml}
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>"""

    # ------------------------------------------------------------------
    # Symbolizer builders
    # ------------------------------------------------------------------

    def _create_symbolizer(
        self,
        symbol: dict,
        geometry_type: Optional[str],
        renderer: Optional[dict] = None,
    ) -> str:
        symbol_type = symbol.get("type", "")

        if not geometry_type:
            if symbol_type == "esriSLS":
                geometry_type = "Line"
            elif symbol_type == "esriSFS":
                geometry_type = "Polygon"
            elif symbol_type in ("esriSMS", "esriPMS"):
                geometry_type = "Point"

        if "Line" in str(geometry_type) or symbol_type == "esriSLS":
            color = self._esri_color_to_hex(symbol.get("color", [0, 112, 255, 255]))
            width = symbol.get("width", 1.0)
            dash_xml = self._create_dasharray_xml(symbol.get("style"), width)
            stroke_opacity_xml = self._create_opacity_xml("stroke-opacity", symbol.get("color", [0, 112, 255, 255]), renderer)
            return f"""          <LineSymbolizer>
            <Stroke>
              <CssParameter name="stroke">{color}</CssParameter>
              <CssParameter name="stroke-width">{self._format_rotation_value(width)}</CssParameter>
{stroke_opacity_xml}
{dash_xml}
            </Stroke>
          </LineSymbolizer>"""

        if "Polygon" in str(geometry_type) or symbol_type in ("esriSFS", "esriPFS"):
            fill_xml = self._create_polygon_fill_xml(symbol, renderer)
            outline = symbol.get("outline") or {}
            stroke_xml = ""
            if isinstance(outline, dict) and outline:
                outline_color = outline.get("color", [0, 0, 0, 255])
                stroke_color = self._esri_color_to_hex(outline_color)
                stroke_width = outline.get("width", 0.5)
                dash_xml = self._create_dasharray_xml(outline.get("style"), stroke_width)
                stroke_opacity_xml = self._create_opacity_xml("stroke-opacity", outline_color, renderer)
                stroke_xml = f"""
            <Stroke>
              <CssParameter name="stroke">{stroke_color}</CssParameter>
              <CssParameter name="stroke-width">{self._format_rotation_value(stroke_width)}</CssParameter>
{stroke_opacity_xml}
{dash_xml}
            </Stroke>"""
            return f"""          <PolygonSymbolizer>
{fill_xml}{stroke_xml}
          </PolygonSymbolizer>"""

        if "Point" in str(geometry_type) or symbol_type in ("esriSMS", "esriPMS"):
            rotation_xml = self._create_rotation_xml(symbol, renderer)
            symbol_color = symbol.get("color", [0, 112, 255, 255])
            color = self._esri_color_to_hex(symbol_color)
            fill_opacity_xml = self._create_opacity_xml("fill-opacity", symbol_color, renderer)
            size = symbol.get("size", 12)
            if symbol_type == "esriPMS":
                width = symbol.get("width", 12)
                height = symbol.get("height", 12)
                size = (width + height) / 2.0
            return f"""          <PointSymbolizer>
            <Graphic>
              <Mark>
                <WellKnownName>circle</WellKnownName>
                <Fill>
                  <CssParameter name="fill">{color}</CssParameter>
{fill_opacity_xml}
                </Fill>
              </Mark>
              <Size>{self._format_rotation_value(size)}</Size>
{rotation_xml}
            </Graphic>
          </PointSymbolizer>"""

        return ""

    def _create_polygon_fill_xml(
        self,
        symbol: dict,
        renderer: Optional[dict] = None,
    ) -> str:
        symbol_type = str(symbol.get("type") or "")
        symbol_style = str(symbol.get("style") or "").lower()
        symbol_color = symbol.get("color", [0, 112, 255, 128])

        if symbol_style == "esrisfsnull":
            return ""

        mark_name = self._esri_polygon_style_to_well_known_name(symbol_style)
        if mark_name:
            color = self._esri_color_to_hex(symbol_color)
            stroke_opacity_xml = self._create_opacity_xml("stroke-opacity", symbol_color, renderer)
            size = self._esri_polygon_style_to_pattern_size(symbol_style)
            return f"""            <Fill>
              <GraphicFill>
                <Graphic>
                  <Mark>
                    <WellKnownName>{mark_name}</WellKnownName>
                    <Stroke>
                      <CssParameter name="stroke">{color}</CssParameter>
                      <CssParameter name="stroke-width">1</CssParameter>
{stroke_opacity_xml}
                    </Stroke>
                  </Mark>
                  <Size>{size}</Size>
                </Graphic>
              </GraphicFill>
            </Fill>"""

        fill_color = self._esri_color_to_hex(symbol_color)
        fill_opacity_xml = self._create_opacity_xml("fill-opacity", symbol_color, renderer)
        return f"""            <Fill>
              <CssParameter name="fill">{fill_color}</CssParameter>
{fill_opacity_xml}
            </Fill>"""

    def _esri_polygon_style_to_well_known_name(self, style: str) -> Optional[str]:
        return {
            "esrisfshorizontal": "shape://horline",
            "esrisfsvertical": "shape://vertline",
            "esrisfsforwarddiagonal": "shape://slash",
            "esrisfsbackwarddiagonal": "shape://backslash",
            "esrisfscross": "shape://plus",
            "esrisfsdiagonalcross": "shape://times",
        }.get(style)

    def _esri_polygon_style_to_pattern_size(self, style: str) -> int:
        if style in {"esrisfscross", "esrisfsdiagonalcross"}:
            return 10
        return 12

    # ------------------------------------------------------------------
    # Filter builders
    # ------------------------------------------------------------------

    def _create_ogc_filter(
        self, fields: List[str], value_string: str, field_delimiter: str = ","
    ) -> str:
        values = value_string.split(field_delimiter)

        if len(fields) == 1:
            field = self._xml_escape(fields[0])
            value = values[0] if values else value_string
            if value in ("<Null>", "null", ""):
                return f"""          <ogc:Filter>
            <ogc:PropertyIsNull>
              <ogc:PropertyName>{field}</ogc:PropertyName>
            </ogc:PropertyIsNull>
          </ogc:Filter>"""
            return f"""          <ogc:Filter>
            <ogc:PropertyIsEqualTo>
              <ogc:PropertyName>{field}</ogc:PropertyName>
              <ogc:Literal>{self._xml_escape(value)}</ogc:Literal>
            </ogc:PropertyIsEqualTo>
          </ogc:Filter>"""

        filters: List[str] = []
        for field, value in zip(fields, values):
            escaped_field = self._xml_escape(field)
            if value in ("<Null>", "null", ""):
                filters.append(
                    f"""            <ogc:PropertyIsNull>
              <ogc:PropertyName>{escaped_field}</ogc:PropertyName>
            </ogc:PropertyIsNull>"""
                )
            else:
                filters.append(
                    f"""            <ogc:PropertyIsEqualTo>
              <ogc:PropertyName>{escaped_field}</ogc:PropertyName>
              <ogc:Literal>{self._xml_escape(value)}</ogc:Literal>
            </ogc:PropertyIsEqualTo>"""
                )
        return (
            "          <ogc:Filter>\n"
            "            <ogc:And>\n"
            + "\n".join(filters)
            + "\n            </ogc:And>\n"
            "          </ogc:Filter>"
        )

    # ------------------------------------------------------------------
    # Scale denominator builder
    # ------------------------------------------------------------------

    def _create_scale_denominators(self, min_scale: int, max_scale: int) -> str:
        """Build SLD scale denominator elements from ArcGIS scale values.

        ArcGIS ``minScale`` → OGC ``MaxScaleDenominator`` (zoom-in limit).
        ArcGIS ``maxScale`` → OGC ``MinScaleDenominator`` (zoom-out limit).
        A value of 0 means "unconstrained" and is omitted.
        """
        parts: List[str] = []
        if max_scale > 0:
            parts.append(f"          <MinScaleDenominator>{max_scale}</MinScaleDenominator>")
        if min_scale > 0:
            parts.append(f"          <MaxScaleDenominator>{min_scale}</MaxScaleDenominator>")
        return "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Label (TextSymbolizer) builder
    # ------------------------------------------------------------------

    def _create_label_feature_type_style(
        self,
        renderer: Optional[dict],
        min_scale: int,
        max_scale: int,
    ) -> str:
        if not isinstance(renderer, dict):
            return ""
        labeling_info = renderer.get("labelingInfo")
        if not isinstance(labeling_info, list) or not labeling_info:
            return ""

        rules: List[str] = []
        for idx, label_cfg in enumerate(labeling_info, 1):
            if not isinstance(label_cfg, dict):
                continue
            label_expression = label_cfg.get("labelExpression")
            label_xml = self._create_label_expression_xml(label_expression)
            if not label_xml:
                continue

            symbol = label_cfg.get("symbol") if isinstance(label_cfg.get("symbol"), dict) else {}
            label_placement = label_cfg.get("labelPlacement") or ""
            text_symbolizer_xml = self._create_text_symbolizer_xml(
                symbol, label_xml, renderer, label_placement
            )

            label_min_scale = label_cfg.get("minScale")
            label_max_scale = label_cfg.get("maxScale")
            scale_xml = self._create_scale_denominators(
                label_min_scale if label_min_scale is not None else min_scale,
                label_max_scale if label_max_scale is not None else max_scale,
            )

            rules.append(
                f"""        <Rule>
          <Name>labels_{idx}</Name>
          <Title>labels_{idx}</Title>
{scale_xml}
{text_symbolizer_xml}
        </Rule>"""
            )

        if not rules:
            return ""

        return "      <FeatureTypeStyle>\n{rules}\n      </FeatureTypeStyle>".format(
            rules="\n".join(rules)
        )

    def _create_label_expression_xml(self, expression: Optional[str]) -> str:
        if not expression:
            return ""
        text = str(expression).strip()
        if not text:
            return ""

        match = re.fullmatch(r"\[([^\]]+)\]", text)
        if match:
            return f"<ogc:PropertyName>{self._xml_escape(match.group(1).strip().lower())}</ogc:PropertyName>"

        parts: List[str] = []
        cursor = 0
        for m in re.finditer(r"\[([^\]]+)\]", text):
            if m.start() > cursor:
                literal = text[cursor : m.start()]
                if literal:
                    parts.append(f"<ogc:Literal>{self._xml_escape(literal)}</ogc:Literal>")
            parts.append(
                f"<ogc:PropertyName>{self._xml_escape(m.group(1).strip().lower())}</ogc:PropertyName>"
            )
            cursor = m.end()
        if cursor < len(text):
            literal = text[cursor:]
            if literal:
                parts.append(f"<ogc:Literal>{self._xml_escape(literal)}</ogc:Literal>")

        if not parts:
            return f"<ogc:Literal>{self._xml_escape(text)}</ogc:Literal>"
        if len(parts) == 1:
            return parts[0]
        return '<ogc:Function name="strConcat">' + "".join(parts) + "</ogc:Function>"

    _ESRI_H_ALIGN_TO_ANCHOR_X = {"left": "0.0", "center": "0.5", "right": "1.0"}
    _ESRI_V_ALIGN_TO_ANCHOR_Y = {"top": "1.0", "middle": "0.5", "bottom": "0.0", "baseline": "0.0"}

    def _create_text_symbolizer_xml(
        self,
        symbol: dict,
        label_xml: str,
        renderer: Optional[dict],
        label_placement: str = "",
    ) -> str:
        color = symbol.get("color") if isinstance(symbol, dict) else None
        if not color:
            color = [0, 0, 0, 255]

        font = symbol.get("font") if isinstance(symbol, dict) else None
        if not isinstance(font, dict):
            font = {}

        font_family_xml = self._create_font_family_xml(self._get_label_font_family(symbol, font))
        font_size = self._xml_escape(self._get_label_font_size(symbol, font))
        font_style = self._xml_escape(self._get_label_font_style(symbol, font))
        font_weight = self._xml_escape(self._get_label_font_weight(symbol, font))
        font_decoration = self._get_label_font_decoration(symbol, font)
        char_spacing = self._get_numeric(
            font.get("letterSpacing")
            or font.get("charSpacing")
            or symbol.get("letterSpacing")
            or symbol.get("charSpacing")
        )
        word_spacing = self._get_numeric(font.get("wordSpacing") or symbol.get("wordSpacing"))

        fill_color = self._esri_color_to_hex(color)
        fill_opacity_xml = self._create_opacity_xml("fill-opacity", color, renderer)

        halo_xml = ""
        halo_color = symbol.get("haloColor") if isinstance(symbol, dict) else None
        halo_size = symbol.get("haloSize") if isinstance(symbol, dict) else None
        if halo_color and halo_size:
            halo_fill_color = self._esri_color_to_hex(halo_color)
            halo_fill_opacity_xml = self._create_opacity_xml("fill-opacity", halo_color, renderer)
            halo_xml = f"""
              <Halo>
                <Radius>{self._xml_escape(str(halo_size))}</Radius>
                <Fill>
                  <CssParameter name="fill">{halo_fill_color}</CssParameter>
{halo_fill_opacity_xml}
                </Fill>
              </Halo>"""

        _lp = str(label_placement).lower()
        if "polygon" in _lp:
            anchor_x, anchor_y = "0.5", "0.5"
        else:
            h_align = str(symbol.get("horizontalAlignment") or "center").strip().lower() if isinstance(symbol, dict) else "center"
            v_align = str(symbol.get("verticalAlignment") or "middle").strip().lower() if isinstance(symbol, dict) else "middle"
            anchor_x = self._ESRI_H_ALIGN_TO_ANCHOR_X.get(h_align, "0.5")
            anchor_y = self._ESRI_V_ALIGN_TO_ANCHOR_Y.get(v_align, "0.5")

        x_offset = self._get_numeric(symbol.get("xoffset") if isinstance(symbol, dict) else None) or 0.0
        y_offset = self._get_numeric(symbol.get("yoffset") if isinstance(symbol, dict) else None) or 0.0
        displacement_xml = ""
        if abs(x_offset) > 1e-9 or abs(y_offset) > 1e-9:
            displacement_xml = f"""
              <Displacement>
                <DisplacementX>{self._format_rotation_value(x_offset)}</DisplacementX>
                <DisplacementY>{self._format_rotation_value(y_offset)}</DisplacementY>
              </Displacement>"""

        label_placement_xml = f"""            <LabelPlacement>
              <PointPlacement>
                <AnchorPoint>
                  <AnchorPointX>{anchor_x}</AnchorPointX>
                  <AnchorPointY>{anchor_y}</AnchorPointY>
                </AnchorPoint>{displacement_xml}{self._create_label_rotation_xml(symbol)}
              </PointPlacement>
            </LabelPlacement>"""

        vendor_options_xml = self._create_text_vendor_options(font_decoration, char_spacing, word_spacing)

        return f"""          <TextSymbolizer>
            <Label>{label_xml}</Label>
            <Font>
{font_family_xml}
              <CssParameter name="font-size">{font_size}</CssParameter>
              <CssParameter name="font-style">{font_style}</CssParameter>
              <CssParameter name="font-weight">{font_weight}</CssParameter>
            </Font>
{label_placement_xml}
            <Fill>
              <CssParameter name="fill">{fill_color}</CssParameter>
{fill_opacity_xml}
            </Fill>{halo_xml}
            <VendorOption name="partials">false</VendorOption>
{vendor_options_xml}
          </TextSymbolizer>"""

    def _get_label_font_family(self, symbol: dict, font: dict) -> str:
        family = (
            font.get("family")
            or font.get("fontFamily")
            or font.get("name")
            or symbol.get("fontFamily")
            or symbol.get("fontName")
            or "Liberation Sans"
        )
        family = str(family).strip() or "Liberation Sans"
        return self._FONT_FAMILY_ALIASES.get(family.lower(), family)

    def _create_font_family_xml(self, primary_family: str) -> str:
        families: List[str] = []
        for family in (primary_family, "Liberation Sans", "SansSerif"):
            family = str(family).strip()
            if family and family.lower() not in [f.lower() for f in families]:
                families.append(family)
        return "\n".join(
            f'              <CssParameter name="font-family">{self._xml_escape(fam)}</CssParameter>'
            for fam in families
        )

    def _get_label_font_size(self, symbol: dict, font: dict) -> str:
        size = self._get_numeric(font.get("size") or font.get("fontSize") or symbol.get("fontSize"))
        if size is None or size <= 0:
            size = 10.0
        unit = str(font.get("unit") or symbol.get("fontSizeUnit") or "pt").strip().lower()
        if unit in ("pt", "point", "points"):
            size *= 96.0 / 72.0
        return self._format_rotation_value(size)

    def _get_label_font_style(self, symbol: dict, font: dict) -> str:
        if self._is_truthy(font.get("italic") or symbol.get("italic")):
            return "italic"
        style = str(font.get("style") or symbol.get("fontStyle") or "normal").strip().lower()
        return style if style in ("italic", "oblique") else "normal"

    def _get_label_font_weight(self, symbol: dict, font: dict) -> str:
        if self._is_truthy(font.get("bold") or symbol.get("bold")):
            return "bold"
        weight = font.get("weight") or symbol.get("fontWeight") or "normal"
        weight_str = str(weight).strip().lower()
        if weight_str in ("bold", "bolder"):
            return "bold"
        numeric_weight = self._get_numeric(weight)
        if numeric_weight is not None and numeric_weight >= 600:
            return "bold"
        return "normal"

    def _get_label_font_decoration(self, symbol: dict, font: dict) -> str:
        if self._is_truthy(font.get("underline") or symbol.get("underline")):
            return "underline"
        if self._is_truthy(font.get("strikethrough") or symbol.get("strikethrough")):
            return "line-through"
        decoration = str(font.get("decoration") or symbol.get("decoration") or "none").strip().lower()
        return decoration if decoration in ("underline", "line-through", "strikethrough") else "none"

    def _create_label_rotation_xml(self, symbol: dict) -> str:
        angle = self._get_numeric(symbol.get("angle") or symbol.get("rotation"))
        if angle is None or abs(angle) <= 1e-9:
            return ""
        return f"\n                  <Rotation>{self._format_rotation_value(angle)}</Rotation>"

    def _create_text_vendor_options(
        self,
        decoration: str,
        char_spacing: Optional[float],
        word_spacing: Optional[float],
    ) -> str:
        options: List[str] = []
        if decoration == "underline":
            options.append('            <VendorOption name="underlineText">true</VendorOption>')
        elif decoration in ("line-through", "strikethrough"):
            options.append('            <VendorOption name="strikethroughText">true</VendorOption>')
        if char_spacing is not None and abs(char_spacing) > 1e-9:
            options.append(
                f'            <VendorOption name="charSpacing">{self._format_rotation_value(char_spacing)}</VendorOption>'
            )
        if word_spacing is not None and word_spacing > 0:
            options.append(
                f'            <VendorOption name="wordSpacing">{self._format_rotation_value(word_spacing)}</VendorOption>'
            )
        return "\n".join(options)

    # ------------------------------------------------------------------
    # Rotation builder
    # ------------------------------------------------------------------

    def _create_rotation_xml(self, symbol: dict, renderer: Optional[dict]) -> str:
        rotation_info = self._get_rotation_visual_variable(renderer)
        constant_angle = self._get_numeric(symbol.get("angle"))

        if not rotation_info and constant_angle is None:
            return ""

        field_expr_xml = ""
        if rotation_info:
            field_name = rotation_info.get("field")
            if field_name:
                escaped_field = self._xml_escape(str(field_name).lower())
                base_expr = f"<ogc:PropertyName>{escaped_field}</ogc:PropertyName>"
                field_expr_xml = self._apply_rotation_type_transform(
                    base_expr, rotation_info.get("rotationType")
                )

        has_constant = constant_angle is not None and abs(constant_angle) > 1e-12

        if field_expr_xml and has_constant:
            return (
                "                  <Rotation>\n"
                "                    <ogc:Add>\n"
                f"                      {field_expr_xml}\n"
                f"                      <ogc:Literal>{self._format_rotation_value(constant_angle)}</ogc:Literal>\n"
                "                    </ogc:Add>\n"
                "                  </Rotation>"
            )
        if field_expr_xml:
            return (
                "                  <Rotation>\n"
                f"                    {field_expr_xml}\n"
                "                  </Rotation>"
            )
        return f"                  <Rotation>{self._format_rotation_value(constant_angle)}</Rotation>"

    def _get_rotation_visual_variable(self, renderer: Optional[dict]) -> Optional[dict]:
        if not isinstance(renderer, dict):
            return None
        visual_variables = renderer.get("visualVariables")
        if not isinstance(visual_variables, list):
            return None
        for item in visual_variables:
            if isinstance(item, dict) and item.get("type") == "rotationInfo":
                return item
        return None

    def _apply_rotation_type_transform(self, field_expr_xml: str, rotation_type: Optional[str]) -> str:
        if str(rotation_type or "").strip().lower() == "arithmetic":
            return (
                "<ogc:Sub>\n"
                "  <ogc:Literal>90</ogc:Literal>\n"
                f"  {field_expr_xml}\n"
                "</ogc:Sub>"
            )
        return field_expr_xml

    # ------------------------------------------------------------------
    # Opacity helpers
    # ------------------------------------------------------------------

    def _create_opacity_xml(
        self,
        css_parameter: str,
        color_array: list,
        renderer: Optional[dict] = None,
    ) -> str:
        symbol_opacity = 1.0
        if color_array and len(color_array) >= 4:
            try:
                alpha = float(color_array[3])
                symbol_opacity = max(0.0, min(alpha, 255.0)) / 255.0
            except (TypeError, ValueError):
                symbol_opacity = 1.0

        layer_opacity = self._get_renderer_opacity_factor(renderer)
        opacity = symbol_opacity * layer_opacity

        if opacity >= 1.0:
            return ""
        return f'              <CssParameter name="{css_parameter}">{self._format_opacity(opacity)}</CssParameter>'

    def _get_renderer_opacity_factor(self, renderer: Optional[dict]) -> float:
        if not isinstance(renderer, dict):
            return 1.0
        transparency = renderer.get("transparency")
        if transparency is None:
            return 1.0
        try:
            t = float(transparency)
        except (TypeError, ValueError):
            return 1.0
        return (100.0 - max(0.0, min(100.0, t))) / 100.0

    # ------------------------------------------------------------------
    # Color ramp helpers
    # ------------------------------------------------------------------

    def _get_color_ramp_colors(self, renderer: dict) -> List[list]:
        try:
            color_ramp = renderer.get("authoringInfo", {}).get("colorRamp", {})
            if color_ramp.get("type") == "multipart":
                return [
                    ramp["fromColor"]
                    for ramp in color_ramp.get("colorRamps", [])
                    if "fromColor" in ramp
                ]
        except Exception:
            pass
        return []

    def _should_use_ramp_colors(
        self, unique_value_infos: List[dict], ramp_colors: List[list]
    ) -> bool:
        if not ramp_colors:
            return False
        symbol_colors = []
        for info in unique_value_infos:
            symbol = info.get("symbol") or {}
            color = symbol.get("color")
            if not color or len(color) < 3:
                return True
            symbol_colors.append(tuple(color[:4]))
        return len(set(symbol_colors)) == 1 and len(ramp_colors) >= len(unique_value_infos)

    # ------------------------------------------------------------------
    # Dash-array helpers
    # ------------------------------------------------------------------

    def _create_dasharray_xml(self, esri_style: Optional[str], width: float) -> str:
        dasharray = self._esri_line_style_to_dasharray(esri_style, width)
        if not dasharray:
            return ""
        return f'              <CssParameter name="stroke-dasharray">{dasharray}</CssParameter>'

    def _esri_line_style_to_dasharray(self, esri_style: Optional[str], width: float) -> Optional[str]:
        if not esri_style:
            return None
        style = esri_style.lower()
        if style in {"esrislssolid", "esrislsnull"}:
            return None
        try:
            stroke_width = max(float(width), 1.0)
        except (TypeError, ValueError):
            stroke_width = 1.0
        patterns = {
            "esrislsdash": [4, 3],
            "esrislsdot": [1, 3],
            "esrislsdashdot": [4, 3, 1, 3],
            "esrislsdashdotdot": [4, 3, 1, 3, 1, 3],
        }
        pattern = patterns.get(style)
        if not pattern:
            return None
        values = [part * stroke_width for part in pattern]
        return " ".join(self._format_dash_value(v) for v in values)

    def _format_dash_value(self, value: float) -> str:
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    # ------------------------------------------------------------------
    # Symbol scaling
    # ------------------------------------------------------------------

    def _scale_symbol_size(self, symbol: dict) -> dict:
        """Convert ArcGIS symbol dimensions from points to SLD pixels."""
        symbol_type = symbol.get("type", "")

        def conv(target: dict, key: str) -> None:
            v = self._get_numeric(target.get(key))
            if v is not None:
                target[key] = v * self._POINTS_TO_PIXELS

        def conv_outline() -> None:
            outline = symbol.get("outline")
            if isinstance(outline, dict):
                conv(outline, "width")

        if symbol_type == "esriSLS":
            conv(symbol, "width")
        elif symbol_type == "esriSFS":
            conv_outline()
        elif symbol_type == "esriSMS":
            conv(symbol, "size")
            conv_outline()
        elif symbol_type in {"esriPMS", "esriPFS"}:
            conv(symbol, "width")
            conv(symbol, "height")

        return symbol

    # ------------------------------------------------------------------
    # Generic utilities
    # ------------------------------------------------------------------

    def _xml_escape(self, value: Optional[str]) -> str:
        return html.escape("" if value is None else str(value), quote=False)

    def _esri_color_to_hex(self, color_array: list) -> str:
        if not color_array or len(color_array) < 3:
            return "#0070ff"
        return f"#{color_array[0]:02x}{color_array[1]:02x}{color_array[2]:02x}"

    def _format_opacity(self, opacity: float) -> str:
        if opacity <= 0:
            return "0"
        if opacity >= 1:
            return "1"
        return f"{opacity:.3f}".rstrip("0").rstrip(".")

    def _format_rotation_value(self, value: Optional[float]) -> str:
        if value is None:
            return "0"
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")

    def _get_numeric(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _is_truthy(self, value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ("1", "true", "yes", "y")

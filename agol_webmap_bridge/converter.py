"""Converter: orchestrates AGOL webmap → target format conversion."""

from __future__ import annotations

import logging
from typing import TypedDict

from agol_webmap_bridge.matcher import MatchResult, match_layers
from agol_webmap_bridge.writers.base_writer import BaseWriter

logger = logging.getLogger(__name__)


class UnsupportedFeature(TypedDict):
    feature: str
    layer: str | None  # layer title, or None for webmap-level features


def _wkid_to_epsg(wkid: int | None) -> str:
    """Convert an AGOL WKID to an EPSG string.
    """
    if wkid is None:
        return "EPSG:4326"
    return f"EPSG:{wkid}"

def _extract_extent(agol_webmap: dict) -> list[float] | None:
    """Extract bounding box [xmin, ymin, xmax, ymax] from the webmap initialState."""
    initial_state = agol_webmap.get("initialState", {})
    viewpoint = initial_state.get("viewpoint", {})
    target = viewpoint.get("targetGeometry", {})

    if target.get("xmin") is not None:
        return [
            target["xmin"],
            target["ymin"],
            target["xmax"],
            target["ymax"],
        ]

    # Fallback: some webmaps store extent at root level
    extent = agol_webmap.get("extent")
    if isinstance(extent, dict) and "xmin" in extent:
        return [extent["xmin"], extent["ymin"], extent["xmax"], extent["ymax"]]

    return None


def _extract_service_sublayers(layer: dict) -> list[dict]:
    """Extract leaf sublayers from an ArcGISMapServiceLayer.

    Within an ArcGIS MapServer service the ``layers`` array may contain both
    *group nodes* (entries with ``subLayerIds``) and *leaf layers* (entries
    without ``subLayerIds``).  Group nodes are logical containers with no
    direct GeoNode dataset equivalent and are therefore skipped.

    Each leaf sublayer is returned as a standalone layer dict that inherits
    ``opacity`` and ``visibility`` from the parent operational layer and uses
    the sublayer ``name`` as ``title`` for matching.  When a leaf belongs to a
    group node its ``group_title`` is set to the group's name so that the
    converter can propagate group metadata to the output.

    If the service has no ``layers`` array the service layer itself is returned
    unchanged so that existing behaviour is preserved.
    """
    service_layers = layer.get("layers")
    if not service_layers:
        return [layer]

    # Build mapping from group node id → group name
    group_names: dict[int, str] = {
        sub["id"]: sub.get("name", "")
        for sub in service_layers
        if sub.get("subLayerIds")
    }

    leaf_layers: list[dict] = []
    for sublayer in service_layers:
        if sublayer.get("subLayerIds"):
            # Group/folder node — not a data layer, skip it
            continue
        leaf: dict = {
            "title": sublayer.get("name", ""),
            "id": f"{layer.get('id', '')}_sub_{sublayer.get('id', '')}",
            "opacity": layer.get("opacity", 1.0),
            "visibility": sublayer.get("defaultVisibility", layer.get("visibility", True)),
            "layerType": "ArcGISMapServiceSublayer",
            "_parent_url": layer.get("url", ""),
            "_sublayer_id": sublayer.get("id"),
        }
        parent_id = sublayer.get("parentLayerId", -1)
        group_title = group_names.get(parent_id, "")
        if group_title:
            leaf["group_title"] = group_title
        leaf_layers.append(leaf)

    # Fall back to the service itself when no leaf sublayers were found
    return leaf_layers if leaf_layers else [layer]


def _detect_unsupported(agol_webmap: dict) -> list[UnsupportedFeature]:
    """Scan *agol_webmap* for features that are not converted and return a report.

    Each entry has a ``feature`` description and an optional ``layer`` title
    (``None`` for webmap-level findings).
    """
    findings: list[UnsupportedFeature] = []

    # Webmap-level checks
    if agol_webmap.get("bookmarks"):
        findings.append({"feature": "Bookmarks", "layer": None})

    if agol_webmap.get("tables"):
        findings.append({"feature": "Non-spatial tables", "layer": None})

    if agol_webmap.get("mapFloorInfo"):
        findings.append({"feature": "Indoor map / mapFloorInfo", "layer": None})

    # Per-layer checks (flatten one level of GroupLayer for scanning)
    all_layers: list[dict] = []
    for layer in agol_webmap.get("operationalLayers", []):
        all_layers.append(layer)
        if layer.get("layerType") == "GroupLayer":
            sub_layers = layer.get("layers", [])
            all_layers.extend(sub_layers)
            # Detect nested group layers (> 1 level deep)
            for sub in sub_layers:
                if sub.get("layerType") == "GroupLayer":
                    findings.append({
                        "feature": "Nested group layer (> 1 level deep)",
                        "layer": sub.get("title") or layer.get("title"),
                    })

    for layer in all_layers:
        title: str | None = layer.get("title") or None

        drawing_info = layer.get("layerDefinition", {}).get("drawingInfo", {})
        if layer.get("renderer") or drawing_info.get("renderer"):
            findings.append({"feature": "Renderer / symbology", "layer": title})

        if layer.get("popupInfo"):
            findings.append({"feature": "Popup configuration (popupInfo)", "layer": title})

        if layer.get("layerDefinition", {}).get("definitionExpression"):
            findings.append({"feature": "Definition expression / filter", "layer": title})

        if layer.get("timeInfo") or layer.get("layerDefinition", {}).get("timeInfo"):
            findings.append({"feature": "Time-aware layer settings", "layer": title})

        if layer.get("layerDefinition", {}).get("fields"):
            findings.append({"feature": "Field configurations", "layer": title})

    return findings


def _flatten_layers(layers: list[dict], group_path: list[str] | None = None) -> list[dict]:
    """Recursively flatten operational layers, tagging each leaf with its full group path.

    * ``GroupLayer`` → recurses into sub-layers with the group title added to the path.
    * ``ArcGISMapServiceLayer`` with sublayers → the service title becomes an extra path
      segment; any internal group nodes within the service add yet another segment.
    * All other layer types → leaf; ``group_title`` is set to the dot-joined path.
    """
    if group_path is None:
        group_path = []

    flat: list[dict] = []
    for layer in layers:
        layer_type = layer.get("layerType", "")
        title = (layer.get("title") or "").strip()

        if layer_type == "GroupLayer":
            new_path = group_path + [title] if title else group_path
            flat.extend(_flatten_layers(layer.get("layers", []), new_path))

        elif layer_type == "ArcGISMapServiceLayer" and layer.get("layers"):
            sublayers_raw = _extract_service_sublayers(layer)
            for sublayer in sublayers_raw:
                sub = dict(sublayer)
                internal_group = sub.pop("group_title", "")
                if title:
                    if internal_group:
                        sub_path = group_path + [title, internal_group]
                    else:
                        sub_path = group_path + [title]
                else:
                    sub_path = group_path + ([internal_group] if internal_group else [])
                sub["group_title"] = ".".join(sub_path)
                flat.append(sub)

        else:
            leaf = dict(layer)
            leaf["group_title"] = ".".join(group_path)
            flat.append(leaf)

    return flat


def convert(
    agol_webmap: dict,
    geonode_datasets: list[dict],
    writer: BaseWriter,
    threshold: float = 0.6,
    webmap_title: str = "",
) -> dict:
    """Convert an AGOL webmap to an intermediate map config and pass it to *writer*.

    Args:
        agol_webmap: Parsed AGOL webmap JSON.
        geonode_datasets: All datasets fetched from GeoNode.
        writer: A :class:`~agol_webmap_bridge.writers.base_writer.BaseWriter` instance.
        threshold: Name-matching similarity threshold (0–1).
        webmap_title: Human-readable title (sourced from AGOL item metadata).

    Returns:
        The intermediate ``map_config`` dict (useful for testing / inspection).
    """
    agol_layers = agol_webmap.get("operationalLayers", [])

    # Recursively flatten group/service layers, tagging each with its group path
    flat_layers = _flatten_layers(agol_layers)

    match_results: list[MatchResult] = match_layers(flat_layers, geonode_datasets, threshold)

    matched = [r for r in match_results if r.geonode_dataset is not None]
    skipped = [r for r in match_results if r.geonode_dataset is None]

    logger.info("%d layers matched, %d layers skipped (no GeoNode dataset found)", len(matched), len(skipped))

    # Build intermediate representation, preserving group_title when present
    layers_config = [
        {
            "geonode_dataset": r.geonode_dataset,
            "opacity": r.agol_layer.get("opacity", 1.0),
            "visibility": r.agol_layer.get("visibility", True),
            **( {"group_title": r.agol_layer["group_title"]} if r.agol_layer.get("group_title") else {} ),
        }
        for r in matched
    ]

    spatial_ref = agol_webmap.get("spatialReference", {})
    wkid = spatial_ref.get("latestWkid") or spatial_ref.get("wkid")

    basemap = agol_webmap.get("baseMap", {})
    basemap_title = basemap.get("title", "")

    abstract_parts = []
    if basemap_title:
        abstract_parts.append(f"Basemap: {basemap_title}")
    abstract = "; ".join(abstract_parts)

    map_config: dict = {
        "title": webmap_title or agol_webmap.get("title", "Untitled"),
        "abstract": abstract,
        "srid": _wkid_to_epsg(wkid),
        "extent": _extract_extent(agol_webmap),
        "layers": layers_config,
        "_matched_count": len(matched),
        "_skipped_count": len(skipped),
        "_unsupported_features": _detect_unsupported(agol_webmap),
    }

    return map_config

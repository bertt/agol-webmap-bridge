"""Converter: orchestrates AGOL webmap → target format conversion."""

from __future__ import annotations

import logging

from agol_webmap_bridge.matcher import MatchResult, match_layers
from agol_webmap_bridge.writers.base_writer import BaseWriter

logger = logging.getLogger(__name__)


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

    # Flatten group layers and expand MapServer service sublayers
    flat_layers: list[dict] = []
    for layer in agol_layers:
        if layer.get("layerType") == "GroupLayer":
            flat_layers.extend(layer.get("layers", []))
        elif layer.get("layerType") == "ArcGISMapServiceLayer" and layer.get("layers"):
            flat_layers.extend(_extract_service_sublayers(layer))
        else:
            flat_layers.append(layer)

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

    # Collect unique groups from matched layers (preserving encounter order)
    seen_groups: set[str] = set()
    groups_config: list[dict] = []
    for r in matched:
        gt = r.agol_layer.get("group_title", "")
        if gt and gt not in seen_groups:
            seen_groups.add(gt)
            groups_config.append({"title": gt, "visibility": True, "layers": []})

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
    }
    if groups_config:
        map_config["groups"] = groups_config

    return map_config

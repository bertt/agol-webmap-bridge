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

    # Flatten group layers (one level deep)
    flat_layers: list[dict] = []
    for layer in agol_layers:
        if layer.get("layerType") == "GroupLayer":
            flat_layers.extend(layer.get("layers", []))
        else:
            flat_layers.append(layer)

    match_results: list[MatchResult] = match_layers(flat_layers, geonode_datasets, threshold)

    matched = [r for r in match_results if r.geonode_dataset is not None]
    skipped = [r for r in match_results if r.geonode_dataset is None]

    logger.info("%d layers matched, %d layers skipped (no GeoNode dataset found)", len(matched), len(skipped))

    # Build intermediate representation
    layers_config = [
        {
            "geonode_dataset": r.geonode_dataset,
            "opacity": r.agol_layer.get("opacity", 1.0),
            "visibility": r.agol_layer.get("visibility", True),
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

    map_config = {
        "title": webmap_title or agol_webmap.get("title", "Untitled"),
        "abstract": abstract,
        "srid": _wkid_to_epsg(wkid),
        "extent": _extract_extent(agol_webmap),
        "layers": layers_config,
    }

    return map_config

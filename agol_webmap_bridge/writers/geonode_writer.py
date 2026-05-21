"""GeoNode Map JSON writer."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from pyproj import Transformer

from agol_webmap_bridge.writers.base_writer import BaseWriter

logger = logging.getLogger(__name__)

_OSM_LAYER = {
    "type": "osm",
    "source": "osm",
    "name": "mapnik",
    "title": "OpenStreetMap",
    "visibility": True,
    "group": "background",
}


class GeoNodeWriter(BaseWriter):
    """Writes the intermediate map config as a GeoNode Map JSON file.

    The produced JSON matches the format accepted by ``POST /api/v2/maps/``
    on a GeoNode instance, using the ``data.map`` nested structure.

    Args:
        geonode_url: Base URL of the GeoNode instance (e.g. ``https://example.com``).
            Used to construct the WMS endpoint URL for each layer.
    """

    def __init__(self, geonode_url: str = "") -> None:
        self._geonode_url = geonode_url.rstrip("/")

    def write(self, map_config: dict, path: Path) -> None:
        """Serialise *map_config* to GeoNode Map JSON and write to *path*.

        Args:
            map_config: Intermediate map configuration dict from the converter.
            path: Destination ``.json`` file path.
        """
        geonode_map = self._build(map_config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(geonode_map, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("GeoNode map JSON written to %s", path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_groups_tree(group_ids: Iterable[str]) -> list[dict]:
        """Build a nested MapStore2/GeoNode groups array from dot-notation group IDs.

        Each group ID like ``"Legger.Zonering"`` results in a parent ``"Legger"``
        node containing a child ``"Legger.Zonering"`` node.  Layers reference their
        group via ``group: "<full dot-notation id>"``.

        ``"Default"`` is MapStore2's built-in root group and is intentionally
        excluded — it is always present and must not be redefined.
        """
        ordered: list[str] = []
        seen: set[str] = set()

        for gid in group_ids:
            if not gid or gid == "Default" or gid == "background" or gid in seen:
                continue
            # Ensure all ancestor segments exist before the leaf
            parts = gid.split(".")
            for depth in range(1, len(parts) + 1):
                ancestor = ".".join(parts[:depth])
                if ancestor not in seen:
                    ordered.append(ancestor)
                    seen.add(ancestor)

        nodes_by_id: dict[str, dict] = {}
        root: list[dict] = []

        for gid in ordered:
            parts = gid.split(".")
            node: dict = {"id": gid, "title": parts[-1], "expanded": True, "nodes": []}
            nodes_by_id[gid] = node
            if len(parts) == 1:
                root.append(node)
            else:
                parent_id = ".".join(parts[:-1])
                nodes_by_id[parent_id]["nodes"].append(node)

        return root

    @staticmethod
    def _to_3857(srid: str, x: float, y: float) -> tuple[float, float]:
        if srid == "EPSG:3857":
            return x, y
        t = Transformer.from_crs(srid, "EPSG:3857", always_xy=True)
        return t.transform(x, y)

    def _build(self, map_config: dict) -> dict:
        srid = map_config.get("srid", "EPSG:3857")
        extent = map_config.get("extent")  # [xmin, ymin, xmax, ymax] in source CRS
        output_srid = "EPSG:3857"

        if extent:
            src_cx = (extent[0] + extent[2]) / 2
            src_cy = (extent[1] + extent[3]) / 2
            cx, cy = self._to_3857(srid, src_cx, src_cy)
            xmin, ymin = self._to_3857(srid, extent[0], extent[1])
            xmax, ymax = self._to_3857(srid, extent[2], extent[3])
            max_extent = [xmin, ymin, xmax, ymax]
        else:
            cx, cy = 0.0, 0.0
            max_extent = [-20037508.34, -20037508.34, 20037508.34, 20037508.34]

        wms_url = f"{self._geonode_url}/geoserver/ows" if self._geonode_url else ""

        wms_layers: list[dict] = []
        for layer in map_config.get("layers", []):
            ds = layer["geonode_dataset"]
            style = (ds.get("default_style") or {}).get("name", "")
            entry: dict = {
                "type": "wms",
                "url": wms_url,
                "name": ds.get("alternate", ""),
                "title": ds.get("title", ""),
                "group": layer.get("group_title", "") or "Default",
                "visibility": layer.get("visibility", True),
                "opacity": layer.get("opacity", 1.0),
                "format": "image/png",
                "singleTile": False,
                "styles": [style] if style else [],
            }
            definition_expression = layer.get("definition_expression")
            if definition_expression:
                entry["params"] = {"CQL_FILTER": definition_expression}
            wms_layers.append(entry)

        # MapStore2 renders layers bottom-to-top and shows the TOC top-to-bottom
        # in reverse array order.  Reversing WMS layers preserves the original
        # AGOL display order (first AGOL layer → top of GeoNode TOC).
        # Default-group layers are placed before custom-group layers in the array
        # so they appear at the bottom of the TOC (below all named groups).
        default_layers = [l for l in wms_layers if l.get("group") == "Default"]
        custom_layers = [l for l in wms_layers if l.get("group") != "Default"]
        layers: list[dict] = (
            [dict(_OSM_LAYER)]
            + list(reversed(default_layers))
            + list(reversed(custom_layers))
        )

        # Collect unique group IDs in encounter order, then build nested tree.
        seen_groups: dict[str, None] = {}
        for layer_entry in layers:
            g = layer_entry.get("group", "")
            if g:
                seen_groups[g] = None
        groups = self._build_groups_tree(seen_groups.keys())

        return {
            "title": map_config.get("title", "Untitled"),
            "abstract": map_config.get("abstract", ""),
            "data": {
                "map": {
                    "projection": output_srid,
                    "units": "m",
                    "zoom": 5,
                    "center": {"x": cx, "y": cy, "crs": output_srid},
                    "maxExtent": max_extent,
                    "groups": groups,
                    "layers": layers,
                }
            },
        }

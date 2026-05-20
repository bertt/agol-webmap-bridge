"""GeoNode Map JSON writer."""

from __future__ import annotations

import json
import logging
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

        layers: list[dict] = [dict(_OSM_LAYER)]
        for layer in map_config.get("layers", []):
            ds = layer["geonode_dataset"]
            style = (ds.get("default_style") or {}).get("name", "")
            entry: dict = {
                "type": "wms",
                "url": wms_url,
                "name": ds.get("alternate", ""),
                "title": ds.get("title", ""),
                "group": layer.get("group_title", "") or "overlay",
                "visibility": layer.get("visibility", True),
                "opacity": layer.get("opacity", 1.0),
                "format": "image/png",
                "singleTile": False,
                "styles": [style] if style else [],
            }
            layers.append(entry)

        # Build groups array from unique group names used by layers.
        # GeoNode requires data.map.groups to be defined; without it every
        # layer falls back to the built-in "Default" group in the UI.
        seen_groups: dict[str, None] = {}  # ordered dedup
        for layer_entry in layers:
            g = layer_entry.get("group", "")
            if g:
                seen_groups[g] = None
        groups = [{"id": g, "title": g, "expanded": True} for g in seen_groups]

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

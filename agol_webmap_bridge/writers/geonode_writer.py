"""GeoNode Map JSON writer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

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

    def _build(self, map_config: dict) -> dict:
        srid = map_config.get("srid", "EPSG:3857")
        extent = map_config.get("extent")  # [xmin, ymin, xmax, ymax]

        if extent:
            cx = (extent[0] + extent[2]) / 2
            cy = (extent[1] + extent[3]) / 2
            max_extent = extent
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

        return {
            "title": map_config.get("title", "Untitled"),
            "abstract": map_config.get("abstract", ""),
            "data": {
                "map": {
                    "projection": srid,
                    "units": "m",
                    "zoom": 5,
                    "center": {"x": cx, "y": cy, "crs": srid},
                    "maxExtent": max_extent,
                    "layers": layers,
                }
            },
        }

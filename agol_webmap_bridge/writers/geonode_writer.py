"""GeoNode Map JSON writer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agol_webmap_bridge.writers.base_writer import BaseWriter

logger = logging.getLogger(__name__)


class GeoNodeWriter(BaseWriter):
    """Writes the intermediate map config as a GeoNode Map JSON file.

    The produced JSON can be POSTed to ``/api/v2/maps/`` on a GeoNode instance.
    """

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
        layers = []
        for layer in map_config.get("layers", []):
            ds = layer["geonode_dataset"]
            entry = {
                "extra_params": {},
                "current_style": (ds.get("default_style") or {}).get("name", ""),
                "opacity": layer.get("opacity", 1.0),
                "visibility": layer.get("visibility", True),
                "dataset": {
                    "pk": ds.get("pk"),
                    "alternate": ds.get("alternate"),
                    "title": ds.get("title"),
                },
            }
            layers.append(entry)

        geonode_map = {
            "title": map_config.get("title", "Untitled"),
            "abstract": map_config.get("abstract", ""),
            "srid": map_config.get("srid", "EPSG:4326"),
            "maplayers": layers,
        }

        # Include extent when available
        extent = map_config.get("extent")
        if extent:
            geonode_map["extent"] = extent

        return geonode_map

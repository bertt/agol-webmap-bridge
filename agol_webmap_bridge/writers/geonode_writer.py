"""GeoNode Map JSON writer."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from pyproj import Transformer

from agol_webmap_bridge.sld_generator import SLDGenerator
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

_SLD_GEN = SLDGenerator()


def _slugify(text: str) -> str:
    """Convert *text* to a filesystem-safe ASCII slug."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "layer"


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

        Also generates one ``.sld`` file per matched layer that carries AGOL
        renderer info, and emits a ``upload_<slug>.sh`` script for bulk upload.

        Args:
            map_config: Intermediate map configuration dict from the converter.
            path: Destination ``.json`` file path.
        """
        output_dir = path.parent
        webmap_slug = map_config.get("_webmap_slug") or path.stem.replace("_geonode", "")

        sld_files: list[tuple[str, str]] = []  # (style_name, sld_path)
        for layer in map_config.get("layers", []):
            renderer = layer.get("renderer")
            if not renderer:
                continue
            ds = layer["geonode_dataset"]
            alternate = ds.get("alternate", ds.get("name", ""))
            title = layer.get("agol_title") or ds.get("title", "") or alternate
            style_name = _slugify(title)
            sld_content = _SLD_GEN.generate_sld(
                renderer=renderer,
                layer_name=alternate,
                geometry_type=layer.get("geometry_type"),
                style_name=style_name,
            )
            if sld_content:
                sld_path = output_dir / f"{style_name}.sld"
                sld_path.write_text(sld_content, encoding="utf-8")
                sld_files.append((style_name, str(sld_path)))
                layer["_sld_style_name"] = style_name
                logger.info("SLD written: %s", sld_path)

        map_config["_sld_count"] = len(sld_files)

        geonode_map = self._build(map_config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(geonode_map, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("GeoNode map JSON written to %s", path)

        if sld_files:
            self._write_upload_script(output_dir, webmap_slug, sld_files, path.name)

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

    def _write_upload_script(
        self,
        output_dir: Path,
        webmap_slug: str,
        sld_files: list[tuple[str, str]],
        map_json_filename: str,
    ) -> None:
        """Write a bash upload script that pushes SLD styles and the map JSON to GeoNode."""
        script_path = output_dir / f"upload_{webmap_slug}.sh"

        sld_upload_lines = "\n".join(
            f'echo "Uploading style {style_name}..."\n'
            f'curl -s -w "\\n  HTTP %{{http_code}}" -X POST "$GEONODE_URL/geoserver/rest/styles?name={style_name}" \\\n'
            f'  -u "$USER:$PASSWORD" \\\n'
            f'  -H "Content-Type: application/vnd.ogc.sld+xml" \\\n'
            f'  --data-binary "@{Path(sld_path).name}"'
            for style_name, sld_path in sld_files
        )

        script = f"""#!/usr/bin/env bash
# Auto-generated by agol-webmap-bridge
# Uploads SLD styles to GeoServer and the map JSON to GeoNode.
#
# Usage:
#   bash upload_{webmap_slug}.sh <geonode_url> <user> <password> <token>
#
# Arguments:
#   geonode_url   Base URL of the GeoNode instance (e.g. https://your-geonode.example.com)
#   user          GeoServer username (Basic Auth for SLD upload)
#   password      GeoServer password (Basic Auth for SLD upload)
#   token         GeoNode API token (Bearer token for map JSON upload)
#
# The script must be run from the directory that contains the .sld files.

set -euo pipefail

GEONODE_URL="${{1:?Usage: $0 <geonode_url> <user> <password> <token>}}"
USER="${{2:?Usage: $0 <geonode_url> <user> <password> <token>}}"
PASSWORD="${{3:?Usage: $0 <geonode_url> <user> <password> <token>}}"
TOKEN="${{4:?Usage: $0 <geonode_url> <user> <password> <token>}}"

# Upload SLD styles to GeoServer (Basic Auth)
{sld_upload_lines}

# Upload map JSON to GeoNode API (Bearer token)
echo ""
echo "Uploading map JSON..."
curl -s -w "\\n  HTTP %{{http_code}}" -X POST "$GEONODE_URL/api/v2/maps/" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d "@{map_json_filename}"

echo ""
echo "Done."
"""
        script_path.write_bytes(script.encode("utf-8"))
        logger.info("Upload script written: %s", script_path)

    def _build(self, map_config: dict) -> dict:
        """Build the GeoNode Map JSON dict from *map_config*."""
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
            # Prefer the SLD style generated for this layer; fall back to GeoNode default
            sld_style_name = layer.get("_sld_style_name")
            if sld_style_name:
                styles = [sld_style_name]
            else:
                default_style = (ds.get("default_style") or {}).get("name", "")
                styles = [default_style] if default_style else []
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
                "styles": styles,
            }
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

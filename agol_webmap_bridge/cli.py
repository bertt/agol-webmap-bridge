"""CLI entry-point for agol-webmap-bridge."""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

import click

from agol_webmap_bridge.agol_client import AGOLError, fetch_webmap
from agol_webmap_bridge.converter import convert
from agol_webmap_bridge.geonode_client import GeoNodeError, fetch_datasets
from agol_webmap_bridge.writers.geonode_writer import GeoNodeWriter


def _slugify(text: str) -> str:
    """Convert *text* to a filesystem-safe slug."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "webmap"


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("webmap_guid")
@click.option(
    "--geonode-url", "-g",
    required=True,
    help="Base URL of the GeoNode instance, e.g. https://example.com",
)
@click.option(
    "--output-dir", "-o",
    default="output",
    show_default=True,
    help="Directory where the output JSON file is written.",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    default=False,
    help="Overwrite the output file without prompting.",
)
@click.option(
    "--match-threshold",
    default=0.6,
    show_default=True,
    type=click.FloatRange(0.0, 1.0),
    help="Minimum similarity ratio (0–1) for layer name matching.",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging verbosity.",
)
def main(
    webmap_guid: str,
    geonode_url: str,
    output_dir: str,
    force: bool,
    match_threshold: float,
    log_level: str,
) -> None:
    """Convert an ArcGIS Online webmap to a GeoNode Map JSON file.

    WEBMAP_GUID is the item GUID of the ArcGIS Online webmap, e.g.
    8a9a419b704e4e03bb98d9f14226a743.
    """
    _setup_logging(log_level)
    logger = logging.getLogger(__name__)

    # 1. Fetch AGOL webmap
    click.echo(f"Fetching AGOL webmap {webmap_guid} …")
    try:
        agol_webmap = fetch_webmap(webmap_guid)
    except AGOLError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    webmap_title = agol_webmap.get("title", webmap_guid)
    click.echo(f"  Title: {webmap_title}")
    layer_count = len(agol_webmap.get("operationalLayers", []))
    click.echo(f"  Operational layers: {layer_count}")

    # 2. Fetch GeoNode datasets
    click.echo(f"Fetching datasets from {geonode_url} …")
    try:
        geonode_datasets = fetch_datasets(geonode_url)
    except GeoNodeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"  Found {len(geonode_datasets)} datasets.")

    # 3. Determine output path
    slug = _slugify(webmap_title)
    out_path = Path(output_dir) / f"{slug}_geonode.json"

    if out_path.exists() and not force:
        overwrite = click.confirm(f"Output file '{out_path}' already exists. Overwrite?", default=False)
        if not overwrite:
            click.echo("Aborted.")
            sys.exit(0)

    # 4. Convert
    writer = GeoNodeWriter(geonode_url=geonode_url)
    map_config = convert(
        agol_webmap=agol_webmap,
        geonode_datasets=geonode_datasets,
        writer=writer,
        threshold=match_threshold,
        webmap_title=webmap_title,
    )

    # 5. Write output
    writer.write(map_config, out_path)

    matched = map_config.get("_matched_count", len(map_config.get("layers", [])))
    skipped = map_config.get("_skipped_count", 0)
    click.echo(
        f"\nDone: {matched} layer(s) matched, {skipped} layer(s) skipped."
        f"\nOutput written to: {out_path}"
    )

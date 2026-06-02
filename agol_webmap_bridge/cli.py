"""CLI entry-point for agol-webmap-bridge."""

from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

import click

from agol_webmap_bridge.agol_client import AGOLError, detect_and_fetch_webmap
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
@click.argument("guid")
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
    guid: str,
    geonode_url: str,
    output_dir: str,
    force: bool,
    match_threshold: float,
    log_level: str,
) -> None:
    """Convert an ArcGIS Online webmap to a GeoNode Map JSON file.

    GUID is either:

    \b
      - An AppConfiguration item GUID (e.g. 2b214417eea74ae9a56119c251ffa960).
        The tool fetches the AppConfiguration, validates type='webmap', and
        resolves the embedded webmap GUID automatically.
      - A direct webmap item GUID (e.g. d0b3a31896d84b0592a32a61c1334532).
        The tool fetches the webmap directly, skipping the AppConfiguration step.

    The type is detected automatically based on the AGOL REST API response.
    """
    _setup_logging(log_level)
    logger = logging.getLogger(__name__)

    # 1. Auto-detect GUID type and fetch the webmap
    click.echo(f"Fetching AGOL item {guid} …")
    try:
        guid_type, webmap_title, agol_webmap = detect_and_fetch_webmap(guid)
    except AGOLError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if guid_type == "appconfiguration":
        click.echo(f"  Detected: AppConfiguration → webmap")
    else:
        click.echo(f"  Detected: direct webmap")
    click.echo(f"  Title: {webmap_title}")
    layer_count = len(agol_webmap.get("operationalLayers", []))
    click.echo(f"  Operational layers: {layer_count}")

    # 3. Fetch GeoNode datasets
    click.echo(f"Fetching datasets from {geonode_url} …")
    try:
        geonode_datasets = fetch_datasets(geonode_url)
    except GeoNodeError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(f"  Found {len(geonode_datasets)} datasets.")

    # 4. Determine output path
    slug = _slugify(webmap_title)
    out_path = Path(output_dir) / f"{slug}_geonode.json"

    if out_path.exists() and not force:
        overwrite = click.confirm(f"Output file '{out_path}' already exists. Overwrite?", default=False)
        if not overwrite:
            click.echo("Aborted.")
            sys.exit(0)

    # 5. Convert
    writer = GeoNodeWriter(geonode_url=geonode_url)
    map_config = convert(
        agol_webmap=agol_webmap,
        geonode_datasets=geonode_datasets,
        writer=writer,
        threshold=match_threshold,
        webmap_title=webmap_title,
        webmap_slug=slug,
    )

    # 6. Write output
    writer.write(map_config, out_path)

    matched = map_config.get("_matched_count", len(map_config.get("layers", [])))
    skipped = map_config.get("_skipped_count", 0)
    click.echo(
        f"\nDone: {matched} layer(s) matched, {skipped} layer(s) skipped."
        f"\nOutput written to: {out_path}"
    )

    sld_count = map_config.get("_sld_count", 0)
    if sld_count:
        upload_script = Path(output_dir) / f"upload_{slug}.sh"
        click.echo(f"\n✓  {sld_count} SLD style(s) generated.")
        click.echo(f"   Upload script: {upload_script}")

    # 7. Unsupported features report
    unsupported: list[dict] = map_config.get("_unsupported_features", [])
    if unsupported:
        click.echo("\n⚠  Unsupported AGOL features detected (not converted):")
        for item in unsupported:
            layer_label = f"  [layer: {item['layer']}]" if item["layer"] else "  [webmap level]"
            click.echo(f"   • {item['feature']}{layer_label}")
    else:
        click.echo("\n✓  No unsupported features detected.")

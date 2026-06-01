"""Layer name matching between AGOL operational layers and GeoNode datasets."""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of matching one AGOL layer to a GeoNode dataset."""

    agol_layer: dict
    geonode_dataset: dict | None
    score: float


def _normalise(text: str) -> str:
    """Lowercase, strip accents, replace non-alphanumeric with space, collapse whitespace."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _normalise_exact(text: str) -> str:
    """Lowercase and strip accents only — preserves underscores and other separators.

    Used for URL service names so that ``Grens_Rijnland_formeel_mask`` stays
    ``grens_rijnland_formeel_mask`` and matches GeoNode ``name`` values
    verbatim.
    """
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def _extract_url_service_name(url: str) -> str:
    """Extract the service name segment from an ArcGIS Server URL.

    For a URL like ``…/services/Folder/MyService/MapServer/0`` the extracted
    name is ``MyService``.  Returns an empty string when the pattern is not
    found.
    """
    # Match the last path segment before a known ArcGIS service type suffix
    match = re.search(
        r"/([^/]+)/(?:MapServer|FeatureServer|ImageServer|WMSServer|WFSServer|WCSServer)"
        r"(?:/|$)",
        url,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _agol_layer_candidates(layer: dict) -> list[str]:
    """Return candidate names for an AGOL layer.

    Priority order:
    1. ``_fetched_name`` — name retrieved from the ArcGIS REST endpoint by the
       converter; used as the sole search term (exact lowercase).
    2. Own ``url`` — service name extracted from the layer URL string as a
       fallback when no pre-fetched name is available.
    3. ``_parent_url`` (sublayers) — parent service name combined with the
       sublayer title: ``<parent>_<title>``.

    Layers with no URL and no ``_fetched_name`` return an empty list and will
    be skipped (no title / id fallback).
    """
    # Priority 1: pre-fetched name from ArcGIS REST API
    fetched = layer.get("_fetched_name", "")
    if fetched:
        return [_normalise_exact(fetched)]

    # Priority 2: extract service name from own URL
    url = layer.get("url") or ""
    service_name = _extract_url_service_name(url)
    if service_name:
        return [_normalise_exact(service_name)]

    # Priority 3: sublayer with _parent_url — combine service name + title
    parent_url = layer.get("_parent_url") or ""
    parent_service = _extract_url_service_name(parent_url)
    if parent_service:
        title = layer.get("title") or ""
        title_exact = _normalise_exact(title.replace(" ", "_"))
        if title_exact:
            return [_normalise_exact(f"{parent_service}_{title_exact}")]

    # No URL available — return empty list, layer will be skipped
    return []


def _suffix_score(layer_cand: str, ds_cand: str) -> float:
    """Return 1.0 if *layer_cand* is a word-boundary suffix of *ds_cand*.

    GeoNode dataset names are sometimes prefixed with a workspace slug, e.g.
    ``hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken``.  When
    the AGOL layer name ``werk_in_uitvoering_vlakken`` is a suffix of that
    string AND is preceded by an underscore (word boundary), it is a reliable
    match even though the raw SequenceMatcher ratio falls below the threshold.
    """
    if layer_cand and ds_cand.endswith(layer_cand):
        prefix_len = len(ds_cand) - len(layer_cand)
        if prefix_len == 0 or ds_cand[prefix_len - 1] == "_":
            return 1.0
    return 0.0


def _candidate_names(dataset: dict) -> list[str]:
    """Return candidate names for a GeoNode dataset.

    Each field produces two variants:
    - exact lowercase (underscores preserved) for matching URL service names
    - fully normalised (underscores → spaces) for fuzzy title matching

    ``name`` and ``alternate`` are stable identifiers; ``title`` is included as
    an additional candidate because GeoNode titles often mirror the layer name
    (e.g. ``Werk_in_uitvoering_vlakken``) and enable a direct match when the
    ``name`` field carries a long workspace-prefixed slug.
    """
    names: list[str] = []
    for field in ("name", "alternate"):
        raw = dataset.get(field) or ""
        if not raw:
            continue
        # 'alternate' is often 'workspace:layer_name' — use just the layer part
        part = raw.split(":", 1)[1] if ":" in raw else raw
        names.append(_normalise_exact(part))   # e.g. grens_rijnland_formeel_mask
        names.append(_normalise(part))          # e.g. grens rijnland formeel mask
    # Include title as an extra candidate (exact lowercase only)
    title = dataset.get("title") or ""
    if title:
        names.append(_normalise_exact(title))
    return [n for n in names if n]


def match_layers(
    agol_layers: list[dict],
    geonode_datasets: list[dict],
    threshold: float = 0.6,
) -> list[MatchResult]:
    """Match each AGOL operational layer to the best GeoNode dataset by name.

    Unmatched layers get ``geonode_dataset=None`` and a WARNING is logged.

    Args:
        agol_layers: List of operational layer dicts from the AGOL webmap.
        geonode_datasets: List of dataset dicts from the GeoNode API.
        threshold: Minimum similarity ratio (0–1) to accept a match.

    Returns:
        List of :class:`MatchResult`, one per AGOL layer.
    """
    # Pre-compute normalised names for all datasets
    dataset_candidates: list[tuple[dict, list[str]]] = [
        (ds, _candidate_names(ds)) for ds in geonode_datasets
    ]

    results: list[MatchResult] = []
    for layer in agol_layers:
        layer_candidates = _agol_layer_candidates(layer)
        logger.debug("Layer '%s' search candidates: %s", layer.get("title"), layer_candidates)
        best_ds: dict | None = None
        best_score = 0.0
        best_pair: tuple[str, str] = ("", "")

        for ds, ds_candidates in dataset_candidates:
            for layer_cand in layer_candidates:
                for ds_cand in ds_candidates:
                    score = max(
                        difflib.SequenceMatcher(None, layer_cand, ds_cand).ratio(),
                        _suffix_score(layer_cand, ds_cand),
                    )
                    logger.debug(
                        "  '%s' vs '%s' (dataset '%s') → %.2f",
                        layer_cand, ds_cand, ds.get("name"), score,
                    )
                    if score > best_score:
                        best_score = score
                        best_ds = ds
                        best_pair = (layer_cand, ds_cand)

        if best_score >= threshold and best_ds is not None:
            logger.info(
                "Matched layer '%s' → dataset '%s' (score=%.2f) | searched on: %s",
                layer.get("title"),
                best_ds.get("title"),
                best_score,
                layer_candidates,
            )
            results.append(MatchResult(agol_layer=layer, geonode_dataset=best_ds, score=best_score))
        else:
            logger.warning(
                "No match found for layer '%s' (best score=%.2f, best pair: '%s' vs '%s') "
                "— layer will be skipped. | searched on: %s",
                layer.get("title"),
                best_score,
                best_pair[0],
                best_pair[1],
                layer_candidates,
            )
            results.append(MatchResult(agol_layer=layer, geonode_dataset=None, score=best_score))

    return results

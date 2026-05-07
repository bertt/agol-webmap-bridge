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

    When a layer has its own ``url``, the service name extracted from it is
    used as the sole search term, preserved with underscores (exact lowercase)
    so it matches GeoNode ``name`` values verbatim.

    Sublayers (no ``url``, only ``_parent_url``) combine the parent service
    name with the sublayer title joined by an underscore, e.g.
    ``Legger_regionale_kering_vigerend`` + ``Buitenbeschermingszone``
    → ``legger_regionale_kering_vigerend_buitenbeschermingszone``.

    Layers without any URL fall back to normalised title / id.
    """
    url = layer.get("url") or ""
    service_name = _extract_url_service_name(url)
    if service_name:
        return [_normalise_exact(service_name)]

    # Sublayer: has _parent_url but no own url — combine service name + title
    parent_url = layer.get("_parent_url") or ""
    parent_service = _extract_url_service_name(parent_url)
    if parent_service:
        title = layer.get("title") or ""
        title_exact = _normalise_exact(title.replace(" ", "_"))
        if title_exact:
            return [_normalise_exact(f"{parent_service}_{title_exact}")]

    # Last fallback: no URL at all — use normalised title / id
    candidates: list[str] = []
    for field in ("title", "id"):
        raw = layer.get(field) or ""
        if raw:
            candidates.append(_normalise(raw))
    return [c for c in candidates if c]


def _candidate_names(dataset: dict) -> list[str]:
    """Return candidate names for a GeoNode dataset.

    Each field produces two variants:
    - exact lowercase (underscores preserved) for matching URL service names
    - fully normalised (underscores → spaces) for fuzzy title matching

    Only ``name`` and ``alternate`` are used; ``title`` is excluded because it
    is free-form while ``name`` / ``alternate`` are stable identifiers.
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
                    score = difflib.SequenceMatcher(None, layer_cand, ds_cand).ratio()
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

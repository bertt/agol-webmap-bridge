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


def _candidate_names(dataset: dict) -> list[str]:
    """Return normalised candidate names for a GeoNode dataset."""
    names = []
    for field in ("title", "name", "alternate"):
        raw = dataset.get(field) or ""
        if raw:
            # 'alternate' often looks like 'workspace:layer_name' – also try just the layer part
            if ":" in raw:
                names.append(_normalise(raw.split(":", 1)[1]))
            names.append(_normalise(raw))
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
        layer_name = _normalise(layer.get("title") or layer.get("id") or "")
        best_ds: dict | None = None
        best_score = 0.0

        for ds, candidates in dataset_candidates:
            for candidate in candidates:
                score = difflib.SequenceMatcher(None, layer_name, candidate).ratio()
                if score > best_score:
                    best_score = score
                    best_ds = ds

        if best_score >= threshold and best_ds is not None:
            logger.info(
                "Matched layer '%s' → dataset '%s' (score=%.2f)",
                layer.get("title"),
                best_ds.get("title"),
                best_score,
            )
            results.append(MatchResult(agol_layer=layer, geonode_dataset=best_ds, score=best_score))
        else:
            logger.warning(
                "No match found for layer '%s' (best score=%.2f) — layer will be skipped.",
                layer.get("title"),
                best_score,
            )
            results.append(MatchResult(agol_layer=layer, geonode_dataset=None, score=best_score))

    return results

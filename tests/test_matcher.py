"""Tests for matcher."""

from agol_webmap_bridge.matcher import MatchResult, match_layers


DATASETS = [
    {"pk": "1", "title": "Woningbouwlocaties", "name": "woningbouwlocaties", "alternate": "hhr:woningbouwlocaties"},
    {"pk": "2", "title": "Grens Rijnland", "name": "grens_rijnland", "alternate": "hhr:grens_rijnland"},
    {"pk": "3", "title": "Completely Different", "name": "completely_different", "alternate": "hhr:completely_different"},
]


def test_exact_title_match():
    layers = [{"id": "l1", "title": "Woningbouwlocaties"}]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert len(results) == 1
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "1"


def test_fuzzy_match():
    layers = [{"id": "l2", "title": "Grens van Rijnland"}]
    results = match_layers(layers, DATASETS, threshold=0.5)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "2"


def test_no_match_returns_none():
    layers = [{"id": "l3", "title": "ZZZ Totally Unrelated Layer AAAA"}]
    results = match_layers(layers, DATASETS, threshold=0.9)
    assert len(results) == 1
    assert results[0].geonode_dataset is None


def test_multiple_layers():
    layers = [
        {"id": "l1", "title": "Woningbouwlocaties"},
        {"id": "l2", "title": "Grens Rijnland"},
        {"id": "l3", "title": "Something Unknown XYZ"},
    ]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert len(results) == 3
    assert results[0].geonode_dataset["pk"] == "1"
    assert results[1].geonode_dataset["pk"] == "2"
    assert results[2].geonode_dataset is None


def test_match_result_contains_original_layer():
    layers = [{"id": "l1", "title": "Woningbouwlocaties", "opacity": 0.75}]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert results[0].agol_layer["opacity"] == 0.75


def test_empty_layers():
    results = match_layers([], DATASETS)
    assert results == []


def test_empty_datasets():
    layers = [{"id": "l1", "title": "Woningbouwlocaties"}]
    results = match_layers(layers, [])
    assert results[0].geonode_dataset is None

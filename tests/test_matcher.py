"""Tests for matcher."""

from agol_webmap_bridge.matcher import MatchResult, _extract_url_service_name, match_layers


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


# ---------------------------------------------------------------------------
# URL service name extraction tests
# ---------------------------------------------------------------------------

def test_extract_url_service_name_mapserver():
    url = "https://example.com/arcgis/rest/services/Folder/MyService/MapServer/0"
    assert _extract_url_service_name(url) == "MyService"


def test_extract_url_service_name_featureserver():
    url = "https://example.com/arcgis/rest/services/MyFeatureService/FeatureServer/3"
    assert _extract_url_service_name(url) == "MyFeatureService"


def test_extract_url_service_name_no_suffix():
    assert _extract_url_service_name("https://example.com/no/match/here") == ""


def test_extract_url_service_name_empty():
    assert _extract_url_service_name("") == ""


def test_match_layers_uses_url_service_name():
    """When title does not match but the URL service name does, the layer should be matched."""
    datasets = [
        {"pk": "99", "title": "Some Title", "name": "Grens_Rijnland_formeel_mask", "alternate": "ws:Grens_Rijnland_formeel_mask"},
    ]
    layers = [
        {
            "id": "l1",
            "title": "Completely Different Title",
            "url": "https://example.com/arcgis/rest/services/Gebied/Grens_Rijnland_formeel_mask/MapServer/0",
        }
    ]
    results = match_layers(layers, datasets, threshold=0.5)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "99"


def test_match_layers_sublayer_combines_parent_and_title():
    """Sublayers combine parent service name + sublayer title for GeoNode name matching.

    ``Legger_regionale_kering_vigerend`` (parent) + ``Buitenbeschermingszone`` (title)
    → searches for ``legger_regionale_kering_vigerend_buitenbeschermingszone``.
    """
    datasets = [
        {
            "pk": "55",
            "title": "Buitenbeschermingszone",
            "name": "Legger_regionale_kering_vigerend_Buitenbeschermingszone",
            "alternate": "ws:Legger_regionale_kering_vigerend_Buitenbeschermingszone",
        },
    ]
    layer = {
        "id": "svc_sub_0",
        "title": "Buitenbeschermingszone",
        "_parent_url": "https://example.com/arcgis/rest/services/Legger/Legger_regionale_kering_vigerend/MapServer",
        "layerType": "ArcGISMapServiceSublayer",
    }
    results = match_layers([layer], datasets, threshold=0.8)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "55"


def test_match_layers_sublayer_no_match_when_only_title():
    """Sublayer with parent URL should NOT match a dataset whose name is only the sublayer title."""
    datasets = [
        {"pk": "42", "title": "Some Title", "name": "kernzone", "alternate": "ws:kernzone"},
    ]
    layer = {
        "id": "svc_sub_0",
        "title": "Kernzone",
        "_parent_url": "https://example.com/arcgis/rest/services/Wonen/Woningbouwlocaties_service/MapServer",
        "layerType": "ArcGISMapServiceSublayer",
    }
    results = match_layers([layer], datasets, threshold=0.9)
    # Combined search term 'woningbouwlocaties_service_kernzone' should not match 'kernzone' at high threshold
    assert results[0].geonode_dataset is None


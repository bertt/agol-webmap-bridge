"""Tests for matcher."""

from agol_webmap_bridge.matcher import MatchResult, _extract_url_service_name, match_layers


DATASETS = [
    {"pk": "1", "title": "Woningbouwlocaties", "name": "woningbouwlocaties", "alternate": "hhr:woningbouwlocaties"},
    {"pk": "2", "title": "Grens Rijnland", "name": "grens_rijnland", "alternate": "hhr:grens_rijnland"},
    {"pk": "3", "title": "Completely Different", "name": "completely_different", "alternate": "hhr:completely_different"},
]


def test_layer_without_url_returns_no_match():
    """Layers without a url, _fetched_name or _parent_url cannot be matched."""
    layers = [{"id": "l1", "title": "Woningbouwlocaties"}]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert len(results) == 1
    assert results[0].geonode_dataset is None


def test_layer_with_fetched_name_matches_exact():
    """_fetched_name is the primary candidate and is matched against GeoNode name."""
    layers = [{"id": "l1", "title": "Irrelevant Title", "_fetched_name": "woningbouwlocaties"}]
    results = match_layers(layers, DATASETS, threshold=0.9)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "1"


def test_layer_with_fetched_name_case_insensitive():
    """_fetched_name matching is case-insensitive."""
    layers = [{"id": "l1", "title": "Irrelevant", "_fetched_name": "Grens_Rijnland"}]
    results = match_layers(layers, DATASETS, threshold=0.9)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "2"


def test_fetched_name_takes_priority_over_url():
    """When both _fetched_name and url are present, _fetched_name wins."""
    layers = [
        {
            "id": "l1",
            "title": "Some Title",
            "_fetched_name": "grens_rijnland",
            "url": "https://example.com/arcgis/rest/services/Wonen/Woningbouwlocaties/MapServer/0",
        }
    ]
    results = match_layers(layers, DATASETS, threshold=0.9)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "2"  # grens_rijnland, not woningbouwlocaties


def test_no_match_returns_none():
    layers = [{"id": "l3", "_fetched_name": "zzz_totally_unknown_layer"}]
    results = match_layers(layers, DATASETS, threshold=0.9)
    assert len(results) == 1
    assert results[0].geonode_dataset is None


def test_multiple_layers_with_fetched_names():
    layers = [
        {"id": "l1", "_fetched_name": "woningbouwlocaties"},
        {"id": "l2", "_fetched_name": "grens_rijnland"},
        {"id": "l3", "title": "No URL at all"},  # no _fetched_name, no url
    ]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert len(results) == 3
    assert results[0].geonode_dataset["pk"] == "1"
    assert results[1].geonode_dataset["pk"] == "2"
    assert results[2].geonode_dataset is None


def test_match_result_contains_original_layer():
    layers = [{"id": "l1", "_fetched_name": "woningbouwlocaties", "opacity": 0.75}]
    results = match_layers(layers, DATASETS, threshold=0.6)
    assert results[0].agol_layer["opacity"] == 0.75


def test_empty_layers():
    results = match_layers([], DATASETS)
    assert results == []


def test_empty_datasets():
    layers = [{"id": "l1", "_fetched_name": "woningbouwlocaties"}]
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


def test_match_layers_uses_url_service_name_when_no_fetched_name():
    """When _fetched_name is absent but URL is present, service name is extracted from URL."""
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


def test_suffix_match_with_workspace_prefixed_name():
    """AGOL layer name is a word-boundary suffix of a long GeoNode name.

    GeoNode dataset name: hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken
    AGOL _fetched_name:   werk_in_uitvoering_vlakken  (suffix after '_')

    Raw SequenceMatcher score ≈ 0.59 — below the default threshold.
    The suffix-match logic should boost this to 1.0.
    """
    datasets = [
        {
            "pk": "420",
            "title": "Werk_in_uitvoering_vlakken",
            "name": "hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken",
            "alternate": "hhsk_op_de_kaart:hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken",
        }
    ]
    layer = {
        "id": "l_wiu",
        "title": "Lopende projecten (gebieden)",
        "_fetched_name": "werk_in_uitvoering_vlakken",
    }
    results = match_layers([layer], datasets, threshold=0.6)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "420"


def test_title_match_when_name_has_long_workspace_prefix():
    """GeoNode title matches AGOL _fetched_name directly (case-insensitive, underscores preserved)."""
    datasets = [
        {
            "pk": "420",
            "title": "Werk_in_uitvoering_vlakken",
            "name": "hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken",
            "alternate": "hhsk_op_de_kaart:hhsk_op_de_kaart_werk_in_uitvoering_werk_in_uitvoering_vlakken",
        }
    ]
    layer = {
        "id": "l_wiu",
        "title": "Lopende projecten (gebieden)",
        "_fetched_name": "Werk_in_uitvoering_vlakken",
    }
    results = match_layers([layer], datasets, threshold=0.9)
    assert results[0].geonode_dataset is not None
    assert results[0].geonode_dataset["pk"] == "420"


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


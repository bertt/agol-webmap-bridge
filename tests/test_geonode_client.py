"""Tests for geonode_client."""

import pytest

from agol_webmap_bridge.geonode_client import GeoNodeError, fetch_datasets


BASE_URL = "https://example.geonode.org"
PAGE1 = {
    "links": {"next": f"{BASE_URL}/api/v2/datasets/?page=2&page_size=100", "previous": None},
    "total": 2,
    "page": 1,
    "page_size": 1,
    "datasets": [{"pk": "1", "title": "Dataset A"}],
}
PAGE2 = {
    "links": {"next": None, "previous": f"{BASE_URL}/api/v2/datasets/?page=1&page_size=100"},
    "total": 2,
    "page": 2,
    "page_size": 1,
    "datasets": [{"pk": "2", "title": "Dataset B"}],
}


def test_fetch_datasets_single_page(requests_mock):
    single_page = {
        "links": {"next": None, "previous": None},
        "total": 1,
        "page": 1,
        "page_size": 100,
        "datasets": [{"pk": "1", "title": "Dataset A"}],
    }
    requests_mock.get(f"{BASE_URL}/api/v2/datasets/", json=single_page)

    result = fetch_datasets(BASE_URL)
    assert len(result) == 1
    assert result[0]["title"] == "Dataset A"


def test_fetch_datasets_pagination(requests_mock):
    requests_mock.get(f"{BASE_URL}/api/v2/datasets/", json=PAGE1)
    requests_mock.get(f"{BASE_URL}/api/v2/datasets/?page=2&page_size=100", json=PAGE2)

    result = fetch_datasets(BASE_URL)
    assert len(result) == 2
    titles = {d["title"] for d in result}
    assert titles == {"Dataset A", "Dataset B"}


def test_fetch_datasets_http_error(requests_mock):
    requests_mock.get(f"{BASE_URL}/api/v2/datasets/", status_code=500)

    with pytest.raises(GeoNodeError):
        fetch_datasets(BASE_URL)


def test_fetch_datasets_strips_trailing_slash(requests_mock):
    single_page = {
        "links": {"next": None},
        "datasets": [{"pk": "1", "title": "X"}],
    }
    requests_mock.get(f"{BASE_URL}/api/v2/datasets/", json=single_page)

    result = fetch_datasets(BASE_URL + "/")  # trailing slash should be stripped
    assert len(result) == 1

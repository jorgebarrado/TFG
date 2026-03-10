import pytest
import requests
from unittest.mock import patch
from citations.services.semantic_scholar_client import get_citing_papers_for_doi, SemanticScholarError
from citations.services.semantic_fetch import get_crossref_citations

@patch('citations.services.semantic_scholar_client.requests.get')
@pytest.mark.parametrize("run", range(50))
def test_semantic_scholar_rate_limit(mock_get, run):
    mock_response = mock_get.return_value
    mock_response.status_code = 429
    mock_response.text = "429 Too Many Requests"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")

    with pytest.raises(SemanticScholarError) as excinfo:
        get_citing_papers_for_doi("10.1234/test.doi")

    assert "429" in str(excinfo.value)

@patch('citations.services.semantic_scholar_client.requests.get')
@pytest.mark.parametrize("run", range(50))
def test_semantic_scholar_gateway_error(mock_get, run):
    mock_response = mock_get.return_value
    mock_response.status_code = 502
    mock_response.text = "502 Bad Gateway"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("502 Bad Gateway")

    with pytest.raises(SemanticScholarError) as excinfo:
        get_citing_papers_for_doi("10.1234/test.doi")

    assert "502" in str(excinfo.value)

@patch('citations.services.semantic_fetch.requests.get')
@pytest.mark.parametrize("run", range(50))
def test_crossref_rate_limit(mock_get, run):
    mock_response = mock_get.return_value
    mock_response.status_code = 429
    mock_response.text = "429 Too Many Requests"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Too Many Requests")

    # get_crossref_citations uses _safe_get which returns None and prints error on exception or non-200
    res = get_crossref_citations("10.1234/crossref.doi")

    # Check that it safely returns empty list on rate limit
    assert res == []

@patch('citations.services.semantic_fetch.requests.get')
@pytest.mark.parametrize("run", range(50))
def test_crossref_gateway_error(mock_get, run):
    mock_response = mock_get.return_value
    mock_response.status_code = 502
    mock_response.text = "502 Bad Gateway"
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("502 Bad Gateway")

    res = get_crossref_citations("10.1234/crossref.doi")
    assert res == []

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from citations.services import semantic_scholar_client
from citations.services.semantic_scholar_client import SemanticScholarError


def _response(status_code=200, payload=None, text=""):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload or {}
    response.content = b"{}"
    return response


class SemanticScholarClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_paginated_citations_quotes_doi_identifier(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.side_effect = [
            _response(payload={"paperId": "abc123"}),
            _response(
                payload={
                    "data": [
                        {
                            "citingPaper": {
                                "title": "Citing paper",
                                "year": 2024,
                                "externalIds": {"DOI": "10.1000/citing"},
                                "authors": [{"name": "Ada"}, {"name": "Grace"}],
                                "url": "https://www.semanticscholar.org/paper/abc",
                            },
                            "contexts": ["cites the original paper"],
                        }
                    ],
                    "next": 10,
                }
            ),
        ]

        citing_papers, next_offset = (
            semantic_scholar_client.get_citing_papers_for_doi_paginated(
                "https://doi.org/10.1145/123/456.",
                limit=10,
                offset=0,
            )
        )

        first_url = session.get.call_args_list[0].args[0]
        second_url = session.get.call_args_list[1].args[0]

        self.assertEqual(
            first_url,
            "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1145%2F123%2F456",
        )
        self.assertEqual(
            second_url,
            "https://api.semanticscholar.org/graph/v1/paper/abc123/citations",
        )
        self.assertEqual(next_offset, 10)
        self.assertEqual(citing_papers[0]["title"], "Citing paper")
        self.assertEqual(citing_papers[0]["authors"], "Ada, Grace")
        self.assertEqual(citing_papers[0]["contexts"], ["cites the original paper"])

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_paginated_citations_exposes_resolver_http_error(
        self,
        mock_session_factory,
    ):
        session = mock_session_factory.return_value
        session.get.return_value = _response(
            status_code=400,
            text="Bad DOI identifier",
        )

        with self.assertRaisesRegex(
            SemanticScholarError,
            r"resolver el paper \(HTTP 400\): Bad DOI identifier",
        ):
            semantic_scholar_client.get_citing_papers_for_doi_paginated(
                "10.1145/123/456"
            )

        session.get.assert_called_once()

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_citation_counts_use_batch_request_and_cache(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.post.return_value = _response(
            payload=[
                {"externalIds": {"DOI": "10.1000/with"}, "citationCount": 7},
                None,
            ]
        )

        counts = semantic_scholar_client.get_citation_counts_for_dois(
            ["https://doi.org/10.1000/with", "10.1000/none"]
        )
        cached_counts = semantic_scholar_client.get_citation_counts_for_dois(
            ["10.1000/with", "10.1000/none"]
        )

        self.assertEqual(counts["https://doi.org/10.1000/with"], 7)
        self.assertEqual(counts["10.1000/with"], 7)
        self.assertEqual(counts["10.1000/none"], 0)
        self.assertEqual(cached_counts["10.1000/with"], 7)
        session.post.assert_called_once()
        self.assertEqual(
            session.post.call_args.kwargs["json"],
            {"ids": ["DOI:10.1000/with", "DOI:10.1000/none"]},
        )

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from citations.services import semantic_scholar_client
from citations.services.semantic_scholar_client import SemanticScholarError


def _response(status_code=200, payload=None, text="", headers=None):
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    response.json.return_value = payload or {}
    response.content = b"{}"
    return response


class SemanticScholarClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        reset_rate_limiter = getattr(
            semantic_scholar_client, "_reset_rate_limiter_for_tests", None
        )
        if reset_rate_limiter:
            reset_rate_limiter()
        self.sleep_patcher = patch("time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def tearDown(self):
        self.sleep_patcher.stop()

    @override_settings(SEMANTIC_SCHOLAR_API_KEY="test-semantic-key")
    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_api_key_header_is_sent_when_configured(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.return_value = _response(payload={"paperId": "abc123"})

        semantic_scholar_client.get_paper_by_id("abc123", fields="paperId")

        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "test-semantic-key")
        self.assertEqual(headers["Accept"], "application/json")

    @override_settings(SEMANTIC_SCHOLAR_API_KEY="")
    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_api_key_header_is_omitted_when_not_configured(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.return_value = _response(payload={"paperId": "abc123"})

        semantic_scholar_client.get_paper_by_id("abc123", fields="paperId")

        headers = session.get.call_args.kwargs["headers"]
        self.assertNotIn("x-api-key", headers)
        self.assertEqual(headers["Accept"], "application/json")

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_429_retries_with_retry_after(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.side_effect = [
            _response(
                status_code=429, text="rate limited", headers={"Retry-After": "3"}
            ),
            _response(payload={"paperId": "abc123"}),
        ]

        data = semantic_scholar_client.get_paper_by_id("abc123", fields="paperId")

        self.assertEqual(data["paperId"], "abc123")
        self.assertEqual(session.get.call_count, 2)
        self.mock_sleep.assert_any_call(3.0)

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_500_retries_with_exponential_backoff(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.side_effect = [
            _response(status_code=500, text="server error"),
            _response(payload={"paperId": "abc123"}),
        ]

        data = semantic_scholar_client.get_paper_by_id("abc123", fields="paperId")

        self.assertEqual(data["paperId"], "abc123")
        self.assertEqual(session.get.call_count, 2)
        self.mock_sleep.assert_any_call(1.0)

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_404_does_not_retry(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.return_value = _response(status_code=404, text="not found")

        with self.assertRaises(SemanticScholarError):
            semantic_scholar_client.get_paper_by_id("missing", fields="paperId")

        session.get.assert_called_once()

    @override_settings(SEMANTIC_SCHOLAR_API_KEY="secret-value-that-must-not-leak")
    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_api_key_is_not_logged_on_auth_error(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.return_value = _response(status_code=403, text="forbidden")

        with self.assertLogs("citations.semantic_scholar", level="WARNING") as logs:
            with self.assertRaises(SemanticScholarError):
                semantic_scholar_client.get_paper_by_id("abc123", fields="paperId")

        log_text = "\n".join(logs.output)
        self.assertIn("API key", log_text)
        self.assertNotIn("secret-value-that-must-not-leak", log_text)
        self.assertNotIn("x-api-key", log_text)

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_public_get_endpoints_are_built_correctly(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.get.side_effect = [
            _response(payload={"paperId": "doi-paper"}),
            _response(payload={"data": []}),
            _response(payload={"data": []}),
            _response(payload={"data": []}),
        ]

        semantic_scholar_client.get_paper_by_doi("10.1145/123/456", fields="paperId")
        semantic_scholar_client.search_papers("test query", fields="paperId")
        semantic_scholar_client.get_paper_citations("paper123", fields="paperId")
        semantic_scholar_client.get_paper_references("paper123", fields="paperId")

        urls = [call.args[0] for call in session.get.call_args_list]
        self.assertEqual(
            urls[0],
            "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1145%2F123%2F456",
        )
        self.assertEqual(
            urls[1],
            "https://api.semanticscholar.org/graph/v1/paper/search",
        )
        self.assertEqual(
            urls[2],
            "https://api.semanticscholar.org/graph/v1/paper/paper123/citations",
        )
        self.assertEqual(
            urls[3],
            "https://api.semanticscholar.org/graph/v1/paper/paper123/references",
        )

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_batch_request_uses_central_post_helper(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.post.return_value = _response(
            payload=[{"paperId": "abc123", "citationCount": 2}]
        )

        counts = semantic_scholar_client.get_citation_counts_for_dois(["10.1000/test"])

        self.assertEqual(counts["10.1000/test"], 2)
        session.post.assert_called_once()
        self.assertEqual(
            session.post.call_args.args[0],
            "https://api.semanticscholar.org/graph/v1/paper/batch",
        )

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
    def test_paginated_citations_uses_cached_doi_page_when_resolver_is_rate_limited(
        self,
        mock_session_factory,
    ):
        session = mock_session_factory.return_value
        session.get.side_effect = [
            _response(payload={"paperId": "abc123"}),
            _response(
                payload={
                    "data": [
                        {
                            "citingPaper": {
                                "title": "Cached citing paper",
                                "year": 2024,
                                "externalIds": {"DOI": "10.1000/citing"},
                                "authors": [{"name": "Ada"}],
                                "url": "https://www.semanticscholar.org/paper/cached",
                            },
                            "contexts": ["cached context"],
                        }
                    ],
                    "next": None,
                }
            ),
        ]
        first_result = semantic_scholar_client.get_citing_papers_for_doi_paginated(
            "10.1000/original",
            limit=10,
            offset=0,
        )
        cache.delete(semantic_scholar_client._paper_id_cache_key("10.1000/original"))

        session.get.reset_mock()
        session.get.side_effect = None
        session.get.return_value = _response(status_code=429)

        cached_result = semantic_scholar_client.get_citing_papers_for_doi_paginated(
            "10.1000/original",
            limit=10,
            offset=0,
        )

        self.assertEqual(cached_result, first_result)
        self.assertEqual(cached_result[0][0]["title"], "Cached citing paper")
        self.assertEqual(session.get.call_count, 4)

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_citation_counts_use_batch_request_and_cache(self, mock_session_factory):
        session = mock_session_factory.return_value
        session.post.return_value = _response(
            payload=[
                {
                    "paperId": "paper-with",
                    "externalIds": {"DOI": "10.1000/with"},
                    "citationCount": 7,
                },
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
        self.assertEqual(
            session.post.call_args.kwargs["params"],
            {"fields": "paperId,externalIds,citationCount"},
        )

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_citation_counts_cache_paper_id_for_paginated_citations(
        self,
        mock_session_factory,
    ):
        session = mock_session_factory.return_value
        session.post.return_value = _response(
            payload=[
                {
                    "paperId": "resolved-paper-id",
                    "externalIds": {"DOI": "10.1000/with"},
                    "citationCount": 7,
                },
            ]
        )

        semantic_scholar_client.get_citation_counts_for_dois(["10.1000/with"])

        self.assertEqual(
            cache.get(semantic_scholar_client._paper_id_cache_key("10.1000/with")),
            "resolved-paper-id",
        )

        session.get.return_value = _response(
            payload={
                "data": [
                    {
                        "citingPaper": {
                            "title": "Citing paper",
                            "year": 2024,
                            "externalIds": {"DOI": "10.1000/citing"},
                            "authors": [{"name": "Ada"}],
                            "url": "https://www.semanticscholar.org/paper/citing",
                        },
                        "contexts": ["cites the original paper"],
                    }
                ],
                "next": None,
            }
        )

        citing_papers, next_offset = (
            semantic_scholar_client.get_citing_papers_for_doi_paginated("10.1000/with")
        )

        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(
            session.get.call_args.args[0],
            "https://api.semanticscholar.org/graph/v1/paper/resolved-paper-id/citations",
        )
        self.assertEqual(citing_papers[0]["title"], "Citing paper")
        self.assertIsNone(next_offset)

    @patch("citations.services.semantic_scholar_client.build_external_api_session")
    def test_citation_counts_backfill_missing_paper_id_when_count_is_cached(
        self,
        mock_session_factory,
    ):
        cache.set(
            semantic_scholar_client._citation_count_cache_key("10.1000/with"),
            7,
        )
        session = mock_session_factory.return_value
        session.post.return_value = _response(
            payload=[
                {
                    "paperId": "backfilled-paper-id",
                    "externalIds": {"DOI": "10.1000/with"},
                    "citationCount": 7,
                },
            ]
        )

        counts = semantic_scholar_client.get_citation_counts_for_dois(["10.1000/with"])

        self.assertEqual(counts["10.1000/with"], 7)
        self.assertEqual(
            cache.get(semantic_scholar_client._paper_id_cache_key("10.1000/with")),
            "backfilled-paper-id",
        )
        session.post.assert_called_once()
        self.assertEqual(
            session.post.call_args.kwargs["json"],
            {"ids": ["DOI:10.1000/with"]},
        )

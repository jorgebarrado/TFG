# Tests del cliente DBLP: búsqueda de artículos por autor, manejo de errores HTTP y caché.
from http.client import RemoteDisconnected
from unittest.mock import Mock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from citations.services import dblp_client


def _build_dblp_response(xml_text: str) -> Mock:
    response = Mock()
    response.content = xml_text.encode("utf-8")
    response.raise_for_status.return_value = None
    return response


class DBLPClientTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_normalize_dblp_url_accepts_pid_without_extension(self):
        self.assertEqual(
            dblp_client._normalize_dblp_url("https://dblp.org/pid/r/GregorioRobles"),
            "https://dblp.org/pid/r/GregorioRobles.xml",
        )

    @patch("citations.services.dblp_client.requests.get")
    @patch("citations.services.dblp_client.requests.Session")
    def test_get_author_papers_uses_session_that_ignores_env_proxy(
        self,
        mock_session_cls,
        mock_requests_get,
    ):
        xml_payload = """<?xml version="1.0"?>
<dblpperson>
  <r>
    <article key="journals/test/Example24">
      <author>Ada Lovelace</author>
      <title>Example paper</title>
      <year>2024</year>
      <ee>https://doi.org/10.1000/example</ee>
      <url>db/journals/test/example.html#Example24</url>
    </article>
  </r>
</dblpperson>
"""
        session = mock_session_cls.return_value
        session.get.return_value = _build_dblp_response(xml_payload)
        mock_requests_get.return_value = _build_dblp_response(xml_payload)

        papers = dblp_client.get_author_papers(
            "https://dblp.org/pid/r/GregorioRobles.html"
        )

        self.assertEqual(len(papers), 1)
        mock_session_cls.assert_called_once()
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with(
            "https://dblp.org/pid/r/GregorioRobles.xml",
            headers=dblp_client.DBLP_REQUEST_HEADERS,
            timeout=12,
        )
        mock_requests_get.assert_not_called()

    @patch("time.sleep")
    @patch("citations.services.dblp_client.build_external_api_session")
    def test_get_author_papers_retries_remote_disconnect_once(
        self,
        mock_build_session,
        mock_sleep,
    ):
        xml_payload = """<?xml version="1.0"?>
<dblpperson>
  <r>
    <article key="journals/test/Retry24">
      <author>Ada Lovelace</author>
      <title>Retry paper</title>
      <year>2024</year>
    </article>
  </r>
</dblpperson>
"""
        session = Mock()
        session.get.side_effect = [
            requests.ConnectionError(
                "Connection aborted.",
                RemoteDisconnected("Remote end closed connection without response"),
            ),
            _build_dblp_response(xml_payload),
        ]
        mock_build_session.return_value = session

        papers = dblp_client.get_author_papers(
            "https://dblp.org/pid/r/GregorioRobles.html"
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(session.get.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("citations.services.dblp_client.build_external_api_session")
    def test_get_author_papers_uses_cache_for_same_profile(self, mock_build_session):
        xml_payload = """<?xml version="1.0"?>
<dblpperson>
  <r>
    <article key="journals/test/Cached24">
      <author>Ada Lovelace</author>
      <title>Cached paper</title>
      <year>2024</year>
    </article>
  </r>
</dblpperson>
"""
        session = Mock()
        session.get.return_value = _build_dblp_response(xml_payload)
        mock_build_session.return_value = session

        first = dblp_client.get_author_papers(
            "https://dblp.org/pid/r/GregorioRobles.html"
        )
        second = dblp_client.get_author_papers("https://dblp.org/pid/r/GregorioRobles")

        self.assertEqual(first, second)
        session.get.assert_called_once_with(
            "https://dblp.org/pid/r/GregorioRobles.xml",
            headers=dblp_client.DBLP_REQUEST_HEADERS,
            timeout=12,
        )

    @patch("citations.services.dblp_client.build_external_api_session")
    def test_get_author_papers_reports_dblp_rate_limit(self, mock_build_session):
        response = Mock()
        response.status_code = 429
        response.headers = {"Retry-After": "30"}
        http_error = requests.HTTPError("429 Too Many Requests")
        http_error.response = response
        response.raise_for_status.side_effect = http_error

        session = Mock()
        session.get.return_value = response
        mock_build_session.return_value = session

        with self.assertRaises(dblp_client.DBLPClientError) as ctx:
            dblp_client.get_author_papers("https://dblp.org/pid/r/GregorioRobles.html")

        message = str(ctx.exception)
        self.assertIn("DBLP esta limitando temporalmente las peticiones", message)
        self.assertIn("30 segundos", message)

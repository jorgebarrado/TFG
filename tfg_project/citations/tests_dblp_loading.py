from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import TestCase
from django.urls import reverse

from citations.models import UserProfile
from citations.services.dblp_client import DBLPClientError


class DBLPLoadingIndicatorTests(TestCase):
    def setUp(self):
        site, _ = Site.objects.get_or_create(
            id=1,
            defaults={"domain": "127.0.0.1", "name": "127.0.0.1"},
        )
        for provider_name in ("google", "orcid"):
            app = SocialApp.objects.create(
                provider=provider_name,
                name=provider_name.capitalize(),
                client_id="test",
                secret="test",
            )
            app.sites.set([site])

    def test_dblp_articles_load_form_renders_loading_indicator(self):
        response = self.client.get(reverse("dblp_articles"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dblp-load-form')
        self.assertContains(response, 'id="include-without-citations"')
        self.assertContains(response, 'name="include_without_citations"')
        self.assertContains(response, 'id="dblp-load-progress"')
        self.assertContains(response, 'class="extract-progress d-none"')
        self.assertContains(response, 'Buscando articulos en DBLP')

    @patch("citations.views.user_views.get_author_papers")
    def test_logged_user_sees_prefilled_form_without_auto_loading_dblp(
        self,
        mock_get_author_papers,
    ):
        user = User.objects.create_user(username="ada", password="test-pass")
        self.client.force_login(user)
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"dblp_url": "https://dblp.org/pid/t/TestAuthor.html"},
        )

        response = self.client.get(reverse("dblp_articles"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dblp-load-form')
        self.assertContains(
            response,
            'value="https://dblp.org/pid/t/TestAuthor.html"',
        )
        self.assertNotContains(response, "<strong>Perfil DBLP:</strong>")
        mock_get_author_papers.assert_not_called()

    def test_citation_review_load_form_renders_loading_indicator(self):
        response = self.client.get(reverse("citation_review_papers"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dblp-load-form')
        self.assertContains(response, 'id="dblp-load-progress"')
        self.assertContains(response, 'class="extract-progress d-none"')
        self.assertContains(response, 'Buscando articulos en DBLP')

    @patch("citations.views.tutor_views.get_author_papers")
    def test_logged_user_sees_prefilled_citation_review_form_without_auto_loading_dblp(
        self,
        mock_get_author_papers,
    ):
        user = User.objects.create_user(username="grace", password="test-pass")
        self.client.force_login(user)
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"dblp_url": "https://dblp.org/pid/t/TestAuthor.html"},
        )

        response = self.client.get(reverse("citation_review_papers"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dblp-load-form')
        self.assertContains(
            response,
            'value="https://dblp.org/pid/t/TestAuthor.html"',
        )
        self.assertNotContains(response, "Artículo aleatorio")
        mock_get_author_papers.assert_not_called()

    @patch("citations.views.tutor_views.get_author_papers")
    def test_citation_review_shows_dblp_error_instead_of_empty_state(
        self,
        mock_get_author_papers,
    ):
        mock_get_author_papers.side_effect = DBLPClientError(
            "No se pudo conectar con DBLP."
        )

        response = self.client.get(
            reverse("citation_review_papers"),
            {"dblp_url": "https://dblp.org/pid/t/TestAuthor.html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo conectar con DBLP.")
        self.assertNotContains(response, "No hemos encontrado articulos en DBLP.")

    @patch("citations.views.user_views.get_citation_count")
    @patch("citations.views.user_views.get_author_papers")
    def test_switch_is_not_shown_after_articles_are_loaded(
        self,
        mock_get_author_papers,
        mock_get_citation_count,
    ):
        mock_get_author_papers.return_value = [
            {"title": "Paper one", "type": "article", "doi": "10.1000/one"},
        ]
        mock_get_citation_count.return_value = 2

        response = self.client.get(
            reverse("dblp_articles"),
            {"dblp_url": "https://dblp.org/pid/t/TestAuthor.html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="include-without-citations"')

    @patch("citations.views.user_views.get_citation_counts_for_dois")
    @patch("citations.views.user_views.get_citation_count")
    @patch("citations.views.user_views.get_author_papers")
    def test_articles_without_citations_are_excluded_when_switch_is_off(
        self,
        mock_get_author_papers,
        mock_get_citation_count,
        mock_get_citation_counts_for_dois,
    ):
        mock_get_author_papers.return_value = [
            {"title": "Has citations", "type": "article", "doi": "10.1000/with"},
            {"title": "Without citations", "type": "article", "doi": "10.1000/none"},
            {"title": "No DOI article", "type": "article", "doi": ""},
        ]
        mock_get_citation_counts_for_dois.return_value = {
            "10.1000/with": 4,
            "10.1000/none": 0,
        }

        response = self.client.get(
            reverse("dblp_articles"),
            {
                "dblp_url": "https://dblp.org/pid/t/TestAuthor.html",
                "include_without_citations": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Has citations")
        self.assertNotContains(response, "Without citations")
        self.assertNotContains(response, "No DOI article")
        mock_get_citation_counts_for_dois.assert_called_once_with(
            ["10.1000/with", "10.1000/none"]
        )
        mock_get_citation_count.assert_not_called()

    @patch("citations.views.user_views.get_citation_count")
    @patch("citations.views.user_views.get_author_papers")
    def test_articles_without_citations_are_kept_when_switch_is_on(
        self,
        mock_get_author_papers,
        mock_get_citation_count,
    ):
        mock_get_author_papers.return_value = [
            {"title": "Has citations", "type": "article", "doi": "10.1000/with"},
            {"title": "Without citations", "type": "article", "doi": "10.1000/none"},
            {"title": "No DOI article", "type": "article", "doi": ""},
        ]

        def citation_count_for_doi(doi):
            return {"10.1000/with": 4, "10.1000/none": 0}.get(doi, 0)

        mock_get_citation_count.side_effect = citation_count_for_doi

        response = self.client.get(
            reverse("dblp_articles"),
            {
                "dblp_url": "https://dblp.org/pid/t/TestAuthor.html",
                "include_without_citations": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Has citations")
        self.assertContains(response, "Without citations")
        self.assertContains(response, "No DOI article")

    @patch("citations.views.user_views.get_citation_count")
    @patch("citations.views.user_views.get_author_papers")
    def test_results_page_load_more_has_spinner_hook(
        self,
        mock_get_author_papers,
        mock_get_citation_count,
    ):
        mock_get_author_papers.return_value = [
            {
                "title": f"Paper {index}",
                "type": "article",
                "doi": f"10.1000/{index}",
            }
            for index in range(11)
        ]
        mock_get_citation_count.return_value = 1

        response = self.client.get(
            reverse("dblp_articles"),
            {"dblp_url": "https://dblp.org/pid/t/TestAuthor.html"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-dblp-load-more')
        self.assertContains(response, 'id="dblp-load-progress"')

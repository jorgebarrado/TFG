from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from citations.models import UserProfile, IncorrectCitation

User = get_user_model()


class DBLPFlowTests(TestCase):
    def setUp(self):
        site, _ = Site.objects.get_or_create(domain="example.com", name="example.com")
        site.save()
        social_app, _ = SocialApp.objects.get_or_create(
            provider="google", name="Google", client_id="test"
        )
        social_app.sites.add(site)
        social_app_orcid, _ = SocialApp.objects.get_or_create(
            provider="orcid", name="ORCID", client_id="test_orcid"
        )
        social_app_orcid.sites.add(site)

        self.user = User.objects.create_user(username="testuser", password="password")
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.client.login(username="testuser", password="password")

    def test_user_without_dblp_url_shows_message(self):
        response = self.client.get(reverse("citation_review_papers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configura tu DBLP")
        self.assertIsNone(response.context["papers"])

    @patch("citations.views.tutor_views.get_author_papers")
    def test_user_with_dblp_url_loads_articles(self, mock_get_papers):
        self.profile.dblp_url = "https://dblp.org/pid/123.xml"
        self.profile.save()

        mock_get_papers.return_value = [
            {
                "title": "Paper 1",
                "year": 2020,
                "doi": "10.123/1",
                "type": "article",
                "authors": ["A"],
            },
            {
                "title": "Paper 2",
                "year": 2021,
                "doi": None,
                "type": "inproceedings",
                "authors": ["B"],
            },
        ]

        response = self.client.get(reverse("citation_review_papers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paper 1")
        self.assertContains(response, "Paper 2")
        self.assertEqual(len(response.context["papers"]), 2)

    @patch("citations.views.tutor_views.get_author_papers")
    @patch("citations.views.tutor_views.get_citing_papers_for_doi_paginated")
    def test_paper_with_doi_queries_citers(self, mock_get_citing, mock_get_papers):
        self.profile.dblp_url = "https://dblp.org/pid/123.xml"
        self.profile.save()

        mock_get_papers.return_value = [
            {
                "title": "Paper 1",
                "year": 2020,
                "doi": "10.123/1",
                "type": "article",
                "authors": ["A"],
            },
        ]

        mock_get_citing.return_value = (
            [
                {
                    "title": "Citing 1",
                    "year": 2022,
                    "doi": "10.123/c1",
                    "authors": "C",
                    "url": "http://ss/c1",
                }
            ],
            1,
        )

        response = self.client.get(reverse("citation_review_citers", args=[0]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Citing 1")
        self.assertContains(response, "10.123/c1")
        self.assertFalse(response.context["citing_papers"][0]["is_reported"])

    @patch("citations.views.tutor_views.get_author_papers")
    def test_paper_without_doi_shows_error(self, mock_get_papers):
        self.profile.dblp_url = "https://dblp.org/pid/123.xml"
        self.profile.save()

        mock_get_papers.return_value = [
            {
                "title": "Paper 1",
                "year": 2020,
                "doi": None,
                "type": "article",
                "authors": ["A"],
            },
        ]

        response = self.client.get(reverse("citation_review_citers", args=[0]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Este artículo no tiene DOI. No se pueden buscar artículos citantes en Semantic Scholar sin un DOI."
        )
        self.assertEqual(response.context["citing_papers"], [])

    @patch("citations.views.tutor_views.get_author_papers")
    @patch("citations.views.tutor_views.get_citing_papers_for_doi_paginated")
    def test_citer_already_registered_shows_as_reported(
        self, mock_get_citing, mock_get_papers
    ):
        self.profile.dblp_url = "https://dblp.org/pid/123.xml"
        self.profile.save()

        IncorrectCitation.objects.create(
            author=self.user,
            doi_original="10.123/1",
            doi_incorrect="10.123/c1",
            incorrect_reason="Test",
            citation_type="not said",
            publication_area="OTH",
        )

        mock_get_papers.return_value = [
            {
                "title": "Paper 1",
                "year": 2020,
                "doi": "10.123/1",
                "type": "article",
                "authors": ["A"],
            },
        ]

        mock_get_citing.return_value = (
            [
                {
                    "title": "Citing 1",
                    "year": 2022,
                    "doi": "10.123/c1",
                    "authors": "C",
                    "url": "http://ss/c1",
                }
            ],
            1,
        )

        response = self.client.get(reverse("citation_review_citers", args=[0]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["citing_papers"][0]["is_reported"])
        self.assertContains(response, "Ya reportado")
        self.assertContains(response, "Ver reporte")

    @patch("citations.views.tutor_views.get_author_papers")
    @patch("citations.views.tutor_views.get_citing_papers_for_doi_paginated")
    def test_semantic_scholar_error_does_not_cause_500(
        self, mock_get_citing, mock_get_papers
    ):
        from citations.services.semantic_scholar_client import SemanticScholarError

        self.profile.dblp_url = "https://dblp.org/pid/123.xml"
        self.profile.save()

        mock_get_papers.return_value = [
            {
                "title": "Paper 1",
                "year": 2020,
                "doi": "10.123/1",
                "type": "article",
                "authors": ["A"],
            },
        ]

        mock_get_citing.side_effect = SemanticScholarError("API Down")

        response = self.client.get(reverse("citation_review_citers", args=[0]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Error al consultar Semantic Scholar: API Down")
        self.assertEqual(response.context["citing_papers"], [])

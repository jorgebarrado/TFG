from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from .models import IncorrectCitation
from unittest.mock import patch

@override_settings(SITE_ID=1)
class SocialAppTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        site, _ = Site.objects.get_or_create(
            id=1, defaults={"domain": "127.0.0.1", "name": "127.0.0.1"}
        )

        # Crear SocialApps para todos los providers usados
        providers = ["google", "orcid"]
        for provider_name in providers:
            app = SocialApp.objects.create(
                provider=provider_name,
                name=provider_name.capitalize(),
                client_id="test",
                secret="test",
            )
            app.sites.set([site])

class HomePageTests(SocialAppTestCase):
    def test_home_status_code(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

class RegisterTests(TestCase):
    def test_register_user(self):
        response = self.client.post(reverse('register'), {
            'username': 'nuevo_usuario',
            'password1': 'contraseñaSegura123',
            'password2': 'contraseñaSegura123',
        })
        self.assertEqual(response.status_code, 302)  # Redirección
        self.assertTrue(User.objects.filter(username='nuevo_usuario').exists())

class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='jorge', password='test1234')

    def test_login_user(self):
        response = self.client.post(reverse('login'), {
            'username': 'jorge',
            'password': 'test1234'
        })
        self.assertEqual(response.status_code, 302)

class ReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='jorge', password='test1234')
        self.client.login(username='jorge', password='test1234')

    def test_create_report(self):
        response = self.client.post(reverse('ajax_submit'), {
            'doi_original': '10.1000/xyz123',
            'doi_incorrect': '10.1000/abc456',
            'incorrect_reason': 'Mal interpretación.',
            'citation_type': 'misinterpretation',
            'publication_area': 'CIS',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IncorrectCitation.objects.count(), 1)
        self.assertEqual(IncorrectCitation.objects.first().author, self.user)

class MetadataTests(TestCase):
    def test_get_metadata_without_doi(self):
        response = self.client.get(reverse('get_all_metadata'))
        self.assertEqual(response.status_code, 400)

class VoteViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.citation = IncorrectCitation.objects.create(
            doi_original='10.1000/orig',
            doi_incorrect='10.1000/inc',
            incorrect_reason='Test reason',
            citation_type='misinterpretation',
            publication_area='CIS'
        )

    def test_vote_unauthenticated(self):
        response = self.client.post(reverse('vote'), {'citation_id': self.citation.id, 'vote': 1})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'not_authenticated')

    def test_vote_missing_parameters(self):
        self.client.login(username='testuser', password='password')
        response = self.client.post(reverse('vote'), {'vote': 1})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Missing parameters')

    def test_vote_invalid_input(self):
        self.client.login(username='testuser', password='password')
        response = self.client.post(reverse('vote'), {'citation_id': 'abc', 'vote': 1})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Invalid input')

    def test_vote_invalid_vote_value(self):
        self.client.login(username='testuser', password='password')
        response = self.client.post(reverse('vote'), {'citation_id': self.citation.id, 'vote': 5})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Invalid vote value')

    def test_vote_nonexistent_citation(self):
        self.client.login(username='testuser', password='password')
        response = self.client.post(reverse('vote'), {'citation_id': 999, 'vote': 1})
        self.assertEqual(response.status_code, 404)

    def test_upvote_citation(self):
        self.client.login(username='testuser', password='password')
        response = self.client.post(reverse('vote'), {'citation_id': self.citation.id, 'vote': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['upvotes'], 1)
        self.assertEqual(response.json()['downvotes'], 0)
        self.assertEqual(response.json()['user_vote'], 1)

class SemanticCitationsViewTests(SocialAppTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        self.original_doi = '10.1000/original'
        self.citing_doi_registered = '10.1000/citing-registered'
        self.citing_doi_unregistered = '10.1000/citing-unregistered'

        # Crear un reporte de cita incorrecta para el DOI registrado
        self.report = IncorrectCitation.objects.create(
            doi_original=self.original_doi,
            doi_incorrect=self.citing_doi_registered,
            incorrect_reason='Test reason',
            citation_type='misinterpretation',
            publication_area='CIS',
            author=self.user
        )

    @patch('citations.views.get_citation_count')
    @patch('citations.views.get_citing_articles')
    def test_semantic_citations_view_marks_registered(self, mock_get_citing_articles, mock_get_citation_count):
        # Configurar los mocks
        mock_get_citation_count.return_value = 2
        mock_get_citing_articles.return_value = [
            {'doi': self.citing_doi_registered, 'title': 'Registered Article', 'authors': 'Author A', 'year': 2023},
            {'doi': self.citing_doi_unregistered, 'title': 'Unregistered Article', 'authors': 'Author B', 'year': 2024},
        ]

        # Realizar la petición
        response = self.client.get(reverse('semantic_citations'), {'doi': self.original_doi})
        self.assertEqual(response.status_code, 200)

        # Verificar el contexto
        citations_context = response.context['citations']
        self.assertEqual(len(citations_context), 2)

        # Cita registrada
        registered_citation = next(c for c in citations_context if c['doi'] == self.citing_doi_registered)
        self.assertTrue(registered_citation['is_registered'])
        self.assertEqual(registered_citation['report_id'], self.report.id)

        # Cita no registrada
        unregistered_citation = next(c for c in citations_context if c['doi'] == self.citing_doi_unregistered)
        self.assertFalse(unregistered_citation['is_registered'])
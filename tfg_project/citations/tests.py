from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp
from .models import IncorrectCitation

@override_settings(SITE_ID=1)
class HomePageTests(TestCase):
    def setUp(self):
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

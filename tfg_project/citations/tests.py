from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from .models import IncorrectCitation

class HomePageTests(TestCase):
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
            'citation_type': 'misinterpretation'
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IncorrectCitation.objects.count(), 1)
        self.assertEqual(IncorrectCitation.objects.first().author, self.user)

class MetadataTests(TestCase):
    def test_get_metadata_without_doi(self):
        response = self.client.get(reverse('get_all_metadata'))
        self.assertEqual(response.status_code, 400)

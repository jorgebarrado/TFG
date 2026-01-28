from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Comment, IncorrectCitation, SavedCitation, Conversation
import os
import json
from django.conf import settings


@override_settings(
    SITE_ID=1,
    LANGUAGE_CODE="en-us",
    ROOT_URLCONF="tfg_project.urls",
)
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
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)


class LoggedInTestCase(SocialAppTestCase):
    def setUp(self):
        super().setUp()
        self.user1 = User.objects.create_user(
            username="user1", password="password"
        )
        self.user2 = User.objects.create_user(
            username="user2", password="password"
        )

        # Datos para user1
        self.report1 = IncorrectCitation.objects.create(
            author=self.user1,
            doi_original="10.1000/orig1",
            doi_incorrect="10.1000/inc1",
            citation_type="misinterpretation",
            publication_area="CIS",
        )
        self.comment1 = Comment.objects.create(
            citation=self.report1, author=self.user1, content="Comentario de user1"
        )
        self.saved1 = SavedCitation.objects.create(
            user=self.user1, citation=self.report1
        )

        # Datos para user2
        self.report2 = IncorrectCitation.objects.create(
            author=self.user2,
            doi_original="10.1000/orig2",
            doi_incorrect="10.1000/inc2",
            citation_type="not said",
            publication_area="ENG",
        )


class PageLoadTests(LoggedInTestCase):
    def test_citation_list_loads(self):
        response = self.client.get(reverse("citation_list"))
        self.assertEqual(response.status_code, 200)

    def test_citation_detail_loads(self):
        response = self.client.get(
            reverse("citation_detail", args=[self.report1.id])
        )
        self.assertEqual(response.status_code, 200)


class RegisterTests(TestCase):
    def test_register_user(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "nuevo_usuario",
                "password1": "contraseñaSegura123",
                "password2": "contraseñaSegura123",
            },
        )
        self.assertEqual(response.status_code, 302)  # Redirección
        self.assertTrue(User.objects.filter(username="nuevo_usuario").exists())


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="jorge", password="test1234")

    def test_login_user(self):
        response = self.client.post(
            reverse("login"), {"username": "jorge", "password": "test1234"}
        )
        self.assertEqual(response.status_code, 302)


class ReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="jorge", password="test1234")
        self.client.login(username="jorge", password="test1234")

    def test_create_report(self):
        response = self.client.post(
            reverse("ajax_submit"),
            {
                "doi_original": "10.1000/xyz123",
                "doi_incorrect": "10.1000/abc456",
                "incorrect_reason": "Mal interpretación.",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IncorrectCitation.objects.count(), 1)
        self.assertEqual(IncorrectCitation.objects.first().author, self.user)


class UserViewsTests(LoggedInTestCase):
    def test_my_reports_view(self):
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_reports"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.report1, response.context["reports"])
        self.assertNotIn(self.report2, response.context["reports"])

    def test_my_comments_view(self):
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_comments"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.comment1, response.context["comments"])

    def test_my_saved_view(self):
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_saved"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.saved1, response.context["saved"])


class MetadataTests(TestCase):
    def test_get_metadata_without_doi(self):
        response = self.client.get(reverse("get_all_metadata"))
        self.assertEqual(response.status_code, 400)


class VoteViewTests(LoggedInTestCase):
    def test_vote_unauthenticated(self):
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 403)

    def test_vote_missing_parameters(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"vote": 1})
        self.assertEqual(response.status_code, 400)

    def test_vote_invalid_input(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"citation_id": "abc", "vote": 1})
        self.assertEqual(response.status_code, 400)

    def test_vote_invalid_vote_value(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 5}
        )
        self.assertEqual(response.status_code, 400)

    def test_vote_nonexistent_citation(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"citation_id": 999, "vote": 1})
        self.assertEqual(response.status_code, 404)

    def test_upvote_citation(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1')
        self.assertContains(response, '0')

    def test_vote_toggles_off(self):
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '0')

    def test_vote_switches(self):
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": -1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1') # Downvotes

    def test_anonymous_user_sees_modal_buttons(self):
        response = self.client.get(reverse("citation_detail", args=[self.report1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-toggle="modal"')
        self.assertContains(response, 'data-bs-target="#loginModal"')
        self.assertNotContains(response, 'hx-post')


class ExternalApiInteractionTests(TestCase):
    @patch("citations.views.ajax_views.requests.get")
    def test_fetch_doi_metadata_valid(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"title": ["Test Title"]}}

        response = self.client.get(reverse("fetch_doi"), {"doi": "10.1000/valid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], ["Test Title"])

    @patch("citations.views.ajax_views.requests.get")
    def test_fetch_doi_metadata_invalid(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 404

        response = self.client.get(reverse("fetch_doi"), {"doi": "10.1000/invalid"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Not found")

    @patch("citations.views.ajax_views.requests.get")
    def test_get_all_metadata_from_doi_valid(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"title": ["A Valid Title"]}}

        response = self.client.get(reverse("get_all_metadata"), {"doi": "10.1000/valid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], ["A Valid Title"])


class ApiViewTests(LoggedInTestCase):
    def test_toggle_saved(self):
        self.client.login(username="user2", password="password")

        # Guardar la cita
        response = self.client.post(
            reverse("toggle_saved"), {"citation_id": self.report1.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guardado")  # Cambiado de "Saved" a "Guardado"
        self.assertTrue(
            SavedCitation.objects.filter(
                user=self.user2, citation=self.report1
            ).exists()
        )

        # Des-guardar la cita
        response = self.client.post(
            reverse("toggle_saved"), {"citation_id": self.report1.id}
        )
        self.assertEqual(response.status_code, 200)
        # Aquí el botón vuelve a decir "Guardar" (o lo que sea el estado no guardado)
        # Si el template dice "Guardar", deberíamos buscar eso.
        # Pero mejor chequear la lógica de DB.
        self.assertFalse(
            SavedCitation.objects.filter(
                user=self.user2, citation=self.report1
            ).exists()
        )

    def test_ajax_submit_citation_valid(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"),
            {
                "doi_original": "10.1000/new_orig",
                "doi_incorrect": "10.1000/new_inc",
                "incorrect_reason": "Razón de prueba",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_ajax_submit_citation_invalid(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"), {"doi_original": "10.1000/new_orig"},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())


class SemanticCitationsViewTests(SocialAppTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        self.original_doi = "10.1000/original"
        self.citing_doi_registered = "10.1000/citing-registered"
        self.citing_doi_unregistered = "10.1000/citing-unregistered"

        # Crear un reporte de cita incorrecta para el DOI registrado
        self.report = IncorrectCitation.objects.create(
            doi_original=self.original_doi,
            doi_incorrect=self.citing_doi_registered,
            incorrect_reason="Test reason",
            citation_type="misinterpretation",
            publication_area="CIS",
            author=self.user,
        )

    @patch("citations.views.page_views.get_citations_with_fallback")
    def test_semantic_citations_view_marks_registered(
        self, mock_get_citations_with_fallback
    ):
        # Configurar los mocks
        mock_get_citations_with_fallback.return_value = (
            2,
            [
                {
                    "doi": self.citing_doi_registered,
                    "title": "Registered Article",
                    "authors": "Author A",
                    "year": 2023,
                },
                {
                    "doi": self.citing_doi_unregistered,
                    "title": "Unregistered Article",
                    "authors": "Author B",
                    "year": 2024,
                },
            ],
            "s2",
        )

        # Realizar la petición
        response = self.client.get(
            reverse("semantic_citations"), {"doi": self.original_doi}
        )
        self.assertEqual(response.status_code, 200)

        # Verificar el contexto
        citations_context = response.context["citations"]
        self.assertEqual(len(citations_context), 2)

        # Cita registrada
        registered_citation = next(
            c for c in citations_context if c["doi"] == self.citing_doi_registered
        )
        self.assertTrue(registered_citation["is_registered"])
        self.assertEqual(registered_citation["report_id"], self.report.id)

        # Cita no registrada
        unregistered_citation = next(
            c for c in citations_context if c["doi"] == self.citing_doi_unregistered
        )
        self.assertFalse(unregistered_citation["is_registered"])


from .trace_logger import TraceLogger

class ContextLoggingTests(TestCase):
    @patch("citations.views_api.extract_contexts_from_pdf")
    @patch("citations.views_api.download_pdf_to_temp")
    @patch("citations.views_api.get_openaccess_pdf_url")
    @patch("citations.views_api.logger")
    def test_logging_and_debug_mode(
        self,
        mock_logger,
        mock_get_openaccess_pdf_url,
        mock_download_pdf_to_temp,
        mock_extract_contexts_from_pdf,
    ):
        mock_get_openaccess_pdf_url.return_value = "http://example.com/paper.pdf"
        mock_download_pdf_to_temp.return_value = "/tmp/fake.pdf"
        mock_extract_contexts_from_pdf.return_value = [{"snippet": "test"}]

        with patch("os.path.getsize", return_value=12345):
            response = self.client.get(
                reverse("get_citation_context"),
                {
                    "citing_doi": "10.1000/citing",
                    "target_title": "Test Title",
                    "debug": "1",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("trace", response.json())

        # Verificar que el método info fue llamado
        mock_logger.info.assert_called_once()


class MessageSystemTests(SocialAppTestCase):
    def setUp(self):
        super().setUp()
        self.user1 = User.objects.create_user(username="user1", password="password")
        self.user2 = User.objects.create_user(username="user2", password="password")
        self.user3 = User.objects.create_user(username="user3", password="password")

    def test_new_conversation_creates_if_not_exists(self):
        self.client.login(username="user1", password="password")
        url = reverse("new_conversation", kwargs={"username": "user2"})
        response = self.client.get(url)

        # Debe crear una nueva y redirigir
        self.assertEqual(Conversation.objects.count(), 1)
        conversation = Conversation.objects.first()
        self.assertEqual(conversation.participants.count(), 2)
        self.assertIn(self.user1, conversation.participants.all())
        self.assertIn(self.user2, conversation.participants.all())

        self.assertRedirects(response, reverse("conversation_detail", args=[conversation.id]))

    def test_new_conversation_finds_existing(self):
        self.client.login(username="user1", password="password")

        # Crear conversación previa
        conv = Conversation.objects.create()
        conv.participants.add(self.user1, self.user2)

        url = reverse("new_conversation", kwargs={"username": "user2"})
        response = self.client.get(url)

        # No debe crear otra
        self.assertEqual(Conversation.objects.count(), 1)
        self.assertRedirects(response, reverse("conversation_detail", args=[conv.id]))

    def test_new_conversation_ignores_if_third_participant(self):
        self.client.login(username="user1", password="password")

        # Conversación con user1, user2 y user3 (grupo)
        conv_group = Conversation.objects.create()
        conv_group.participants.add(self.user1, self.user2, self.user3)

        url = reverse("new_conversation", kwargs={"username": "user2"})
        response = self.client.get(url)

        # Debe crear una NUEVA exclusiva entre user1 y user2
        self.assertEqual(Conversation.objects.count(), 2)

        new_conv = Conversation.objects.exclude(id=conv_group.id).first()
        self.assertEqual(new_conv.participants.count(), 2)
        self.assertIn(self.user1, new_conv.participants.all())
        self.assertIn(self.user2, new_conv.participants.all())
        self.assertNotIn(self.user3, new_conv.participants.all())

        self.assertRedirects(response, reverse("conversation_detail", args=[new_conv.id]))

    def test_self_conversation(self):
        self.client.login(username="user1", password="password")
        url = reverse("new_conversation", kwargs={"username": "user1"})
        response = self.client.get(url)

        # Debe crear conversación con solo user1
        self.assertEqual(Conversation.objects.count(), 1)
        conv = Conversation.objects.first()
        self.assertEqual(conv.participants.count(), 1)
        self.assertIn(self.user1, conv.participants.all())

        self.assertRedirects(response, reverse("conversation_detail", args=[conv.id]))

    def test_self_conversation_finds_existing(self):
        self.client.login(username="user1", password="password")

        conv = Conversation.objects.create()
        conv.participants.add(self.user1)

        url = reverse("new_conversation", kwargs={"username": "user1"})
        response = self.client.get(url)

        self.assertEqual(Conversation.objects.count(), 1)
        self.assertRedirects(response, reverse("conversation_detail", args=[conv.id]))

    def test_conversation_list_view(self):
        """Prueba básica de que la vista de inbox no crashea"""
        self.client.login(username="user1", password="password")
        # Asegurar URL
        url = reverse("messages_inbox")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

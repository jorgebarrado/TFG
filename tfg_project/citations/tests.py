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
    """
    Clase base de prueba que configura el entorno para django-allauth.
    """
    def setUp(self):
        """Configura el cliente de prueba, el sitio y las aplicaciones sociales."""
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
    """Pruebas para la página de inicio."""
    def test_home_status_code(self):
        """Verifica que la página de inicio carga correctamente (código 200)."""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)


class LoggedInTestCase(SocialAppTestCase):
    """
    Clase base para pruebas que requieren usuarios autenticados y datos iniciales.
    """
    def setUp(self):
        """Crea usuarios, reportes, comentarios y guardados para pruebas."""
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
    """Pruebas de carga de páginas principales."""
    def test_citation_list_loads(self):
        """Verifica que la lista de citas carga correctamente."""
        response = self.client.get(reverse("citation_list"))
        self.assertEqual(response.status_code, 200)

    def test_citation_detail_loads(self):
        """Verifica que el detalle de una cita carga correctamente."""
        response = self.client.get(
            reverse("citation_detail", args=[self.report1.id])
        )
        self.assertEqual(response.status_code, 200)


class RegisterTests(TestCase):
    """Pruebas para el registro de usuarios."""
    def test_register_user(self):
        """Verifica que un usuario se puede registrar correctamente."""
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
    """Pruebas para el inicio de sesión."""
    def setUp(self):
        """Crea un usuario para probar el login."""
        self.user = User.objects.create_user(username="jorge", password="test1234")

    def test_login_user(self):
        """Verifica que un usuario puede iniciar sesión con credenciales correctas."""
        response = self.client.post(
            reverse("login"), {"username": "jorge", "password": "test1234"}
        )
        self.assertEqual(response.status_code, 302)


class ReportTests(TestCase):
    """Pruebas para la creación de reportes."""
    def setUp(self):
        """Crea y autentica un usuario."""
        self.user = User.objects.create_user(username="jorge", password="test1234")
        self.client.login(username="jorge", password="test1234")

    def test_create_report(self):
        """Verifica la creación de un nuevo reporte de cita incorrecta."""
        response = self.client.post(
            reverse("ajax_submit"),
            {
                "doi_original": "10.1000/xyz123",
                "doi_incorrect": "10.1000/abc456",
                "incorrect_reason": "Mal interpretación.",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IncorrectCitation.objects.count(), 1)
        self.assertEqual(IncorrectCitation.objects.first().author, self.user)


class UserViewsTests(LoggedInTestCase):
    """Pruebas para las vistas específicas del usuario (mis reportes, etc.)."""
    def test_my_reports_view(self):
        """Verifica que la vista 'Mis reportes' muestra solo los reportes del usuario."""
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_reports"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.report1, response.context["reports"])
        self.assertNotIn(self.report2, response.context["reports"])

    def test_my_comments_view(self):
        """Verifica que la vista 'Mis comentarios' muestra los comentarios del usuario."""
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_comments"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.comment1, response.context["comments"])

    def test_my_saved_view(self):
        """Verifica que la vista 'Mis guardados' muestra las citas guardadas por el usuario."""
        self.client.login(username="user1", password="password")
        response = self.client.get(reverse("my_saved"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.saved1, response.context["saved"])


class MetadataTests(TestCase):
    """Pruebas para la obtención de metadatos."""
    def test_get_metadata_without_doi(self):
        """Verifica que se devuelve error 400 si no se proporciona DOI."""
        response = self.client.get(reverse("get_all_metadata"))
        self.assertEqual(response.status_code, 400)


class VoteViewTests(LoggedInTestCase):
    """Pruebas para la funcionalidad de votación."""
    def test_vote_unauthenticated(self):
        """Verifica que usuarios no autenticados no pueden votar."""
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 403)

    def test_vote_missing_parameters(self):
        """Verifica error 400 si faltan parámetros en la votación."""
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"vote": 1})
        self.assertEqual(response.status_code, 400)

    def test_vote_invalid_input(self):
        """Verifica error 400 si el ID de la cita no es válido."""
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"citation_id": "abc", "vote": 1})
        self.assertEqual(response.status_code, 400)

    def test_vote_invalid_vote_value(self):
        """Verifica error 400 si el valor del voto no es 1 o -1."""
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 5}
        )
        self.assertEqual(response.status_code, 400)

    def test_vote_nonexistent_citation(self):
        """Verifica error 404 si se intenta votar una cita inexistente."""
        self.client.login(username="user1", password="password")
        response = self.client.post(reverse("vote"), {"citation_id": 999, "vote": 1})
        self.assertEqual(response.status_code, 404)

    def test_upvote_citation(self):
        """Verifica que un voto positivo se registra correctamente."""
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1')
        self.assertContains(response, '0')

    def test_vote_toggles_off(self):
        """Verifica que votar lo mismo dos veces elimina el voto (toggle)."""
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '0')

    def test_vote_switches(self):
        """Verifica que cambiar de voto positivo a negativo funciona."""
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": -1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1') # Downvotes

    def test_anonymous_user_sees_modal_buttons(self):
        """Verifica que usuarios anónimos ven botones que activan el modal de login."""
        response = self.client.get(reverse("citation_detail", args=[self.report1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-toggle="modal"')
        self.assertContains(response, 'data-bs-target="#loginModal"')
        self.assertNotContains(response, 'hx-post')


class ExternalApiInteractionTests(TestCase):
    """Pruebas de interacción con APIs externas (mockeadas)."""
    @patch("citations.views.ajax_views.requests.get")
    def test_fetch_doi_metadata_valid(self, mock_get):
        """Verifica la obtención de metadatos para un DOI válido."""
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"title": ["Test Title"]}}

        response = self.client.get(reverse("fetch_doi"), {"doi": "10.1000/valid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], ["Test Title"])

    @patch("citations.views.ajax_views.requests.get")
    def test_fetch_doi_metadata_invalid(self, mock_get):
        """Verifica el manejo de error para un DOI inválido."""
        mock_response = mock_get.return_value
        mock_response.status_code = 404

        response = self.client.get(reverse("fetch_doi"), {"doi": "10.1000/invalid"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Not found")

    @patch("citations.views.ajax_views.requests.get")
    def test_get_all_metadata_from_doi_valid(self, mock_get):
        """Verifica la obtención de todos los metadatos de un DOI."""
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"title": ["A Valid Title"]}}

        response = self.client.get(reverse("get_all_metadata"), {"doi": "10.1000/valid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], ["A Valid Title"])


class ApiViewTests(LoggedInTestCase):
    """Pruebas para vistas API internas (AJAX)."""
    def test_toggle_saved(self):
        """Verifica guardar y des-guardar una cita."""
        self.client.login(username="user2", password="password")

        # Guardar la cita
        response = self.client.post(
            reverse("toggle_saved"), {"citation_id": self.report1.id}
        )
        self.assertEqual(response.status_code, 200)
        # Se espera 'Guardado' porque el sistema está en español por defecto
        self.assertContains(response, "Guardado")
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
        # El botón debería volver a su estado inicial (por ejemplo, mostrar el icono pero no el texto 'Guardado')
        # O dependiendo de la implementación, verificar que NO contiene 'Guardado'
        self.assertNotContains(response, "Guardado")
        self.assertFalse(
            SavedCitation.objects.filter(
                user=self.user2, citation=self.report1
            ).exists()
        )

    def test_ajax_submit_citation_valid(self):
        """Verifica el envío correcto de una cita via AJAX."""
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
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_ajax_submit_citation_invalid(self):
        """Verifica el manejo de errores al enviar cita inválida via AJAX."""
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"), {"doi_original": "10.1000/new_orig"},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())


class SemanticCitationsViewTests(SocialAppTestCase):
    """Pruebas para la vista de citas semánticas."""
    def setUp(self):
        """Configura un escenario con citas registradas y no registradas."""
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
        """Verifica que las citas ya reportadas se marcan como registradas."""
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
    """Pruebas para el sistema de logging y trazas."""
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
        """Verifica que se genera la traza en modo debug."""
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
    """Pruebas para el sistema de mensajería privada."""
    def setUp(self):
        """Crea usuarios para las pruebas de mensajería."""
        super().setUp()
        self.user1 = User.objects.create_user(username="user1", password="password")
        self.user2 = User.objects.create_user(username="user2", password="password")
        self.user3 = User.objects.create_user(username="user3", password="password")

    def test_new_conversation_creates_if_not_exists(self):
        """Verifica que se crea una nueva conversación si no existe."""
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
        """Verifica que se reutiliza una conversación existente."""
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
        """Verifica que no se reutiliza una conversación de grupo para un chat privado."""
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
        """Verifica la creación de una conversación con uno mismo."""
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
        """Verifica que se reutiliza una conversación existente con uno mismo."""
        self.client.login(username="user1", password="password")

        conv = Conversation.objects.create()
        conv.participants.add(self.user1)

        url = reverse("new_conversation", kwargs={"username": "user1"})
        response = self.client.get(url)

        self.assertEqual(Conversation.objects.count(), 1)
        self.assertRedirects(response, reverse("conversation_detail", args=[conv.id]))

    def test_conversation_list_view(self):
        """Verifica que la vista de bandeja de entrada carga correctamente."""
        self.client.login(username="user1", password="password")
        # Asegurar URL
        url = reverse("messages_inbox")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

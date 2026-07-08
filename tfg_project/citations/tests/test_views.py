# Tests de integración Django: vistas de páginas, reportes, comentarios, votaciones, mensajes y APIs de metadatos.
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from allauth.socialaccount.models import SocialApp
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.sites.models import Site
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ..models import Comment, Conversation, IncorrectCitation, SavedCitation


@override_settings(
    SITE_ID=1,
    LANGUAGE_CODE="en-us",
    ROOT_URLCONF="config.urls",
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

    def test_home_cards_do_not_render_pdf_dropzone_or_dblp_login_prompt(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Extraer citas")
        self.assertContains(response, "Explorar con Perfil DBLP")
        self.assertContains(response, "Explorar con DOI")
        self.assertNotContains(response, "Arrastra un PDF")
        self.assertNotContains(response, "Inicia sesión para añadir tu DBLP")

    def test_extract_modal_hides_debug_controls_for_non_admin(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-debug-enabled="false"')
        self.assertNotContains(response, "Guardar JSON de depuración de referencias")
        self.assertNotContains(response, "Descargar depuración")

    def test_extract_modal_shows_debug_controls_for_admin(self):
        admin = User.objects.create_user(
            username="admin", password="password", is_staff=True
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-debug-enabled="true"')
        self.assertContains(response, "Guardar JSON de depuración de referencias")
        self.assertContains(response, "Descargar depuración")

    def test_reader_marks_debug_tools_disabled_for_non_admin(self):
        response = self.client.get(reverse("citation_reader_preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-debug-enabled="false"')

    def test_reader_marks_debug_tools_enabled_for_admin(self):
        admin = User.objects.create_user(
            username="reader-admin", password="password", is_staff=True
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("citation_reader_preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-debug-enabled="true"')


class LoggedInTestCase(SocialAppTestCase):
    def setUp(self):
        super().setUp()
        self.user1 = User.objects.create_user(username="user1", password="password")
        self.user2 = User.objects.create_user(username="user2", password="password")

        # Datos para user1
        self.report1 = IncorrectCitation.objects.create(
            author=self.user1,
            doi_original="10.1000/orig1",
            doi_incorrect="10.1000/inc1",
            incorrect_reason="Motivo inicial user1",
            citation_type="misinterpretation",
            publication_area="CIS",
            metadata_original={
                "title_override": "Quantum citations report",
                "author": [{"given": "Ada", "family": "Lovelace"}],
            },
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
            incorrect_reason="Motivo inicial user2",
            citation_type="not said",
            publication_area="ENG",
        )


class PageLoadTests(LoggedInTestCase):
    def test_citation_list_loads(self):
        response = self.client.get(reverse("citation_list"))
        self.assertEqual(response.status_code, 200)

    def test_citation_list_shows_server_pagination_controls(self):
        for idx in range(30):
            IncorrectCitation.objects.create(
                author=self.user1,
                doi_original=f"10.1000/pag-orig-{idx}",
                doi_incorrect=f"10.1000/pag-inc-{idx}",
                incorrect_reason=f"Pagination case {idx}",
                citation_type="misinterpretation",
                publication_area="CIS",
            )

        response = self.client.get(reverse("citation_list"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["citations"].has_next())
        self.assertContains(response, "?page=2")

    def test_citation_list_preserves_filters_in_pagination_links(self):
        for idx in range(30):
            IncorrectCitation.objects.create(
                author=self.user1,
                doi_original=f"10.1000/filter-orig-{idx}",
                doi_incorrect=f"10.1000/filter-inc-{idx}",
                incorrect_reason=f"Filtered pagination case {idx}",
                citation_type="misinterpretation",
                publication_area="CIS",
            )

        response = self.client.get(reverse("citation_list"), {"area": "CIS"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["citations"].has_next())
        self.assertContains(response, "?area=CIS&amp;page=2")

    def test_citation_list_filters_by_search_term(self):
        response = self.client.get(reverse("citation_list"), {"q": "Quantum"})

        self.assertEqual(response.status_code, 200)
        citation_ids = {
            citation.id for citation in response.context["citations"].object_list
        }
        self.assertIn(self.report1.id, citation_ids)
        self.assertNotIn(self.report2.id, citation_ids)

    def test_citation_list_filters_by_publication_area(self):
        response = self.client.get(reverse("citation_list"), {"area": "CIS"})

        self.assertEqual(response.status_code, 200)
        citation_ids = {
            citation.id for citation in response.context["citations"].object_list
        }
        self.assertEqual(citation_ids, {self.report1.id})

    def test_citation_list_filters_by_citation_type(self):
        response = self.client.get(
            reverse("citation_list"), {"ctype": "misinterpretation"}
        )

        self.assertEqual(response.status_code, 200)
        citation_ids = {
            citation.id for citation in response.context["citations"].object_list
        }
        self.assertEqual(citation_ids, {self.report1.id})

    def test_citation_detail_loads(self):
        response = self.client.get(reverse("citation_detail", args=[self.report1.id]))
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
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"),
            {
                "doi_original": "10.1000/xyz123",
                "doi_incorrect": "10.1000/abc456",
                "incorrect_reason": "Mal interpretación.",
                "report_title": "Reporte de prueba",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
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


class ReportEditTests(LoggedInTestCase):
    def test_creator_can_edit_report(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "report_title": "Titulo actualizado por el autor",
                "doi_original": self.report1.doi_original,
                "doi_incorrect": self.report1.doi_incorrect,
                "incorrect_reason": "Motivo actualizado por el autor",
                "citation_type": self.report1.citation_type,
                "publication_area": self.report1.publication_area,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(
            self.report1.incorrect_reason, "Motivo actualizado por el autor"
        )

    def test_admin_can_edit_report(self):
        admin = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="password"
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "report_title": "Titulo actualizado por admin",
                "doi_original": self.report1.doi_original,
                "doi_incorrect": self.report1.doi_incorrect,
                "incorrect_reason": "Motivo actualizado por admin",
                "citation_type": self.report1.citation_type,
                "publication_area": self.report1.publication_area,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(self.report1.incorrect_reason, "Motivo actualizado por admin")

    def test_non_owner_non_admin_cannot_edit_report(self):
        self.client.login(username="user2", password="password")
        old_reason = self.report1.incorrect_reason
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "doi_original": self.report1.doi_original,
                "doi_incorrect": self.report1.doi_incorrect,
                "incorrect_reason": "No deberia poder editar",
                "citation_type": self.report1.citation_type,
                "publication_area": self.report1.publication_area,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(self.report1.incorrect_reason, old_reason)

    def test_creator_can_edit_single_block_reason(self):
        self.client.login(username="user1", password="password")
        old_doi_original = self.report1.doi_original
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "section": "reason",
                "incorrect_reason": "Motivo actualizado solo en bloque",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(
            self.report1.incorrect_reason, "Motivo actualizado solo en bloque"
        )
        self.assertEqual(self.report1.doi_original, old_doi_original)

    def test_creator_can_edit_header_title(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "section": "header",
                "report_title": "Titulo personalizado del reporte",
                "doi_original": self.report1.doi_original,
                "citation_type": self.report1.citation_type,
                "publication_area": self.report1.publication_area,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(
            (self.report1.metadata_original or {}).get("title_override"),
            "Titulo personalizado del reporte",
        )

    def test_creator_can_edit_all_from_global_form(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("citation_edit", args=[self.report1.id]),
            {
                "section": "all",
                "report_title": "Titulo global",
                "doi_original": "10.1000/original-global",
                "doi_incorrect": "10.1000/incorrect-global",
                "incorrect_reason": "Motivo global actualizado",
                "citation_type": self.report1.citation_type,
                "publication_area": self.report1.publication_area,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.report1.refresh_from_db()
        self.assertEqual(self.report1.doi_original, "10.1000/original-global")
        self.assertEqual(self.report1.doi_incorrect, "10.1000/incorrect-global")
        self.assertEqual(self.report1.incorrect_reason, "Motivo global actualizado")
        self.assertEqual(
            (self.report1.metadata_original or {}).get("title_override"),
            "Titulo global",
        )


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
        self.assertContains(response, "1")
        self.assertContains(response, "0")

    def test_vote_toggles_off(self):
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0")

    def test_vote_switches(self):
        self.client.login(username="user1", password="password")
        self.client.post(reverse("vote"), {"citation_id": self.report1.id, "vote": 1})
        response = self.client.post(
            reverse("vote"), {"citation_id": self.report1.id, "vote": -1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1")  # Downvotes

    def test_anonymous_user_sees_modal_buttons(self):
        response = self.client.get(reverse("citation_detail", args=[self.report1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-bs-toggle="modal"')
        self.assertContains(response, 'data-bs-target="#loginModal"')
        self.assertNotContains(response, "hx-post")


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

        response = self.client.get(
            reverse("get_all_metadata"), {"doi": "10.1000/valid"}
        )
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
        self.assertContains(response, "Guardar")
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
                "report_title": "Reporte AJAX de prueba",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        citation = IncorrectCitation.objects.latest("id")
        self.assertEqual(citation.citation_contexts, None)

    def test_ajax_submit_citation_normalizes_manual_evidence(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"),
            {
                "doi_original": "10.1000/new_orig",
                "doi_incorrect": "10.1000/new_inc",
                "incorrect_reason": "Razón de prueba",
                "report_title": "Reporte con evidencia",
                "citation_type": "misinterpretation",
                "publication_area": "CIS",
                "manual_evidence_text": "Texto citado manualmente",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        citation = IncorrectCitation.objects.get(id=response.json()["citation_id"])
        self.assertEqual(citation.citation_contexts[0]["source"], "manual")
        self.assertEqual(
            citation.citation_contexts[0]["text"], "Texto citado manualmente"
        )

    def test_add_evidence_endpoint_appends_reader_selection(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("citation_add_evidence", args=[self.report1.id]),
            data=json.dumps(
                {
                    "source": "reader_selection",
                    "article": "citing",
                    "kind": "pdf_selection",
                    "text": "Texto seleccionado en el reader",
                    "page": 4,
                    "boxes": [],
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.report1.refresh_from_db()
        self.assertEqual(
            self.report1.citation_contexts[0]["source"], "reader_selection"
        )
        self.assertEqual(self.report1.citation_contexts[0]["page"], 4)

    def test_ajax_submit_citation_invalid(self):
        self.client.login(username="user1", password="password")
        response = self.client.post(
            reverse("ajax_submit"),
            {"doi_original": "10.1000/new_orig"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
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


class ContextLoggingTests(TestCase):
    @patch("citations.views.views_api.extract_contexts_from_pdf")
    @patch("citations.views.views_api.download_pdf_to_temp")
    @patch("citations.views.views_api.get_openaccess_pdf_url")
    @patch("citations.views.views_api.logger")
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


class ReferenceDebugDownloadTests(TestCase):
    def test_download_reference_debug_requires_admin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            debug_root = Path(temp_dir)
            target_dir = debug_root / "paper"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / "debug-123.json"
            target_file.write_text('{"ok": true}', encoding="utf-8")

            with patch("citations.views.views_api.REFERENCE_DEBUG_DIR", debug_root):
                response = self.client.get(
                    reverse("api_reference_debug_download"),
                    {"file": "paper/debug-123.json"},
                )

            self.assertEqual(response.status_code, 403)

    def test_download_reference_debug_serves_json_attachment_for_admin(self):
        admin = User.objects.create_user(
            username="debug-admin", password="password", is_staff=True
        )
        self.client.force_login(admin)

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_root = Path(temp_dir)
            target_dir = debug_root / "paper"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / "debug-123.json"
            target_file.write_text('{"ok": true}', encoding="utf-8")

            with patch("citations.views.views_api.REFERENCE_DEBUG_DIR", debug_root):
                response = self.client.get(
                    reverse("api_reference_debug_download"),
                    {"file": "paper/debug-123.json"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/json")
            self.assertIn(
                'attachment; filename="debug-123.json"',
                response["Content-Disposition"],
            )
            self.assertEqual(b"".join(response.streaming_content), b'{"ok": true}')

    def test_download_reference_debug_rejects_path_traversal(self):
        admin = User.objects.create_user(
            username="debug-path-admin", password="password", is_staff=True
        )
        self.client.force_login(admin)

        with tempfile.TemporaryDirectory() as temp_dir:
            debug_root = Path(temp_dir)

            with patch("citations.views.views_api.REFERENCE_DEBUG_DIR", debug_root):
                response = self.client.get(
                    reverse("api_reference_debug_download"),
                    {"file": "../secret.json"},
                )

            self.assertEqual(response.status_code, 404)


class ExtractDebugAccessTests(TestCase):
    @staticmethod
    def _reference_stats():
        return {
            "pages_total": 1,
            "references_total": 0,
            "dois_total": 0,
            "references_numbered": False,
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
        }

    @staticmethod
    def _reconciliation_payload():
        return {
            "reconciliation_summary": {},
            "final_structured_references": [],
            "final_references_total": 0,
            "final_citation_style": "non_numeric",
            "final_max_reference_index": 0,
            "final_references": [],
        }

    @staticmethod
    def _enrichment_payload():
        return {
            "local_references": [],
            "references_data_references": [],
            "cited_by": [],
            "enrichment": {
                "doi_provided": False,
                "doi_normalized": "",
                "paper_resolved": False,
                "references_enriched": 0,
                "cited_by_count": 0,
                "sources_used": [],
            },
        }

    @patch("citations.views.views_api.write_reference_detection_debug_json")
    @patch("citations.views.views_api.finalize_reference_detection_debug_payload")
    @patch("citations.views.views_api.enrich_extraction_with_doi")
    @patch("citations.views.views_api.reconcile_reference_sources")
    @patch("citations.views.views_api.build_references_data")
    @patch("citations.views.views_api.extract_pdf_data")
    @patch("citations.views.views_api.process_manuscript")
    @patch("citations.views.views_api.extract_pdf_references")
    def test_extract_ignores_reference_debug_request_for_non_admin(
        self,
        mock_extract_pdf_references,
        mock_process_manuscript,
        mock_extract_pdf_data,
        mock_build_references_data,
        mock_reconcile_reference_sources,
        mock_enrich_extraction_with_doi,
        mock_finalize_reference_detection_debug_payload,
        mock_write_reference_detection_debug_json,
    ):
        def build_references_data_side_effect(**kwargs):
            if kwargs.get("debug_reference_detection"):
                return {
                    "references": [],
                    "debug_payload": {"metadata": {"pipeline_version": "test"}},
                    "reference_debug_steps": [{"key": "rows", "items": []}],
                }
            return {"references": []}

        mock_extract_pdf_references.return_value = ([], self._reference_stats())
        mock_process_manuscript.return_value = {
            "ok": True,
            "results": [],
            "engine_used": "papermage",
        }
        mock_extract_pdf_data.return_value = {
            "pages": [{"page": 0}],
            "layers": {"tokens": [{"text": "sample", "page": 0}]},
        }
        mock_build_references_data.side_effect = build_references_data_side_effect
        mock_reconcile_reference_sources.return_value = self._reconciliation_payload()
        mock_enrich_extraction_with_doi.return_value = self._enrichment_payload()
        mock_finalize_reference_detection_debug_payload.return_value = {
            "metadata": {"pipeline_version": "test"}
        }
        mock_write_reference_detection_debug_json.return_value = "debug.json"
        upload = SimpleUploadedFile(
            "paper.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"
        )

        response = self.client.post(
            reverse("api_extract_citations"),
            {
                "manuscript": upload,
                "engine": "papermage",
                "debug": "1",
                "debug_reference_detection": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            mock_build_references_data.call_args.kwargs["debug_reference_detection"]
        )
        mock_write_reference_detection_debug_json.assert_not_called()
        payload = response.json()
        self.assertNotIn("reference_debug", payload)
        self.assertNotIn("reference_debug_steps", payload)
        self.assertEqual(payload.get("layers"), {"tokens": [{"text": "sample", "page": 0}]})
        self.assertEqual(payload.get("pages"), [{"page": 0}])

    @patch("citations.views.views_api.extract_pdf_data")
    def test_reader_layers_upload_is_available_for_non_admin(self, mock_extract_pdf_data):
        mock_extract_pdf_data.return_value = {
            "pages": [{"page": 0}],
            "layers": {"tokens": [{"text": "sample", "page": 0}]},
        }
        upload = SimpleUploadedFile(
            "paper.pdf", b"%PDF-1.4\n%%EOF", content_type="application/pdf"
        )

        response = self.client.post(
            reverse("api_pdf_reader_v2_upload"),
            {"pdf_file": upload},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pages"], [{"page": 0}])
        self.assertEqual(payload["layers"], {"tokens": [{"text": "sample", "page": 0}]})


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

        self.assertRedirects(
            response, reverse("conversation_detail", args=[conversation.id])
        )

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

        self.assertRedirects(
            response, reverse("conversation_detail", args=[new_conv.id])
        )

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

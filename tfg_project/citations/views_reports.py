import json
import uuid

from django.core.files.storage import default_storage
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import IncorrectCitation
from .services.evidence import normalize_evidence_items
from .services.report_tags import CITATION_TYPE_CHOICES, PUBLICATION_AREA_LABELS

# Flujo avanzado de CitationReport reservado para mantener estable IncorrectCitation.
# Ahora mismo no se usa en produccion; el flujo activo usa IncorrectCitation.


def create_report_wizard(request):
    """Crea un borrador y abre el detalle del reporte en modo edicion."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('home')}?show_login_modal=1")

    draft = IncorrectCitation.objects.create(
        author=request.user,
        doi_original="",
        doi_incorrect="",
        incorrect_reason="",
        citation_type="",
        publication_area="",
        metadata_original={},
        metadata_incorrect={},
        citation_contexts=[],
    )
    return redirect(f"{reverse('citation_detail', args=[draft.pk])}?edit=1")


@require_POST
def ajax_submit_report(request):
    """Recibe el POST del wizard legacy y crea un IncorrectCitation."""
    original_doi = (request.POST.get("original_doi") or "").strip()
    citing_doi = (request.POST.get("citing_doi") or "").strip()
    error_type = (request.POST.get("error_type") or "other").strip()
    user_explanation = (request.POST.get("user_explanation") or "").strip()

    if not original_doi or not citing_doi:
        return HttpResponseBadRequest("Faltan DOIs para crear el reporte.")

    def parse_json_field(name, default):
        raw = request.POST.get(name)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    original_metadata = parse_json_field("original_metadata_json", {})
    citing_metadata = parse_json_field("citing_metadata_json", {})
    evidence_items = normalize_evidence_items(
        request.POST.get("citation_contexts_json")
        or request.POST.get("citing_paragraphs_json"),
        default_source="pdf_extractor",
        default_article="citing",
        default_kind="pdf_extracted_context",
        default_doi=citing_doi,
    )

    allowed_types = dict(CITATION_TYPE_CHOICES)
    citation_type = error_type if error_type in allowed_types else "not said"
    publication_area = (request.POST.get("publication_area") or "OTH").strip()
    if publication_area not in PUBLICATION_AREA_LABELS:
        publication_area = "OTH"

    citation = IncorrectCitation(
        doi_original=original_doi,
        doi_incorrect=citing_doi,
        incorrect_reason=user_explanation or "Pendiente de completar",
        citation_type=citation_type,
        publication_area=publication_area,
        metadata_original=original_metadata,
        metadata_incorrect=citing_metadata,
        citation_contexts=evidence_items,
    )

    if request.user.is_authenticated:
        citation.author = request.user

    citation.save()

    original_pdf = request.FILES.get("original_pdf_uploaded")
    if original_pdf:
        upload_path = default_storage.save(
            f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{original_pdf.name}",
            original_pdf,
        )
        original_metadata = dict(original_metadata)
        original_metadata["uploaded_pdf_path"] = upload_path
        original_metadata["uploaded_pdf_path_original"] = upload_path
        original_metadata["url"] = default_storage.url(upload_path)
        citation.metadata_original = original_metadata

    citing_pdf = request.FILES.get("citing_pdf_uploaded")
    if citing_pdf:
        upload_path = default_storage.save(
            f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{citing_pdf.name}",
            citing_pdf,
        )
        citing_metadata = dict(citing_metadata)
        citing_metadata["uploaded_pdf_path"] = upload_path
        citing_metadata["uploaded_pdf_path_incorrect"] = upload_path
        citing_metadata["url"] = default_storage.url(upload_path)
        citation.metadata_incorrect = citing_metadata

    if original_pdf or citing_pdf:
        citation.save(update_fields=["metadata_original", "metadata_incorrect"])

    detail_url = reverse("citation_detail", args=[citation.pk])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": detail_url})

    return redirect(detail_url)

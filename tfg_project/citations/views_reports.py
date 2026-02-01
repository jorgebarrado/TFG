import json

from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
# TODO: futuro flujo avanzado de reportes (CitationReport).
# Ahora mismo no se usa en produccion; el flujo activo usa IncorrectCitation.

from .models import AREA_CHOICES, CitationReport


def create_report_wizard(request):
    """Renderiza el flujo guiado para crear un reporte enriquecido."""
    return render(
        request,
        "citations/report_wizard.html",
        {"publication_area_choices": AREA_CHOICES},
    )


@require_POST
def ajax_submit_report(request):
    """
    Recibe el POST del wizard y crea un CitationReport.

    Procesa los datos enviados por el wizard, incluyendo metadatos, DOIs,
    archivos PDF subidos y explicaciones del usuario, para crear un nuevo
    registro de reporte.
    """
    original_doi = (request.POST.get("original_doi") or "").strip()
    citing_doi = (request.POST.get("citing_doi") or "").strip()
    error_type = (request.POST.get("error_type") or "other").strip()
    user_explanation = (request.POST.get("user_explanation") or "").strip()

    if not original_doi or not citing_doi:
        return HttpResponseBadRequest("Faltan DOIs para crear el reporte.")

    def parse_json_field(name, default):
        """
        Intenta parsear un campo JSON del POST, devolviendo un valor por defecto si falla.

        Args:
            name (str): El nombre del campo en request.POST.
            default (Any): El valor a devolver en caso de error o ausencia.

        Returns:
            Any: El valor parseado o el valor por defecto.
        """
        raw = request.POST.get(name)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    original_metadata = parse_json_field("original_metadata_json", {})
    citing_metadata = parse_json_field("citing_metadata_json", {})
    citing_paragraphs = parse_json_field("citing_paragraphs_json", [])

    report = CitationReport(
        original_doi=original_doi,
        original_metadata=original_metadata,
        citing_doi=citing_doi,
        citing_metadata=citing_metadata,
        citing_paragraphs=citing_paragraphs,
        error_type=error_type,
        user_explanation=user_explanation,
    )

    if request.user.is_authenticated:
        report.created_by = request.user

    original_pdf = request.FILES.get("original_pdf_uploaded")
    if original_pdf:
        report.original_pdf_uploaded = original_pdf

    citing_pdf = request.FILES.get("citing_pdf_uploaded")
    if citing_pdf:
        report.citing_pdf_uploaded = citing_pdf

    report.save()

    detail_url = reverse("citation_detail", args=[report.pk])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "redirect_url": detail_url})

    return redirect(detail_url)

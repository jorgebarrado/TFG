from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import IncorrectCitation
from .services.ai_citation_detector import ai_detect_citations_for_report
from .services.ai_report_evaluator import analyze_report_with_ai


@require_POST
def citation_ai_detect(request, pk):
    """Lanza la detección automática de citas mediante IA y guarda los contextos encontrados.

    Utiliza el servicio `ai_detect_citations_for_report` para analizar el PDF y encontrar menciones.

    Args:
        request: Objeto HttpRequest.
        pk (int): Primary Key del reporte (IncorrectCitation).

    Returns:
        HttpResponse: Redirección al detalle del reporte con mensaje de éxito o error.
    """
    citation = get_object_or_404(IncorrectCitation, pk=pk)

    try:
        contexts = ai_detect_citations_for_report(citation)
        citation.citation_contexts = contexts
        citation.save()
        messages.success(
            request,
            f"Se han detectado {len(contexts)} posibles fragmentos donde se cita el artículo original.",
        )
    except Exception as exc:  # pylint: disable=broad-except
        messages.error(request, f"No se ha podido ejecutar la detección automática: {exc}")

    return redirect("citation_detail", pk=pk)


@require_POST
def citation_ai_evaluate(request, pk):
    """Evalúa con IA si la cita está bien o mal utilizada basándose en los datos del reporte.

    Utiliza el servicio `analyze_report_with_ai` para generar una evaluación automática.

    Args:
        request: Objeto HttpRequest.
        pk (int): Primary Key del reporte (IncorrectCitation).

    Returns:
        HttpResponse: Redirección al detalle del reporte con mensaje de éxito o error.
    """
    citation = get_object_or_404(IncorrectCitation, pk=pk)

    try:
        analyze_report_with_ai(citation)
        messages.success(request, "Análisis IA del reporte completado.")
    except Exception as exc:  # pylint: disable=broad-except
        messages.error(request, f"No se ha podido ejecutar el análisis IA del reporte: {exc}")

    return redirect("citation_detail", pk=pk)

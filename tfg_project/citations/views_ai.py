from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .models import IncorrectCitation
from .services.ai_citation_detector import ai_detect_citations_for_report
from .services.ai_report_evaluator import analyze_report_with_ai


@require_POST
def citation_ai_detect(request, pk):
    """Lanza detección automática de citas mediante IA y guarda contexts."""
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
        messages.error(
            request, f"No se ha podido ejecutar la detección automática: {exc}"
        )

    return redirect("citation_detail", pk=pk)


@require_POST
def citation_ai_evaluate(request, pk):
    """Evalúa con IA si la cita está bien/mal con los datos del reporte."""
    citation = get_object_or_404(IncorrectCitation, pk=pk)

    try:
        analyze_report_with_ai(citation)
        messages.success(request, "Análisis IA del reporte completado.")
    except Exception as exc:  # pylint: disable=broad-except
        messages.error(
            request, f"No se ha podido ejecutar el análisis IA del reporte: {exc}"
        )

    return redirect("citation_detail", pk=pk)

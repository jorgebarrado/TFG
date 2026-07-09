# Vistas de gestión de reportes: creación de borradores.
from django.shortcuts import redirect
from django.urls import reverse

from ..models import IncorrectCitation


def create_report_draft(request):
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

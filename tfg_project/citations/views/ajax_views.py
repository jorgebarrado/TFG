"""Vistas que gestionan peticiones AJAX y devuelven respuestas JSON."""

import json
import requests
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..forms import IncorrectCitationForm, RegisterForm
from ..models import Comment, IncorrectCitation, SavedCitation, Vote
from ..services.semantic_fetch import get_citations_with_fallback


@require_POST
def vote_view(request):
    """Gestiona los votos (positivos y negativos) en los reportes de citas.

    Permite votar o cambiar el voto en un reporte. Si ya existe un voto idéntico,
    se elimina (toggle). Devuelve el fragmento HTML actualizado de los botones.

    Args:
        request: La solicitud HTTP POST.

    Returns:
        HttpResponse: Fragmento HTML actualizado con el estado de los votos.
        JsonResponse: Error JSON si faltan parámetros o no está autenticado.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "not_authenticated"}, status=403)

    citation_id_str = request.POST.get("citation_id")
    vote_value_str = request.POST.get("vote")

    if not citation_id_str or not vote_value_str:
        return JsonResponse({"error": "Missing parameters"}, status=400)

    try:
        citation_id = int(citation_id_str)
        vote_value = int(vote_value_str)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid input"}, status=400)

    if vote_value not in [1, -1]:
        return JsonResponse({"error": "Invalid vote value"}, status=400)

    citation = get_object_or_404(IncorrectCitation, id=citation_id)

    existing_vote = Vote.objects.filter(citation=citation, user=request.user).first()

    if existing_vote:
        if existing_vote.value == vote_value:
            existing_vote.delete()
        else:
            existing_vote.value = vote_value
            existing_vote.save()
    else:
        Vote.objects.create(citation=citation, user=request.user, value=vote_value)

    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()
    current_vote = Vote.objects.filter(citation=citation, user=request.user).first()
    user_vote = current_vote.value if current_vote else 0

    context = {
        "citation": citation,
        "upvotes": upvotes,
        "downvotes": downvotes,
        "user_vote": user_vote,
    }
    return render(
        request, "citations/partials/_vote_buttons.html", context
    )


@require_POST
@login_required
def toggle_saved(request):
    """Guarda o elimina una cita de la lista de guardados de un usuario.

    Actúa como un toggle: si ya está guardada, la borra; si no, la crea.

    Args:
        request: La solicitud HTTP POST.

    Returns:
        HttpResponse: Fragmento HTML del botón de guardado actualizado.
    """
    citation_id = request.POST.get("citation_id")
    citation = get_object_or_404(IncorrectCitation, id=citation_id)

    saved, created = SavedCitation.objects.get_or_create(
        user=request.user, citation=citation
    )

    if not created:
        saved.delete()
        is_saved = False
    else:
        is_saved = True

    context = {"citation": citation, "is_saved": is_saved}
    return render(
        request, "citations/partials/_save_button.html", context
    )


def ajax_submit_citation(request):
    """Guarda un reporte de cita incorrecta enviado desde el formulario principal.

    Maneja tanto solicitudes AJAX como envíos de formularios tradicionales.
    Si es AJAX, devuelve JSON; si no, redirige.

    Args:
        request: La solicitud HTTP (POST).

    Returns:
        JsonResponse | HttpResponseRedirect: Respuesta según el tipo de solicitud.
    """
    def _is_ajax(req):
        return req.headers.get("HX-Request") == "true" or req.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest"

    if request.method != "POST":
        if _is_ajax(request):
            return JsonResponse({"error": _("Método no permitido")}, status=405)
        messages.error(request, _("Método no permitido."))
        return redirect("home")

    form = IncorrectCitationForm(request.POST)
    if form.is_valid():
        doi_original = form.cleaned_data.get("doi_original")
        doi_incorrect = form.cleaned_data.get("doi_incorrect")

        if doi_original and doi_incorrect:
            existing = IncorrectCitation.objects.filter(
                doi_original=doi_original, doi_incorrect=doi_incorrect
            ).first()
            if existing:
                if _is_ajax(request):
                    return JsonResponse(
                        {"success": True, "citation_id": existing.id, "existing": True},
                        status=200,
                    )
                messages.info(request, _("Ese reporte ya existe."))
                return redirect("citation_detail", pk=existing.pk)

        citation = form.save(commit=False)
        if request.user.is_authenticated:
            citation.author = request.user

        # Metadatos del artículo original (A)
        raw_original = request.POST.get("original_metadata_json")
        if raw_original:
            try:
                citation.metadata_original = json.loads(raw_original)
            except json.JSONDecodeError:
                pass

        # Metadatos del artículo que cita (B)
        raw_incorrect = request.POST.get("citing_metadata_json")
        if raw_incorrect:
            try:
                citation.metadata_incorrect = json.loads(raw_incorrect)
            except json.JSONDecodeError:
                pass

        # Contextos seleccionados donde aparece la cita
        raw_contexts = request.POST.get("citing_paragraphs_json")
        if raw_contexts:
            try:
                citation.citation_contexts = json.loads(raw_contexts)
            except json.JSONDecodeError:
                pass

        citation.save()

        if _is_ajax(request):
            return JsonResponse(
                {"success": True, "citation_id": citation.id},
                status=200,
            )
        messages.success(request, _("Reporte creado correctamente."))
        return redirect("citation_detail", pk=citation.pk)

    if _is_ajax(request):
        return JsonResponse({"errors": form.errors}, status=400)

    messages.error(request, _("Revisa los datos del formulario."))
    return redirect("home")


def fetch_doi_metadata(request):
    """Obtiene los metadatos básicos de un DOI desde CrossRef.

    Args:
        request: La solicitud HTTP GET con el parámetro 'doi'.

    Returns:
        JsonResponse: Metadatos del DOI o error si no se encuentra.
    """
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "No DOI"}, status=400)

    url = f"https://api.crossref.org/works/{doi}"
    r = requests.get(url, timeout=6)
    if r.status_code == 200:
        return JsonResponse(r.json()["message"])
    return JsonResponse({"error": "Not found"}, status=404)


def get_all_metadata_from_doi(request):
    """Obtiene todos los metadatos disponibles de un DOI desde CrossRef.

    Args:
        request: La solicitud HTTP GET con el parámetro 'doi'.

    Returns:
        JsonResponse: Metadatos completos o error.
    """
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "No DOI provided"}, status=400)

    url = f"https://api.crossref.org/works/{doi}"
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json().get("message", {})
        return JsonResponse(data, safe=False)
    return JsonResponse({"error": "DOI not found or invalid"}, status=404)


@require_POST
def register_ajax(request):
    """Gestiona el registro de usuarios a través de una solicitud AJAX.

    Crea el usuario y lo autentica automáticamente si el formulario es válido.

    Args:
        request: La solicitud HTTP POST con datos de registro.

    Returns:
        JsonResponse: Éxito o lista de errores de validación.
    """
    form = RegisterForm(request.POST)
    if form.is_valid():
        user = form.save()
        auth_user = authenticate(
            request, username=user.username, password=form.cleaned_data["password1"]
        )
        if auth_user:
            login(request, auth_user)
        return JsonResponse({"success": True})
    errors = {field: errs.get_json_data() for field, errs in form.errors.items()}
    return JsonResponse({"success": False, "errors": errors}, status=400)


@login_required
def delete_comment(request, pk):
    """Elimina un comentario si el usuario es el autor o un superusuario.

    Args:
        request: La solicitud HTTP.
        pk (int): ID del comentario a eliminar.

    Returns:
        HttpResponseRedirect: Redirige al detalle del reporte.
        HttpResponseForbidden: Si no tiene permisos.
    """
    comment = get_object_or_404(Comment, pk=pk)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
        messages.success(request, "Comentario eliminado correctamente.")
    else:
        return HttpResponseForbidden("No tienes permiso para eliminar este comentario.")
    return redirect("citation_detail", pk=comment.citation.pk)


def citation_suggest(request):
    """Sugiere reportes de citas existentes para autocompletado.

    Busca coincidencias parciales en el DOI original o título del artículo.

    Args:
        request: La solicitud HTTP GET con el parámetro 'term'.

    Returns:
        JsonResponse: Lista de sugerencias (doi_original, title).
    """
    term = request.GET.get("term", "")
    qs = IncorrectCitation.objects.filter(
        Q(doi_original__icontains=term) | Q(metadata__title__icontains=term)
    ).values("doi_original", "metadata__title")[:5]

    return JsonResponse(list(qs), safe=False)


def get_semantic_citations(request):
    """Obtiene y compara las citas de un artículo desde Semantic Scholar.

    Consulta los citadores en Semantic Scholar y marca aquellos que ya
    tienen un reporte registrado en el sistema local.

    Args:
        request: La solicitud HTTP GET con el parámetro 'doi'.

    Returns:
        JsonResponse: Datos de citas, incluyendo estado de registro.
    """
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "No DOI provided"}, status=400)

    citation_count, citations, source = get_citations_with_fallback(doi)
    citing_dois = [c.get("doi") for c in citations if c.get("doi")]
    registered_citations = IncorrectCitation.objects.filter(
        doi_original=doi, doi_incorrect__in=citing_dois
    ).values("doi_incorrect", "id")
    registered_map = {item["doi_incorrect"]: item["id"] for item in registered_citations}

    for c in citations:
        citing_doi = c.get("doi")
        if citing_doi and citing_doi in registered_map:
            c["is_registered"] = True
            c["report_id"] = registered_map[citing_doi]
        else:
            c["is_registered"] = False

    return JsonResponse({
        "doi": doi,
        "citation_count": citation_count,
        "citations": citations,
        "source": source,
    })

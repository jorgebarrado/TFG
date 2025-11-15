"""Views that handle AJAX requests and return JSON responses."""

import requests
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import IncorrectCitationForm, RegisterForm
from ..models import Comment, IncorrectCitation, SavedCitation, Vote
from ..services.semantic_fetch import get_citations_with_fallback


@require_POST
def vote_view(request):
    """
    Gestiona los votos (positivos y negativos) en los reportes de citas.
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
    """
    Guarda o elimina una cita de la lista de guardados de un usuario.
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
    """
    Guarda un reporte de cita incorrecta enviado a través de AJAX.
    """
    if request.method == "POST":
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            citation = form.save(commit=False)
            if request.user.is_authenticated:
                citation.author = request.user
            citation.save()
            return JsonResponse({"success": True})
        return JsonResponse({"errors": form.errors}, status=400)
    return JsonResponse({"error": "Método no permitido"}, status=405)


def fetch_doi_metadata(request):
    """
    Obtiene los metadatos de un DOI desde CrossRef.
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
    """
    Obtiene todos los metadatos de un DOI desde CrossRef.
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
    """
    Gestiona el registro de usuarios a través de una solicitud AJAX.
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
    """
    Elimina un comentario si el usuario es el autor o un superusuario.
    """
    comment = get_object_or_404(Comment, pk=pk)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
        messages.success(request, "Comentario eliminado correctamente.")
    else:
        return HttpResponseForbidden("No tienes permiso para eliminar este comentario.")
    return redirect("citation_detail", pk=comment.citation.pk)


def citation_suggest(request):
    """
    Sugiere citas incorrectas basadas en un término de búsqueda.
    """
    term = request.GET.get("term", "")
    qs = IncorrectCitation.objects.filter(
        Q(doi_original__icontains=term) | Q(metadata__title__icontains=term)
    ).values("doi_original", "metadata__title")[:5]

    return JsonResponse(list(qs), safe=False)


def get_semantic_citations(request):
    """
    Obtiene las citas de un artículo desde Semantic Scholar y las devuelve en formato JSON.
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

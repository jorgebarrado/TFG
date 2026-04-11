"""Views that handle AJAX requests and return JSON responses."""

import json
import uuid
import requests
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from ..forms import IncorrectCitationForm, RegisterForm
from ..models import Comment, IncorrectCitation, SavedCitation, Vote
from ..services.report_tags import (
    CITATION_TYPE_CHOICES,
    PUBLICATION_AREA_LABELS,
    apply_report_tags,
    normalize_tag_values,
)
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
    return render(request, "citations/partials/_vote_buttons.html", context)


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

    context = {
        "citation": citation,
        "is_saved": is_saved,
        "variant": (request.POST.get("variant") or "").strip(),
    }
    return render(request, "citations/partials/_save_button.html", context)


def ajax_submit_citation(request):
    """
    Guarda un reporte de cita incorrecta enviado desde el formulario principal.
    Acepta solicitudes AJAX y tradicionales.
    """

    def _is_ajax(req):
        return (
            req.headers.get("HX-Request") == "true"
            or req.headers.get("X-Requested-With") == "XMLHttpRequest"
        )

    if request.method != "POST":
        if _is_ajax(request):
            return JsonResponse({"error": _("Método no permitido")}, status=405)
        messages.error(request, _("Método no permitido."))
        return redirect("home")

    selected_types = normalize_tag_values(
        request.POST.getlist("citation_type"), dict(CITATION_TYPE_CHOICES)
    )
    selected_areas = normalize_tag_values(
        request.POST.getlist("publication_area"), PUBLICATION_AREA_LABELS
    )
    form_data = request.POST.copy()
    form_data["citation_type"] = selected_types[0] if selected_types else ""
    form_data["publication_area"] = selected_areas[0] if selected_areas else ""

    form = IncorrectCitationForm(form_data)
    if form.is_valid():
        report_title = (request.POST.get("report_title") or "").strip()
        if not report_title:
            error_msg = _("El titulo del reporte es obligatorio.")
            if _is_ajax(request):
                return JsonResponse(
                    {"errors": {"report_title": [error_msg]}}, status=400
                )
            messages.error(request, error_msg)
            return redirect("home")

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

        apply_report_tags(citation, selected_types, selected_areas)
        citation.save()

        metadata_fields_to_update = []
        updated_original = (
            citation.metadata_original
            if isinstance(citation.metadata_original, dict)
            else {}
        )
        updated_original = dict(updated_original)
        updated_incorrect = (
            citation.metadata_incorrect
            if isinstance(citation.metadata_incorrect, dict)
            else {}
        )
        updated_incorrect = dict(updated_incorrect)

        updated_original["title_override"] = report_title
        citation.metadata_original = updated_original
        metadata_fields_to_update.append("metadata_original")

        uploaded_original_pdf = request.FILES.get("uploaded_pdf_original_file")
        if uploaded_original_pdf:
            original_name = uploaded_original_pdf.name or "uploaded_original.pdf"
            if not original_name.lower().endswith(".pdf"):
                original_name = f"{original_name}.pdf"
            upload_path = default_storage.save(
                f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{original_name}",
                uploaded_original_pdf,
            )
            updated_original["uploaded_pdf_path"] = upload_path
            updated_original["uploaded_pdf_path_original"] = upload_path
            updated_original["url"] = default_storage.url(upload_path)
            citation.metadata_original = updated_original
            if "metadata_original" not in metadata_fields_to_update:
                metadata_fields_to_update.append("metadata_original")

        uploaded_incorrect_pdf = request.FILES.get(
            "uploaded_pdf_incorrect_file"
        ) or request.FILES.get("uploaded_pdf_file")
        if uploaded_incorrect_pdf:
            incorrect_name = uploaded_incorrect_pdf.name or "uploaded_incorrect.pdf"
            if not incorrect_name.lower().endswith(".pdf"):
                incorrect_name = f"{incorrect_name}.pdf"
            upload_path = default_storage.save(
                f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{incorrect_name}",
                uploaded_incorrect_pdf,
            )
            updated_incorrect["uploaded_pdf_path"] = upload_path
            updated_incorrect["uploaded_pdf_path_incorrect"] = upload_path
            updated_incorrect["url"] = default_storage.url(upload_path)
            citation.metadata_incorrect = updated_incorrect
            if "metadata_incorrect" not in metadata_fields_to_update:
                metadata_fields_to_update.append("metadata_incorrect")

        if metadata_fields_to_update:
            citation.save(update_fields=metadata_fields_to_update)

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
    registered_map = {
        item["doi_incorrect"]: item["id"] for item in registered_citations
    }

    for c in citations:
        citing_doi = c.get("doi")
        if citing_doi and citing_doi in registered_map:
            c["is_registered"] = True
            c["report_id"] = registered_map[citing_doi]
        else:
            c["is_registered"] = False

    return JsonResponse(
        {
            "doi": doi,
            "citation_count": citation_count,
            "citations": citations,
            "source": source,
        }
    )

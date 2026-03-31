"""Views for pages that render complete HTML pages."""

import os
import re
import tempfile
import uuid
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import ExtractYear
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from ..forms import (
    CommentForm,
    DBLPUrlForm,
    IncorrectCitationForm,
    LoginForm,
    RegisterForm,
)
from ..models import (
    AREA_CHOICES,
    Comment,
    IncorrectCitation,
    SavedCitation,
    UserProfile,
    Vote,
)
from ..services.semantic_fetch import get_citations_with_fallback
from ..services.citation_extractor import process_manuscript
from ..services.engines import ALLOWED_ENGINES
from ..services.reader_data import extract_pdf_references, extract_pdf_url_from_metadata
from ..services.report_tags import (
    CITATION_TYPE_CHOICES,
    PUBLICATION_AREA_LABELS,
    apply_report_tags,
    extract_report_tag_labels,
    extract_report_tag_values,
    normalize_tag_values,
)
from ..services.semanticscholar import download_pdf_to_temp


def _reader_build_stamp() -> str:
    """Return reader.js mtime as a cache-busting stamp for templates."""
    reader_js = os.path.join(
        settings.BASE_DIR, "citations", "static", "reader", "reader.js"
    )
    try:
        return str(int(os.path.getmtime(reader_js)))
    except OSError:
        return ""


def _can_edit_report(user, citation) -> bool:
    return user.is_authenticated and (user == citation.author or user.is_superuser)


EDITABLE_REPORT_FIELDS = (
    "doi_original",
    "doi_incorrect",
    "incorrect_reason",
    "citation_type",
    "publication_area",
)

EDIT_SECTIONS = {
    "original": ("doi_original",),
    "incorrect": ("doi_incorrect",),
    "classification": ("citation_type", "publication_area"),
    "header": ("doi_original", "citation_type", "publication_area"),
    "reason": ("incorrect_reason",),
    "all": EDITABLE_REPORT_FIELDS,
}


def _base_edit_data(citation):
    return {field: getattr(citation, field) for field in EDITABLE_REPORT_FIELDS}


def _extract_report_title(citation) -> str:
    metadata = citation.metadata_original if isinstance(citation.metadata_original, dict) else {}
    override = str(metadata.get("title_override") or "").strip()
    if override:
        return override
    title = metadata.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    return str(title or "").strip()


def _set_report_title(citation, title_value: str) -> None:
    metadata = citation.metadata_original if isinstance(citation.metadata_original, dict) else {}
    metadata = dict(metadata)
    clean_title = str(title_value or "").strip()
    if clean_title:
        metadata["title_override"] = clean_title
    else:
        metadata.pop("title_override", None)
    citation.metadata_original = metadata


def _has_required_report_data(citation) -> bool:
    report_title = _extract_report_title(citation)
    return all(
        [
            str(report_title or "").strip(),
            str(citation.doi_original or "").strip(),
            str(citation.doi_incorrect or "").strip(),
            str(citation.incorrect_reason or "").strip(),
            str(citation.citation_type or "").strip(),
            str(citation.publication_area or "").strip(),
        ]
    )


def _selected_tag_values_from_post(post_data):
    selected_types = normalize_tag_values(
        post_data.getlist("citation_type"), dict(CITATION_TYPE_CHOICES)
    )
    selected_areas = normalize_tag_values(
        post_data.getlist("publication_area"), PUBLICATION_AREA_LABELS
    )
    return selected_types, selected_areas


def _get_uploaded_pdf_path(
    citation,
    metadata_attr: str = "metadata_incorrect",
    path_keys=("uploaded_pdf_path",),
) -> str:
    metadata_raw = getattr(citation, metadata_attr, None)
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    candidates = []
    for key in path_keys:
        stored_path = str(metadata.get(key) or "").strip()
        if stored_path:
            candidates.extend(
                [
                    stored_path,
                    stored_path.replace("\\", "/"),
                    stored_path.replace("/", os.sep),
                ]
            )

    legacy_url = str(metadata.get("url") or metadata.get("URL") or "").strip()
    media_url = str(getattr(settings, "MEDIA_URL", "") or "")
    if legacy_url:
        parsed = urlparse(legacy_url)
        legacy_path = parsed.path or legacy_url
        if media_url and legacy_path.startswith(media_url):
            candidates.append(legacy_path[len(media_url) :].lstrip("/"))
        if legacy_path.startswith("/media/"):
            candidates.append(legacy_path[len("/media/") :].lstrip("/"))
        candidates.append(legacy_path.lstrip("/"))

    for candidate in candidates:
        normalized = unquote(str(candidate or "").strip())
        if normalized and default_storage.exists(normalized):
            return normalized
    return ""


def _normalize_context_text(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _context_dedupe_key(page, paragraph: str, snippet: str) -> tuple[str, str]:
    primary_text = _normalize_context_text(paragraph) or _normalize_context_text(snippet)
    page_key = str(page).strip() if page is not None else ""
    return page_key, primary_text


DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
AUTHOR_YEAR_REGEX = re.compile(r"\b([A-Z][A-Za-z\-]+)\s*\(\s*((?:19|20)\d{2})\s*\)")


def _normalize_doi(value: str) -> str:
    candidate = str(value or "").strip()
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE)
    return candidate.rstrip(").,;:]").strip().lower()


def _extract_doi(text: str) -> str:
    if not text:
        return ""
    url_match = DOI_URL_REGEX.search(text)
    if url_match:
        return _normalize_doi(url_match.group(1))
    match = DOI_REGEX.search(text)
    if match:
        return _normalize_doi(match.group(0))
    return ""


def _extract_original_year(metadata: dict) -> str:
    for key in ("published-print", "published-online", "issued"):
        date_parts = (metadata.get(key, {}) or {}).get("date-parts", [])
        if not isinstance(date_parts, list) or not date_parts:
            continue
        first = date_parts[0]
        if isinstance(first, list) and first:
            year = first[0]
            if isinstance(year, int):
                return str(year)
            year_str = str(year or "").strip()
            if year_str.isdigit() and len(year_str) == 4:
                return year_str
    return ""


def _extract_original_authors(metadata: dict) -> set[str]:
    authors = metadata.get("author") or []
    normalized: set[str] = set()
    if not isinstance(authors, list):
        return normalized
    for author in authors:
        if not isinstance(author, dict):
            continue
        family = str(author.get("family") or "").strip().lower()
        if family:
            normalized.add(family)
    return normalized


def _build_target_hints(citation) -> dict:
    metadata = citation.metadata_original if isinstance(citation.metadata_original, dict) else {}
    return {
        "doi": _normalize_doi(citation.doi_original or ""),
        "year": _extract_original_year(metadata),
        "authors": _extract_original_authors(metadata),
    }


def _reference_entry_matches_target(reference_entry: dict, target_hints: dict) -> bool:
    target_doi = str(target_hints.get("doi") or "")
    target_year = str(target_hints.get("year") or "")
    target_authors: set[str] = set(target_hints.get("authors") or set())

    reference_raw = str(reference_entry.get("raw") or "")
    reference_doi = _normalize_doi(str(reference_entry.get("doi") or "")) or _extract_doi(
        reference_raw
    )
    reference_lower = reference_raw.lower()

    if target_doi and reference_doi:
        return reference_doi == target_doi
    if target_doi and not reference_doi:
        return False

    if target_year and target_authors:
        has_year = target_year in reference_lower
        has_author = any(author in reference_lower for author in target_authors)
        return has_year and has_author

    return False


def _item_mentions_target(item: dict, target_hints: dict, references_by_index: dict[int, dict]) -> bool:
    target_doi = str(target_hints.get("doi") or "")
    target_year = str(target_hints.get("year") or "")
    target_authors: set[str] = set(target_hints.get("authors") or set())
    if not target_doi and not (target_year and target_authors):
        return True

    item_type = str(item.get("type") or item.get("pattern") or "").strip().lower()
    raw_payload = item.get("raw")
    raw_data = raw_payload if isinstance(raw_payload, dict) else {}
    match_text = str(
        raw_data.get("match")
        or item.get("match")
        or item.get("snippet")
        or item.get("paragraph")
        or ""
    )

    if item_type == "doi":
        if not target_doi:
            return False
        return _extract_doi(match_text) == target_doi

    if item_type == "numeric":
        raw_numbers = raw_data.get("citation_numbers")
        numbers: list[int] = []
        if isinstance(raw_numbers, list):
            for value in raw_numbers:
                try:
                    parsed = int(value)
                except (TypeError, ValueError):
                    continue
                if parsed > 0:
                    numbers.append(parsed)

        if not numbers or not references_by_index:
            return False

        for number in numbers:
            reference_entry = references_by_index.get(number)
            if reference_entry and _reference_entry_matches_target(reference_entry, target_hints):
                return True
        return False

    if item_type in {"authoryear", "author-year"}:
        match = AUTHOR_YEAR_REGEX.search(match_text)
        if not match:
            return False
        author = str(match.group(1) or "").strip().lower()
        year = str(match.group(2) or "").strip()
        if target_year and year != target_year:
            return False
        if target_authors and author not in target_authors:
            return False
        return bool(author and year)

    return False


def citation_list(request):
    """
    Muestra una lista paginada de citas incorrectas, con opciones de filtrado.
    """
    qs = (
        IncorrectCitation.objects.select_related("author")
        .prefetch_related("votes")
        .order_by("-created_at")
    )

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(doi_original__icontains=q)
            | Q(doi_incorrect__icontains=q)
            | Q(metadata__title__icontains=q)
            | Q(metadata__authors__icontains=q)
        )

    area = request.GET.get("area")
    ctype = request.GET.get("ctype")
    year = request.GET.get("year")

    if area:
        qs = qs.filter(publication_area=area)
    if ctype:
        qs = qs.filter(citation_type=ctype)
    if year and year.isdigit():
        qs = qs.filter(created_at__year=year)

    areas = AREA_CHOICES
    citation_types = IncorrectCitation._meta.get_field("citation_type").choices
    years = (
        IncorrectCitation.objects.annotate(y=ExtractYear("created_at"))
        .values_list("y", flat=True)
        .distinct()
        .order_by("-y")
    )

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "citations": page_obj,
        "areas": areas,
        "citation_types": citation_types,
        "years": years,
    }
    return render(request, "citations/citation_list.html", context)


def home(request):
    """
    Renderiza la pogina de inicio.
    """
    show_login_modal = request.GET.get("show_login_modal") == "1"
    dblp_form = None

    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if request.method == "POST" and "update_dblp_home" in request.POST:
            dblp_form = DBLPUrlForm(request.POST, instance=profile)
            if dblp_form.is_valid():
                dblp_form.save()
                messages.success(request, "DBLP actualizado correctamente.")
                return redirect("home")
            messages.error(request, "Revisa la URL de DBLP.")
        else:
            dblp_form = DBLPUrlForm(instance=profile)

    return render(
        request,
        "citations/home.html",
        {
            "show_login_modal": show_login_modal,
            "login_form": LoginForm(),
            "register_form": RegisterForm(),
            "dblp_form": dblp_form,
        },
    )


def citation_detail(request, pk):
    citation = get_object_or_404(
        IncorrectCitation.objects.select_related("author").prefetch_related("votes"),
        pk=pk,
    )

    comments = (
        Comment.objects.filter(citation=citation)
        .select_related("author", "parent")
        .order_by("created_at")
    )

    # otros reportes de la misma orea (excluyendo el actual)
    other_area_reports = (
        IncorrectCitation.objects.filter(publication_area=citation.publication_area)
        .exclude(pk=citation.pk)
        .order_by("-created_at")[:5]
    )

    # reportes populares (por ngmero de votos positivos)
    popular_reports = (
        IncorrectCitation.objects.annotate(
            upvotes_count=Count("votes", filter=Q(votes__value=1))
        )
        .order_by("-upvotes_count", "-created_at")[:5]
    )

    for report in other_area_reports:
        type_tags, area_tags = extract_report_tag_labels(report)
        report.publication_area_display_tags = area_tags
        report.citation_type_display_tags = type_tags

    is_hx_request = request.headers.get("HX-Request", "").lower() == "true"

    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.citation = citation
            comment.author = request.user

            parent_id = request.POST.get("parent_id")
            if parent_id:
                comment.parent_id = int(parent_id)

            comment.save()

            if is_hx_request:
                response = render(
                    request,
                    "citations/partials/_comment.html",
                    {"comment": comment},
                )
                response["HX-Trigger"] = "comment-added"
                return response

            return redirect("citation_detail", pk=pk)

        if is_hx_request:
            error_response = render(
                request,
                "citations/partials/_comment_errors.html",
                {"errors": form.errors},
                status=400,
            )
            error_response["HX-Retarget"] = "#commentFeedback"
            error_response["HX-Reswap"] = "innerHTML"
            return error_response
    else:
        form = CommentForm()

    original_uploaded_pdf_path = _get_uploaded_pdf_path(
        citation,
        metadata_attr="metadata_original",
        path_keys=("uploaded_pdf_path", "uploaded_pdf_path_original"),
    )
    if original_uploaded_pdf_path and default_storage.exists(original_uploaded_pdf_path):
        original_pdf_url = reverse(
            "citation_uploaded_pdf_article",
            kwargs={"pk": citation.pk, "article": "original"},
        )
    else:
        original_pdf_url = extract_pdf_url_from_metadata(citation.metadata_original)

    incorrect_uploaded_pdf_path = _get_uploaded_pdf_path(
        citation,
        metadata_attr="metadata_incorrect",
        path_keys=("uploaded_pdf_path", "uploaded_pdf_path_incorrect"),
    )
    if incorrect_uploaded_pdf_path and default_storage.exists(incorrect_uploaded_pdf_path):
        incorrect_pdf_url = reverse(
            "citation_uploaded_pdf_article",
            kwargs={"pk": citation.pk, "article": "incorrect"},
        )
    else:
        incorrect_pdf_url = extract_pdf_url_from_metadata(citation.metadata_incorrect)

    can_edit_report = _can_edit_report(request.user, citation)
    report_edit_mode = can_edit_report and (
        request.GET.get("edit") == "1" or request.GET.get("edit_header") == "1"
    )
    header_edit_mode = report_edit_mode
    report_title = _extract_report_title(citation)
    report_title_display = report_title or f"Reporte #{citation.id}"
    selected_citation_type_values, selected_publication_area_values = (
        extract_report_tag_values(citation)
    )
    display_citation_type_tags, display_publication_area_tags = (
        extract_report_tag_labels(citation)
    )
    required_report_complete = _has_required_report_data(citation)
    creation_guard_enabled = report_edit_mode and not required_report_complete
    discard_draft_url = (
        reverse("citation_discard_draft", kwargs={"pk": citation.pk})
        if creation_guard_enabled
        else ""
    )

    context = {
        "citation": citation,
        "comment_form": form,
        "comments": comments,
        "other_area_reports": other_area_reports,
        "popular_reports": popular_reports,
        "pdf_url": incorrect_pdf_url or "",
        "original_pdf_url": original_pdf_url or "",
        "incorrect_pdf_url": incorrect_pdf_url or "",
        "can_edit_report": can_edit_report,
        "report_edit_mode": report_edit_mode,
        "header_edit_mode": header_edit_mode,
        "report_title": report_title,
        "report_title_display": report_title_display,
        "selected_citation_type_values": selected_citation_type_values,
        "selected_publication_area_values": selected_publication_area_values,
        "display_citation_type_tags": display_citation_type_tags,
        "display_publication_area_tags": display_publication_area_tags,
        "creation_guard_enabled": creation_guard_enabled,
        "discard_draft_url": discard_draft_url,
        "citation_type_choices": CITATION_TYPE_CHOICES,
        "publication_area_choices": AREA_CHOICES,
    }
    return render(request, "citations/citation_detail.html", context)

    is_hx_request = request.headers.get("HX-Request", "").lower() == "true"

    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.citation = citation
            comment.author = request.user

            parent_id = request.POST.get("parent_id")
            if parent_id:
                comment.parent_id = int(parent_id)

            comment.save()

            if is_hx_request:
                response = render(
                    request,
                    "citations/partials/_comment.html",
                    {"comment": comment},
                )
                response["HX-Trigger"] = "comment-added"
                return response

            return redirect("citation_detail", pk=pk)

        if is_hx_request:
            error_response = render(
                request,
                "citations/partials/_comment_errors.html",
                {"errors": form.errors},
                status=400,
            )
            error_response["HX-Retarget"] = "#commentFeedback"
            error_response["HX-Reswap"] = "innerHTML"
            return error_response
    else:
        form = CommentForm()

    context = {
        "citation": citation,
        "comment_form": form,
        "comments": comments,
        "other_area_reports": other_area_reports,
        "popular_reports": popular_reports,
    }
    return render(request, "citations/citation_detail.html", context)


@login_required
def citation_edit(request, pk):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    if not _can_edit_report(request.user, citation):
        messages.error(request, "No tienes permiso para editar este reporte.")
        return redirect("citation_detail", pk=pk)

    if request.method != "POST":
        return redirect("citation_detail", pk=pk)

    section = request.POST.get("section", "all")
    allowed_fields = EDIT_SECTIONS.get(section)
    if not allowed_fields:
        messages.error(request, "Seccion de edicion no valida.")
        return redirect("citation_detail", pk=pk)

    required_by_section = {
        "all": (
            ("report_title", "Titulo del reporte"),
            ("doi_original", "DOI original"),
            ("doi_incorrect", "DOI incorrecto"),
            ("incorrect_reason", "Motivo / Explicacion"),
            ("citation_type", "Tipo de error"),
            ("publication_area", "Area de publicacion"),
        ),
        "header": (
            ("report_title", "Titulo del reporte"),
            ("doi_original", "DOI original"),
            ("citation_type", "Tipo de error"),
            ("publication_area", "Area de publicacion"),
        ),
        "original": (("doi_original", "DOI original"),),
        "incorrect": (("doi_incorrect", "DOI incorrecto"),),
        "reason": (("incorrect_reason", "Motivo / Explicacion"),),
    }
    missing_labels = [
        label
        for field, label in required_by_section.get(section, ())
        if not str(request.POST.get(field) or "").strip()
    ]
    if missing_labels:
        messages.error(
            request,
            "Faltan campos obligatorios: " + ", ".join(missing_labels) + ".",
        )
        return redirect(f"{reverse('citation_detail', args=[pk])}?edit=1")

    selected_types, selected_areas = _selected_tag_values_from_post(request.POST)

    data = _base_edit_data(citation)
    for field in allowed_fields:
        if field in request.POST:
            data[field] = request.POST.get(field)
    if "citation_type" in allowed_fields:
        data["citation_type"] = selected_types[0] if selected_types else ""
    if "publication_area" in allowed_fields:
        data["publication_area"] = selected_areas[0] if selected_areas else ""

    uploaded_pdf_saved = False

    uploaded_original_pdf = request.FILES.get("uploaded_pdf_original_file")
    if uploaded_original_pdf:
        original_name = uploaded_original_pdf.name or "uploaded_original.pdf"
        if not original_name.lower().endswith(".pdf"):
            original_name = f"{original_name}.pdf"
        upload_path = default_storage.save(
            f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{original_name}",
            uploaded_original_pdf,
        )
        metadata_original = (
            citation.metadata_original if isinstance(citation.metadata_original, dict) else {}
        )
        metadata_original = dict(metadata_original)
        metadata_original["uploaded_pdf_path"] = upload_path
        metadata_original["uploaded_pdf_path_original"] = upload_path
        metadata_original["url"] = default_storage.url(upload_path)
        citation.metadata_original = metadata_original
        citation.save(update_fields=["metadata_original"])
        uploaded_pdf_saved = True

    uploaded_incorrect_pdf = request.FILES.get("uploaded_pdf_incorrect_file") or request.FILES.get("uploaded_pdf_file")
    if uploaded_incorrect_pdf:
        original_name = uploaded_incorrect_pdf.name or "uploaded.pdf"
        if not original_name.lower().endswith(".pdf"):
            original_name = f"{original_name}.pdf"
        upload_path = default_storage.save(
            f"incorrect_pdfs/{citation.id}/{uuid.uuid4().hex}_{original_name}",
            uploaded_incorrect_pdf,
        )
        metadata_incorrect = (
            citation.metadata_incorrect if isinstance(citation.metadata_incorrect, dict) else {}
        )
        metadata_incorrect = dict(metadata_incorrect)
        metadata_incorrect["uploaded_pdf_path"] = upload_path
        metadata_incorrect["uploaded_pdf_path_incorrect"] = upload_path
        metadata_incorrect["url"] = default_storage.url(upload_path)
        citation.metadata_incorrect = metadata_incorrect
        citation.save(update_fields=["metadata_incorrect"])
        uploaded_pdf_saved = True

    form = IncorrectCitationForm(data=data, instance=citation)
    if form.is_valid():
        form.save()
        metadata_needs_save = False
        if section in {"header", "all", "classification"}:
            apply_report_tags(citation, selected_types, selected_areas)
            metadata_needs_save = True
        if section in {"header", "all"}:
            _set_report_title(citation, request.POST.get("report_title", ""))
            metadata_needs_save = True
        if metadata_needs_save:
            citation.save(update_fields=["metadata_original"])
        messages.success(request, "Reporte actualizado correctamente.")
    else:
        if uploaded_pdf_saved:
            messages.warning(
                request,
                "El PDF se guardó, pero hay campos del reporte que debes revisar.",
            )
        else:
            messages.error(request, "Revisa los datos del formulario de edicion.")

    return redirect("citation_detail", pk=pk)


@login_required
@require_POST
def citation_delete(request, pk):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    if not _can_edit_report(request.user, citation):
        messages.error(request, "No tienes permiso para eliminar este reporte.")
        return redirect("citation_detail", pk=pk)

    citation.delete()
    messages.success(request, "Reporte eliminado correctamente.")
    return redirect("citation_list")


@login_required
@require_POST
def citation_discard_draft(request, pk):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    if not _can_edit_report(request.user, citation):
        return JsonResponse({"success": False, "error": "forbidden"}, status=403)

    if _has_required_report_data(citation):
        return JsonResponse(
            {"success": False, "error": "report_already_complete"},
            status=409,
        )

    citation.delete()
    return JsonResponse({"success": True})


@xframe_options_sameorigin
def citation_uploaded_pdf(request, pk, article: str = "incorrect"):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    normalized_article = (article or "incorrect").lower()
    if normalized_article == "original":
        upload_path = _get_uploaded_pdf_path(
            citation,
            metadata_attr="metadata_original",
            path_keys=("uploaded_pdf_path", "uploaded_pdf_path_original"),
        )
        download_name = "articulo_original.pdf"
    elif normalized_article == "incorrect":
        upload_path = _get_uploaded_pdf_path(
            citation,
            metadata_attr="metadata_incorrect",
            path_keys=("uploaded_pdf_path", "uploaded_pdf_path_incorrect"),
        )
        download_name = "articulo_incorrecto.pdf"
    else:
        raise Http404("Tipo de artículo no válido.")

    if not upload_path or not default_storage.exists(upload_path):
        raise Http404("No hay PDF subido para este reporte.")
    pdf_file = default_storage.open(upload_path, "rb")
    response = FileResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{download_name}"'
    return response


def citation_preview(request, pk):
    citation = get_object_or_404(
        IncorrectCitation.objects
            .select_related("author")
            .prefetch_related("votes"),
        pk=pk,
    )

    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()

    user_vote = None
    if request.user.is_authenticated:
        user_vote = citation.votes.filter(user=request.user).first()

    is_saved = False
    if request.user.is_authenticated:
        is_saved = citation.saved_by.filter(user=request.user).exists()

    vote_buttons_html = render_to_string(
        "citations/partials/_vote_buttons.html",
        {
            "citation": citation,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "user_vote": user_vote,
            "user": request.user,
        },
        request=request,
    )

    save_button_html = render_to_string(
        "citations/partials/_save_button.html",
        {
            "citation": citation,
            "is_saved": is_saved,
            "user": request.user,
        },
        request=request,
    )

    return render(
        request,
        "citations/partials/_citation_preview.html",
        {
            "citation": citation,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "user_vote": user_vote,
            "vote_buttons_html": vote_buttons_html,
            "save_button_html": save_button_html,
        }
    )


@login_required
@require_POST
def citation_extract_contexts(request, pk):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    if not _can_edit_report(request.user, citation):
        messages.error(request, "No tienes permiso para actualizar los parrafos de cita.")
        return redirect("citation_detail", pk=pk)

    if request.POST.get("context_selection") == "1":
        existing_contexts = (
            citation.citation_contexts if isinstance(citation.citation_contexts, list) else []
        )
        selected_indices = set()
        for raw_idx in request.POST.getlist("selected_context_index"):
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx >= 0:
                selected_indices.add(idx)

        selected_contexts = [
            ctx for idx, ctx in enumerate(existing_contexts) if idx in selected_indices
        ]
        citation.citation_contexts = selected_contexts
        citation.save(update_fields=["citation_contexts"])
        messages.success(
            request,
            f"Seleccion actualizada: {len(selected_contexts)} parrafos guardados.",
        )
        return redirect("citation_detail", pk=pk)

    engine = (request.POST.get("engine") or "generic").strip().lower()
    if engine not in ALLOWED_ENGINES:
        messages.error(request, "Herramienta de extraccion no valida.")
        return redirect("citation_detail", pk=pk)

    tmp_path = ""
    uploaded_pdf_path = _get_uploaded_pdf_path(
        citation,
        metadata_attr="metadata_incorrect",
        path_keys=("uploaded_pdf_path", "uploaded_pdf_path_incorrect"),
    )
    if uploaded_pdf_path and default_storage.exists(uploaded_pdf_path):
        suffix = os.path.splitext(uploaded_pdf_path)[1] or ".pdf"
        with default_storage.open(uploaded_pdf_path, "rb") as stored_file:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                for chunk in stored_file.chunks():
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name
    else:
        pdf_url = extract_pdf_url_from_metadata(citation.metadata_incorrect)
        if not pdf_url:
            messages.error(request, "No hay PDF disponible para extraer parrafos.")
            return redirect("citation_detail", pk=pk)
        tmp_path = download_pdf_to_temp(pdf_url) or ""

    if not tmp_path:
        messages.error(request, "No se pudo preparar el PDF para el extractor.")
        return redirect("citation_detail", pk=pk)

    try:
        data = process_manuscript(tmp_path, engine=engine, debug=False)
        if not data.get("ok", False):
            messages.error(
                request,
                data.get("error") or "No se pudieron extraer parrafos con el motor seleccionado.",
            )
            return redirect("citation_detail", pk=pk)

        references, _ = extract_pdf_references(tmp_path)
        references_by_index: dict[int, dict] = {}
        for reference in references:
            if not isinstance(reference, dict):
                continue
            raw_index = reference.get("index")
            try:
                idx = int(raw_index)
            except (TypeError, ValueError):
                continue
            if idx > 0 and idx not in references_by_index:
                references_by_index[idx] = reference
        target_hints = _build_target_hints(citation)

        contexts = []
        seen_context_keys: set[tuple[str, str]] = set()
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            if not _item_mentions_target(item, target_hints, references_by_index):
                continue
            raw_payload = item.get("raw")
            raw_data = raw_payload if isinstance(raw_payload, dict) else {}
            paragraph = str(item.get("paragraph") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not paragraph and not snippet:
                continue
            dedupe_key = _context_dedupe_key(
                item.get("page"),
                paragraph=paragraph,
                snippet=snippet,
            )
            if not dedupe_key[1] or dedupe_key in seen_context_keys:
                continue
            seen_context_keys.add(dedupe_key)
            contexts.append(
                {
                    "page": item.get("page"),
                    "pattern": item.get("type") or item.get("pattern") or "",
                    "snippet": snippet,
                    "paragraph": paragraph,
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "confidence": item.get("confidence") or 0,
                    "citation_numbers": (
                        raw_data.get("citation_numbers")
                        if isinstance(raw_data.get("citation_numbers"), list)
                        else []
                    ),
                    "citation_block": str(
                        raw_data.get("citation_block") or raw_data.get("match") or ""
                    ),
                }
            )

        citation.citation_contexts = contexts
        citation.save(update_fields=["citation_contexts"])
        messages.success(
            request,
            f"Extractor aplicado: {len(contexts)} fragmentos guardados.",
        )
        return redirect("citation_detail", pk=pk)
    except Exception as exc:  # pylint: disable=broad-except
        messages.error(request, f"No se pudo ejecutar el extractor: {exc}")
        return redirect("citation_detail", pk=pk)
    finally:
        try:
            if tmp_path:
                os.remove(tmp_path)
        except OSError:
            pass

def semantic_citations_view(request):
    """
    Muestra las citas de un art??culo obtenidas de Semantic Scholar.
    """
    doi = request.GET.get("doi")
    if not doi:
        return redirect("account_settings")

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

    context = {
        "doi": doi,
        "citation_count": citation_count,
        "citations": citations,
        "source": source,
    }
    return render(request, "citations/semantic_citations.html", context)


def citation_reader(request, report_id: int):
    citation = get_object_or_404(IncorrectCitation, pk=report_id)
    uploaded_pdf_path = _get_uploaded_pdf_path(citation)
    if uploaded_pdf_path and default_storage.exists(uploaded_pdf_path):
        pdf_url = reverse("citation_uploaded_pdf", kwargs={"pk": citation.pk})
    else:
        pdf_url = extract_pdf_url_from_metadata(citation.metadata_incorrect)
    context = {
        "citation": citation,
        "pdf_url": pdf_url or "",
        "report_id": report_id,
        "reader_build": _reader_build_stamp(),
    }
    return render(request, "citations/reader.html", context)


def citation_reader_preview(request):
    pdf_url = request.GET.get("pdf_url", "")
    context = {
        "pdf_url": pdf_url or "",
        "reader_build": _reader_build_stamp(),
    }
    return render(request, "citations/reader_preview.html", context)

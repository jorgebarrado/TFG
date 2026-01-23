"""Views for pages that render complete HTML pages."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import ExtractYear
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.db.models import Count, Q
from ..forms import CommentForm, DBLPUrlForm, LoginForm, RegisterForm
from ..models import (
    AREA_CHOICES,
    Comment,
    IncorrectCitation,
    SavedCitation,
    UserProfile,
    Vote,
)
from ..services.semantic_fetch import get_citations_with_fallback
from ..services.reader_data import extract_pdf_url_from_metadata
from django.shortcuts import get_object_or_404, render
from ..models import IncorrectCitation


def citation_list(request):
    """
    Muestra una lista paginada de citas incorrectas, con opciones de filtrado.

    Permite buscar por texto (DOI, título, autores) y filtrar por área de publicación,
    tipo de error y año de creación del reporte.

    Args:
        request: El objeto HttpRequest de Django.

    Returns:
        HttpResponse: La página renderizada con la lista de citas.
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
    Renderiza la página de inicio.

    Muestra un modal de inicio de sesión si se solicita y permite actualizar
    la URL de DBLP del usuario autenticado.

    Args:
        request: El objeto HttpRequest de Django.

    Returns:
        HttpResponse: La página de inicio renderizada.
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
    """
    Muestra los detalles de un reporte de cita incorrecta.

    Permite ver la información del reporte, comentarios, y agregar nuevos comentarios.
    Soporta peticiones AJAX (HTMX) para agregar comentarios dinámicamente.

    Args:
        request: El objeto HttpRequest de Django.
        pk (int): La clave primaria del reporte de cita incorrecta.

    Returns:
        HttpResponse: La página de detalles del reporte o fragmentos HTML para HTMX.
    """
    citation = get_object_or_404(
        IncorrectCitation.objects.select_related("author").prefetch_related("votes"),
        pk=pk,
    )

    comments = (
        Comment.objects.filter(citation=citation)
        .select_related("author", "parent")
        .order_by("created_at")
    )

    # otros reportes de la misma area (excluyendo el actual)
    other_area_reports = (
        IncorrectCitation.objects.filter(publication_area=citation.publication_area)
        .exclude(pk=citation.pk)
        .order_by("-created_at")[:5]
    )

    # reportes populares (por numero de votos positivos)
    popular_reports = (
        IncorrectCitation.objects.annotate(
            upvotes_count=Count("votes", filter=Q(votes__value=1))
        )
        .order_by("-upvotes_count", "-created_at")[:5]
    )

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


def citation_preview(request, pk):
    """
    Renderiza una vista previa de un reporte de cita (para modales o cards).

    Args:
        request: El objeto HttpRequest de Django.
        pk (int): La clave primaria del reporte.

    Returns:
        HttpResponse: Fragmento HTML con la vista previa del reporte.
    """
    citation = get_object_or_404(
        IncorrectCitation.objects.select_related("author").prefetch_related("votes"),
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
        },
    )


def semantic_citations_view(request):
    """
    Muestra las citas de un artículo obtenidas de Semantic Scholar.

    Si un DOI obtenido de Semantic Scholar ya está registrado en la base de datos
    como una cita incorrecta, se marca como registrado.

    Args:
        request: El objeto HttpRequest de Django, debe contener el parámetro 'doi'.

    Returns:
        HttpResponse: La página con la lista de citas obtenidas.
    """
    doi = request.GET.get("doi")
    if not doi:
        return redirect("account_settings")

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

    context = {
        "doi": doi,
        "citation_count": citation_count,
        "citations": citations,
        "source": source,
    }
    return render(request, "citations/semantic_citations.html", context)


def citation_reader(request, report_id: int):
    """
    Renderiza la vista del lector para un reporte específico.

    Args:
        request: El objeto HttpRequest de Django.
        report_id (int): El ID del reporte a leer.

    Returns:
        HttpResponse: La página del lector.
    """
    citation = get_object_or_404(IncorrectCitation, pk=report_id)
    pdf_url = extract_pdf_url_from_metadata(citation.metadata_incorrect)
    context = {
        "citation": citation,
        "pdf_url": pdf_url or "",
        "report_id": report_id,
    }
    return render(request, "citations/reader.html", context)


def citation_reader_preview(request):
    """
    Renderiza una vista previa del lector basada en una URL de PDF proporcionada.

    Args:
        request: El objeto HttpRequest de Django, puede contener 'pdf_url'.

    Returns:
        HttpResponse: La página de vista previa del lector.
    """
    pdf_url = request.GET.get("pdf_url", "")
    context = {
        "pdf_url": pdf_url or "",
    }
    return render(request, "citations/reader_preview.html", context)

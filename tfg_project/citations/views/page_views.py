"""Views for pages that render complete HTML pages."""

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import ExtractYear
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import CommentForm, LoginForm, RegisterForm
from ..models import (
    AREA_CHOICES,
    Comment,
    IncorrectCitation,
    SavedCitation,
    Vote,
)
from ..services.semantic_fetch import get_citations_with_fallback


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
    Renderiza la página de inicio.
    """
    show_login_modal = request.GET.get("show_login_modal") == "1"
    return render(
        request,
        "citations/home.html",
        {
            "show_login_modal": show_login_modal,
            "login_form": LoginForm(),
            "register_form": RegisterForm(),
        },
    )


def citation_detail(request, pk):
    """
    Muestra los detalles de un reporte de cita incorrecta.
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
    upvotes = sum(1 for vote in citation.votes.all() if vote.value == 1)
    downvotes = sum(1 for vote in citation.votes.all() if vote.value == -1)

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

            if request.headers.get("HX-Request"):
                return render(
                    request,
                    "citations/partials/_comment.html",
                    {"comment": comment},
                )
            return redirect("citation_detail", pk=pk)
    else:
        form = CommentForm()

    user_vote = None
    if request.user.is_authenticated:
        vote = Vote.objects.filter(citation=citation, user=request.user).first()
        if vote:
            user_vote = vote.value

    is_saved = False
    if request.user.is_authenticated:
        is_saved = SavedCitation.objects.filter(
            user=request.user, citation=citation
        ).exists()

    context = {
        "citation": citation,
        "comment_form": form,
        "comments": comments,
        "upvotes": upvotes,
        "downvotes": downvotes,
        "user_vote": user_vote,
        "is_saved": is_saved,
    }
    return render(request, "citations/citation_detail.html", context)


def semantic_citations_view(request):
    """
    Muestra las citas de un artículo obtenidas de Semantic Scholar.
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

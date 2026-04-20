"""Views related to user profiles and personalized content."""


from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import activate

from ..forms import CustomPasswordChangeForm, ProfileForm, UserProfileForm
from ..models import (
    Comment,
    IncorrectCitation,
    SavedCitation,
    UserProfile,
    Vote,
)
from ..services.dblp_client import DBLPClientError, get_author_papers
from ..services.semantic_scholar_client import (
    SemanticScholarError,
    get_citation_counts_for_dois,
    get_citing_papers_for_doi_paginated,
    get_paper_metadata_by_doi,
)
from ..utils import get_citation_count

User = get_user_model()


def get_avatar_initial(user):
    if getattr(user, "username", ""):
        return user.username[0].upper()
    if getattr(user, "first_name", ""):
        return user.first_name[0].upper()
    return "?"


def profile_view(request, username):
    profile_user = get_object_or_404(User, username=username)
    profile, _ = UserProfile.objects.get_or_create(user=profile_user)

    latest_reports = IncorrectCitation.objects.filter(author=profile_user).order_by(
        "-created_at"
    )[:5]

    context = {
        "profile_user": profile_user,
        "profile": profile,
        "latest_reports": latest_reports,
        "avatar_initial": get_avatar_initial(profile_user),
        "is_self_profile": request.user.is_authenticated
        and request.user == profile_user,
    }

    return render(request, "citations/public_profile.html", context)


@login_required
def account_settings(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == "POST":
        profile_form = ProfileForm(request.POST, instance=user)
        userprofile_form = UserProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
        )
        pwd_form = CustomPasswordChangeForm(user, request.POST)

        # distinguir qué formulario se ha enviado por el name del botón
        if "update_basic_profile" in request.POST:
            if profile_form.is_valid() and userprofile_form.is_valid():
                profile_form.save()
                profile = userprofile_form.save()

                lang = profile.preferred_language
                url = reverse("account_settings") + "#section-basic"
                response = redirect(url)
                if lang:
                    activate(lang)
                    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang)

                messages.success(request, "Perfil actualizado correctamente.")
                return response

        elif "update_extended_profile" in request.POST:
            if userprofile_form.is_valid():
                profile = userprofile_form.save()

                lang = profile.preferred_language
                url = reverse("account_settings") + "#section-extended"
                response = redirect(url)
                if lang:
                    activate(lang)
                    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang)

                messages.success(request, "Perfil extendido actualizado.")
                return response

        if "change_password" in request.POST and pwd_form.is_valid():
            pwd_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Contraseña actualizada.")
            url = reverse("account_settings") + "#section-password"
            return redirect(url)

    else:
        profile_form = ProfileForm(instance=user)
        userprofile_form = UserProfileForm(instance=profile)
        pwd_form = CustomPasswordChangeForm(user)

    context = {
        "profile_form": profile_form,
        "userprofile_form": userprofile_form,
        "pwd_form": pwd_form,
        "profile": profile,
        "avatar_initial": get_avatar_initial(user),
    }
    return render(request, "citations/account_settings.html", context)


@login_required
def my_reports(request):
    """
    Muestra los reportes de citas incorrectas creados por el usuario actual.
    """
    reports = (
        IncorrectCitation.objects.filter(author=request.user)
        .prefetch_related("votes", "comments")
        .order_by("-created_at")
    )
    return render(request, "citations/my_reports.html", {"reports": reports})


@login_required
def my_comments(request):
    """
    Muestra los comentarios realizados por el usuario actual.
    """
    comments = (
        Comment.objects.filter(author=request.user)
        .select_related("citation", "citation__author")
        .order_by("-created_at")
    )
    return render(request, "citations/my_comments.html", {"comments": comments})


@login_required
def my_saved(request):
    """
    Muestra las citas guardadas por el usuario actual.
    """
    saved = (
        SavedCitation.objects.filter(user=request.user)
        .select_related("citation", "citation__author")
        .order_by("-created_at")
    )
    return render(request, "citations/my_saved.html", {"saved": saved})


def dblp_articles_view(request):
    """
    Muestra los artículos de un usuario obtenidos de DBLP.

    Este flujo usa la misma fuente de datos que la revisión de citantes para
    que el paper_id sea consistente y podamos lanzar la revisión directamente
    desde la búsqueda en DBLP.
    """
    has_dblp_url_param = "dblp_url" in request.GET
    dblp_url = request.GET.get("dblp_url", "").strip()
    include_without_citations_raw = request.GET.get("include_without_citations")
    if include_without_citations_raw is None:
        include_without_citations = True
    else:
        include_without_citations = include_without_citations_raw.lower() in {
            "1",
            "true",
            "on",
            "yes",
        }

    saved_dblp_url = ""
    if request.user.is_authenticated:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        saved_dblp_url = profile.dblp_url or ""

    if not has_dblp_url_param:
        return render(
            request,
            "citations/dblp_articles.html",
            {
                "dblp_url": saved_dblp_url,
                "show_dblp_form": True,
                "include_without_citations": include_without_citations,
            },
        )

    if not dblp_url:
        return render(
            request,
            "citations/dblp_articles.html",
            {
                "dblp_url": "",
                "show_dblp_form": True,
                "include_without_citations": include_without_citations,
            },
        )

    try:
        all_articles = get_author_papers(dblp_url)
    except DBLPClientError as exc:
        messages.error(request, str(exc))
        all_articles = []

    for idx, article in enumerate(all_articles):
        article["paper_id"] = idx

    tipo = request.GET.get("tipo", "").strip()
    busqueda = request.GET.get("q", "").strip().lower()
    tipos_disponibles = sorted({a.get("type") for a in all_articles if a.get("type")})

    citation_filter_error = None

    def _attach_citation_data(article, citation_counts=None):
        doi = article.get("doi")
        article["can_review_citers"] = bool(doi)
        if not doi:
            article["citation_count"] = 0
        elif citation_counts is not None:
            article["citation_count"] = citation_counts.get(str(doi).strip(), 0)
        else:
            article["citation_count"] = get_citation_count(doi)

    articles = all_articles
    if tipo:
        articles = [a for a in articles if a.get("type") == tipo]
    if busqueda:
        articles = [
            a for a in articles if busqueda in (a.get("title") or "").lower()
        ]
    if not include_without_citations:
        citation_counts = {}
        try:
            citation_counts = get_citation_counts_for_dois(
                [a.get("doi") for a in articles if a.get("doi")]
            )
        except SemanticScholarError as exc:
            citation_filter_error = str(exc)

        filtered_articles = []
        for article in articles:
            _attach_citation_data(article, citation_counts)
            if article["citation_count"] > 0:
                filtered_articles.append(article)
        articles = filtered_articles

    paginator = Paginator(articles, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    for article in page:
        if "citation_count" not in article or "can_review_citers" not in article:
            _attach_citation_data(article)

    context = {
        "articles": page,
        "dblp_url": dblp_url,
        "tipo_actual": tipo,
        "tipos_disponibles": tipos_disponibles,
        "busqueda": busqueda,
        "include_without_citations": include_without_citations,
        "citation_filter_error": citation_filter_error,
    }
    return render(request, "citations/dblp_articles.html", context)


def doi_search_view(request):
    """Busca citadores de un artículo introducido por DOI."""
    doi = request.GET.get("doi", "").strip()

    if not doi:
        return render(request, "citations/doi_search.html", {"doi": ""})

    paper = None
    citing_papers = []
    next_page_offset = None
    error_message = None
    limit = 10
    offset = 0
    offset_raw = request.GET.get("offset")
    if offset_raw and offset_raw.isdigit():
        offset = int(offset_raw)

    import json as _json
    paper_metadata_json = ""
    try:
        paper = get_paper_metadata_by_doi(doi)
        if paper is None:
            error_message = f"No se encontró ningún artículo con DOI '{doi}' en Semantic Scholar."
        else:
            paper_metadata_json = _json.dumps({
                "title": paper.get("title"),
                "doi": paper.get("doi") or doi,
                "year": paper.get("year"),
                "authors": paper.get("authors"),
                "venue": paper.get("venue"),
                "source": "semantic_scholar",
            }, ensure_ascii=True)
            citing_papers, next_page_offset = get_citing_papers_for_doi_paginated(
                paper.get("doi") or doi, limit=limit, offset=offset
            )
    except SemanticScholarError as exc:
        error_message = str(exc)

    range_start = offset + 1 if citing_papers else 0
    range_end = offset + len(citing_papers)

    context = {
        "doi": doi,
        "paper": paper,
        "paper_metadata_json": paper_metadata_json,
        "citing_papers": citing_papers,
        "error_message": error_message,
        "offset": offset,
        "limit": limit,
        "next_offset": next_page_offset,
        "range_start": range_start,
        "range_end": range_end,
    }
    return render(request, "citations/doi_search.html", context)


@login_required
def my_profile(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Stats
    reports_qs = IncorrectCitation.objects.filter(author=user)
    comments_qs = Comment.objects.filter(author=user)
    votes_qs = Vote.objects.filter(user=user)
    saved_qs = SavedCitation.objects.filter(user=user)

    stats = {
        "reports": reports_qs.count(),
        "comments": comments_qs.count(),
        "votes": votes_qs.count(),
        "saved": saved_qs.count(),
        "joined": user.date_joined,
    }

    # Última actividad (simple pero efectiva)
    # OPTIMIZATION: Slice querysets at the database level to avoid loading all objects
    # into memory, and use select_related to avoid N+1 queries when accessing citation fields
    activities = []

    # Get up to 20 most recent of each type, since we only need 20 max for the feed
    # No select_related needed for reports_qs because the report IS the citation object,
    # and we only access r.doi_original, but adding author just in case the template uses it
    recent_reports = reports_qs.select_related("author").order_by("-created_at")[:20]
    for r in recent_reports:
        activities.append(
            {
                "type": "report",
                "created_at": r.created_at,
                "text": f"Creó el reporte “{r.doi_original}”",
                "citation": r,
            }
        )

    recent_comments = comments_qs.select_related("citation").order_by("-created_at")[
        :20
    ]
    for c in recent_comments:
        activities.append(
            {
                "type": "comment",
                "created_at": c.created_at,
                "text": f"Comentó en “{c.citation.doi_original}”",
                "citation": c.citation,
            }
        )

    recent_saves = saved_qs.select_related("citation").order_by("-created_at")[:20]
    for s in recent_saves:
        activities.append(
            {
                "type": "saved",
                "created_at": s.created_at,
                "text": f"Guardó el reporte “{s.citation.doi_original}”",
                "citation": s.citation,
            }
        )

    # Vote doesn't have created_at, using citation.created_at as fallback
    recent_votes = votes_qs.select_related("citation").order_by(
        "-citation__created_at"
    )[:20]
    for v in recent_votes:
        label = "Votó positivo" if v.value == 1 else "Votó negativo"
        activities.append(
            {
                "type": "vote",
                "created_at": v.citation.created_at,  # o un campo created_at si lo tienes
                "text": f"{label} en “{v.citation.doi_original}”",
                "citation": v.citation,
            }
        )

    activities = sorted(activities, key=lambda a: a["created_at"], reverse=True)[:20]

    context = {
        "profile_user": user,
        "profile": profile,
        "stats": stats,
        "activities": activities,
        "reports_list": reports_qs.order_by("-created_at")[:20],
        "comments_list": comments_qs.select_related("citation").order_by("-created_at")[
            :20
        ],
        "saved_list": saved_qs.select_related("citation").order_by("-created_at")[:20],
        "votes_list": votes_qs.select_related("citation").order_by(
            "citation__created_at"
        )[:20],
        "avatar_initial": get_avatar_initial(user),
    }

    return render(request, "citations/profile.html", context)

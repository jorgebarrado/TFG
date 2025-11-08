"""Views for citations app."""

import requests
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import ExtractYear
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

# Formularios propios
from .forms import (
    CommentForm,
    CustomPasswordChangeForm,
    IncorrectCitationForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    UserProfileForm,
)

# Modelos propios
from .models import (
    AREA_CHOICES,
    Comment,
    IncorrectCitation,
    SavedCitation,
    UserProfile,
    Vote,
)
from .services.semantic_fetch import get_citations_with_fallback
from .utils import check_doi_has_citations, get_articles_from_dblp


@login_required
def dblp_articles_view(request):
    """
    Displays a list of articles from the user's DBLP profile.

    This view fetches articles from the DBLP URL stored in the user's profile,
    allows filtering by publication type and a search query, and paginates the
    results. For each article on the current page, it also checks if there are
    any known citations via the Semantic Scholar API.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'dblp_articles.html' template
        with the filtered and paginated list of articles.
    """
    user = request.user
    profile = UserProfile.objects.get(user=user)
    all_articles = get_articles_from_dblp(profile.dblp_url) if profile.dblp_url else []

    tipo = request.GET.get("tipo", "").strip()
    busqueda = request.GET.get("q", "").strip().lower()
    tipos_disponibles = sorted(set(a["type"] for a in all_articles))

    # Aplicar filtros
    articles = all_articles
    if tipo:
        articles = [a for a in articles if a["type"] == tipo]
    if busqueda:
        articles = [a for a in articles if busqueda in a["title"].lower()]

    # Paginación (10 por página)
    paginator = Paginator(articles, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    # Verificar si tienen citas (solo para artículos de esta página)
    for article in page:
        if article.get("doi"):
            article["has_citations"] = check_doi_has_citations(article["doi"])
        else:
            article["has_citations"] = False

    return render(
        request,
        "citations/dblp_articles.html",
        {
            "articles": page,
            "dblp_url": profile.dblp_url,
            "tipo_actual": tipo,
            "tipos_disponibles": tipos_disponibles,
            "busqueda": busqueda,
        },
    )


def citation_suggest(request):
    """
    Provides suggestions for citations based on a search term.

    This view is used for autocomplete functionality. It searches for incorrect
    citations where the original DOI or title contains the provided search term
    and returns a JSON response with the top 5 matches.

    Args:
        request: The HttpRequest object, containing the 'term' GET parameter.

    Returns:
        A JsonResponse with a list of matching citations.
    """
    term = request.GET.get("term", "")
    qs = IncorrectCitation.objects.filter(
        Q(doi_original__icontains=term) | Q(metadata__title__icontains=term)
    ).values("doi_original", "metadata__title")[:5]

    return JsonResponse(list(qs), safe=False)


def fetch_doi_metadata(request):
    """
    Fetches metadata for a given DOI from the CrossRef API.

    Args:
        request: The HttpRequest object, containing the 'doi' GET parameter.

    Returns:
        A JsonResponse with the DOI's metadata if found, otherwise an error
        message.
    """
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "No DOI"}, status=400)

    url = f"https://api.crossref.org/works/{doi}"
    r = requests.get(url, timeout=6)
    if r.status_code == 200:
        return JsonResponse(r.json()["message"])
    return JsonResponse({"error": "Not found"}, status=404)


def citation_list(request):
    """
    Displays a paginated list of all incorrect citation reports.

    This view allows users to browse through all submitted reports, with
    options to filter by publication area, citation type, and year. It also
    supports a free-text search across DOIs, titles, and authors.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'citation_list.html' template
        with the filtered and paginated list of reports.
    """
    qs = IncorrectCitation.objects.select_related("author").order_by("-created_at")

    # -------------------- búsqueda libre --------------------
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

    paginator = Paginator(qs, 25)  # Muestra 25 reportes por página
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "citations": page_obj,  # Pasamos el objeto de página a la plantilla
        "areas": areas,
        "citation_types": citation_types,
        "years": years,
    }
    return render(request, "citations/citation_list.html", context)


User = get_user_model()


@login_required
def account_settings(request):
    """
    Manages user account settings.

    This view handles three forms: one for updating the user's profile
    (first name, username), one for changing the password, and one for
    setting the DBLP profile URL. It processes the submitted form and
    displays success messages upon successful updates.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'account_settings.html'
        template with the profile, password change, and DBLP forms.
    """
    user = request.user
    profile_form = ProfileForm(instance=user)
    pwd_form = CustomPasswordChangeForm(user)
    userprofile, _ = UserProfile.objects.get_or_create(user=user)
    dblp_form = UserProfileForm(instance=userprofile)

    # Obtener artículos si hay URL DBLP
    articles = []
    if userprofile.dblp_url:
        articles = get_articles_from_dblp(userprofile.dblp_url)

    # Procesar formularios
    if request.method == "POST":
        if "save_profile" in request.POST:
            profile_form = ProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Perfil actualizado.")
                return redirect("account_settings")

        elif "change_password" in request.POST:
            pwd_form = CustomPasswordChangeForm(user, request.POST)
            if pwd_form.is_valid():
                pwd_form.save()
                update_session_auth_hash(request, pwd_form.user)
                messages.success(request, "Contraseña cambiada.")
                return redirect("account_settings")

        elif "save_dblp" in request.POST:
            dblp_form = UserProfileForm(request.POST, instance=userprofile)
            if dblp_form.is_valid():
                dblp_form.save()
                messages.success(request, "URL de DBLP actualizada.")
                return redirect("account_settings")

    context = {
        "profile_form": profile_form,
        "pwd_form": pwd_form,
        "dblp_form": dblp_form,
        "articles": articles,
    }
    return render(request, "citations/account_settings.html", context)


# Landing page
def home(request):
    """
    Renders the home page.

    Also handles showing the login modal if the 'show_login_modal' GET
    parameter is set.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'home.html' template.
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


# Vista de login con soporte para `next`
def login_view(request):
    """
    Handles user login.

    If the login is successful, the user is redirected to the URL specified
    in the 'next' parameter, or to the home page if 'next' is not provided.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object, either redirecting on successful login or
        rendering the home page with the login form and an error message on
        failure.
    """
    next_url = request.POST.get("next", request.GET.get("next", "/"))
    if request.method == "POST":
        form = LoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(next_url or "/")
    else:
        form = LoginForm(request)
    return render(
        request,
        "citations/home.html",
        {"login_form": form, "register_form": RegisterForm(), "show_login_modal": True},
    )


def register_view(request):
    """
    Handles user registration.

    On successful registration, the new user is automatically logged in and
    redirected to the URL specified in the 'next' parameter, or to the home
    page if 'next' is not provided.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object, either redirecting on successful registration
        or rendering the home page with the registration form and validation
        errors.
    """
    next_url = request.POST.get("next", request.GET.get("next", "/"))

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # ① Crear el usuario en la BD
            user = form.save()

            # ② Autenticarlo de nuevo con las credenciales recién creadas
            auth_user = authenticate(
                request,
                username=user.username,
                password=form.cleaned_data["password1"],
            )

            # ③ Iniciar sesión (login) con el backend correcto
            if auth_user is not None:
                login(request, auth_user)

            return redirect(next_url or "/")
    else:
        form = RegisterForm()

    return render(
        request,
        "citations/home.html",
        {
            "register_form": form,
            "login_form": LoginForm(),
            "show_register_modal": True,
        },
    )


# Logout
def logout_view(request):
    """
    Logs the user out.

    Redirects to the URL specified in the 'next' parameter, or to the home
    page if 'next' is not provided.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponseRedirect to the 'next' URL or the home page.
    """
    logout(request)
    return redirect(request.GET.get("next", "/"))


# Vista AJAX para guardar el reporte
def ajax_submit_citation(request):
    """
    Handles the submission of an incorrect citation report via AJAX.

    Args:
        request: The HttpRequest object.

    Returns:
        A JsonResponse indicating success or failure. On failure, it includes
        a dictionary of form errors.
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


# Página del reporte individual
def citation_detail(request, pk):
    """
    Displays the details of a single incorrect citation report.

    This view shows the information about the incorrect citation, its comments,
    and vote counts. It also handles the submission of new comments.

    Args:
        request: The HttpRequest object.
        pk (int): The primary key of the incorrect citation report.

    Returns:
        An HttpResponse object rendering the 'citation_detail.html' template.
    """
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    comments = (
        Comment.objects.filter(citation=citation)
        .select_related("author", "parent")
        .order_by("created_at")
    )
    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()

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

    return render(
        request,
        "citations/citation_detail.html",
        {
            "citation": citation,
            "comment_form": form,
            "comments": comments,
            "upvotes": upvotes,
            "downvotes": downvotes,
            "user_vote": user_vote,
            "is_saved": is_saved,
        },
    )


# Vista alternativa (usada antes)
def submit_incorrect_citation(request):
    """
    Handles the submission of an incorrect citation report (non-AJAX).

    This is an older view that renders a dedicated page for submitting a report.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object, either redirecting on success or rendering the
        'submit_citation.html' template with the form.
    """
    if request.method == "POST":
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            citation = form.save(commit=False)
            if request.user.is_authenticated:
                citation.author = request.user
            citation.save()
            return redirect("citation_submitted")
    else:
        form = IncorrectCitationForm()
    return render(request, "citations/submit_citation.html", {"form": form})


# Página de confirmación tras reporte
def citation_submitted(request):
    """
    Displays a confirmation page after a report has been submitted.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'citation_submitted.html'
        template.
    """
    return render(request, "citations/citation_submitted.html")


# Obtener metadatos del DOI
def get_all_metadata_from_doi(request):
    """
    Fetches all available metadata for a given DOI from the CrossRef API.

    Args:
        request: The HttpRequest object, containing the 'doi' GET parameter.

    Returns:
        A JsonResponse with the DOI's metadata if found, otherwise an error
        message.
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


@login_required
def delete_comment(request, pk):
    """
    Deletes a comment.

    Only the author of the comment or a superuser can delete it.

    Args:
        request: The HttpRequest object.
        pk (int): The primary key of the comment to be deleted.

    Returns:
        An HttpResponseRedirect to the detail page of the citation the
        comment belonged to, or an HttpResponseForbidden if the user is not
        authorized.
    """
    comment = get_object_or_404(Comment, pk=pk)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
        messages.success(request, "Comentario eliminado correctamente.")
    else:
        return HttpResponseForbidden("No tienes permiso para eliminar este comentario.")
    return redirect("citation_detail", pk=comment.citation.pk)


@require_POST
def vote_view(request):
    """
    Handles user votes on incorrect citation reports.

    A user can upvote (1) or downvote (-1). Voting again with the same value
    removes the vote. Voting with a different value changes the vote.

    Args:
        request: The HttpRequest object.

    Returns:
        A JsonResponse with the updated vote counts and the current user's
        vote status.
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

    # Busca si el usuario ya votó
    existing_vote = Vote.objects.filter(citation=citation, user=request.user).first()

    if existing_vote:
        if existing_vote.value == vote_value:
            existing_vote.delete()  # desmarcar voto
        else:
            existing_vote.value = vote_value
            existing_vote.save()
    else:
        Vote.objects.create(citation=citation, user=request.user, value=vote_value)

    # Conteos actualizados
    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()

    # Obtener el voto actual del usuario (puede ser None si lo borró)
    current_vote = Vote.objects.filter(citation=citation, user=request.user).first()
    user_vote = current_vote.value if current_vote else 0

    return JsonResponse(
        {
            "upvotes": upvotes,
            "downvotes": downvotes,
            "user_vote": user_vote,
        }
    )


@require_POST
@login_required
def toggle_saved(request):
    """
    Toggles the saved status of an incorrect citation report for the user.

    If the report is already saved, it will be unsaved, and vice-versa.

    Args:
        request: The HttpRequest object.

    Returns:
        A JsonResponse indicating the new saved status (`is_saved`).
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

    return JsonResponse({"is_saved": is_saved})


@login_required
def my_reports(request):
    """
    Displays a list of the current user's incorrect citation reports.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'my_reports.html' template.
    """
    reports = IncorrectCitation.objects.filter(author=request.user).order_by(
        "-created_at"
    )
    return render(request, "citations/my_reports.html", {"reports": reports})


@login_required
def my_comments(request):
    """
    Displays a list of the current user's comments.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'my_comments.html' template.
    """
    comments = (
        Comment.objects.filter(author=request.user)
        .select_related("citation")
        .order_by("-created_at")
    )
    return render(request, "citations/my_comments.html", {"comments": comments})


@login_required
def my_saved(request):
    """
    Displays a list of the current user's saved citation reports.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'my_saved.html' template.
    """
    saved = (
        SavedCitation.objects.filter(user=request.user)
        .select_related("citation")
        .order_by("-created_at")
    )
    return render(request, "citations/my_saved.html", {"saved": saved})


@require_POST
def register_ajax(request):
    """
    Handles user registration via AJAX.

    This view receives the registration form data via a POST request and
    returns a JSON response, which is useful for single-page applications or
    when registering from a modal without a full page reload.

    Args:
        request: The HttpRequest object.

    Returns:
        A JsonResponse indicating success or failure. On failure, it includes
        a dictionary of form errors.
    """
    form = RegisterForm(request.POST)
    if form.is_valid():
        user = form.save()
        auth_user = authenticate(
            request,
            username=user.username,
            password=form.cleaned_data["password1"],
        )
        if auth_user:
            login(request, auth_user)
        return JsonResponse({"success": True})

    errors = {field: errs.get_json_data() for field, errs in form.errors.items()}
    return JsonResponse({"success": False, "errors": errors}, status=400)


@login_required
def semantic_citations_view(request):
    """
    Displays citations for a given DOI from Semantic Scholar or Crossref.

    This view fetches the citations for a specified DOI, checks which of them
    have already been reported as incorrect in the database, and displays the
    list to the user.

    Args:
        request: The HttpRequest object.

    Returns:
        An HttpResponse object rendering the 'semantic_citations.html'
        template with the citation data.
    """
    doi = request.GET.get("doi")
    if not doi:
        return redirect("account_settings")

    # 🔹 Recuperar citas y conteo (usa Semantic Scholar, con fallback a Crossref)
    citation_count, citations, source = get_citations_with_fallback(doi)

    # 🔹 Obtener los DOIs de las citas recuperadas
    citing_dois = [c.get("doi") for c in citations if c.get("doi")]

    # 🔹 Comprobar cuáles ya están registrados como incorrectos
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

    return render(
        request,
        "citations/semantic_citations.html",
        {
            "doi": doi,
            "citation_count": citation_count,
            "citations": citations,
            "source": source,
        },
    )

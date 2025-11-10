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
    Muestra los artículos de un usuario obtenidos de DBLP.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de artículos.
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
    Sugiere citas incorrectas basadas en un término de búsqueda.

    Args:
        request (HttpRequest): La solicitud HTTP, que debe contener el parámetro 'term'.

    Returns:
        JsonResponse: Una lista de citas sugeridas en formato JSON.
    """
    term = request.GET.get("term", "")
    qs = IncorrectCitation.objects.filter(
        Q(doi_original__icontains=term) | Q(metadata__title__icontains=term)
    ).values("doi_original", "metadata__title")[:5]

    return JsonResponse(list(qs), safe=False)


def fetch_doi_metadata(request):
    """
    Obtiene los metadatos de un DOI desde CrossRef.

    Args:
        request (HttpRequest): La solicitud HTTP, que debe contener el parámetro 'doi'.

    Returns:
        JsonResponse: Los metadatos del DOI en formato JSON, o un error si no se encuentra.
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
    Muestra una lista paginada de citas incorrectas, con opciones de filtrado.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de citas.
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
    Gestiona la configuración de la cuenta de usuario, incluyendo el perfil, la contraseña y la URL de DBLP.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con los formularios de configuración.
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
    Renderiza la página de inicio.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la página de inicio.
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
    Gestiona el inicio de sesión de los usuarios.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: Redirige al usuario a la página siguiente o renderiza el formulario de inicio de sesión.
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
    Gestiona el registro de nuevos usuarios.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: Redirige al usuario a la página siguiente o renderiza el formulario de registro.
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
    Cierra la sesión del usuario.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: Redirige al usuario a la página anterior.
    """
    logout(request)
    return redirect(request.GET.get("next", "/"))


# Vista AJAX para guardar el reporte
def ajax_submit_citation(request):
    """
    Guarda un reporte de cita incorrecta enviado a través de AJAX.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        JsonResponse: Una respuesta JSON indicando si la operación fue exitosa.
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
    Muestra los detalles de un reporte de cita incorrecta, incluyendo comentarios y votos.

    Args:
        request (HttpRequest): La solicitud HTTP.
        pk (int): La clave primaria del reporte de cita incorrecta.

    Returns:
        HttpResponse: La respuesta HTTP con los detalles del reporte.
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
    Renderiza y procesa el formulario para reportar una cita incorrecta.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP, que puede ser el formulario o una redirección.
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
    Muestra una página de confirmación después de que un reporte ha sido enviado.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la página de confirmación.
    """
    return render(request, "citations/citation_submitted.html")


# Obtener metadatos del DOI
def get_all_metadata_from_doi(request):
    """
    Obtiene todos los metadatos de un DOI desde CrossRef.

    Args:
        request (HttpRequest): La solicitud HTTP, que debe contener el parámetro 'doi'.

    Returns:
        JsonResponse: Los metadatos del DOI en formato JSON, o un error si no se encuentra.
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
    Elimina un comentario si el usuario es el autor o un superusuario.

    Args:
        request (HttpRequest): La solicitud HTTP.
        pk (int): La clave primaria del comentario a eliminar.

    Returns:
        HttpResponse: Redirige a la página de detalles de la cita o devuelve un error de prohibido.
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
    Gestiona los votos (positivos y negativos) en los reportes de citas.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        JsonResponse: Una respuesta JSON con el recuento actualizado de votos.
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
    Guarda o elimina una cita de la lista de guardados de un usuario.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        JsonResponse: Una respuesta JSON indicando si la cita está ahora guardada.
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
    Muestra los reportes de citas incorrectas creados por el usuario actual.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de reportes del usuario.
    """
    reports = IncorrectCitation.objects.filter(author=request.user).order_by(
        "-created_at"
    )
    return render(request, "citations/my_reports.html", {"reports": reports})


@login_required
def my_comments(request):
    """
    Muestra los comentarios realizados por el usuario actual.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de comentarios del usuario.
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
    Muestra las citas guardadas por el usuario actual.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de citas guardadas del usuario.
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
    Gestiona el registro de usuarios a través de una solicitud AJAX.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        JsonResponse: Una respuesta JSON que indica si el registro fue exitoso o devuelve los errores.
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
    Muestra las citas de un artículo obtenidas de Semantic Scholar, con fallback a Crossref.

    Args:
        request (HttpRequest): La solicitud HTTP, que debe contener el parámetro 'doi'.

    Returns:
        HttpResponse: La respuesta HTTP con la lista de citas.
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

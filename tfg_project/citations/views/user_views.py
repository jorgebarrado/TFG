"""Views related to user profiles and personalized content."""

from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from ..forms import CustomPasswordChangeForm, ProfileForm, UserProfileForm
from ..models import Comment, IncorrectCitation, SavedCitation, UserProfile
from django.shortcuts import get_object_or_404
from ..utils import check_doi_has_citations, get_articles_from_dblp


def user_profile(request, username):
    """
    Vista pública del perfil de usuario.
    Muestra información básica, redes sociales y estadísticas.
    """
    user_obj = get_object_or_404(get_user_model(), username=username)
    profile, _ = UserProfile.objects.get_or_create(user=user_obj)

    comments_count = user_obj.comment_set.count()
    votes_count = user_obj.vote_set.count()
    reports_count = IncorrectCitation.objects.filter(author=user_obj).count()

    context = {
        "profile_user": user_obj,
        "user_profile": profile,
        "comments_count": comments_count,
        "votes_count": votes_count,
        "reports_count": reports_count,
    }
    return render(request, "citations/user_profile.html", context)


@login_required
def account_settings(request):
    """
    Gestiona la configuración de la cuenta de usuario.
    """
    user = request.user
    profile_form = ProfileForm(instance=user)
    pwd_form = CustomPasswordChangeForm(user)
    userprofile, _ = UserProfile.objects.get_or_create(user=user)
    dblp_form = UserProfileForm(instance=userprofile)

    articles = []
    if userprofile.dblp_url:
        articles = get_articles_from_dblp(userprofile.dblp_url)

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
            dblp_form = UserProfileForm(request.POST, request.FILES, instance=userprofile)
            if dblp_form.is_valid():
                dblp_form.save()
                messages.success(request, "Ajustes de perfil actualizados.")
                return redirect("account_settings")

    context = {
        "profile_form": profile_form,
        "pwd_form": pwd_form,
        "dblp_form": dblp_form,
        "articles": articles,
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


@login_required
def dblp_articles_view(request):
    """
    Muestra los artículos de un usuario obtenidos de DBLP.
    """
    user = request.user
    profile = UserProfile.objects.get(user=user)
    all_articles = get_articles_from_dblp(profile.dblp_url) if profile.dblp_url else []

    tipo = request.GET.get("tipo", "").strip()
    busqueda = request.GET.get("q", "").strip().lower()
    tipos_disponibles = sorted(set(a["type"] for a in all_articles))

    articles = all_articles
    if tipo:
        articles = [a for a in articles if a["type"] == tipo]
    if busqueda:
        articles = [a for a in articles if busqueda in a["title"].lower()]

    paginator = Paginator(articles, 10)
    page_number = request.GET.get("page")
    page = paginator.get_page(page_number)

    for article in page:
        if article.get("doi"):
            article["has_citations"] = check_doi_has_citations(article["doi"])
        else:
            article["has_citations"] = False

    context = {
        "articles": page,
        "dblp_url": profile.dblp_url,
        "tipo_actual": tipo,
        "tipos_disponibles": tipos_disponibles,
        "busqueda": busqueda,
    }
    return render(request, "citations/dblp_articles.html", context)

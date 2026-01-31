"""Views related to user profiles and personalized content."""

from itertools import chain

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
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
from ..utils import check_doi_has_citations, get_articles_from_dblp

User = get_user_model()


def get_avatar_initial(user):
    """Obtiene la inicial del avatar del usuario (username o first_name)."""
    if getattr(user, "username", ""):
        return user.username[0].upper()
    if getattr(user, "first_name", ""):
        return user.first_name[0].upper()
    return "?"


def profile_view(request, username):
    """
    Vista pública del perfil de un usuario.
    Muestra sus reportes recientes y detalles del perfil.
    """
    profile_user = get_object_or_404(User, username=username)
    profile, _ = UserProfile.objects.get_or_create(user=profile_user)

    latest_reports = (
        IncorrectCitation.objects.filter(author=profile_user)
        .order_by("-created_at")[:5]
    )

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
    """
    Vista para editar la configuración de la cuenta y el perfil del usuario.
    Permite cambiar contraseña, información básica y extendida.
    """
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


@login_required
def my_profile(request):
    """
    Vista del perfil privado del usuario ("Mi Perfil").
    Muestra estadísticas y actividad reciente.
    """
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
    activities = []

    for r in reports_qs:
        activities.append(
            {
                "type": "report",
                "created_at": r.created_at,
                "text": f"Creó el reporte “{r.doi_original}”",
                "citation": r,
            }
        )

    for c in comments_qs:
        activities.append(
            {
                "type": "comment",
                "created_at": c.created_at,
                "text": f"Comentó en “{c.citation.doi_original}”",
                "citation": c.citation,
            }
        )

    for s in saved_qs:
        activities.append(
            {
                "type": "saved",
                "created_at": s.created_at,
                "text": f"Guardó el reporte “{s.citation.doi_original}”",
                "citation": s.citation,
            }
        )

    for v in votes_qs:
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
        "comments_list": comments_qs.select_related("citation").order_by("-created_at")[:20],
        "saved_list": saved_qs.select_related("citation").order_by("-created_at")[:20],
        "votes_list": votes_qs.select_related("citation").order_by("citation__created_at")[:20],
        "avatar_initial": get_avatar_initial(user),
    }

    return render(request, "citations/profile.html", context)

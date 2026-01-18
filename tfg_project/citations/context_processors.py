"""Procesadores de contexto para templates."""

from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """
    Inyecta los formularios de login y registro en todas las vistas.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """
    Inyecta el conteo y las últimas notificaciones del usuario logueado.
    """
    if not request.user.is_authenticated:
        return {
            "notifications_unread_count": 0,
            "notifications_latest": [],
        }

    latest = (
        Notification.objects.filter(user=request.user)
        .only("id", "title", "message", "url", "is_read", "created_at")
        .order_by("-created_at")[:5]
    )
    unread_count = Notification.objects.filter(
        user=request.user,
        is_read=False,
    ).count()

    return {
        "notifications_unread_count": unread_count,
        "notifications_latest": latest,
    }

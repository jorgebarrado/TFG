"""Procesadores de contexto para la aplicación citations."""

from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """Añade formularios de login y registro al contexto de la plantilla.

    Permite que los modales de login y registro estén disponibles en todas
    las páginas.

    Args:
        request: La solicitud HTTP actual.

    Returns:
        dict: Diccionario con 'login_form' y 'register_form'.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """Añade contadores y lista de notificaciones recientes al contexto.

    Si el usuario está autenticado, recupera sus notificaciones no leídas
    y las 5 más recientes.

    Args:
        request: La solicitud HTTP actual.

    Returns:
        dict: Datos de notificaciones ('notifications_unread_count', 'notifications_latest').
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

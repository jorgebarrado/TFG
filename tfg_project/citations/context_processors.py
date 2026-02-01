from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """
    Context processor para añadir formularios de login y registro a todas las plantillas.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        dict: Diccionario con los formularios de login y registro.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """
    Context processor para añadir notificaciones no leídas y recientes a todas las plantillas.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        dict: Diccionario con el conteo de no leídas y las últimas notificaciones.
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

from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """
    Agrega los formularios de inicio de sesión y registro al contexto de todas las plantillas.

    Args:
        request: HttpRequest.

    Returns:
        dict: Diccionario con las instancias de los formularios.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """
    Agrega información sobre notificaciones no leídas y recientes al contexto global.

    Args:
        request: HttpRequest.

    Returns:
        dict: Conteo de no leídas y lista de las últimas 5 notificaciones.
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

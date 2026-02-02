from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """Agrega los formularios de login y registro al contexto global.

    Args:
        request: Objeto HttpRequest.

    Returns:
        dict: Contexto con 'login_form' y 'register_form'.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """Agrega notificaciones no leídas y recientes al contexto.

    Permite mostrar el contador de notificaciones en la barra de navegación.

    Args:
        request: Objeto HttpRequest.

    Returns:
        dict: Contexto con 'notifications_unread_count' y 'notifications_latest'.
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

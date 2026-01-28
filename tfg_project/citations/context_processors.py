from .forms import LoginForm, RegisterForm
from .models import Notification


def login_register_forms(request):
    """
    Processor de contexto para inyectar los formularios de login y registro en todas las plantillas.

    Args:
        request: El objeto HttpRequest actual.

    Returns:
        dict: Un diccionario con instancias de `LoginForm` y `RegisterForm`.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }


def notifications_context(request):
    """
    Processor de contexto para inyectar notificaciones del usuario en todas las plantillas.

    Proporciona el conteo de notificaciones no leídas y una lista de las últimas 5 notificaciones.
    Si el usuario no está autenticado, devuelve valores vacíos.

    Args:
        request: El objeto HttpRequest actual.

    Returns:
        dict: Diccionario con 'notifications_unread_count' y 'notifications_latest'.
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

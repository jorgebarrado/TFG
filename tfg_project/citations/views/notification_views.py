from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import Notification


@login_required
def notification_list(request):
    """Muestra la lista de notificaciones del usuario.

    Ordena las notificaciones por fecha de creación descendente.

    Args:
        request: El objeto HttpRequest de Django. Requiere autenticación.

    Returns:
        HttpResponse: La página con la lista de notificaciones renderizada.
    """
    notifications = Notification.objects.filter(user=request.user).order_by(
        "-created_at"
    )
    return render(
        request,
        "notifications/list.html",
        {"notifications": notifications},
    )


@login_required
@require_POST
def mark_all_read(request):
    """Marca todas las notificaciones del usuario como leídas.

    Args:
        request: El objeto HttpRequest de Django. Requiere POST y autenticación.

    Returns:
        HttpResponseRedirect: Redirección a la lista de notificaciones.
    """
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("notifications_list")


@login_required
def notification_read(request, pk):
    """Marca una notificación individual como leída y redirige a su destino.

    Si la notificación tiene una URL asociada, redirige allí. De lo contrario,
    redirige a la lista de notificaciones.

    Args:
        request: El objeto HttpRequest de Django. Requiere autenticación.
        pk (int): ID de la notificación.

    Returns:
        HttpResponseRedirect: Redirección al destino de la notificación o lista.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    if notification.url:
        return redirect(notification.url)
    return redirect("notifications_list")

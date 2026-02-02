from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import Notification


@login_required
def notification_list(request):
    """Muestra la lista de notificaciones del usuario.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponse: Renderiza la plantilla 'notifications/list.html'.
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
    """Marca todas las notificaciones no leídas del usuario como leídas.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponseRedirect: Redirige a la lista de notificaciones.
    """
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("notifications_list")


@login_required
def notification_read(request, pk):
    """Marca una notificación específica como leída y redirige a su URL asociada.

    Args:
        request: Objeto HttpRequest.
        pk (int): ID de la notificación.

    Returns:
        HttpResponseRedirect: Redirige a la URL de la notificación o a la lista si no tiene URL.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    if notification.url:
        return redirect(notification.url)
    return redirect("notifications_list")

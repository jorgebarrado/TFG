from django.urls import reverse

from ..models import Notification


def notify(*, user, notification_type, title, message, url="", actor=None):
    """
    Crea una nueva notificación para un usuario.

    Evita crear notificaciones si el actor es el mismo usuario (auto-notificación).

    Args:
        user (User): El usuario destinatario de la notificación.
        notification_type (str): El tipo de notificación (e.g., 'NEW_COMMENT').
        title (str): Título de la notificación.
        message (str): Cuerpo del mensaje.
        url (str, optional): Enlace relacionado. Por defecto es "".
        actor (User, optional): El usuario que generó el evento. Por defecto es None.

    Returns:
        Notification | None: La notificación creada o None si no se creó.
    """
    if user is None:
        return None
    if actor is not None and actor == user:
        return None

    return Notification.objects.create(
        user=user,
        actor=actor,
        notification_type=notification_type,
        title=title,
        message=message,
        url=url,
    )


def notify_new_comment(comment):
    """
    Genera una notificación cuando alguien comenta en un reporte.

    Verifica las preferencias de notificación del autor del reporte antes de enviar.

    Args:
        comment (Comment): El objeto comentario recién creado.

    Returns:
        Notification | None: La notificación creada o None.
    """
    report = comment.citation
    recipient = report.author
    if recipient is None:
        return None
    if comment.author is not None and comment.author == recipient:
        return None

    profile = getattr(recipient, "profile", None)
    if profile is not None and not profile.notify_comments_on_my_reports:
        return None

    actor_name = comment.author.username if comment.author else "Alguien"
    url = reverse("citation_detail", kwargs={"pk": report.pk})
    return notify(
        user=recipient,
        actor=comment.author,
        notification_type=Notification.NotificationType.NEW_COMMENT,
        title="Nuevo comentario",
        message=f"@{actor_name} comento en tu reporte.",
        url=url,
    )


def notify_new_vote(vote):
    """
    Genera una notificación cuando alguien vota en un reporte.

    Args:
        vote (Vote): El objeto voto recién creado.

    Returns:
        Notification | None: La notificación creada o None.
    """
    report = vote.citation
    recipient = report.author
    if recipient is None:
        return None
    if vote.user == recipient:
        return None

    profile = getattr(recipient, "profile", None)
    if profile is not None and not profile.notify_votes_on_my_reports:
        return None

    url = reverse("citation_detail", kwargs={"pk": report.pk})
    return notify(
        user=recipient,
        actor=vote.user,
        notification_type=Notification.NotificationType.NEW_VOTE,
        title="Nuevo voto",
        message=f"@{vote.user.username} voto tu reporte.",
        url=url,
    )


def notify_new_message(message):
    """
    Genera notificaciones para todos los participantes de una conversación (excepto el remitente)
    cuando se envía un nuevo mensaje.

    Args:
        message (Message): El mensaje enviado.

    Returns:
        List[Notification]: Lista de notificaciones enviadas.
    """
    conversation = message.conversation
    recipients = conversation.participants.exclude(id=message.sender_id)
    url = reverse("conversation_detail", kwargs={"conversation_id": conversation.id})

    notifications = []
    for recipient in recipients:
        notifications.append(
            notify(
                user=recipient,
                actor=message.sender,
                notification_type=Notification.NotificationType.NEW_MESSAGE,
                title="Nuevo mensaje",
                message=f"Tienes un nuevo mensaje de @{message.sender.username}.",
                url=url,
            )
        )

    return notifications

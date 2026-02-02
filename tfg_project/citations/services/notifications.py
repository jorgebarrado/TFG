from django.urls import reverse

from ..models import Notification


def notify(*, user, notification_type, title, message, url="", actor=None):
    """Crea una notificación para un usuario, evitando duplicados o auto-notificaciones.

    Args:
        user (User): El usuario destinatario.
        notification_type (str): Tipo de notificación (ver Notification.NotificationType).
        title (str): Título breve.
        message (str): Mensaje descriptivo.
        url (str, optional): Enlace relacionado. Defaults to "".
        actor (User, optional): Usuario que generó el evento. Defaults to None.

    Returns:
        Notification or None: La instancia creada o None si no se notificó.
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
    """Notifica al autor de un reporte sobre un nuevo comentario.

    Verifica las preferencias del usuario y evita notificar al propio autor del comentario.

    Args:
        comment (Comment): El comentario recién creado.

    Returns:
        Notification or None: La notificación creada o None.
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
    """Notifica al autor de un reporte sobre un nuevo voto.

    Verifica las preferencias del usuario y evita notificar al propio votante.

    Args:
        vote (Vote): El voto registrado.

    Returns:
        Notification or None: La notificación creada o None.
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
    """Notifica a los participantes de una conversación sobre un nuevo mensaje.

    Envía notificaciones a todos los participantes excepto al remitente.

    Args:
        message (Message): El mensaje enviado.

    Returns:
        list: Lista de notificaciones creadas.
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

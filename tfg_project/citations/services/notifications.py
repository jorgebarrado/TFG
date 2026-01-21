from django.urls import reverse

from ..models import Notification


def notify(*, user, notification_type, title, message, url="", actor=None):
    """
    Crea una notificación para un usuario, verificando condiciones básicas.
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
    Envía una notificación al autor del reporte cuando recibe un nuevo comentario.
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
    Envía una notificación al autor del reporte cuando recibe un nuevo voto.
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
    Envía notificaciones a los participantes de una conversación cuando hay un nuevo mensaje.
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

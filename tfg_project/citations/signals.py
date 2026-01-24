from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Comment, Message, UserProfile, Vote
from .services.notifications import (
    notify_new_comment,
    notify_new_message,
    notify_new_vote,
)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Crea un UserProfile automáticamente cuando se crea un nuevo User.

    Args:
        sender: Modelo User.
        instance (User): La instancia del usuario creado.
        created (bool): Si es una nueva creación.
        **kwargs: Otros argumentos de la señal.
    """
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Guarda el UserProfile asociado cuando se guarda el User.

    Args:
        sender: Modelo User.
        instance (User): La instancia del usuario.
        **kwargs: Otros argumentos de la señal.
    """
    if hasattr(instance, "profile"):
        instance.profile.save()


@receiver(post_save, sender=Comment)
def comment_notification(sender, instance, created, **kwargs):
    """Genera una notificación cuando se crea un nuevo comentario.

    Args:
        sender: Modelo Comment.
        instance (Comment): El comentario creado.
        created (bool): Si es una nueva creación.
        **kwargs: Otros argumentos de la señal.
    """
    if not created:
        return
    notify_new_comment(instance)


@receiver(post_save, sender=Vote)
def vote_notification(sender, instance, created, **kwargs):
    """Genera una notificación cuando se emite un nuevo voto.

    Args:
        sender: Modelo Vote.
        instance (Vote): El voto creado.
        created (bool): Si es una nueva creación.
        **kwargs: Otros argumentos de la señal.
    """
    if not created:
        return
    notify_new_vote(instance)


@receiver(post_save, sender=Message)
def message_notification(sender, instance, created, **kwargs):
    """Genera notificaciones cuando se envía un nuevo mensaje en una conversación.

    Args:
        sender: Modelo Message.
        instance (Message): El mensaje enviado.
        created (bool): Si es una nueva creación.
        **kwargs: Otros argumentos de la señal.
    """
    if not created:
        return
    notify_new_message(instance)

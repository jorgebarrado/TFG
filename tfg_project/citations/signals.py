"""Señales y receptores para la aplicación citations."""

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
    """Crea un UserProfile automáticamente cuando se crea un User.

    Args:
        sender (Type[User]): La clase del modelo que envía la señal.
        instance (User): La instancia del usuario creado.
        created (bool): Indica si se acaba de crear el registro.
        **kwargs: Argumentos adicionales de la señal.
    """
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Guarda el UserProfile asociado cuando se guarda un User.

    Args:
        sender (Type[User]): La clase del modelo que envía la señal.
        instance (User): La instancia del usuario guardado.
        **kwargs: Argumentos adicionales de la señal.
    """
    if hasattr(instance, "profile"):
        instance.profile.save()


@receiver(post_save, sender=Comment)
def comment_notification(sender, instance, created, **kwargs):
    """Genera una notificación cuando se crea un nuevo comentario.

    Args:
        sender (Type[Comment]): La clase del modelo Comment.
        instance (Comment): El comentario creado.
        created (bool): Indica si es una nueva creación.
        **kwargs: Argumentos adicionales.
    """
    if not created:
        return
    notify_new_comment(instance)


@receiver(post_save, sender=Vote)
def vote_notification(sender, instance, created, **kwargs):
    """Genera una notificación cuando se recibe un nuevo voto.

    Args:
        sender (Type[Vote]): La clase del modelo Vote.
        instance (Vote): El voto registrado.
        created (bool): Indica si es un nuevo voto.
        **kwargs: Argumentos adicionales.
    """
    if not created:
        return
    notify_new_vote(instance)


@receiver(post_save, sender=Message)
def message_notification(sender, instance, created, **kwargs):
    """Genera una notificación cuando se envía un nuevo mensaje.

    Args:
        sender (Type[Message]): La clase del modelo Message.
        instance (Message): El mensaje enviado.
        created (bool): Indica si es un nuevo mensaje.
        **kwargs: Argumentos adicionales.
    """
    if not created:
        return
    notify_new_message(instance)

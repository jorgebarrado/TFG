"""Señales (signals) para la gestión de eventos y notificaciones."""

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
    """Crea un perfil de usuario automáticamente al crear un usuario."""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Guarda el perfil de usuario cuando se guarda el usuario."""
    if hasattr(instance, "profile"):
        instance.profile.save()


@receiver(post_save, sender=Comment)
def comment_notification(sender, instance, created, **kwargs):
    """Envía notificación al crear un nuevo comentario."""
    if not created:
        return
    notify_new_comment(instance)


@receiver(post_save, sender=Vote)
def vote_notification(sender, instance, created, **kwargs):
    """Envía notificación al registrar un nuevo voto."""
    if not created:
        return
    notify_new_vote(instance)


@receiver(post_save, sender=Message)
def message_notification(sender, instance, created, **kwargs):
    """Envía notificación al recibir un nuevo mensaje privado."""
    if not created:
        return
    notify_new_message(instance)

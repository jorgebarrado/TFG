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
    """Crea un UserProfile automáticamente cuando se crea un usuario."""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Guarda el perfil asociado cuando se guarda el usuario."""
    if hasattr(instance, "profile"):
        instance.profile.save()


@receiver(post_save, sender=Comment)
def comment_notification(sender, instance, created, **kwargs):
    """Envía notificación al autor del reporte cuando se crea un comentario."""
    if not created:
        return
    notify_new_comment(instance)


@receiver(post_save, sender=Vote)
def vote_notification(sender, instance, created, **kwargs):
    """Envía notificación al autor del reporte cuando se recibe un voto."""
    if not created:
        return
    notify_new_vote(instance)


@receiver(post_save, sender=Message)
def message_notification(sender, instance, created, **kwargs):
    """Envía notificaciones a los participantes cuando hay un nuevo mensaje."""
    if not created:
        return
    notify_new_message(instance)

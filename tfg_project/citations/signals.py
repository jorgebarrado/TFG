from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Creates a UserProfile instance when a new User is created.

    This signal handler is connected to the `post_save` signal of the User
    model. It checks if a new user has been created and, if so, creates a
    corresponding UserProfile.

    Args:
        sender: The model class that sent the signal (User).
        instance: The actual instance of the User that was saved.
        created (bool): A boolean indicating whether a new record was created.
        **kwargs: Additional keyword arguments.
    """
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    Saves the UserProfile instance whenever the User is saved.

    This signal handler is connected to the `post_save` signal of the User
    model. It ensures that the associated UserProfile is also saved.

    Args:
        sender: The model class that sent the signal (User).
        instance: The actual instance of the User that was saved.
        **kwargs: Additional keyword arguments.
    """
    instance.userprofile.save()

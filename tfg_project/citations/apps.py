from django.apps import AppConfig


class CitationsConfig(AppConfig):
    """
    Configuration for the citations Django app.

    This class defines the configuration for the 'citations' app, including
    the default auto field for models and the app's name.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

from django.apps import AppConfig


class CitationsConfig(AppConfig):
    """
    Configuración de la aplicación 'citations'.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

    def ready(self):
        """Inicialización de la aplicación (ej. importación de señales)."""
        from . import signals  # noqa: F401

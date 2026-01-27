from django.apps import AppConfig


class CitationsConfig(AppConfig):
    """Configuración de la aplicación Citations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

    def ready(self):
        """Inicializa la aplicación y registra las señales."""
        from . import signals  # noqa: F401

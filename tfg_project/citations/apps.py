from django.apps import AppConfig


class CitationsConfig(AppConfig):
    """
    Configuración de la aplicación 'citations'.
    """
    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

    def ready(self):
        """
        Método llamado cuando la aplicación está lista.
        Importa las señales para asegurar que se registren.
        """
        from . import signals  # noqa: F401

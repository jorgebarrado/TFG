"""Configuración de la aplicación citations."""

from django.apps import AppConfig


class CitationsConfig(AppConfig):
    """Configuración principal de la aplicación citations.

    Define el campo auto incremental por defecto y el nombre de la aplicación.
    También importa las señales cuando la aplicación está lista.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

    def ready(self):
        """Método llamado cuando la aplicación está lista.

        Importa el módulo de señales para asegurar que los receptores se registren.
        """
        from . import signals  # noqa: F401

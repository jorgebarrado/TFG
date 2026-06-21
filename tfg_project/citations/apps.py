# Configuración de la app citations: nombre, campo auto y carga de señales al arrancar Django.
from django.apps import AppConfig


class CitationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "citations"

    def ready(self):
        from . import signals  # noqa: F401

"""Módulo para el registro de trazas de ejecución en la aplicación."""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from django.http import HttpRequest

logger = logging.getLogger("citations.context")


class TraceLogger:
    """Recopila y registra trazas detalladas para una solicitud HTTP.

    Permite monitorizar el rendimiento y el flujo de ejecución de una petición,
    almacenando tiempos y estados de cada paso.
    """

    def __init__(self, request: HttpRequest):
        """Inicializa el logger de trazas.

        Args:
            request (HttpRequest): La solicitud HTTP actual.
        """
        self.request = request
        self.steps: List[Dict[str, Any]] = []
        self.start_time = time.monotonic()
        self.trace_data: Dict[str, Any] = {
            "user_id": request.user.id
            if request.user.is_authenticated
            else "anonymous",
            "steps": self.steps,
        }

    def add_step(self, step_name: str, status: str, details: Optional[str] = None):
        """Añade un paso a la traza actual.

        Registra el tiempo transcurrido desde el inicio de la solicitud hasta
        este paso.

        Args:
            step_name (str): El nombre identificativo del paso.
            status (str): El estado del paso (ej. 'ok', 'miss', 'error').
            details (Optional[str], optional): Detalles adicionales sobre el paso.
        """
        elapsed_ms = (time.monotonic() - self.start_time) * 1000
        self.steps.append(
            {
                "step": step_name,
                "status": status,
                "detail": details,
                "ms": round(elapsed_ms),
            }
        )

    def log(self):
        """Escribe la traza acumulada en el log del sistema.

        Solo registra si la variable de entorno LOG_CITATIONS está activa (valor '1').
        """
        if os.getenv("LOG_CITATIONS", "1") == "1":
            logger.info(self.trace_data)

    def get_trace(self) -> Dict[str, Any]:
        """Devuelve los datos de la traza acumulados hasta el momento.

        Returns:
            Dict[str, Any]: Diccionario con el ID de usuario y la lista de pasos.
        """
        return self.trace_data

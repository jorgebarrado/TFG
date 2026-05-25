import logging
import os
import time
from typing import Any, Dict, List, Optional

from django.http import HttpRequest

logger = logging.getLogger("citations.context")


class TraceLogger:
    """
    Recopila y registra trazas detalladas para una solicitud.
    """

    def __init__(self, request: HttpRequest):
        """
        Inicializa el logger de trazas.

        Args:
            request (HttpRequest): La solicitud HTTP.
        """
        self.request = request
        self.steps: List[Dict[str, Any]] = []
        self.start_time = time.monotonic()
        self.trace_data: Dict[str, Any] = {
            "user_id": (
                request.user.id if request.user.is_authenticated else "anonymous"
            ),
            "steps": self.steps,
        }

    def add_step(self, step_name: str, status: str, details: Optional[str] = None):
        """
        Añade un paso a la traza.

        Args:
            step_name (str): El nombre del paso.
            status (str): El estado del paso ('ok', 'miss', 'error').
            details (Optional[str], optional): Detalles adicionales. Defaults to None.
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
        """
        Escribe la traza en el log si el logging está habilitado.
        """
        if os.getenv("LOG_CITATIONS", "1") == "1":
            logger.info(self.trace_data)

    def get_trace(self) -> Dict[str, Any]:
        """
        Devuelve la traza de datos.

        Returns:
            Dict[str, Any]: La traza de datos.
        """
        return self.trace_data

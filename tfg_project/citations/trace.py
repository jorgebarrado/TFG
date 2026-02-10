from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone


class Trace:
    """Clase para recolectar y estructurar trazas de ejecución (tracing) para logs y depuración.

    Almacena una secuencia de pasos con tiempos y metadatos, y permite exportarla como JSON.
    Útil para el endpoint `get_citation_context`.

    Attributes:
        cid (str): Correlation ID único para esta traza.
        steps (list[dict]): Lista de pasos registrados.
        started (float): Timestamp de inicio (perf_counter).
        ts (str): Timestamp ISO de creación.
        citing_doi (str): DOI del artículo citante.
        target (dict): Metadatos del artículo objetivo (citado).
        pdf_url (str, optional): URL del PDF procesado.
        pdf_size (int, optional): Tamaño en bytes del PDF.
        hit_count (int): Número de coincidencias encontradas.
        error (str, optional): Mensaje de error si ocurrió alguno.
    """

    def __init__(self, citing_doi: str = "", target: dict | None = None):
        """Inicializa una nueva traza.

        Args:
            citing_doi (str, optional): DOI del artículo que cita.
            target (dict | None, optional): Diccionario con datos del objetivo (doi, title, etc.).
        """
        self.cid = uuid.uuid4().hex
        self.steps: list[dict] = []
        self.started = time.perf_counter()
        self.ts = datetime.now(timezone.utc).isoformat()
        self.citing_doi = citing_doi or ""
        target = target or {}
        self.target = {
            "doi": target.get("doi") or "",
            "title": target.get("title") or "",
            "first_author": target.get("first_author") or "",
            "year": target.get("year") or "",
        }
        self.pdf_url = None
        self.pdf_size = None
        self.hit_count = 0
        self.error = None

    def add(self, step: str, status: str, detail: str = ""):
        """Registra un nuevo paso en la traza.

        Calcula automáticamente el tiempo transcurrido desde el inicio.

        Args:
            step (str): Nombre del paso (e.g., 'download', 'extract').
            status (str): Estado del paso ('ok', 'error', 'miss').
            detail (str, optional): Información adicional.
        """
        self.steps.append(
            {
                "step": step,
                "status": status,
                "detail": detail,
                "ms": int((time.perf_counter() - self.started) * 1000),
            }
        )

    def as_log_line(self, level: str = "INFO") -> str:
        """Genera una cadena JSON con toda la información de la traza para el log.

        Args:
            level (str, optional): Nivel de log. Por defecto "INFO".

        Returns:
            str: JSON string.
        """
        payload = {
            "ts": self.ts,
            "level": level,
            "logger": "citations.context",
            "cid": self.cid,
            "citing_doi": self.citing_doi,
            "target_doi": self.target["doi"],
            "target_title": self.target["title"],
            "target_first_author": self.target["first_author"],
            "target_year": self.target["year"],
            "steps": self.steps,
            "pdf_url": self.pdf_url,
            "pdf_size": self.pdf_size,
            "hit_count": self.hit_count,
            "error": self.error,
        }
        return json.dumps(payload, ensure_ascii=False)

    def as_public_trace(self) -> list[dict]:
        """Devuelve la lista de pasos para exponer públicamente (e.g., en modo debug).

        Returns:
            list[dict]: Lista de pasos.
        """
        # Para devolver al cliente si debug=1
        return self.steps.copy()

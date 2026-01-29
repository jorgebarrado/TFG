from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone


class Trace:
    """Recolecta pasos de ejecución y construye un log JSON estructurado.

    Se utiliza para monitorizar el proceso de extracción de contextos de citas,
    registrando tiempos, éxitos y errores en cada paso.
    """

    def __init__(self, citing_doi: str = "", target: dict | None = None):
        """Inicializa una nueva traza.

        Args:
            citing_doi (str): DOI del artículo que cita.
            target (dict, optional): Datos del artículo objetivo (citado).
                Puede contener keys 'doi', 'title', 'first_author', 'year'.
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
        """Añade un paso a la traza.

        Args:
            step (str): Nombre del paso (ej. 'openaccess', 'download').
            status (str): Estado del paso (ej. 'ok', 'error').
            detail (str): Información adicional o mensaje de error.
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
        """Devuelve la traza completa como una cadena JSON para logging.

        Args:
            level (str): Nivel de log (por defecto 'INFO').

        Returns:
            str: JSON string con toda la información de la traza.
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
        """Devuelve una versión pública de los pasos para depuración en cliente.

        Returns:
            list[dict]: Lista de pasos ejecutados.
        """
        # Para devolver al cliente si debug=1
        return self.steps.copy()

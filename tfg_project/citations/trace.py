from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone


class Trace:
    """Recolecta pasos ordenados y construye el JSON final para log.

    Utilizado para trazabilidad detallada de la extracción de contextos de cita.
    """

    def __init__(self, citing_doi: str = "", target: dict | None = None):
        """Inicializa una nueva traza.

        Args:
            citing_doi (str): DOI del artículo citador.
            target (dict, optional): Datos del artículo objetivo (citado).
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
        """Registra un paso en el proceso.

        Args:
            step (str): Nombre del paso (p.ej. 'download').
            status (str): Estado del paso ('ok', 'error', 'miss').
            detail (str, optional): Detalles adicionales.
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
        """Genera una cadena JSON para escribir en el log.

        Args:
            level (str, optional): Nivel de log ('INFO', 'ERROR'). Defaults to "INFO".

        Returns:
            str: Cadena JSON con toda la información de la traza.
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
        """Devuelve la lista de pasos para exponer públicamente (modo debug).

        Returns:
            list: Lista de diccionarios con los pasos ejecutados.
        """
        # Para devolver al cliente si debug=1
        return self.steps.copy()

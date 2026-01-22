from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone


class Trace:
    """
    Clase para recolectar y estructurar trazas de ejecución de operaciones complejas.
    Útil para debugging y auditoría de procesos largos como extracciones de PDF.

    Attributes:
        cid (str): ID único de correlación.
        steps (list[dict]): Lista de pasos ejecutados.
        started (float): Tiempo de inicio en segundos.
        ts (str): Timestamp ISO del inicio.
        citing_doi (str): DOI del artículo citante.
        target (dict): Información del artículo objetivo.
    """

    def __init__(self, citing_doi: str = "", target: dict | None = None):
        """
        Inicializa una nueva traza.

        Args:
            citing_doi (str): DOI del artículo que cita.
            target (dict | None): Diccionario con datos del artículo citado (doi, title, etc.).
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
        """
        Registra un paso en la traza.

        Args:
            step (str): Nombre del paso.
            status (str): Estado del paso ('ok', 'error', 'miss').
            detail (str): Detalles adicionales.
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
        """
        Genera una representación JSON de la traza para el log del sistema.

        Args:
            level (str): Nivel de log.

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
        """
        Devuelve la lista de pasos para ser consumida por el cliente (frontend).

        Returns:
            list[dict]: Lista de pasos.
        """
        return self.steps.copy()

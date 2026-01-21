from __future__ import annotations
import json
import time
import uuid
from datetime import datetime, timezone


class Trace:
    """
    Recolecta pasos ordenados y construye el JSON final para log.
    """

    def __init__(self, citing_doi: str = "", target: dict | None = None):
        """Inicializa el objeto de traza con metadatos básicos."""
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
        """Agrega un paso a la traza con tiempo de ejecución."""
        self.steps.append(
            {
                "step": step,
                "status": status,
                "detail": detail,
                "ms": int((time.perf_counter() - self.started) * 1000),
            }
        )

    def as_log_line(self, level: str = "INFO") -> str:
        """Devuelve la traza completa como una cadena JSON para logging."""
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
        """Devuelve la lista de pasos para exponer al cliente (debug mode)."""
        # Para devolver al cliente si debug=1
        return self.steps.copy()

from __future__ import annotations
from typing import List

# Detecta si está instalado; tú has dicho que NO, así que esto quedará False
try:
    import papermage  # noqa: F401

    PM_AVAILABLE = True
except Exception:
    PM_AVAILABLE = False


def pm_extract_paragraphs(pdf_path: str) -> List[str]:
    """
    Stub: aún no integrado. Como NO quieres fallback fuera de AUTO, lanzamos error aquí.
    """
    if not PM_AVAILABLE:
        raise RuntimeError(
            "PaperMage no está disponible en este entorno (no instalado)."
        )
    raise NotImplementedError(
        "PaperMage instalado, pero pipeline no integrado todavía."
    )

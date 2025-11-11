from __future__ import annotations
from typing import List, Dict, Any, Tuple

# ---- Declaraciones de disponibilidad e import seguro ----
try:
    from .papermage_extractor import pm_extract_paragraphs, PM_AVAILABLE
except Exception:
    PM_AVAILABLE = False
    pm_extract_paragraphs = None  # type: ignore

try:
    from .papercraft_extractor import pc_extract_paragraphs, PC_AVAILABLE
except Exception:
    PC_AVAILABLE = False
    pc_extract_paragraphs = None  # type: ignore

from .generic_extractor import generic_extract_paragraphs  # siempre disponible

EngineAttempt = Dict[str, Any]

def _attempt(name: str, available: bool, fn, pdf_path: str) -> Tuple[List[str], EngineAttempt, str | None]:
    """
    Ejecuta un motor y devuelve:
      (paragraphs, attempt_info, error_message)
    """
    att: EngineAttempt = {
        "name": name,
        "available": bool(available and fn),
        "attempted": False,
        "ok": False,
        "error": None,
        "count": 0,
    }
    if not att["available"]:
        # No disponible: no se intenta
        return [], att, f"{name} not available"

    try:
        att["attempted"] = True
        paras = fn(pdf_path) or []
        att["ok"] = bool(paras)
        att["count"] = len(paras)
        if not paras:
            return [], att, f"{name} returned no paragraphs"
        return paras, att, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        att["error"] = msg
        return [], att, msg

def run_engine(engine_requested: str, pdf_path: str) -> Tuple[str | None, List[str], List[EngineAttempt], str | None]:
    """
    Política:
      - 'papermage' -> solo papermage; si falla o no está, ERROR (no fallback genérico).
      - 'papercraft' -> solo papercraft; si falla o no está, ERROR.
      - 'auto' -> intenta papermage, luego papercraft, y por último generic (fallback).
    Retorna: (engine_used, paragraphs, attempts, error_message)
    """
    engine = (engine_requested or "auto").lower().strip()
    attempts: List[EngineAttempt] = []

    if engine == "papermage":
        paras, att, err = _attempt("papermage", PM_AVAILABLE, pm_extract_paragraphs, pdf_path)
        attempts.append(att)
        if err:
            return None, [], attempts, err
        return "papermage", paras, attempts, None

    if engine == "papercraft":
        paras, att, err = _attempt("papercraft", PC_AVAILABLE, pc_extract_paragraphs, pdf_path)
        attempts.append(att)
        if err:
            return None, [], attempts, err
        return "papercraft", paras, attempts, None

    # AUTO
    # 1) PaperMage
    paras, att, err = _attempt("papermage", PM_AVAILABLE, pm_extract_paragraphs, pdf_path)
    attempts.append(att)
    if not err:
        return "papermage", paras, attempts, None

    # 2) PaperCraft
    paras, att, err2 = _attempt("papercraft", PC_AVAILABLE, pc_extract_paragraphs, pdf_path)
    attempts.append(att)
    if not err2:
        return "papercraft", paras, attempts, None

    # 3) Generic (siempre)
    paras, att, err3 = _attempt("generic", True, generic_extract_paragraphs, pdf_path)
    attempts.append(att)
    # Generic no debería errar; si viniera vacío, es lo que hay
    return "generic", paras, attempts, None

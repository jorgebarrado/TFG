from __future__ import annotations

from typing import Any, Dict, List, Tuple

# ---- Declaraciones de disponibilidad e import seguro ----
try:
    from .papermage_extractor import (
        PM_AVAILABLE,
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
    )
except Exception:
    PM_AVAILABLE = False
    pm_extract_paragraphs = None  # type: ignore
    pm_extract_paragraphs_with_positions = None  # type: ignore


EngineAttempt = Dict[str, Any]

ENGINE_LABELS = {
    "papermage": "PaperMage",
}

ALLOWED_ENGINES = set(ENGINE_LABELS.keys())


def list_extractor_engines() -> List[Dict[str, Any]]:
    return [
        {
            "key": "papermage",
            "label": ENGINE_LABELS["papermage"],
            "available": PM_AVAILABLE,
        },
    ]


def _attempt(
    name: str, available: bool, fn, fn_with_positions, pdf_path: str
) -> Tuple[List[str], List[dict], EngineAttempt, str | None]:
    """
    Ejecuta un motor y devuelve:
      (paragraphs, paragraphs_with_positions, attempt_info, error_message)
    """
    att: EngineAttempt = {
        "name": name,
        "available": bool(available and (fn or fn_with_positions)),
        "attempted": False,
        "ok": False,
        "error": None,
        "count": 0,
    }
    if not att["available"]:
        # No disponible: no se intenta
        return [], [], att, f"{name} not available"

    try:
        att["attempted"] = True
        paras: List[str] = []
        paragraphs_with_positions: List[dict] = []
        if fn_with_positions:
            paragraphs_with_positions = fn_with_positions(pdf_path) or []
            paras = [item.get("text", "") for item in paragraphs_with_positions]
        if not any(p.strip() for p in paras) and fn:
            paras = fn(pdf_path) or []
            paragraphs_with_positions = []
            if paras:
                paragraphs_with_positions = [
                    {"page": None, "index": idx, "text": text}
                    for idx, text in enumerate(paras)
                ]
        att["ok"] = any(p.strip() for p in paras)
        att["count"] = len(paras)
        if not att["ok"]:
            return [], [], att, f"{name} returned no paragraphs"
        return paras, paragraphs_with_positions, att, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        att["error"] = msg
        return [], [], att, msg


def run_engine(
    engine_requested: str, pdf_path: str
) -> Tuple[str | None, List[str], List[EngineAttempt], str | None, List[dict]]:
    """
    Política:
      - PaperMage es el único motor disponible ('auto' también lo usa).
      - Si falla o no está disponible, ERROR (no hay fallback).
    Retorna: (engine_used, paragraphs, attempts, error_message, paragraphs_with_positions)
    """
    attempts: List[EngineAttempt] = []

    paras, with_pos, att, err = _attempt(
        "papermage",
        PM_AVAILABLE,
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(att)
    if err:
        return None, [], attempts, err, []
    return "papermage", paras, attempts, None, with_pos

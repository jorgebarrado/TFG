from __future__ import annotations

from typing import Any, Dict, List, Tuple

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
    attempt: EngineAttempt = {
        "name": name,
        "available": bool(available and (fn or fn_with_positions)),
        "attempted": False,
        "ok": False,
        "error": None,
        "count": 0,
    }
    if not attempt["available"]:
        return [], [], attempt, f"{name} not available"

    try:
        attempt["attempted"] = True
        paragraphs: List[str] = []
        paragraphs_with_positions: List[dict] = []
        if fn_with_positions:
            paragraphs_with_positions = fn_with_positions(pdf_path) or []
            paragraphs = [item.get("text", "") for item in paragraphs_with_positions]
        if not any(paragraph.strip() for paragraph in paragraphs) and fn:
            paragraphs = fn(pdf_path) or []
            paragraphs_with_positions = []
            if paragraphs:
                paragraphs_with_positions = [
                    {"page": None, "index": idx, "text": text}
                    for idx, text in enumerate(paragraphs)
                ]
        attempt["ok"] = any(paragraph.strip() for paragraph in paragraphs)
        attempt["count"] = len(paragraphs)
        if not attempt["ok"]:
            return [], [], attempt, f"{name} returned no paragraphs"
        return paragraphs, paragraphs_with_positions, attempt, None
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        attempt["error"] = message
        return [], [], attempt, message


def run_engine(
    engine_requested: str, pdf_path: str
) -> Tuple[str | None, List[str], List[EngineAttempt], str | None, List[dict]]:
    engine = (engine_requested or "papermage").lower().strip()
    attempts: List[EngineAttempt] = []

    if engine != "papermage":
        return None, [], attempts, f"Motor no soportado: {engine}", []

    paragraphs, with_positions, attempt, error = _attempt(
        "papermage",
        PM_AVAILABLE,
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(attempt)
    if error:
        return None, [], attempts, error, []
    return "papermage", paragraphs, attempts, None, with_positions

# Registro de motores de extracción de PDF disponibles y función run_engine que despacha al motor seleccionado.
from __future__ import annotations

import os
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
    "ai_claude": "IA · Claude (Haiku)",
    "ai_openai": "IA · OpenAI (GPT-4.1 mini)",
    "ai_gemini": "IA · Gemini (3.5 Flash)",
}

ALLOWED_ENGINES = set(ENGINE_LABELS.keys())

_AI_ENGINE_ENV_KEYS = {
    "ai_claude": "ANTHROPIC_API_KEY",
    "ai_openai": "OPENAI_API_KEY",
    "ai_gemini": "GOOGLE_API_KEY",
}


def _ai_engine_available(engine_key: str) -> bool:
    env_var = _AI_ENGINE_ENV_KEYS.get(engine_key, "")
    return bool(env_var and os.environ.get(env_var))


def list_extractor_engines() -> List[Dict[str, Any]]:
    return [
        {
            "key": "papermage",
            "label": ENGINE_LABELS["papermage"],
            "available": PM_AVAILABLE,
        },
        {
            "key": "ai_claude",
            "label": ENGINE_LABELS["ai_claude"],
            "available": _ai_engine_available("ai_claude"),
        },
        {
            "key": "ai_openai",
            "label": ENGINE_LABELS["ai_openai"],
            "available": _ai_engine_available("ai_openai"),
        },
        {
            "key": "ai_gemini",
            "label": ENGINE_LABELS["ai_gemini"],
            "available": _ai_engine_available("ai_gemini"),
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
    """Despacha al motor de extracción de párrafos. Solo para motores no-IA."""
    engine = (engine_requested or "papermage").lower().strip()
    attempts: List[EngineAttempt] = []

    if engine != "papermage":
        return None, [], attempts, f"Motor no soportado en run_engine: {engine}", []

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

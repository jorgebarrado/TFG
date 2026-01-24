from __future__ import annotations
from typing import Callable, Any, List, Optional, Tuple
import os
import time

try:
    from .papermage_extractor import (
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
    )

    PAPERMAGE_AVAILABLE = True
except Exception:
    pm_extract_paragraphs = None
    pm_extract_paragraphs_with_positions = None
    PAPERMAGE_AVAILABLE = False

try:
    from .papercraft_extractor import (
        pc_extract_paragraphs,
        pc_extract_paragraphs_with_positions,
    )

    PAPERCRAFT_AVAILABLE = True
except Exception:
    pc_extract_paragraphs = None
    pc_extract_paragraphs_with_positions = None
    PAPERCRAFT_AVAILABLE = False

from .generic_extractor import (
    generic_extract_paragraphs,
    generic_extract_paragraphs_with_positions,
    GENERIC_AVAILABLE,
)

ALLOWED_ENGINES = ["auto", "paper-mage", "paper-craft", "generic"]


def list_extractor_engines() -> List[dict]:
    """Lista los motores de extracción disponibles y su estado.

    Returns:
        List[dict]: Lista de diccionarios con claves 'key', 'label' y 'available'.
    """
    return [
        {
            "key": "auto",
            "label": "Automático (secuencial)",
            "available": True,
        },
        {
            "key": "paper-mage",
            "label": "PaperMage (AllenAI)",
            "available": PAPERMAGE_AVAILABLE,
        },
        {
            "key": "paper-craft",
            "label": "PaperCraft (PyMuPDF/PyPDF2)",
            "available": PAPERCRAFT_AVAILABLE,
        },
        {
            "key": "generic",
            "label": "Genérico (Texto plano)",
            "available": GENERIC_AVAILABLE,
        },
    ]


def _attempt(
    engine_name: str,
    available: bool,
    func_text: Callable[[str], List[str]] | None,
    func_pos: Callable[[str], List[dict]] | None,
    pdf_path: str,
) -> Tuple[List[str] | None, List[dict] | None, dict, str | None]:
    """Intenta ejecutar un motor de extracción específico.

    Args:
        engine_name (str): Nombre del motor.
        available (bool): Si el motor está disponible (importado correctamente).
        func_text (Callable): Función para extraer solo texto (lista de strings).
        func_pos (Callable): Función para extraer texto con posiciones.
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        Tuple: (paragraphs, paragraphs_with_positions, trace_dict, error_message).
    """
    trace: dict = {"engine": engine_name, "available": available, "ok": False}
    start_t = time.time()
    if not available or not func_text:
        trace["error"] = "Not available"
        return None, None, trace, "Not available"

    try:
        # Preferimos la versión con posiciones si existe
        if func_pos:
            paras_pos = func_pos(pdf_path)
            # Y de ahí derivamos la lista simple de textos
            paras_text = [p["text"] for p in paras_pos] if paras_pos else []
            # Si ambas fallan (lista vacía) consideramos error o empty?
            # Depende de la lógica; aquí asumimos que si no hay excepción, es OK (aunque sea 0 paras).
            trace["ok"] = True
            trace["count"] = len(paras_text)
            trace["time_ms"] = int((time.time() - start_t) * 1000)
            return paras_text, paras_pos, trace, None
        else:
            # Fallback solo texto
            paras_text = func_text(pdf_path)
            trace["ok"] = True
            trace["count"] = len(paras_text)
            trace["time_ms"] = int((time.time() - start_t) * 1000)
            return paras_text, None, trace, None
    except Exception as e:
        trace["error"] = str(e)
        trace["time_ms"] = int((time.time() - start_t) * 1000)
        return None, None, trace, str(e)


def run_engine(
    engine_requested: str, pdf_path: str
) -> Tuple[str | None, List[str], List[dict], str | None, List[dict] | None]:
    """Ejecuta la lógica de selección y ejecución del motor de extracción.

    Si se solicita 'auto', prueba los motores en orden: PaperMage -> PaperCraft -> Generic.
    Si se solicita uno específico, ejecuta solo ese.

    Args:
        engine_requested (str): El ID del motor solicitado ('auto', 'paper-mage', etc.).
        pdf_path (str): Ruta al PDF.

    Returns:
        Tuple: (engine_used, paragraphs, attempts_trace, error_msg, paragraphs_with_positions).
    """
    req = engine_requested.lower()
    attempts: List[dict] = []

    # 1. PaperMage
    if req == "auto" or req == "paper-mage":
        paras, with_pos, att, err1 = _attempt(
            "paper-mage",
            PAPERMAGE_AVAILABLE,
            pm_extract_paragraphs,
            pm_extract_paragraphs_with_positions,
            pdf_path,
        )
        attempts.append(att)
        if not err1 and paras:
            return "paper-mage", paras, attempts, None, with_pos
        # Si era específico y falló
        if req == "paper-mage":
            return None, [], attempts, err1 or "Empty results", None

    # 2. PaperCraft
    if req == "auto" or req == "paper-craft":
        paras, with_pos, att, err2 = _attempt(
            "paper-craft",
            PAPERCRAFT_AVAILABLE,
            pc_extract_paragraphs,
            pc_extract_paragraphs_with_positions,
            pdf_path,
        )
        attempts.append(att)
        if not err2 and paras:
            return "paper-craft", paras, attempts, None, with_pos
        if req == "paper-craft":
            return None, [], attempts, err2 or "Empty results", None

    # 3. Generic (siempre último recurso en auto)
    paras, with_pos, att, err3 = _attempt(
        "generic",
        GENERIC_AVAILABLE,
        generic_extract_paragraphs,
        generic_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(att)
    # Generic no debería errar; si viniera vacío, es lo que hay
    return "generic", paras or [], attempts, None, with_pos

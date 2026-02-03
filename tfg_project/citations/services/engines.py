from __future__ import annotations
from typing import List, Dict, Any, Tuple

# ---- Declaraciones de disponibilidad e import seguro ----
try:
    from .papermage_extractor import (
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
        PM_AVAILABLE,
    )
except Exception:
    PM_AVAILABLE = False
    pm_extract_paragraphs = None  # type: ignore
    pm_extract_paragraphs_with_positions = None  # type: ignore

try:
    from .papercraft_extractor import (
        pc_extract_paragraphs,
        pc_extract_paragraphs_with_positions,
        PC_AVAILABLE,
    )
except Exception:
    PC_AVAILABLE = False
    pc_extract_paragraphs = None  # type: ignore
    pc_extract_paragraphs_with_positions = None  # type: ignore

from .generic_extractor import (
    generic_extract_paragraphs,
    generic_extract_paragraphs_with_positions,
    GENERIC_AVAILABLE,
)

EngineAttempt = Dict[str, Any]

ENGINE_LABELS = {
    "papermage": "PaperMage",
    "generic": "Generico (rapido)",
    "papercraft": "PaperCraft",
}

ALLOWED_ENGINES = set(ENGINE_LABELS.keys())


def list_extractor_engines() -> List[Dict[str, Any]]:
    """Enumera los motores de extracción disponibles y su estado.

    Returns:
        List[Dict[str, Any]]: Lista de diccionarios, cada uno representando un motor
        con sus claves 'key', 'label' y 'available'.
    """
    return [
        {
            "key": "papermage",
            "label": ENGINE_LABELS["papermage"],
            "available": PM_AVAILABLE,
        },
        {
            "key": "generic",
            "label": ENGINE_LABELS["generic"],
            "available": GENERIC_AVAILABLE,
        },
        {
            "key": "papercraft",
            "label": ENGINE_LABELS["papercraft"],
            "available": PC_AVAILABLE,
        },
    ]


def _attempt(
    name: str, available: bool, fn, fn_with_positions, pdf_path: str
) -> Tuple[List[str], List[dict], EngineAttempt, str | None]:
    """Intenta ejecutar un motor de extracción específico.

    Esta función auxiliar maneja la lógica de ejecución segura, captura de errores
    y construcción del objeto de intento.

    Args:
        name (str): Nombre del motor.
        available (bool): Si el motor está disponible (importado correctamente).
        fn (callable): Función de extracción de texto plano.
        fn_with_positions (callable): Función de extracción con posiciones.
        pdf_path (str): Ruta al PDF.

    Returns:
        Tuple[List[str], List[dict], EngineAttempt, str | None]:
            - Lista de párrafos (texto).
            - Lista de párrafos con posiciones.
            - Diccionario con info del intento.
            - Mensaje de error (o None).
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
        if not paras and fn:
            paras = fn(pdf_path) or []
            if paras and not paragraphs_with_positions:
                paragraphs_with_positions = [
                    {"page": None, "index": idx, "text": text}
                    for idx, text in enumerate(paras)
                ]
        att["ok"] = bool(paras)
        att["count"] = len(paras)
        if not paras:
            return [], [], att, f"{name} returned no paragraphs"
        return paras, paragraphs_with_positions, att, None
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        att["error"] = msg
        return [], [], att, msg


def run_engine(
    engine_requested: str, pdf_path: str
) -> Tuple[str | None, List[str], List[EngineAttempt], str | None, List[dict]]:
    """Ejecuta la lógica de selección y fallback de motores de extracción.

    Política de ejecución:
      - 'papermage': Solo PaperMage; falla si no está disponible o error.
      - 'papercraft': Solo PaperCraft; falla si no está disponible o error.
      - 'auto': Intenta PaperMage -> PaperCraft -> Generic (fallback seguro).

    Args:
        engine_requested (str): Nombre del motor solicitado ('auto', 'papermage', etc.).
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        Tuple[str | None, List[str], List[EngineAttempt], str | None, List[dict]]:
            - Nombre del motor usado finalmente.
            - Lista de párrafos extraídos (texto).
            - Historial de intentos realizados.
            - Mensaje de error global si fallaron todos los intentos permitidos.
            - Lista de párrafos con metadatos posicionales.
    """
    engine = (engine_requested or "auto").lower().strip()
    attempts: List[EngineAttempt] = []

    if engine == "papermage":
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

    if engine == "papercraft":
        paras, with_pos, att, err = _attempt(
            "papercraft",
            PC_AVAILABLE,
            pc_extract_paragraphs,
            pc_extract_paragraphs_with_positions,
            pdf_path,
        )
        attempts.append(att)
        if err:
            return None, [], attempts, err, []
        return "papercraft", paras, attempts, None, with_pos

    if engine == "generic":
        paras, with_pos, att, err = _attempt(
            "generic",
            GENERIC_AVAILABLE,
            generic_extract_paragraphs,
            generic_extract_paragraphs_with_positions,
            pdf_path,
        )
        attempts.append(att)
        if err:
            return None, [], attempts, err, []
        return "generic", paras, attempts, None, with_pos

    # AUTO
    # 1) PaperMage
    paras, with_pos, att, err = _attempt(
        "papermage",
        PM_AVAILABLE,
        pm_extract_paragraphs,
        pm_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(att)
    if not err:
        return "papermage", paras, attempts, None, with_pos

    # 2) PaperCraft
    paras, with_pos, att, err2 = _attempt(
        "papercraft",
        PC_AVAILABLE,
        pc_extract_paragraphs,
        pc_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(att)
    if not err2:
        return "papercraft", paras, attempts, None, with_pos

    # 3) Generic (siempre)
    paras, with_pos, att, err3 = _attempt(
        "generic",
        GENERIC_AVAILABLE,
        generic_extract_paragraphs,
        generic_extract_paragraphs_with_positions,
        pdf_path,
    )
    attempts.append(att)
    # Generic no debería errar; si viniera vacío, es lo que hay
    return "generic", paras, attempts, None, with_pos

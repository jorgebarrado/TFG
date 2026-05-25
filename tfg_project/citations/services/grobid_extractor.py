"""
Extractor EXPERIMENTAL basado en GROBID.

Orquesta la llamada al cliente GROBID (fulltext o references), el parseo del TEI XML
y el guardado opcional de artefactos de debug.

No forma parte del flujo principal del proyecto.
No modifica ni reemplaza ningún extractor existente.

Uso programático:
    from citations.services.grobid_extractor import run_grobid_extraction

    result = run_grobid_extraction("/ruta/al/paper.pdf", save_artifacts=True)
    if result["ok"]:
        refs = result["parsed"]["references"]
        logger.info("GROBID encontró %s referencias", len(refs))
    else:
        logger.error("Error: %s", result["error"])

Estructura de retorno de run_grobid_extraction():
    {
        "ok": bool,
        "error": str | None,          # mensaje de error si ok=False
        "error_type": str | None,     # "connection" | "http" | "invalid_response" | "parse_error" | "error"
        "pdf": str,                   # ruta absoluta al PDF
        "tei_xml": str | None,        # TEI XML crudo (solo si la respuesta era TEI válido)
        "mode": str,                  # "fulltext" | "references"
        "endpoint": str,              # processFulltextDocument | processReferences
        "parsed": dict | None,        # resultado de parser según modo
        "artifacts": {                # rutas a ficheros guardados
            # Éxito:
            "tei_xml": str,           # solo cuando ok=True
            "parsed_json": str,       # solo cuando ok=True
            # Fallo de respuesta inválida o parseo:
            "response_body": str,     # body crudo recibido
            "error_json": str,        # detalles del error en JSON
        },
        "run_dir": str,               # directorio donde se guardaron los artefactos
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .grobid_client import (
    GrobidError,
    GrobidHTTPError,
    GrobidInvalidResponseError,
    GrobidUnavailableError,
    process_fulltext_document,
    process_references,
)
from .grobid_parser import GrobidParseError, parse_references_tei, parse_tei

logger = logging.getLogger("citations.grobid")

# Directorio de salida por defecto: <repo_root>/tmp/grobid_debug/
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "tmp" / "grobid_debug"
_VALID_MODES = {"fulltext", "references"}
_ENDPOINT_BY_MODE = {
    "fulltext": "processFulltextDocument",
    "references": "processReferences",
}


def _classify_invalid_response(exc: "GrobidInvalidResponseError") -> str:
    """
    Clasifica GrobidInvalidResponseError en un error_type más específico.

    Valores posibles:
        huggingface_space_warming_up  — URL de HF Space + respuesta HTML (Space dormido)
        non_tei_html_response         — respuesta HTML de otro origen (proxy, landing page)
        non_tei_response              — respuesta no-HTML pero sin <TEI (inesperado)
        invalid_response              — fallback genérico
    """
    url_lower = (exc.url or "").lower()
    body_lower = (exc.body_preview or "").lower()

    is_html = "<!doctype html" in body_lower or "<html" in body_lower
    is_hf = "hf.space" in url_lower or "huggingface" in url_lower

    if is_hf and is_html:
        return "huggingface_space_warming_up"
    if is_html:
        return "non_tei_html_response"
    if "<tei" not in body_lower:
        return "non_tei_response"
    return "invalid_response"


def run_grobid_extraction(
    pdf_path: str | Path,
    *,
    save_artifacts: bool = True,
    output_dir: Optional[Path] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
    mode: str = "fulltext",
    run_dir: Optional[Path] = None,
    artifact_prefix: str = "",
    include_raw_citation: bool = True,
) -> Dict[str, Any]:
    """
    Ejecuta GROBID sobre un PDF local y retorna un resultado estructurado.

    Args:
        pdf_path:       Ruta al PDF local.
        save_artifacts: Si True, guarda TEI XML y JSON parseado en output_dir.
        output_dir:     Directorio raíz para los artefactos.
                        Cada ejecución crea un subdirectorio con timestamp.
                        Default: tmp/grobid_debug/
        base_url:       Override de URL base de GROBID.
        timeout:        Override de timeout en segundos.

    Returns:
        Dict estructurado (ver docstring del módulo).
    """
    mode = (mode or "fulltext").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Modo GROBID no soportado: {mode!r}. Valores válidos: {sorted(_VALID_MODES)}"
        )

    pdf_path = Path(pdf_path).resolve()
    if run_dir is not None:
        out_dir = Path(run_dir)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_name = f"{ts}_{pdf_path.stem}"
        out_dir = (output_dir or DEFAULT_OUTPUT_DIR) / run_name

    endpoint_name = _ENDPOINT_BY_MODE[mode]
    prefix = artifact_prefix or ""

    result: Dict[str, Any] = {
        "ok": False,
        "error": None,
        "error_type": None,
        "mode": mode,
        "endpoint": endpoint_name,
        "pdf": str(pdf_path),
        "tei_xml": None,
        "parsed": None,
        "artifacts": {},
        "run_dir": str(out_dir),
    }

    # ------------------------------------------------------------------
    # 1. Llamada a GROBID
    # ------------------------------------------------------------------
    logger.info("Iniciando extracción GROBID (%s): %s", mode, pdf_path.name)
    try:
        if mode == "references":
            tei_xml = process_references(pdf_path, base_url=base_url, timeout=timeout)
        else:
            tei_xml = process_fulltext_document(
                pdf_path, base_url=base_url, timeout=timeout
            )
    except GrobidInvalidResponseError as exc:
        result["error"] = str(exc)
        result["error_type"] = _classify_invalid_response(exc)
        logger.error("Respuesta inválida de GROBID [%s]: %s", result["error_type"], exc)
        if save_artifacts:
            _save_error_artifacts(
                out_dir, result, invalid_exc=exc, artifact_prefix=prefix
            )
        return result
    except GrobidUnavailableError as exc:
        result["error"] = str(exc)
        result["error_type"] = "connection"
        logger.error("GROBID no disponible: %s", exc)
        if save_artifacts:
            _save_error_artifacts(out_dir, result, artifact_prefix=prefix)
        return result
    except GrobidHTTPError as exc:
        result["error"] = str(exc)
        result["error_type"] = "http"
        logger.error("HTTP error de GROBID: %s", exc)
        if save_artifacts:
            _save_error_artifacts(out_dir, result, artifact_prefix=prefix)
        return result
    except GrobidError as exc:
        result["error"] = str(exc)
        result["error_type"] = "error"
        logger.error("Error de GROBID: %s", exc)
        if save_artifacts:
            _save_error_artifacts(out_dir, result, artifact_prefix=prefix)
        return result

    result["tei_xml"] = tei_xml
    logger.info("TEI recibido de GROBID: %d chars.", len(tei_xml))

    # ------------------------------------------------------------------
    # 2. Parseo del TEI XML
    # ------------------------------------------------------------------
    try:
        if mode == "references":
            parsed = parse_references_tei(
                tei_xml, include_raw_citation=include_raw_citation
            )
        else:
            parsed = parse_tei(tei_xml)
    except GrobidParseError as exc:
        result["error"] = str(exc)
        result["error_type"] = "parse_error"
        logger.error("Error parseando TEI de GROBID: %s", exc)
        if save_artifacts:
            _save_error_artifacts(
                out_dir, result, raw_body=tei_xml, artifact_prefix=prefix
            )
        return result

    result["parsed"] = parsed
    result["ok"] = True
    logger.info(
        "Parseado (%s): %d referencias, %d citas inline, %d secciones.",
        mode,
        parsed.get("reference_count", 0),
        parsed.get("inline_citation_count", 0),
        len(parsed.get("sections") or []),
    )

    # ------------------------------------------------------------------
    # 3. Guardado de artefactos (solo cuando hay TEI real y parseo OK)
    # ------------------------------------------------------------------
    if save_artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)

        tei_filename = f"{prefix}tei.xml" if prefix else "tei.xml"
        tei_path = out_dir / tei_filename
        tei_path.write_text(tei_xml, encoding="utf-8")
        result["artifacts"]["tei_xml"] = str(tei_path)

        parsed_filename = f"{prefix}parsed.json" if prefix else "parsed.json"
        parsed_path = out_dir / parsed_filename
        parsed_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["artifacts"]["parsed_json"] = str(parsed_path)

        logger.debug("Artefactos guardados en: %s", out_dir)

    return result


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _save_error_artifacts(
    out_dir: Path,
    result: Dict[str, Any],
    invalid_exc: Optional[GrobidInvalidResponseError] = None,
    raw_body: Optional[str] = None,
    artifact_prefix: str = "",
) -> None:
    """
    Guarda artefactos de diagnóstico cuando la extracción falla.
    No produce tei.xml ni parsed.json (reservados para éxito real).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    error_payload = {
        "error_type": result.get("error_type"),
        "error": result.get("error"),
        "pdf": result.get("pdf"),
        "mode": result.get("mode"),
        "endpoint": result.get("endpoint"),
    }

    if invalid_exc is not None:
        error_payload["url"] = invalid_exc.url
        error_payload["content_type"] = invalid_exc.content_type
        error_payload["body_preview"] = invalid_exc.body_preview
        # Guardar el body completo recibido (sea HTML o lo que sea) para inspección
        full_body = invalid_exc.body or invalid_exc.body_preview
        if full_body:
            body_filename = (
                f"{artifact_prefix}response_body.txt"
                if artifact_prefix
                else "response_body.txt"
            )
            body_path = out_dir / body_filename
            body_path.write_text(full_body, encoding="utf-8")
            result["artifacts"]["response_body"] = str(body_path)

    elif raw_body is not None:
        body_filename = (
            f"{artifact_prefix}response_body.txt"
            if artifact_prefix
            else "response_body.txt"
        )
        body_path = out_dir / body_filename
        body_path.write_text(raw_body, encoding="utf-8")
        result["artifacts"]["response_body"] = str(body_path)

    error_filename = f"{artifact_prefix}error.json" if artifact_prefix else "error.json"
    error_path = out_dir / error_filename
    error_path.write_text(
        json.dumps(error_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["artifacts"]["error_json"] = str(error_path)

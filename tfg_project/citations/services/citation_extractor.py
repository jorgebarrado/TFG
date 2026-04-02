"""
EN: Citation extractor utility
------------------------------
Given a manuscript (plain text or PDF),
detect in-text citations (numeric like [1] or author–year like (Smith, 2020)),
and return for each citation one or more occurrences with paragraph,
snippet (±window), and character positions.

ES: Utilidad para extraer citas
-------------------------------
Dado un manuscrito (texto plano o PDF),
detecta citas en el texto (numéricas tipo [1] o autor–año tipo (Smith, 2020)),
y devuelve para cada cita una o más ocurrencias con párrafo, fragmento (±ventana)
y posiciones de caracteres.
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, List, Tuple
from ..logging_utils import get_logger

logger = get_logger(__name__)
TRACE_REFERENCES = os.getenv("TRACE_REFERENCES", "0") == "1"

try:
    # pypdf is lightweight and built-in text extractor is enough for many PDFs
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover
    PdfReader = None  # Fallback handled later


# EN: Patterns for numeric and author–year citations (more tolerant).
# ES: Patrones para citas numéricas y autor–año (más tolerantes).
NUMERIC = r"\[\s*\d+(?:\s*[,;-]\s*\d+)*\s*\]"  # [1], [1, 2], [1-3]
AUTHOR = r"[A-Z][A-Za-z'`\-]+(?:\s+[A-Z][A-Za-z'`\-]+)*(?:\s+Jr\.)?"
AUTHORS_LIST = rf"{AUTHOR}(?:\s*(?:,|;|&)\s*{AUTHOR})*(?:\s+et al\.)?"
YEAR = r"\d{4}[a-z]?"
AUTHOR_YEAR = rf"\(\s*{AUTHORS_LIST}\s*,\s*{YEAR}\s*\)"
CITATION = re.compile(rf"({NUMERIC}|{AUTHOR_YEAR})")


def _normalize_key(raw: str) -> str:
    """EN: Normalize keys so '(Smith, 2020)' and '(Smith et al., 2020)' group together.
    ES: Normaliza claves para agrupar '(Smith, 2020)' y '(Smith et al., 2020)'.
    """
    k = raw.strip()
    if k.startswith("(") and k.endswith(")"):
        k = k[1:-1].strip()
    k = re.sub(r"\bet al\.\b", "", k, flags=re.I)
    k = re.sub(r"\s+", " ", k)
    return k.strip()


def extract_text_from_pdf(pdf_path: str) -> tuple[str, List[Tuple[int, int]]]:
    """EN: Return (full_text, page_spans). page_spans = [(start, end), ...].
    ES: Devuelve (texto, rangos_por_página). rangos_por_página = [(inicio, fin), ...].
    """
    if PdfReader is None:
        return "", []
    try:
        reader = PdfReader(pdf_path)  # type: ignore
        text, spans = "", []
        pos = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            start, end = pos, pos + len(t)
            spans.append((start, end))
            text += t
            pos = end
        return text, spans
    except Exception:
        # If PDF fails, return empty so caller can decide
        return "", []


def _page_from_offset(offset: int, page_spans: List[Tuple[int, int]]) -> int | None:
    """EN: Get 1-based page number for a given char offset.
    ES: Obtiene el número de página (base 1) para un offset de caracteres.
    """
    for i, (s, e) in enumerate(page_spans, start=1):
        if s <= offset < e:
            return i
    return None


def _paragraphs(text: str) -> List[str]:
    """EN: Split by blank lines. ES: Divide por líneas en blanco."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _find_matches_in_paragraph(para: str) -> List[Tuple[str, Tuple[int, int]]]:
    """EN: Find citations in paragraph and return [(raw_key, (start, end))].
    ES: Encuentra citas en el párrafo y devuelve [(clave_cruda, (inicio, fin))].
    """
    hits: List[Tuple[str, Tuple[int, int]]] = []
    for m in CITATION.finditer(para):
        hits.append((m.group(0), m.span()))
    return hits


def _snippet(para: str, span: Tuple[int, int], window: int = 120) -> str:
    """EN: Return ±window chars around the match; single-line.
    ES: Devuelve ±window caracteres alrededor del match; en una sola línea.
    """
    s, e = span
    start = max(0, s - window)
    end = min(len(para), e + window)
    frag = para[start:end].replace("\n", " ")
    return re.sub(r"\s+", " ", frag).strip()


def process_manuscript(path_or_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Main entry.
    Accept a file path (.pdf/.txt) or raw text; return JSON-like dict.

    Entrada principal.
    Acepta ruta de archivo (.pdf/.txt) o texto; devuelve dict tipo JSON.

    Returns:
        {
          "Smith 2020": [
              {"paragraph": "...", "snippet": "...", "start": 123, "end": 130}
          ],
          "[1]": [...]
        }
    """
    logger.debug(
        "process_manuscript_start",
        extra={
            "is_file": any(
                path_or_text.lower().endswith(ext) for ext in (".pdf", ".txt")
            )
        },
    )
    text: str = ""
    page_spans: List[Tuple[int, int]] = []

    # If looks like a file path
    if any(path_or_text.lower().endswith(ext) for ext in (".pdf", ".txt")):
        if path_or_text.lower().endswith(".pdf"):
            text, page_spans = extract_text_from_pdf(path_or_text)
        else:
            try:
                with open(path_or_text, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except Exception:
                text = ""
    else:
        # Raw text
        text = path_or_text or ""

    if not text:
        logger.warning(
            "process_manuscript_empty", extra={"reason": "no_text_extracted"}
        )
        return {}

    result: Dict[str, List[Dict[str, Any]]] = {}
    total_references = 0
    paras = _paragraphs(text)

    for i, para in enumerate(paras):
        matches = _find_matches_in_paragraph(para)
        for raw_key, span in matches:
            key = _normalize_key(raw_key)
            s, e = span
            snippet = _snippet(para, span)
            item = {
                "paragraph": para,
                "snippet": snippet,
                "start": s,
                "end": e,
            }
            result.setdefault(key, [])
            if item not in result[key]:
                result[key].append(item)
                total_references += 1

                if TRACE_REFERENCES and total_references <= 20:
                    logger.debug(
                        "reference_detected",
                        extra={"ref_key": key, "start": s, "end": e, "para_index": i},
                    )

    logger.info(
        "process_manuscript_complete",
        extra={
            "total_references_detected": total_references,
            "unique_keys": len(result),
        },
    )

    return result

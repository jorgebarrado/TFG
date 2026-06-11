from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .citation_patterns import NARRATIVE_AUTHOR_YEAR_REGEX as CIT_AUTHORYEAR
from .citation_patterns import NUMERIC_CITATION_REGEX as NUMERIC_CITATION_BLOCK
from .citation_patterns import (
    find_citation_matches,
    infer_numeric_style,
)
from .citation_patterns import max_reference_index as _max_reference_index
from .engines import run_engine

try:
    from .papermage_extractor import pm_extract_paragraphs
except Exception:
    pm_extract_paragraphs = None
# ====== Imports de extractores específicos (opcionales) ======
# PaperMage (si tu módulo actual está orientado a "target matching", NO lo uses aquí)
try:
    from .papermage_extractor import (
        extract_contexts_from_pdf as pm_ctx,  # puede requerir params extra
    )
except Exception:
    pm_ctx = None

# ====== Regex básicos: [n] y Autor (Año) ======
# Alias historico del AUTHOR_YEAR original. La logica viva esta en
# `citation_patterns.NARRATIVE_AUTHOR_YEAR_REGEX`.
AUTHOR_YEAR = CIT_AUTHORYEAR


def _make_snippet(text: str, start: int, end: int, padding: int = 80) -> str:
    left = max(start - padding, 0)
    right = min(end + padding, len(text))
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def find_numeric_citation_blocks(text: str) -> List[re.Match[str]]:
    if not text:
        return []
    return list(NUMERIC_CITATION_BLOCK.finditer(text))


def _find_hits(
    paragraph: str,
    citation_style: str = "",
    total_references: int = 0,
) -> List[Dict[str, Any]]:
    """Devuelve todas las citas in-text de `paragraph`.

    Delega en `citation_patterns.find_citation_matches`, que cubre numericas,
    autor-anio (narrativo y parentetico, con et al., diacriticos, multi-cita
    y sufijos de anio) y DOI desnudos.
    """
    return find_citation_matches(
        paragraph,
        citation_style=citation_style,
        total_references=total_references,
    )


def _build_results(
    paragraphs: List[str],
    paragraphs_with_positions: List[dict] | None = None,
    citation_style: str = "",
    total_references: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    flat: List[Dict[str, Any]] = []
    total = 0
    if paragraphs_with_positions:
        items = [
            {
                "text": item.get("text", ""),
                "page": item.get("page"),
            }
            for item in paragraphs_with_positions
        ]
    else:
        items = [{"text": p, "page": None} for p in paragraphs]

    for ref, item in enumerate(items, start=1):
        text = item["text"]
        page = item.get("page")
        hs = _find_hits(
            text,
            citation_style=citation_style,
            total_references=total_references,
        )
        if not hs:
            continue
        total += len(hs)
        for i, h in enumerate(hs, start=1):
            flat.append(
                {
                    "ref": ref,
                    "idx": i,
                    "page": page,
                    "type": h["type"],
                    "confidence": h.get("confidence", 0.0),
                    "snippet": h.get("snippet", h["match"]),
                    "paragraph": text,
                    "start": h["start"],
                    "end": h["end"],
                    "raw": h,
                }
            )
    return flat, total


def _find_citations_in_paragraph(
    p: str,
    citation_style: str = "",
    total_references: int = 0,
) -> list[dict]:
    """Variante legacy con shape `{ref, pattern, ...}` para callers viejos.

    Convierte la salida de `find_citation_matches` al formato historico que
    usa `_pm_loose_extract`.
    """
    out: list[dict] = []
    for hit in find_citation_matches(
        p,
        citation_style=citation_style,
        total_references=total_references,
    ):
        common = {
            "snippet": hit["snippet"],
            "paragraph": p,
            "start": hit["start"],
            "end": hit["end"],
            "match": hit["match"],
        }
        if hit["type"] == "numeric":
            for ref_idx in hit.get("citation_numbers", []) or []:
                out.append({"ref": ref_idx, "pattern": "numeric", **common})
        elif hit["type"] == "authoryear":
            years = hit.get("years") or []
            out.append(
                {
                    "ref": 0,
                    "pattern": "author-year",
                    "author": hit.get("authors", ""),
                    "year": years[0] if years else "",
                    **common,
                }
            )
        elif hit["type"] == "doi":
            out.append(
                {
                    "ref": 0,
                    "pattern": "doi",
                    "doi": hit.get("doi", ""),
                    **common,
                }
            )
    return out


def _pm_loose_extract(path: str) -> list[dict]:
    if pm_extract_paragraphs is None:
        return []
    try:
        paragraphs = pm_extract_paragraphs(path) or []
        out = []
        for p in paragraphs:
            out.extend(_find_citations_in_paragraph(p))
        return out
    except Exception:
        return []


def process_manuscript(
    pdf_path: str,
    *,
    engine: str = "auto",
    debug: bool = False,
    references: Sequence[Dict[str, Any]] | None = None,
    citation_style: str | None = None,
    total_references: int | None = None,
) -> Dict[str, Any]:
    references_list = [item for item in (references or []) if isinstance(item, dict)]
    inferred_numeric_style = infer_numeric_style(references_list)
    resolved_citation_style = str(citation_style or "").strip().lower()
    if resolved_citation_style not in {"numeric", "non_numeric", "non-numeric"}:
        resolved_citation_style = "numeric" if inferred_numeric_style else "non_numeric"
    if resolved_citation_style == "non-numeric":
        resolved_citation_style = "non_numeric"

    max_reference_index = _max_reference_index(references_list)
    if max_reference_index <= 0:
        max_reference_index = len(references_list)
    try:
        resolved_total_references = (
            int(total_references) if total_references is not None else 0
        )
    except (TypeError, ValueError):
        resolved_total_references = 0
    if resolved_total_references <= 0:
        resolved_total_references = max_reference_index
    if resolved_total_references <= 0:
        resolved_total_references = len(references_list)

    engine_used, paragraphs, attempts, err, paragraphs_with_positions = run_engine(
        engine, pdf_path
    )

    # PaperMage es el único motor: si hubo error, no hay fallback
    if err:
        payload: Dict[str, Any] = {
            "ok": False,
            "engine_requested": engine,
            "engine_used": None,
            "error": err,
        }
        if debug:
            payload["trace"] = {"engines": attempts}
        return payload

    # Sin error: construimos resultados (aunque paragraphs pueda estar vacío)
    results, total = _build_results(
        paragraphs,
        paragraphs_with_positions,
        citation_style=resolved_citation_style,
        total_references=resolved_total_references,
    )
    payload = {
        "ok": True,
        "engine_requested": engine,
        "engine_used": engine_used,
        "summary": {"paragraphs": len(paragraphs), "count": total},
        "results": results,
        "citation_style": resolved_citation_style,
        "total_references": resolved_total_references,
        "max_reference_index": max_reference_index,
    }
    if debug:
        payload["trace"] = {"engines": attempts}
    return payload

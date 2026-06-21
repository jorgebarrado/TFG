from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .citation_patterns import (
    find_citation_matches,
    infer_numeric_style,
)
from .citation_patterns import max_reference_index as _max_reference_index
from .engines import run_engine


def _find_hits(
    paragraph: str,
    citation_style: str = "",
    total_references: int = 0,
) -> List[Dict[str, Any]]:
    """Devuelve todas las citas in-text de `paragraph`."""
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
        items = [{"text": paragraph, "page": None} for paragraph in paragraphs]

    for ref, item in enumerate(items, start=1):
        text = item["text"]
        page = item.get("page")
        hits = _find_hits(
            text,
            citation_style=citation_style,
            total_references=total_references,
        )
        if not hits:
            continue
        total += len(hits)
        for idx, hit in enumerate(hits, start=1):
            flat.append(
                {
                    "ref": ref,
                    "idx": idx,
                    "page": page,
                    "type": hit["type"],
                    "confidence": hit.get("confidence", 0.0),
                    "snippet": hit.get("snippet", hit["match"]),
                    "paragraph": text,
                    "start": hit["start"],
                    "end": hit["end"],
                    "raw": hit,
                }
            )
    return flat, total


def process_manuscript(
    pdf_path: str,
    *,
    engine: str = "papermage",
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

    engine_used, paragraphs, attempts, error, paragraphs_with_positions = run_engine(
        engine, pdf_path
    )

    if error:
        payload: Dict[str, Any] = {
            "ok": False,
            "engine_requested": engine,
            "engine_used": None,
            "error": error,
        }
        if debug:
            payload["trace"] = {"engines": attempts}
        return payload

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

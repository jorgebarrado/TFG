from __future__ import annotations
from typing import Any, Dict, List, Sequence, Tuple
import re
from .engines import run_engine

try:
    from .papermage_extractor import pm_extract_paragraphs
except Exception:
    pm_extract_paragraphs = None
# ====== Imports de extractores específicos (opcionales) ======
# PaperMage (si tu módulo actual está orientado a "target matching", NO lo uses aquí)
try:
    from .papermage_extractor import (
        extract_contexts_from_pdf as pm_ctx,
    )  # puede requerir params extra
except Exception:
    pm_ctx = None

# PaperCraft (si no existe, quedará None)
try:
    from .papercraft_extractor import extract_contexts_from_pdf as pc_extract  # type: ignore
except Exception:
    pc_extract = None

# ====== Dependencia ligera para el extractor genérico ======
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# ====== Regex básicos: [n] y Autor (Año) ======
NUMERIC_CITATION_BLOCK = re.compile(
    r"\[\s*\d+(?:\s*(?:[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+))*\s*\]"
)
AUTHOR_YEAR = re.compile(
    r"\b([A-Z][A-Za-z-]+(?:\s(?:and|&)\s[A-Z][A-Za-z-]+|(?:\s+et al\.)?)?)\s*\(((?:19|20)\d{2})\)"
)

CIT_AUTHORYEAR = re.compile(r"\b([A-Z][A-Za-z\-]+)\s*\(\s*(19|20)\d{2}\s*\)")
CIT_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


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


def expand_numeric_citation_block(block_text: str) -> List[int]:
    if not block_text:
        return []
    inner = str(block_text).strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]

    values: List[int] = []
    for part in re.split(r"[,;]", inner):
        token = part.replace("\u2013", "-").replace("\u2014", "-").strip()
        if not token:
            continue
        if "-" in token:
            bounds = [segment.strip() for segment in token.split("-", 1)]
            if len(bounds) != 2:
                continue
            try:
                start = int(bounds[0])
                end = int(bounds[1])
            except (TypeError, ValueError):
                continue
            step = 1 if start <= end else -1
            span = min(abs(end - start) + 1, 50)
            for idx in range(span):
                number = start + idx * step
                if number > 0:
                    values.append(number)
            continue
        try:
            number = int(token)
        except (TypeError, ValueError):
            continue
        if number > 0:
            values.append(number)

    seen: set[int] = set()
    ordered: List[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def infer_numeric_style(references: Sequence[Dict[str, Any]] | None) -> bool:
    if not references:
        return False
    numeric_labels: List[int] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        raw_index = reference.get("index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index > 0:
            numeric_labels.append(index)
    if len(numeric_labels) < 3:
        return False
    numeric_labels = sorted(set(numeric_labels))
    return numeric_labels[0] == 1 and len(numeric_labels) >= 3


def is_valid_numeric_citation(number, total_references):
    try:
        parsed_number = int(number)
        parsed_total = int(total_references)
    except (TypeError, ValueError):
        return False
    return 1 <= parsed_number <= parsed_total


def _max_reference_index(references: Sequence[Dict[str, Any]] | None) -> int:
    if not references:
        return 0
    max_index = 0
    for reference in references:
        if not isinstance(reference, dict):
            continue
        raw_index = reference.get("index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index > max_index:
            max_index = index
    return max_index


def _find_hits(
    paragraph: str,
    citation_style: str = "",
    total_references: int = 0,
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    normalized_style = str(citation_style or "").strip().lower()
    for m in find_numeric_citation_blocks(paragraph):
        block = m.group(0)
        expanded = expand_numeric_citation_block(block)
        if normalized_style == "numeric":
            expanded = [
                number
                for number in expanded
                if is_valid_numeric_citation(number, total_references)
            ]
        if not expanded:
            continue
        hits.append(
            {
                "type": "numeric",
                "match": block,
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
                "citation_block": block,
                "citation_numbers": expanded,
            }
        )
    for m in CIT_AUTHORYEAR.finditer(paragraph):
        hits.append(
            {
                "type": "authoryear",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
            }
        )
    for m in CIT_DOI.finditer(paragraph):
        hits.append(
            {
                "type": "doi",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
            }
        )
    return hits


def _extract_text_from_pdf_generic(path: str) -> str:
    if PyPDF2 is None:
        return ""
    text_parts: list[str] = []
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    pass
    except Exception:
        return ""
    return "\n".join(text_parts)


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


def _split_paragraphs(text: str) -> list[str]:
    # separa por doble salto o líneas largas
    raw = re.split(r"\n\s*\n", text)
    paras: list[str] = []
    for p in raw:
        p = p.strip()
        if not p:
            continue
        # une líneas cortadas
        p = re.sub(r"[ \t]*\n[ \t]*", " ", p).strip()
        if p:
            paras.append(p)
    return paras


def _find_citations_in_paragraph(
    p: str,
    citation_style: str = "",
    total_references: int = 0,
) -> list[dict]:
    out: list[dict] = []
    normalized_style = str(citation_style or "").strip().lower()
    # [n], [1,2], [23-25], [23–25], etc.
    for m in find_numeric_citation_blocks(p):
        s, e = m.span()
        snippet = p[max(0, s - 80) : min(len(p), e + 80)]
        block = m.group(0)
        for ref_idx in expand_numeric_citation_block(block):
            if normalized_style == "numeric" and not is_valid_numeric_citation(
                ref_idx, total_references
            ):
                continue
            out.append(
                {
                    "ref": ref_idx,
                    "snippet": snippet,
                    "paragraph": p,
                    "start": s,
                    "end": e,
                    "pattern": "numeric",
                    "match": block,
                }
            )
    # Autor (Año)
    for m in AUTHOR_YEAR.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s - 80) : min(len(p), e + 80)]
        out.append(
            {
                "ref": 0,
                "snippet": snippet,
                "paragraph": p,
                "start": s,
                "end": e,
                "pattern": "author-year",
                "author": m.group(1),
                "year": m.group(2),
            }
        )
    return out


def _generic_extract_contexts(path: str) -> list[dict]:
    text = _extract_text_from_pdf_generic(path)
    if not text:
        return []
    contexts: list[dict] = []
    for p in _split_paragraphs(text):
        hits = _find_citations_in_paragraph(p)
        if hits:
            contexts.extend(hits)
    return contexts


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

    # Si NO estamos en 'auto' y hubo error → NO hay fallback, devolvemos error
    if engine.lower() != "auto" and err:
        payload: Dict[str, Any] = {
            "ok": False,
            "engine_requested": engine,
            "engine_used": None,
            "error": err,
        }
        if debug:
            payload["trace"] = {"engines": attempts}
        return payload

    # AUTO (o motor explícito sin error): construimos resultados (aunque paragraphs pueda estar vacío)
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

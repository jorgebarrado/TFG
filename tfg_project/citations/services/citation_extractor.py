from __future__ import annotations
from typing import Any, Dict, List, Tuple
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
NUMERIC_CITE = re.compile(r"\[(\d+)\]")
AUTHOR_YEAR = re.compile(
    r"\b([A-Z][A-Za-z-]+(?:\s(?:and|&)\s[A-Z][A-Za-z-]+|(?:\s+et al\.)?)?)\s*\(((?:19|20)\d{2})\)"
)

CIT_NUMERIC = re.compile(r"\[(\d{1,3})\]")
CIT_AUTHORYEAR = re.compile(r"\b([A-Z][A-Za-z\-]+)\s*\(\s*(19|20)\d{2}\s*\)")
CIT_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def _make_snippet(text: str, start: int, end: int, padding: int = 80) -> str:
    left = max(start - padding, 0)
    right = min(end + padding, len(text))
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _find_hits(paragraph: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for m in CIT_NUMERIC.finditer(paragraph):
        hits.append(
            {
                "type": "numeric",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
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
        hs = _find_hits(text)
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


def _find_citations_in_paragraph(p: str) -> list[dict]:
    out: list[dict] = []
    # [n]
    for m in NUMERIC_CITE.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s - 80) : min(len(p), e + 80)]
        out.append(
            {
                "ref": int(m.group(1)),
                "snippet": snippet,
                "paragraph": p,
                "start": s,
                "end": e,
                "pattern": "numeric",
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
    pdf_path: str, *, engine: str = "auto", debug: bool = False
) -> Dict[str, Any]:
    """Procesa un manuscrito para extraer citas utilizando el motor especificado.

    Orquesta la ejecución de los motores de extracción (PaperMage, PaperCraft, Generic)
    según la configuración solicitada, manejando reintentos y fallbacks en modo 'auto'.

    Args:
        pdf_path (str): Ruta al archivo PDF en el sistema.
        engine (str, optional): Nombre del motor a usar ('auto', 'papermage', etc.).
            Defaults to "auto".
        debug (bool, optional): Si es True, incluye trazas de depuración. Defaults to False.

    Returns:
        dict: Diccionario con los resultados de la extracción (párrafos, citas, metadatos).
    """
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
    results, total = _build_results(paragraphs, paragraphs_with_positions)
    payload = {
        "ok": True,
        "engine_requested": engine,
        "engine_used": engine_used,
        "summary": {"paragraphs": len(paragraphs), "count": total},
        "results": results,
    }
    if debug:
        payload["trace"] = {"engines": attempts}
    return payload

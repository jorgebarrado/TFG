# -*- coding: utf-8 -*-
"""
Extractor de citas desde PDF o TXT.
Devuelve JSON con:
- total: nº de citas detectadas
- items: lista de dicts con {style, raw, paragraph, snippet, start, end}
"""

from __future__ import annotations

import re
from typing import Dict, List

# Preferimos PyPDF2 (ya lo tienes instalado). Si no, intenta pypdf.
try:
    from PyPDF2 import PdfReader
except Exception:  # pragma: no cover
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:  # pragma: no cover
        PdfReader = None  # type: ignore


# Patrones de citación: numérico [1], [2–5], (1), etc. y autor-año (Smith, 2021)
NUMERIC_CITATION = re.compile(
    r"""
    (?:\[(?:\d+[\s,\-–]*?)+\])      # [1], [2,5], [2–5], [2-5]
    |                               # o
    (?:\((?:\d+[\s,\-–]*?)+\))      # (1), (2,5), (2–5), (2-5)
    """,
    re.VERBOSE,
)

AUTHOR_YEAR_CITATION = re.compile(
    r"""
    \(
      (?:
        [A-Z][A-Za-z\-']+(?:\s+et\s+al\.)?   # Apellido o 'X et al.'
        (?:\s*&\s*[A-Z][A-Za-z\-']+)?        # opcional '& Apellido'
      )
      \s*,\s*
      (?:19|20)\d{2}                         # año 19xx o 20xx
      (?:[a-z])?                             # letra opcional 2021a
    \)
    """,
    re.VERBOSE,
)

SNIPPET_RADIUS = 120  # caracteres a cada lado


def _split_paragraphs(text: str) -> List[str]:
    # Divide en párrafos por líneas en blanco
    parts = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _find_citations_in_paragraph(paragraph: str) -> List[Dict]:
    items: List[Dict] = []

    for m in NUMERIC_CITATION.finditer(paragraph):
        start, end = m.span()
        raw = m.group(0)
        left = max(0, start - SNIPPET_RADIUS)
        right = min(len(paragraph), end + SNIPPET_RADIUS)
        snippet = paragraph[left:right]
        items.append(
            {
                "style": "numeric",
                "raw": raw,
                "paragraph": paragraph,
                "snippet": snippet,
                "start": start,
                "end": end,
            }
        )

    for m in AUTHOR_YEAR_CITATION.finditer(paragraph):
        start, end = m.span()
        raw = m.group(0)
        left = max(0, start - SNIPPET_RADIUS)
        right = min(len(paragraph), end + SNIPPET_RADIUS)
        snippet = paragraph[left:right]
        items.append(
            {
                "style": "author-year",
                "raw": raw,
                "paragraph": paragraph,
                "snippet": snippet,
                "start": start,
                "end": end,
            }
        )

    return items


def _extract_text_from_pdf(path: str) -> str:
    if PdfReader is None:
        raise RuntimeError(
            "No se encontró PdfReader. Instala PyPDF2 (recomendado) o pypdf."
        )
    reader = PdfReader(path)
    chunks: List[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            # Algunos PDFs pueden fallar en una página suelta; sigue con el resto
            continue
    return "\n".join(chunks)


def process_manuscript(path: str) -> Dict:
    """
    Devuelve un dict JSON-serializable:
    {
      "total": int,
      "items": [ {style, raw, paragraph, snippet, start, end}, ... ]
    }
    """
    path_lower = path.lower()
    if path_lower.endswith(".pdf"):
        text = _extract_text_from_pdf(path)
    else:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

    items: List[Dict] = []
    for para in _split_paragraphs(text):
        items.extend(_find_citations_in_paragraph(para))

    return {"total": len(items), "items": items}

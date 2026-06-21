# Normalización de texto para comparación de referencias en experimentos: limpieza, DOIs, años y campos estructurados.
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_doi(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    return text.rstrip(").,;:]").strip().lower() or None


def coerce_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            year = coerce_year(item)
            if year is not None:
                return year
        return None
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_text(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = clean_text(item)
                if text:
                    return text
            continue
        text = clean_text(value)
        if text:
            return text
    return None


def normalize_authors(values: Iterable[Any]) -> List[str]:
    authors: List[str] = []
    for value in values:
        if isinstance(value, dict):
            given = clean_text(value.get("given"))
            family = clean_text(value.get("family"))
            literal = clean_text(value.get("literal"))
            joined = " ".join(part for part in [given, family] if part).strip()
            candidate = joined or literal
        else:
            candidate = clean_text(value)
        if candidate:
            authors.append(candidate)
    return authors


def build_normalized_entry(
    *,
    index: int,
    raw_input: str,
    parser: str,
    title: Optional[str] = None,
    authors: Optional[Iterable[str]] = None,
    year: Optional[int] = None,
    doi: Optional[str] = None,
    venue: Optional[str] = None,
    pages: Optional[str] = None,
    entry_type: Optional[str] = None,
    identifiers: Optional[Dict[str, Any]] = None,
    raw_output: Any = None,
    warnings: Optional[Iterable[str]] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "index": index,
        "raw_input": clean_text(raw_input),
        "title": clean_text(title) or None,
        "authors": [clean_text(item) for item in (authors or []) if clean_text(item)],
        "year": year,
        "doi": clean_doi(doi),
        "venue": clean_text(venue) or None,
        "pages": clean_text(pages) or None,
        "type": clean_text(entry_type) or None,
        "identifiers": identifiers or {},
        "parser": parser,
        "raw_output": raw_output,
        "warnings": [clean_text(item) for item in (warnings or []) if clean_text(item)],
        "confidence": confidence,
    }


def is_almost_empty(entry: Dict[str, Any]) -> bool:
    if entry.get("title"):
        return False
    if entry.get("authors"):
        return False
    if entry.get("year"):
        return False
    if entry.get("doi"):
        return False
    if entry.get("venue"):
        return False
    if entry.get("pages"):
        return False
    if entry.get("type"):
        return False
    if entry.get("identifiers"):
        return False
    return True

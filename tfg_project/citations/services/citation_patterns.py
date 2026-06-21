# Patrones regex de citas in-text (numérico, autor-año narrativo y parentético) compartidos por backend y reader.
"""Patrones y utilidades de deteccion de citas in-text en textos academicos.

Este modulo concentra todos los regex de citas para que tanto el backend
(`citation_extractor`) como el frontend (`reader-app.jsx`) compartan la misma
definicion. Cubre los estilos mas comunes en papers cientificos:

- Numericas: ``[1]``, ``[1, 2]``, ``[1-3]``, ``[1; 2-4]``.
- Autor-anio narrativo: ``Smith (2020)``, ``Smith et al. (2020)``,
  ``Smith and Jones (2020)``, ``Smith et al. (2020a, 2021b)``.
- Autor-anio parentetico: ``(Smith, 2020)``, ``(Smith et al., 2020)``,
  ``(Smith and Jones, 2020)``, ``(Smith, 2020; Jones, 2021)``,
  ``(Smith 2020)`` (sin coma), ``(Garcia et al., 2020a)`` (con sufijo).
- DOI desnudo: ``10.1145/...`` (recortando puntuacion final).

La idea es: cualquier cita que un humano resaltaria con seleccion en el PDF
deberia detectarse aqui.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

# ---------------------------------------------------------------------------
# Regex publicos
# ---------------------------------------------------------------------------

# Numericas: [1], [1,2], [1-3], [1; 2-4], [12,13,14], soporta -, EN DASH, EM DASH.
NUMERIC_CITATION_REGEX = re.compile(
    r"\[\s*\d{1,4}(?:\s*(?:[,;]\s*\d{1,4}|\s*[-–—]\s*\d{1,4}))*\s*\]"
)

# Apellidos: aceptan Mayuscula inicial + minusculas/diacriticos/guiones/apostrofes.
# Cubre acentos latinos comunes y eszett, evitando que el regex se quede corto
# con apellidos como "Garcia", "Muller", "O'Brien", "Jimenez-Garcia".
# Tambien incluimos marcas diacriticas combinantes (U+0300..U+036F) para que
# funcione con texto descompuesto en NFKD (lo que devuelve el PDF text layer
# tras la normalizacion del frontend).
_NAME = r"[A-ZÀ-ÜĀ-ſ]" r"[A-Za-zÀ-ÿĀ-ſ'\-̀-ͯ]+"

# Grupo de autores: un apellido, dos con and/&, "et al." o lista enumerada.
_AUTHOR_GROUP = (
    rf"{_NAME}"
    rf"(?:"
    rf"\s+et\s+al\.?"
    rf"|\s+(?:and|&)\s+{_NAME}"
    rf"|(?:,\s+{_NAME}){{1,3}}(?:,?\s+(?:and|&)\s+{_NAME})?"
    rf")?"
)

# Anio plausible (1500-2099) opcionalmente con sufijo a-z (Smith, 2020a).
_YEAR = r"(?:1[5-9]|20)\d{2}[a-z]?"
_YEAR_LIST = rf"{_YEAR}(?:\s*,\s*{_YEAR})*"

# Narrativo: "Smith et al. (2020)", "Smith and Jones (2020a, 2021b)".
NARRATIVE_AUTHOR_YEAR_REGEX = re.compile(rf"\b{_AUTHOR_GROUP}\s*\(\s*{_YEAR_LIST}\s*\)")

# Parentetico: "(Smith, 2020)", "(Smith et al., 2020; Jones, 2021)",
# "(Smith 2020)" sin coma. Permite separadores ; o , entre items.
_PAREN_ITEM = rf"{_AUTHOR_GROUP}(?:\s*,)?\s+{_YEAR}"
PARENTHETICAL_AUTHOR_YEAR_REGEX = re.compile(
    rf"\(\s*{_PAREN_ITEM}(?:\s*[;]\s*{_PAREN_ITEM})*\s*\)"
)

# DOI: bloque base. Recortamos puntuacion final fuera del regex porque las
# DOIs pueden contener parentesis legitimos.
DOI_REGEX = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)

# Palabras que parecen apellidos pero no lo son y suelen aparecer junto a un
# anio en parentesis (ej. "Figure 1 (2020 dataset)"). Las descartamos para
# reducir falsos positivos en el detector de autor-anio.
_FALSE_POSITIVE_HEAD = frozenset(
    {
        "figure",
        "fig",
        "figures",
        "figs",
        "table",
        "tables",
        "tab",
        "section",
        "sections",
        "sec",
        "chapter",
        "chapters",
        "ch",
        "page",
        "pages",
        "pg",
        "equation",
        "equations",
        "eq",
        "eqs",
        "theorem",
        "theorems",
        "lemma",
        "lemmas",
        "corollary",
        "corollaries",
        "definition",
        "definitions",
        "proposition",
        "propositions",
        "algorithm",
        "algorithms",
        "alg",
        "listing",
        "listings",
        "appendix",
        "appendices",
        "app",
        "volume",
        "volumes",
        "vol",
        "issue",
        "no",
        "number",
        "numbers",
        "part",
        "parts",
        "step",
        "steps",
        "phase",
        "phases",
        "case",
        "cases",
        "example",
        "examples",
        "ex",
    }
)


# ---------------------------------------------------------------------------
# Funciones publicas
# ---------------------------------------------------------------------------


def expand_numeric_block(block_text: str, *, max_span: int = 50) -> List[int]:
    """Convierte ``[1, 2-4, 7]`` en ``[1, 2, 3, 4, 7]``.

    Mantiene el orden de aparicion y descarta numeros no positivos. Limita
    cada rango a ``max_span`` para evitar expansiones absurdas (errores OCR).
    """
    if not block_text:
        return []
    inner = str(block_text).strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]

    values: List[int] = []
    for part in re.split(r"[,;]", inner):
        token = part.replace("–", "-").replace("—", "-").strip()
        if not token:
            continue
        if "-" in token:
            bounds = [seg.strip() for seg in token.split("-", 1)]
            if len(bounds) != 2:
                continue
            try:
                start = int(bounds[0])
                end = int(bounds[1])
            except (TypeError, ValueError):
                continue
            step = 1 if start <= end else -1
            span = min(abs(end - start) + 1, max_span)
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


def is_valid_numeric_citation(number: Any, total_references: Any) -> bool:
    try:
        parsed_number = int(number)
        parsed_total = int(total_references)
    except (TypeError, ValueError):
        return False
    return 1 <= parsed_number <= parsed_total


def _strip_doi_trailing(value: str) -> str:
    """Retira puntuacion final no parte del DOI."""
    cleaned = value
    while cleaned and cleaned[-1] in ".,;:!?)]}>":
        # ')' puede ser legitimo si el DOI empezo con paren abierto sin cerrar.
        if cleaned[-1] == ")" and cleaned.count("(") > cleaned.count(")"):
            break
        cleaned = cleaned[:-1]
    return cleaned


def _looks_like_false_positive_authoryear(name_head: str) -> bool:
    return name_head.strip().lower() in _FALSE_POSITIVE_HEAD


def _make_snippet(text: str, start: int, end: int, padding: int = 80) -> str:
    left = max(start - padding, 0)
    right = min(end + padding, len(text))
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def find_citation_matches(
    paragraph: str,
    *,
    citation_style: str = "",
    total_references: int = 0,
    snippet_padding: int = 80,
) -> List[Dict[str, Any]]:
    """Localiza todas las citas in-text en ``paragraph``.

    Devuelve una lista ordenada por posicion con dicts homogeneos:

    ``{"type": "numeric"|"authoryear"|"doi", "match": str, "start": int,
       "end": int, "snippet": str, "confidence": float, ...extras}``

    - Para ``numeric`` incluye ``citation_block`` y ``citation_numbers``.
    - Para ``authoryear`` incluye ``authors`` (heuristico) y ``years``.
    - Para ``doi`` incluye ``doi``.

    Si ``citation_style == "numeric"`` y ``total_references > 0``, se
    descartan los numeros fuera de rango (filtra capturas accidentales como
    ``[42]`` cuando solo hay 30 referencias).
    """
    if not paragraph:
        return []

    style = str(citation_style or "").strip().lower()
    if style == "non-numeric":
        style = "non_numeric"

    hits: List[Dict[str, Any]] = []
    spans_taken: List[tuple[int, int]] = []

    def overlaps_existing(start: int, end: int) -> bool:
        for s, e in spans_taken:
            if start < e and end > s:
                return True
        return False

    # 1) Numericas.
    for m in NUMERIC_CITATION_REGEX.finditer(paragraph):
        block = m.group(0)
        numbers = expand_numeric_block(block)
        if style == "numeric" and total_references:
            numbers = [
                n for n in numbers if is_valid_numeric_citation(n, total_references)
            ]
            if not numbers:
                continue
        if not numbers:
            continue
        start, end = m.span()
        hits.append(
            {
                "type": "numeric",
                "match": block,
                "start": start,
                "end": end,
                "snippet": _make_snippet(paragraph, start, end, snippet_padding),
                "confidence": 0.95,
                "citation_block": block,
                "citation_numbers": numbers,
            }
        )
        spans_taken.append((start, end))

    # 2) DOI desnudos. Antes que autor-anio para evitar solapes.
    for m in DOI_REGEX.finditer(paragraph):
        raw = m.group(0)
        cleaned = _strip_doi_trailing(raw)
        if not cleaned or len(cleaned) < len("10.1/a"):
            continue
        start = m.start()
        end = start + len(cleaned)
        if overlaps_existing(start, end):
            continue
        hits.append(
            {
                "type": "doi",
                "match": cleaned,
                "start": start,
                "end": end,
                "snippet": _make_snippet(paragraph, start, end, snippet_padding),
                "confidence": 0.99,
                "doi": cleaned.lower(),
            }
        )
        spans_taken.append((start, end))

    # 3) Autor-anio narrativo: "Smith (2020)".
    for m in NARRATIVE_AUTHOR_YEAR_REGEX.finditer(paragraph):
        start, end = m.span()
        if overlaps_existing(start, end):
            continue
        head = paragraph[start:end].split("(", 1)[0].strip()
        first_token = head.split()[0] if head else ""
        if _looks_like_false_positive_authoryear(first_token):
            continue
        years = re.findall(_YEAR, paragraph[start:end])
        hits.append(
            {
                "type": "authoryear",
                "match": paragraph[start:end],
                "start": start,
                "end": end,
                "snippet": _make_snippet(paragraph, start, end, snippet_padding),
                "confidence": 0.85,
                "authors": head,
                "years": years,
                "style": "narrative",
            }
        )
        spans_taken.append((start, end))

    # 4) Autor-anio parentetico: "(Smith, 2020; Jones, 2021)".
    for m in PARENTHETICAL_AUTHOR_YEAR_REGEX.finditer(paragraph):
        start, end = m.span()
        if overlaps_existing(start, end):
            continue
        inner = paragraph[start:end].strip("() ")
        first_token = inner.split()[0] if inner else ""
        if _looks_like_false_positive_authoryear(first_token):
            continue
        years = re.findall(_YEAR, inner)
        if not years:
            continue
        hits.append(
            {
                "type": "authoryear",
                "match": paragraph[start:end],
                "start": start,
                "end": end,
                "snippet": _make_snippet(paragraph, start, end, snippet_padding),
                "confidence": 0.8,
                "authors": inner,
                "years": years,
                "style": "parenthetical",
            }
        )
        spans_taken.append((start, end))

    hits.sort(key=lambda h: (h["start"], h["end"]))
    return hits


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


def max_reference_index(references: Sequence[Dict[str, Any]] | None) -> int:
    if not references:
        return 0
    best = 0
    for reference in references:
        if not isinstance(reference, dict):
            continue
        raw_index = reference.get("index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index > best:
            best = index
    return best

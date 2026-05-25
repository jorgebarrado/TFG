"""ConstrucciÃ³n de referencias, anclajes y diagnÃ³sticos para el reader.

Este mÃ³dulo concentra heurÃ­sticas de extracciÃ³n que dependen de geometrÃ­a del
PDF, texto normalizado y metadatos externos. La prioridad de mantenimiento es
preservar el contrato de salida que consume el reader y los tests de regresiÃ³n.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from citations.logging_utils import get_logger

from .crossref_client import fetch_work_by_doi as crossref_fetch_work_by_doi
from .reference_reconciliation import validate_reference_against_metadata

logger = get_logger("citations.references")
TRACE_REFERENCES = os.getenv("TRACE_REFERENCES", "0") == "1"

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
INLINE_CITATION_REGEX = re.compile(
    r"\[\s*(\d+(?:\s*[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+)*)\s*\]"
)
BRACKETED_REFERENCE_LINE_RE = re.compile(r"^\s*\[\s*(\d+)\s*\]")
NUMBERED_REFERENCE_LINE_RE = BRACKETED_REFERENCE_LINE_RE
NUMBERED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")
DOTTED_REFERENCE_CANDIDATE_RE = re.compile(r"^\s*(\d{1,4})\.(.*)$")
SUFFIX_PAREN_REFERENCE_CANDIDATE_RE = re.compile(r"^\s*(\d{1,4})\)(.*)$")
WRAPPED_PAREN_REFERENCE_CANDIDATE_RE = re.compile(r"^\s*\(\s*(\d{1,4})\s*\)(.*)$")
SPLITTABLE_PAREN_ANCHOR_RE = re.compile(r"\(\s*\d{1,4}\s*\)|\b\d{1,4}\)")
MARKER_ONLY_BRACKETED_REFERENCE_RE = re.compile(r"^\s*\[\s*(\d{1,4})\s*\]\s*$")
MARKER_ONLY_DOTTED_REFERENCE_RE = re.compile(r"^\s*(\d{1,4})\.\s*$")
MARKER_ONLY_SUFFIX_PAREN_REFERENCE_RE = re.compile(r"^\s*(\d{1,4})\)\s*$")
MARKER_ONLY_WRAPPED_PAREN_REFERENCE_RE = re.compile(r"^\s*\(\s*(\d{1,4})\s*\)\s*$")
NUMERIC_ANCHOR_STYLES = (
    "bracketed",
    "dotted",
    "suffix_paren",
    "wrapped_paren",
)
REFERENCE_AUTHORISH_LEAD_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'`\-]{1,}"
    r"(?:\s+(?:[A-Z]{1,4}\.?|[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'`\-]{1,})){0,2}"
    r"(?:,|\.|\s+et\s+al\.?)"
)
DOTTED_ANCHOR_DOI_LIKE_RE = re.compile(
    r"^(?:/|doi\b|https?://|www\.|\d{2,9}\s*/|\d{2,9}(?:[-._]\d+){2,})",
    re.IGNORECASE,
)
HEADER_LIKE_REFERENCE_RE = re.compile(
    r"\b(?:wipsce|copyright|all rights reserved|acm isbn|proceedings)\b",
    re.IGNORECASE,
)
FIXED_ARTIFACT_RE = re.compile(
    r"\b(?:proceedings|copyright|all rights reserved|acm isbn|issn|vol\.|volume|number|no\.)\b",
    re.IGNORECASE,
)
PAGE_NUMBER_ONLY_RE = re.compile(r"^\s*\(?\d{1,4}\)?\s*$")
REFERENCE_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
REFERENCE_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
REFERENCE_GLUE_RE = re.compile(r"\b[A-Za-zÀ-ÿ]{4,}[a-zà-ÿ][A-ZÀ-ß][A-Za-zÀ-ÿ]{2,}\b")
REFERENCE_TRAILING_AFTER_DOI_RE = re.compile(
    r"(?:https?://\S+|10\.\d{4,9}/\S+)\s+[A-Za-zÀ-ÿ]",
    re.IGNORECASE,
)
REFERENCE_FRAGMENT_AFTER_PAGES_RE = re.compile(
    r"\b\d+(?:[–-]\d+)?\.\s+"
    r"(?:of|education|network|behavior|methods|technology|sciences)\b",
    re.IGNORECASE,
)
REFERENCE_END_CONNECTORS = (
    "and",
    "for",
    "from",
    "of",
    "the",
    "through",
    "with",
)
REFERENCE_MIDDLE_CONNECTORS = (
    "and",
    "for",
    "from",
    "through",
    "using",
    "with",
    "without",
)
REFERENCE_SUFFIX_SPLITS = (
    "analysis",
    "behavior",
    "computing",
    "education",
    "network",
    "practice",
    "programming",
    "programs",
    "school",
    "sciences",
    "technology",
    "technologies",
    "thinking",
)
REFERENCE_GLUE_SUFFIX_CONNECTORS = (
    "and",
    "for",
    "the",
    "through",
    "with",
)
REFERENCE_TRAILING_VENUE_FRAGMENT_RE = re.compile(
    r"\b(?:journal|transactions?|proceedings?|behavior|methods|network|computing)\b"
    r".{0,80}\.\s+"
    r"(?:of|for|education|network|behavior|methods|technology|sciences)\b",
    re.IGNORECASE,
)
REFERENCE_COMPARE_NORMALIZE_RE = re.compile(r"[^\w]+", re.UNICODE)
REFERENCE_NOISE_RE = re.compile(
    r"\b(?:"
    r"view publication stats|"
    r"researchgate|"
    r"wipsce\s*[’']?\s*\d{2}|"
    r"nijmegen,\s*netherlands|"
    r"brackmann,\s*rom[aá]n-gonz[aá]lez,\s*robles,\s*moreno-le[oó]n,\s*casali\s*and\s*barone"
    r")\b",
    re.IGNORECASE,
)
REFERENCE_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:references|bibliography|referencias|bibliografia|works cited)\s*$",
    re.IGNORECASE,
)
REFERENCE_DEBUG_FILE_PREFIX = "debug-"
REFERENCE_DEBUG_FILE_EXTENSION = ".json"
REFERENCE_PIPELINE_VERSION = "references-phased-v4"
NUMERIC_REFERENCE_PIPELINE_V2_NAME = "numeric_reference_pipeline_v2"
NUMERIC_REFERENCE_PIPELINE_V2_RUN_MODE = "debug_only"
NUMERIC_REFERENCE_PIPELINE_V3_NAME = "numeric_reference_pipeline_v3"
NUMERIC_REFERENCE_PIPELINE_V3_RUN_MODE = "debug_only"
REFERENCE_DEBUG_DIR = Path(__file__).resolve().parents[3] / "tmp" / "reference_debug"
REFERENCE_DIAGNOSTIC_TAIL_NOISE_MARKERS = (
    "cite this article",
    "how to cite",
    "copyright",
    "received:",
    "accepted:",
    "published online",
    "correspondence:",
    "license",
    "funding:",
)
ROW_REJECTION_AUDIT_LIMIT = 120
REFERENCE_FAILURE_AUDIT_LIMIT = 80


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _to_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _normalize_page_zero_based(raw_page: Any) -> Optional[int]:
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None
    # Snippets suelen venir 1-based; layers ya vienen 0-based.
    if page > 0:
        return page - 1
    return page


def _normalize_box(raw_box: Any) -> Optional[List[float]]:
    if not isinstance(raw_box, (list, tuple)) or len(raw_box) < 4:
        return None

    x = _to_float(raw_box[0])
    y = _to_float(raw_box[1])
    w = _to_float(raw_box[2])
    h = _to_float(raw_box[3])
    if x is None or y is None or w is None or h is None:
        return None
    if w <= 0 or h <= 0:
        return None

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w <= 0 or h <= 0:
        return None
    return [x, y, w, h]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _normalize_mention_text(text: str) -> str:
    normalized = _normalize_text(text or "")
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _quantize_box(
    box: Any, decimals: int = 3
) -> Optional[Tuple[float, float, float, float]]:
    normalized_box = _normalize_box(box)
    if normalized_box is None:
        return None
    return tuple(round(float(value), decimals) for value in normalized_box)


def _tokenize(value: str) -> set[str]:
    text = _normalize_text(value)
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text)
        if token not in {"http", "https", "www", "doi"}
    }


def _normalize_doi(value: str) -> str:
    candidate = str(value or "").strip()
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    return candidate.rstrip(").,;:]").strip().lower()


def _extract_doi(text: str) -> str:
    if not text:
        return ""
    url_match = DOI_URL_REGEX.search(text)
    if url_match:
        return _normalize_doi(url_match.group(1))
    match = DOI_REGEX.search(text)
    if match:
        return _normalize_doi(match.group(0))
    return ""


def _parse_citation_numbers(text: str) -> List[int]:
    if not text:
        return []
    numbers: set[int] = set()
    for match in INLINE_CITATION_REGEX.finditer(text):
        raw = match.group(1)
        parts = re.split(r"[,;]", raw)
        for part in parts:
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
                    numbers.add(start + idx * step)
                continue
            try:
                numbers.add(int(token))
            except (TypeError, ValueError):
                continue
    return sorted(number for number in numbers if number > 0)


def _entry_index(entry: Dict[str, Any]) -> Optional[int]:
    raw_index = entry.get("index")
    if isinstance(raw_index, int) and raw_index > 0:
        return raw_index
    try:
        parsed = int(raw_index)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return None


def _layer_items(layers: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    raw_items = layers.get(key)
    if not isinstance(raw_items, list):
        return []
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        if not isinstance(page, int):
            try:
                page = int(page)
            except (TypeError, ValueError):
                continue
        box = _normalize_box(item.get("box"))
        if page < 0 or box is None:
            continue
        out.append(
            {
                "id": str(item.get("id") or f"{key}-{idx}"),
                "text": str(item.get("text") or ""),
                "page": page,
                "box": box,
            }
        )
    return out


def _reference_match_score(
    reference_text: str, reference_index: int, reference_doi: str, candidate_text: str
) -> float:
    score = 0.0
    cand_norm = _normalize_text(candidate_text)
    if not cand_norm:
        return score

    if reference_doi and reference_doi in cand_norm:
        score += 5.0

    if reference_index > 0:
        if re.search(rf"^\s*\[\s*{reference_index}\s*\]", cand_norm):
            score += 3.0
        elif re.search(rf"^\s*{reference_index}[\.\)]\s*", cand_norm):
            score += 2.5

    ref_tokens = _tokenize(reference_text)
    cand_tokens = _tokenize(candidate_text)
    if ref_tokens and cand_tokens:
        overlap = len(ref_tokens.intersection(cand_tokens))
        score += overlap / max(len(ref_tokens), 1)

    return score


def _box_center(box: Sequence[float]) -> Tuple[float, float]:
    return (float(box[0]) + float(box[2]) / 2.0, float(box[1]) + float(box[3]) / 2.0)


def _contains_box(container: Sequence[float], inner: Sequence[float]) -> bool:
    cx, cy = _box_center(inner)
    return float(container[0]) <= cx <= float(container[0]) + float(
        container[2]
    ) and float(container[1]) <= cy <= float(container[1]) + float(container[3])


def is_after_bibliography(
    page: Optional[int],
    y: Optional[float],
    bibliography_anchor: Optional[Tuple[int, float]],
) -> bool:
    if bibliography_anchor is None:
        return False
    if not isinstance(page, int) or page < 0:
        return False

    anchor_page, anchor_y = bibliography_anchor
    if page > anchor_page:
        return True
    if page < anchor_page:
        return False
    if y is None:
        return True
    return float(y) >= float(anchor_y)


def is_inside_bibliography(
    box: Any,
    bibliography_items: Sequence[Dict[str, Any]],
) -> bool:
    if not bibliography_items:
        return False

    candidate_page: Optional[int] = None
    candidate_box: Optional[List[float]] = None
    if isinstance(box, dict):
        raw_page = box.get("page")
        if isinstance(raw_page, int) and raw_page >= 0:
            candidate_page = raw_page
        candidate_box = _normalize_box(box.get("box"))
    else:
        candidate_box = _normalize_box(box)

    if candidate_box is None:
        return False

    for bibliography_item in bibliography_items:
        bibliography_page = bibliography_item.get("page")
        bibliography_box = bibliography_item.get("box")
        if not isinstance(bibliography_page, int) or bibliography_page < 0:
            continue
        if candidate_page is not None and bibliography_page != candidate_page:
            continue
        if not isinstance(bibliography_box, (list, tuple)) or len(bibliography_box) < 4:
            continue
        if _contains_box(bibliography_box, candidate_box):
            return True
        if _overlap_ratio(bibliography_box, candidate_box) >= 0.6:
            return True
    return False


def _overlap_ratio(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    ax0 = float(box_a[0])
    ay0 = float(box_a[1])
    ax1 = ax0 + float(box_a[2])
    ay1 = ay0 + float(box_a[3])
    bx0 = float(box_b[0])
    by0 = float(box_b[1])
    bx1 = bx0 + float(box_b[2])
    by1 = by0 + float(box_b[3])

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    area = max(float(box_b[2]) * float(box_b[3]), 1e-9)
    return inter / area


def _box_area(box: Sequence[float]) -> float:
    return max(float(box[2]), 0.0) * max(float(box[3]), 0.0)


def _box_iou(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    ax0 = float(box_a[0])
    ay0 = float(box_a[1])
    ax1 = ax0 + float(box_a[2])
    ay1 = ay0 + float(box_a[3])
    bx0 = float(box_b[0])
    by0 = float(box_b[1])
    bx1 = bx0 + float(box_b[2])
    by1 = by0 + float(box_b[3])

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = _box_area(box_a) + _box_area(box_b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def _union_boxes(boxes: Sequence[Sequence[float]]) -> Optional[List[float]]:
    if not boxes:
        return None
    x0 = min(float(box[0]) for box in boxes)
    y0 = min(float(box[1]) for box in boxes)
    x1 = max(float(box[0]) + float(box[2]) for box in boxes)
    y1 = max(float(box[1]) + float(box[3]) for box in boxes)
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    if width <= 0 or height <= 0:
        return None
    return [x0, y0, width, height]


def _line_sort_key(line: Dict[str, Any]) -> Tuple[int, float, float]:
    page = int(line.get("page", 0))
    y0 = _to_float(line.get("y0"))
    x0 = _to_float(line.get("x0"))
    if y0 is None or x0 is None:
        box = line.get("box") or [0.0, 0.0, 0.0, 0.0]
        return (page, float(box[1]), float(box[0]))
    return (page, float(y0), float(x0))


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _is_reference_noise_text(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return bool(REFERENCE_NOISE_RE.search(text))


def _split_reference_row_on_anchors(
    row: Dict[str, Any],
) -> List[Dict[str, Any]]:
    text = str(row.get("text") or "").strip()
    allow_noise_override = bool(
        row.get("header_footer_noise_overridden")
        or str(row.get("noise_override") or "").strip()
        == "bibliography_continuation_context"
    )
    if not text or (_is_reference_noise_text(text) and not allow_noise_override):
        return []

    split_matches: List[Tuple[int, int]] = [
        (match.start(), match.end()) for match in NUMBERED_ANCHOR_RE.finditer(text)
    ]
    for match in SPLITTABLE_PAREN_ANCHOR_RE.finditer(text):
        candidate = _match_reference_anchor_at_line_start(text[match.start() :])
        if not candidate or not candidate.get("accepted"):
            continue
        candidate_style = str(candidate.get("anchor_style") or "")
        if candidate_style not in {"suffix_paren", "wrapped_paren"}:
            continue
        if match.start() > 0 and not text[match.start() - 1].isspace():
            continue
        split_matches.append((match.start(), match.end()))
    matches = sorted(set(split_matches))
    if not matches:
        return [dict(row)]

    spans: List[Tuple[int, int]] = []
    if matches[0][0] > 0:
        spans.append((0, matches[0][0]))
    for idx, match in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(text)
        spans.append((match[0], next_start))

    parts: List[Dict[str, Any]] = []
    for part_idx, (start_char, end_char) in enumerate(spans):
        segment_text = text[start_char:end_char].strip()
        if not segment_text or (
            _is_reference_noise_text(segment_text) and not allow_noise_override
        ):
            continue
        next_row = dict(row)
        next_row["id"] = f"{row.get('id') or 'row'}::seg-{part_idx}"
        next_row["text"] = segment_text
        next_row["split_segment"] = True
        next_row["split_segment_index"] = part_idx
        next_row["split_segment_total"] = len(spans)
        parts.append(next_row)
    return parts


def _sanitize_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("._")
    return cleaned or "reference_debug"


def _box_to_corners(box: Sequence[float]) -> Dict[str, float]:
    return {
        "x0": round(float(box[0]), 6),
        "y0": round(float(box[1]), 6),
        "x1": round(float(box[0]) + float(box[2]), 6),
        "y1": round(float(box[1]) + float(box[3]), 6),
    }


def _box_from_corners(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> Optional[List[float]]:
    width = float(x1) - float(x0)
    height = float(y1) - float(y0)
    if width <= 0 or height <= 0:
        return None
    return _normalize_box([x0, y0, width, height])


def _serialize_box(box: Any) -> Optional[Dict[str, float]]:
    normalized_box = _normalize_box(box)
    if normalized_box is None:
        return None
    return _box_to_corners(normalized_box)


def _serialize_layer_item(item: Dict[str, Any]) -> Dict[str, Any]:
    serialized = {
        "id": str(item.get("id") or ""),
        "text": str(item.get("text") or ""),
        "page": item.get("page"),
        "box": _serialize_box(item.get("box")),
    }
    if "column_id" in item:
        serialized["column_id"] = item.get("column_id")
    if "anchor_index" in item:
        serialized["anchor_index"] = item.get("anchor_index")
    return serialized


def _is_reference_heading_text(value: str) -> bool:
    return bool(REFERENCE_SECTION_HEADING_RE.match(str(value or "").strip()))


def _has_bibliographic_lead_signal(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) < 16 or not normalized or not normalized[0].isalpha():
        return False
    if DOI_REGEX.match(normalized) or DOI_URL_REGEX.match(normalized):
        return False

    alpha_words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", normalized[:96])
    if len(alpha_words) < 3:
        return False

    head = normalized[:120]
    if REFERENCE_AUTHORISH_LEAD_RE.match(head):
        return True

    comma_early = "," in head[:48]
    year_present = bool(REFERENCE_YEAR_RE.search(normalized[:180]))
    et_al_early = bool(re.search(r"\bet\s+al\.?\b", head, re.IGNORECASE))
    return bool((comma_early and year_present) or et_al_early)


def _match_reference_anchor_at_line_start(
    text: str,
    *,
    include_rejected: bool = False,
) -> Optional[Dict[str, Any]]:
    value = str(text or "")

    bracketed_match = BRACKETED_REFERENCE_LINE_RE.match(value)
    if bracketed_match:
        try:
            index = int(bracketed_match.group(1))
        except (TypeError, ValueError):
            index = 0
        if index > 0:
            return {
                "index": index,
                "anchor_style": "bracketed",
                "accepted": True,
                "anchor_rejected_reason": None,
            }

    dotted_match = DOTTED_REFERENCE_CANDIDATE_RE.match(value)
    if dotted_match:
        try:
            index = int(dotted_match.group(1))
        except (TypeError, ValueError):
            return None
        if index <= 0:
            return None

        tail_raw = dotted_match.group(2) or ""
        tail = tail_raw.lstrip()
        has_spacing_after_dot = bool(tail_raw[:1].isspace())
        rejected_reason: Optional[str] = None

        if not tail:
            rejected_reason = "weak_bibliographic_signal"
        elif DOTTED_ANCHOR_DOI_LIKE_RE.match(tail):
            rejected_reason = "doi_like"
        elif not has_spacing_after_dot and not tail[0].isalpha():
            rejected_reason = "missing_spacing"
        elif not _has_bibliographic_lead_signal(tail):
            rejected_reason = "weak_bibliographic_signal"

        candidate = {
            "index": index,
            "anchor_style": "dotted",
            "accepted": rejected_reason is None,
            "anchor_rejected_reason": rejected_reason,
        }
        if candidate["accepted"] or include_rejected:
            return candidate
    for candidate_pattern, candidate_style in (
        (SUFFIX_PAREN_REFERENCE_CANDIDATE_RE, "suffix_paren"),
        (WRAPPED_PAREN_REFERENCE_CANDIDATE_RE, "wrapped_paren"),
    ):
        candidate_match = candidate_pattern.match(value)
        if not candidate_match:
            continue
        try:
            candidate_index = int(candidate_match.group(1))
        except (TypeError, ValueError):
            return None
        if candidate_index <= 0:
            return None

        tail_raw = candidate_match.group(2) or ""
        tail = tail_raw.lstrip()
        has_spacing_after_marker = bool(tail_raw[:1].isspace())
        candidate_rejected_reason: Optional[str] = None

        if 1900 <= candidate_index <= 2099:
            candidate_rejected_reason = "year_like"
        elif not tail:
            candidate_rejected_reason = "weak_bibliographic_signal"
        elif DOTTED_ANCHOR_DOI_LIKE_RE.match(tail):
            candidate_rejected_reason = "doi_like"
        elif not has_spacing_after_marker and not tail[0].isalpha():
            candidate_rejected_reason = "missing_spacing"
        elif not _has_bibliographic_lead_signal(tail):
            candidate_rejected_reason = "weak_bibliographic_signal"

        candidate = {
            "index": candidate_index,
            "anchor_style": candidate_style,
            "accepted": candidate_rejected_reason is None,
            "anchor_rejected_reason": candidate_rejected_reason,
        }
        if candidate["accepted"] or include_rejected:
            return candidate
    return None


def _extract_inline_anchor_numbers(text: str) -> List[int]:
    numbers: List[int] = []
    seen: set[int] = set()
    leading_anchor = _match_reference_anchor_at_line_start(text)
    if leading_anchor and leading_anchor.get("accepted"):
        try:
            index = int(leading_anchor.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        if index > 0:
            numbers.append(index)
            seen.add(index)
    for match in NUMBERED_ANCHOR_RE.finditer(text or ""):
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in seen:
            numbers.append(number)
            seen.add(number)
    return numbers


def _score_header_noise(text: str) -> float:
    normalized = _normalize_text(text or "")
    if not normalized:
        return 1.0
    if REFERENCE_NOISE_RE.search(normalized):
        return 1.0
    if _is_reference_heading_text(normalized):
        return 0.88
    if HEADER_LIKE_REFERENCE_RE.search(normalized):
        has_reference_signals = bool(
            REFERENCE_YEAR_RE.search(normalized)
            or _extract_doi(text or "")
            or len(normalized) >= 90
            or bool(_match_reference_anchor_at_line_start(text))
        )
        if not has_reference_signals:
            return 0.74
    if FIXED_ARTIFACT_RE.search(normalized):
        has_reference_signals = bool(
            REFERENCE_YEAR_RE.search(normalized)
            or _extract_doi(text or "")
            or len(normalized) >= 90
        )
        if not has_reference_signals:
            return 0.56
    if PAGE_NUMBER_ONLY_RE.match(normalized):
        return 0.92
    return 0.0


def _normalize_crossref_reference_candidate(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = {
        "doi": _normalize_doi(candidate.get("doi")),
        "title": str(candidate.get("title") or "").strip(),
        "authors": [
            str(author).strip()
            for author in (candidate.get("authors") or [])
            if str(author).strip()
        ],
        "year": candidate.get("year"),
        "venue": str(candidate.get("venue") or "").strip() or None,
        "raw_text": str(candidate.get("raw_text") or "").strip(),
        "source": str(candidate.get("source") or "crossref"),
    }
    if not normalized["raw_text"]:
        normalized["raw_text"] = " ".join(
            part
            for part in [
                normalized["title"],
                ", ".join(normalized["authors"]),
                str(normalized["year"] or "").strip(),
                str(normalized["venue"] or "").strip(),
            ]
            if part
        ).strip()
    return normalized


def _detect_article_doi_from_rows(
    row_items: Sequence[Dict[str, Any]],
    bibliography_start_page: Optional[int],
) -> str:
    best_candidate = ""
    best_rank: Optional[Tuple[int, float, int]] = None
    max_page = (
        bibliography_start_page if isinstance(bibliography_start_page, int) else 3
    )
    for row in row_items:
        page = row.get("page")
        box = _normalize_box(row.get("box"))
        text = str(row.get("text") or "")
        if not isinstance(page, int) or page < 0 or page > max_page:
            continue
        if box is None or not text:
            continue
        candidate_doi = _extract_doi(text)
        if not candidate_doi:
            continue
        normalized = _normalize_text(text)
        has_explicit_doi_label = "doi" in normalized
        has_article_like_context = any(
            token in normalized
            for token in ("doi:", "https://doi.org/", "acm isbn", "article")
        )
        y0 = float(box[1])
        priority = 0
        if has_explicit_doi_label:
            priority -= 4
        if has_article_like_context:
            priority -= 2
        if page == 0:
            priority -= 2
        rank = (priority, y0, page)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_candidate = candidate_doi
    return best_candidate


def _prepare_crossref_context(
    *,
    article_doi: str,
    row_items: Sequence[Dict[str, Any]],
    bibliography_start_page: Optional[int],
) -> Dict[str, Any]:
    detected_doi = _normalize_doi(article_doi) or _detect_article_doi_from_rows(
        row_items,
        bibliography_start_page,
    )
    context: Dict[str, Any] = {
        "article_doi": detected_doi or None,
        "crossref_available": False,
        "crossref_queried": False,
        "crossref_article_metadata": None,
        "crossref_reference_candidates": [],
        "crossref_reference_count": 0,
    }
    if not detected_doi:
        return context

    context["crossref_queried"] = True
    try:
        crossref_work = crossref_fetch_work_by_doi(detected_doi, timeout=6)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("crossref phase failed doi=%s error=%s", detected_doi, exc)
        crossref_work = None
    if not isinstance(crossref_work, dict):
        return context

    references = [
        _normalize_crossref_reference_candidate(candidate)
        for candidate in (crossref_work.get("references") or [])
        if isinstance(candidate, dict)
    ]
    context["crossref_available"] = True
    context["crossref_article_metadata"] = {
        "doi": _normalize_doi(crossref_work.get("doi")),
        "title": str(crossref_work.get("title") or "").strip(),
        "authors": [
            str(author).strip()
            for author in (crossref_work.get("authors") or [])
            if str(author).strip()
        ],
        "year": crossref_work.get("year"),
        "venue": str(crossref_work.get("venue") or "").strip() or None,
        "url": str(crossref_work.get("url") or "").strip() or None,
        "source": str(crossref_work.get("source") or "crossref"),
    }
    context["crossref_reference_candidates"] = references
    context["crossref_reference_count"] = int(
        crossref_work.get("reference_count") or len(references)
    )
    return context


def _collect_bibliography_lines(
    rows: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
    bibliography_anchor: Optional[Tuple[int, float]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int, str]] = set()
    for row in rows:
        text = str(row.get("text") or "").strip()
        page = row.get("page")
        box = _normalize_box(row.get("box"))
        if not text or not isinstance(page, int) or box is None:
            continue
        if _is_reference_noise_text(text):
            continue

        x0 = float(box[0])
        y0 = float(box[1])
        x1 = x0 + float(box[2])
        y1 = y0 + float(box[3])
        y = _to_float(y0)
        if y is not None and (y < 0.01 or y > 0.99):
            continue

        in_scope = False
        if bibliography_items and is_inside_bibliography(
            {"page": page, "box": box},
            bibliography_items,
        ):
            in_scope = True
        elif is_after_bibliography(page, y, bibliography_anchor):
            in_scope = True
        if not in_scope:
            continue

        dedupe_key = (
            page,
            int(round(float(box[1]) * 10000)),
            _normalize_text(text)[:180],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(
            {
                "id": str(row.get("id") or f"row-{page}-{len(out) + 1}"),
                "text": text,
                "page": page,
                "box": box,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "width": float(box[2]),
                "height": float(box[3]),
            }
        )

    exploded: List[Dict[str, Any]] = []
    for row in out:
        exploded.extend(_split_reference_row_on_anchors(row))
    return exploded


def _artifact_text_key(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"\b\d+\b", "#", normalized)
    normalized = re.sub(r"[^a-z0-9#\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_repeating_page_artifacts(
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    pages_per_key: Dict[str, set[int]] = defaultdict(set)
    for row in rows:
        page = row.get("page")
        text = str(row.get("text") or "").strip()
        y0 = _to_float(row.get("y0"))
        y1 = _to_float(row.get("y1"))
        if not isinstance(page, int) or not text:
            continue
        if y0 is None or y1 is None:
            continue
        if y0 > 0.16 and y1 < 0.84:
            continue
        key = _artifact_text_key(text)
        if len(key) < 9:
            continue
        pages_per_key[key].add(page)
    repeated_keys = {key for key, pages in pages_per_key.items() if len(pages) >= 2}
    return {"repeated_text_keys": repeated_keys}


def _is_header_footer_row(
    row: Dict[str, Any],
    artifact_info: Dict[str, Any],
) -> bool:
    text = str(row.get("text") or "").strip()
    if not text:
        return True
    if _is_reference_noise_text(text):
        return True
    if _match_reference_anchor_at_line_start(text):
        return False
    y0 = _to_float(row.get("y0"))
    y1 = _to_float(row.get("y1"))
    if y0 is None or y1 is None:
        box = _normalize_box(row.get("box"))
        if box is not None:
            y0 = float(box[1])
            y1 = y0 + float(box[3])
    in_margin = (
        y0 is not None and y1 is not None and (float(y0) <= 0.14 or float(y1) >= 0.88)
    )
    if in_margin and PAGE_NUMBER_ONLY_RE.match(text):
        return True
    if in_margin and FIXED_ARTIFACT_RE.search(text):
        has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", text))
        has_doi = bool(_extract_doi(text))
        if not has_year and not has_doi and len(text) <= 140:
            return True
    key = _artifact_text_key(text)
    repeated_keys = artifact_info.get("repeated_text_keys", set())
    if in_margin and key and key in repeated_keys:
        return True
    return False


def _build_same_column_row_context(
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    grouped_rows: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        page = row.get("page")
        column_id = str(row.get("column_id") or "left")
        if not isinstance(page, int):
            continue
        grouped_rows[(page, column_id)].append(row)

    context_by_row_id: Dict[str, Dict[str, Any]] = {}
    for (page, column_id), page_rows in grouped_rows.items():
        ordered_rows = sorted(page_rows, key=_line_sort_key)
        anchor_payloads: List[Optional[Dict[str, Any]]] = []
        for row in ordered_rows:
            anchor = _match_reference_anchor_at_line_start(str(row.get("text") or ""))
            if anchor and anchor.get("accepted"):
                anchor_payloads.append(
                    {
                        "index": int(anchor.get("index") or 0),
                        "page": page,
                        "column_id": column_id,
                        "row": row,
                    }
                )
            else:
                anchor_payloads.append(None)

        next_anchor = None
        next_anchor_by_idx: List[Optional[Dict[str, Any]]] = [None] * len(ordered_rows)
        for idx in range(len(ordered_rows) - 1, -1, -1):
            next_anchor_by_idx[idx] = next_anchor
            if anchor_payloads[idx] is not None:
                next_anchor = anchor_payloads[idx]

        previous_anchor = None
        for idx, row in enumerate(ordered_rows):
            row_id = str(row.get("id") or f"{page}:{column_id}:{idx}")
            context_by_row_id[row_id] = {
                "previous_row": ordered_rows[idx - 1] if idx > 0 else None,
                "next_row": (
                    ordered_rows[idx + 1] if idx + 1 < len(ordered_rows) else None
                ),
                "current_anchor": previous_anchor,
                "next_anchor": next_anchor_by_idx[idx],
            }
            if anchor_payloads[idx] is not None:
                previous_anchor = anchor_payloads[idx]
    return context_by_row_id


def _strong_bibliography_continuation_row(
    *,
    row: Dict[str, Any],
    previous_row: Optional[Dict[str, Any]],
    current_anchor: Optional[Dict[str, Any]],
    next_anchor: Optional[Dict[str, Any]],
    in_bibliography_zone: bool,
) -> Dict[str, Any]:
    result = {"accepted": False, "reasons": []}
    text = str(row.get("text") or "").strip()
    if not in_bibliography_zone or not text:
        return result

    row_page = row.get("page")
    row_column = str(row.get("column_id") or "left")
    if not isinstance(row_page, int):
        return result
    if _match_reference_anchor_at_line_start(text):
        return result
    if _is_reference_heading_text(text) or _is_reference_header_like(text):
        return result

    current_index = int((current_anchor or {}).get("index") or 0)
    next_index = int((next_anchor or {}).get("index") or 0)
    current_page = (current_anchor or {}).get("page")
    next_page = (next_anchor or {}).get("page")
    current_column = str((current_anchor or {}).get("column_id") or "left")
    next_column = str((next_anchor or {}).get("column_id") or "left")
    if (
        current_index <= 0
        or next_index != current_index + 1
        or row_page != current_page
        or row_page != next_page
        or row_column != current_column
        or row_column != next_column
    ):
        return result

    if not isinstance(previous_row, dict):
        return result
    previous_page = previous_row.get("page")
    previous_column = str(previous_row.get("column_id") or "left")
    if row_page != previous_page or row_column != previous_column:
        return result

    row_box = _normalize_box(row.get("box"))
    previous_box = _normalize_box(previous_row.get("box"))
    next_anchor_row = (next_anchor or {}).get("row") or next_anchor or {}
    next_anchor_box = _normalize_box(next_anchor_row.get("box"))
    if row_box is None or previous_box is None or next_anchor_box is None:
        return result

    row_y0 = float(row_box[1])
    row_y1 = row_y0 + float(row_box[3])
    previous_y1 = float(previous_box[1]) + float(previous_box[3])
    next_anchor_y0 = float(next_anchor_box[1])
    gap_from_previous = row_y0 - previous_y1
    gap_to_next_anchor = next_anchor_y0 - row_y1
    if gap_from_previous < -0.004 or gap_from_previous > 0.045:
        return result
    if gap_to_next_anchor < -0.004 or gap_to_next_anchor > 0.065:
        return result

    previous_x0 = float(previous_box[0])
    previous_x1 = previous_x0 + float(previous_box[2])
    row_x0 = float(row_box[0])
    row_x1 = row_x0 + float(row_box[2])
    if abs(row_x0 - previous_x0) > 0.08 or abs(row_x1 - previous_x1) > 0.06:
        return result

    if row_y0 <= 0.14 or row_y1 >= 0.88:
        return result

    alpha_words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", text)
    has_bibliographic_text = bool(
        _extract_doi(text) or REFERENCE_YEAR_RE.search(text) or len(text) >= 72
    )
    if len(alpha_words) < 6 or not has_bibliographic_text:
        return result

    result["accepted"] = True
    result["reasons"] = [
        "same_column_between_anchors",
        "vertical_continuity_ok",
        "horizontal_alignment_ok",
        "no_new_section_detected",
        "bibliographic_text_ok",
    ]
    return result


def _detect_page_column_split(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    if len(rows) < 4:
        return None
    content_rows = [
        row
        for row in rows
        if (
            (
                _to_float(row.get("y0"))
                or (_normalize_box(row.get("box")) or [0.0, 0.0, 0.0, 0.0])[1]
            )
            > 0.08
            and (
                _to_float(row.get("y1"))
                or (
                    ((_normalize_box(row.get("box")) or [0.0, 0.0, 0.0, 0.0])[1])
                    + ((_normalize_box(row.get("box")) or [0.0, 0.0, 0.0, 0.0])[3])
                )
            )
            < 0.94
        )
    ]
    sample = content_rows if len(content_rows) >= 4 else list(rows)
    x_values = sorted(
        float(
            _to_float(row.get("x0"))
            if _to_float(row.get("x0")) is not None
            else (_normalize_box(row.get("box")) or [0.0, 0.0, 0.0, 0.0])[0]
        )
        for row in sample
        if _to_float(row.get("x0")) is not None
        or _normalize_box(row.get("box")) is not None
    )
    if len(x_values) < 4:
        return None

    left_cluster = [
        float(row.get("x0"))
        for row in sample
        if _to_float(row.get("x0")) is not None and float(row.get("x0")) <= 0.32
    ]
    right_cluster = [
        float(row.get("x0"))
        for row in sample
        if _to_float(row.get("x0")) is not None and float(row.get("x0")) >= 0.45
    ]
    if len(left_cluster) >= 3 and len(right_cluster) >= 3:
        left_median = _median(left_cluster)
        right_median = _median(right_cluster)
        if right_median - left_median >= 0.18:
            return (left_median + right_median) / 2.0

    max_gap = 0.0
    split_threshold: Optional[float] = None
    for left_x, right_x in zip(x_values, x_values[1:]):
        gap = float(right_x) - float(left_x)
        if gap > max_gap:
            max_gap = gap
            split_threshold = (float(left_x) + float(right_x)) / 2.0
    gap_threshold = 0.2 if len(sample) < 8 else 0.12
    if split_threshold is None or max_gap < gap_threshold:
        return None
    left_count = sum(1 for row in sample if float(row.get("x0", 0.0)) < split_threshold)
    right_count = len(sample) - left_count
    min_side_count = 2 if len(sample) < 8 else 3
    if left_count < min_side_count or right_count < min_side_count:
        return None
    balance = min(left_count, right_count) / max(left_count, right_count)
    if balance < 0.18:
        return None
    return split_threshold


def _assign_column_ids(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        page = row.get("page")
        if not isinstance(page, int):
            continue
        next_row = dict(row)
        box = _normalize_box(next_row.get("box"))
        if box is not None:
            next_row.setdefault("x0", float(box[0]))
            next_row.setdefault("y0", float(box[1]))
            next_row.setdefault("x1", float(box[0]) + float(box[2]))
            next_row.setdefault("y1", float(box[1]) + float(box[3]))
        by_page[page].append(next_row)

    out: List[Dict[str, Any]] = []
    for page in sorted(by_page.keys()):
        page_rows = by_page[page]
        split = _detect_page_column_split(page_rows)
        for row in page_rows:
            next_row = dict(row)
            x_center = (
                float(next_row.get("x0", 0.0)) + float(next_row.get("x1", 0.0))
            ) / 2.0
            if split is None:
                column_id = "left"
            else:
                column_id = "left" if x_center < split else "right"
            next_row["column_id"] = column_id
            if split is not None:
                next_row["column_split_x"] = split
            out.append(next_row)
    return out


def build_bibliography_reading_flow(
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in _assign_column_ids(rows):
        page = row.get("page")
        if not isinstance(page, int):
            continue
        by_page[page].append(row)

    ordered: List[Dict[str, Any]] = []
    flow_position = 0
    for page in sorted(by_page.keys()):
        page_rows = by_page[page]
        left_rows = [row for row in page_rows if row.get("column_id") == "left"]
        right_rows = [row for row in page_rows if row.get("column_id") == "right"]

        left_ordered = sorted(left_rows, key=_line_sort_key)
        right_ordered = sorted(right_rows, key=_line_sort_key)
        page_flow = left_ordered + right_ordered if right_rows else left_ordered
        for row in page_flow:
            next_row = dict(row)
            next_row["flow_position"] = flow_position
            ordered.append(next_row)
            flow_position += 1
    return ordered


def _collect_page_split_map(
    rows: Sequence[Dict[str, Any]],
) -> Dict[int, Optional[float]]:
    page_splits: Dict[int, Optional[float]] = {}
    for row in rows:
        page = row.get("page")
        if not isinstance(page, int):
            continue
        split = _to_float(row.get("column_split_x"))
        if split is not None:
            page_splits[page] = split
        elif page not in page_splits:
            page_splits[page] = None
    return page_splits


def _detect_reference_heading_candidates(
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    page_splits: Dict[int, Optional[float]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int, str]] = set()
    for source, items, confidence in (
        ("sections", sections, 0.92),
        ("rows", rows, 0.86),
    ):
        for item in items:
            page = item.get("page")
            box = _normalize_box(item.get("box"))
            text = str(item.get("text") or "").strip()
            if (
                not isinstance(page, int)
                or box is None
                or not _is_reference_heading_text(text)
            ):
                continue
            dedupe_key = (
                page,
                int(round(float(box[1]) * 10000)),
                _normalize_text(text),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            split = page_splits.get(page)
            x_center = float(box[0]) + float(box[2]) / 2.0
            if split is None:
                column_id = "left"
            else:
                column_id = "left" if x_center < split else "right"
            candidates.append(
                {
                    "page": page,
                    "box": box,
                    "text": text,
                    "source": source,
                    "confidence": confidence,
                    "column_id": column_id,
                }
            )
    return sorted(
        candidates, key=lambda item: (item["page"], item["box"][1], item["box"][0])
    )


def _build_bibliography_segments(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rows_with_columns = _assign_column_ids(rows)
    page_splits = _collect_page_split_map(rows_with_columns)
    max_page = max(
        (
            int(row.get("page"))
            for row in rows_with_columns
            if isinstance(row.get("page"), int)
        ),
        default=-1,
    )
    tail_page_span = max(3, int((max_page + 1) * 0.35))
    tail_start_page = max(0, max_page - tail_page_span + 1)
    heading_candidates = _detect_reference_heading_candidates(
        rows_with_columns,
        sections,
        page_splits,
    )
    anchors = detect_reference_anchors_from_rows(
        build_bibliography_reading_flow(rows_with_columns)
    )
    anchor_rows = [anchor for anchor in anchors if isinstance(anchor.get("page"), int)]
    tail_heading_candidates = [
        candidate
        for candidate in heading_candidates
        if int(candidate.get("page") or -1) >= tail_start_page
    ]
    tail_anchor_rows = [
        anchor
        for anchor in anchor_rows
        if int(anchor.get("page") or -1) >= tail_start_page
    ]
    tail_bibliography_pages = sorted(
        {
            int(item.get("page"))
            for item in bibliography_items
            if isinstance(item.get("page"), int)
            and int(item.get("page")) >= tail_start_page
        }
    )
    start_page_candidates = [candidate["page"] for candidate in tail_heading_candidates]
    start_page_candidates.extend(anchor.get("page") for anchor in tail_anchor_rows[:4])
    if not start_page_candidates and tail_bibliography_pages:
        start_page_candidates.append(tail_bibliography_pages[0])
    if not start_page_candidates:
        start_page_candidates.extend(
            candidate["page"] for candidate in heading_candidates
        )
        start_page_candidates.extend(anchor.get("page") for anchor in anchor_rows[:4])
    valid_start_pages = [
        int(page)
        for page in start_page_candidates
        if isinstance(page, int) and page >= 0
    ]
    start_page = min(valid_start_pages) if valid_start_pages else None
    selected_heading = None
    heading_pool = tail_heading_candidates or heading_candidates
    if heading_pool:
        selected_heading = min(
            heading_pool,
            key=lambda item: (
                abs(int(item["page"]) - int(start_page or item["page"])),
                item["box"][1],
                item["box"][0],
            ),
        )
        if start_page is None:
            start_page = selected_heading["page"]

    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    grouped_rows: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows_with_columns:
        page = row.get("page")
        column_id = row.get("column_id") or "left"
        if not isinstance(page, int) or start_page is None or page < start_page:
            continue
        grouped_rows[(page, str(column_id))].append(row)

    anchor_columns_by_page: Dict[int, set[str]] = defaultdict(set)
    for anchor in anchor_rows:
        page = anchor.get("page")
        column_id = str(anchor.get("column_id") or "left")
        if isinstance(page, int):
            anchor_columns_by_page[page].add(column_id)

    bibliography_segments: List[Dict[str, Any]] = []
    section_records: List[Dict[str, Any]] = []
    candidate_noise_sections: List[Dict[str, Any]] = []
    for section in sections:
        page = section.get("page")
        if not isinstance(page, int):
            continue
        record = _serialize_layer_item(section)
        score = _score_header_noise(section.get("text") or "")
        record["noise_score"] = round(score, 3)
        record["kind"] = (
            "heading"
            if _is_reference_heading_text(section.get("text") or "")
            else "section"
        )
        if score >= 0.5 and page >= int(start_page or page):
            record["candidate_noise"] = True
            candidate_noise_sections.append(record)
        else:
            record["candidate_noise"] = False
        section_records.append(record)

    for (page, column_id), page_rows in sorted(grouped_rows.items()):
        ordered_rows = sorted(page_rows, key=_line_sort_key)
        filtered_rows: List[Dict[str, Any]] = []
        segment_top_source = None
        for row in ordered_rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            if _is_header_footer_row(
                row, artifact_info
            ) and not _match_reference_anchor_at_line_start(text):
                continue
            if page == start_page and selected_heading is not None:
                heading_page = int(selected_heading.get("page") or -1)
                heading_column = str(selected_heading.get("column_id") or "left")
                heading_y = float(selected_heading["box"][1])
                if page == heading_page:
                    if anchor_columns_by_page.get(page):
                        if column_id not in anchor_columns_by_page[page]:
                            continue
                    elif column_id != heading_column:
                        continue
                    if column_id == heading_column:
                        segment_top_source = "heading_bottom"
                        if float(row.get("y1") or 0.0) < heading_y:
                            continue
                    elif segment_top_source is None:
                        segment_top_source = "column_rows_min_y"
            filtered_rows.append(row)
        if not filtered_rows:
            continue
        if segment_top_source is None:
            segment_top_source = "column_rows_min_y"
        segment_box = _union_boxes(
            [row["box"] for row in filtered_rows if _normalize_box(row.get("box"))]
        )
        if segment_box is None:
            continue
        overlap_with_layer = max(
            (
                _overlap_ratio(item["box"], segment_box)
                for item in bibliography_items
                if item.get("page") == page and _normalize_box(item.get("box"))
            ),
            default=0.0,
        )
        confidence = 0.58
        if (
            anchor_columns_by_page.get(page)
            and column_id in anchor_columns_by_page[page]
        ):
            confidence += 0.22
        if page == start_page and selected_heading is not None:
            confidence += 0.12
        if overlap_with_layer >= 0.2:
            confidence += min(overlap_with_layer, 0.12)
        bibliography_segments.append(
            {
                "page": page,
                "column_id": column_id,
                "box": segment_box,
                "source": "+".join(
                    part
                    for part, enabled in (
                        ("rows", True),
                        (
                            "sections",
                            page == start_page and selected_heading is not None,
                        ),
                        ("bibliography_layer", overlap_with_layer >= 0.2),
                    )
                    if enabled
                ),
                "confidence": round(min(confidence, 0.98), 3),
                "row_count": len(filtered_rows),
                "raw_text": _clean_reference_text(filtered_rows),
                "row_ids": [str(row.get("id") or "") for row in filtered_rows],
                "segment_top_source": segment_top_source,
            }
        )

    bibliography_anchor = None
    if bibliography_segments:
        first_segment = min(
            bibliography_segments,
            key=lambda item: (
                int(item["page"]),
                float(item["box"][1]),
                float(item["box"][0]),
            ),
        )
        bibliography_anchor = (
            int(first_segment["page"]),
            float(first_segment["box"][1]),
        )
    return {
        "rows_with_columns": rows_with_columns,
        "page_splits": page_splits,
        "heading_candidates": heading_candidates,
        "selected_heading": selected_heading,
        "bibliography_segments": bibliography_segments,
        "bibliography_anchor": bibliography_anchor,
        "candidate_noise_sections": candidate_noise_sections,
        "section_records": section_records,
        "start_page": start_page,
    }


def _row_in_any_segment(
    row: Dict[str, Any],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> bool:
    page = row.get("page")
    box = _normalize_box(row.get("box"))
    if not isinstance(page, int) or box is None:
        return False
    for segment in bibliography_segments:
        if segment.get("page") != page:
            continue
        segment_box = _normalize_box(segment.get("box"))
        if segment_box is None:
            continue
        if (
            segment.get("column_id")
            and row.get("column_id")
            and segment.get("column_id") != row.get("column_id")
        ):
            continue
        if _contains_box(segment_box, box) or _overlap_ratio(segment_box, box) >= 0.6:
            return True
    return False


def _collect_bibliography_rows_from_segments(
    rows_with_columns: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    row_context = _build_same_column_row_context(rows_with_columns)
    selected_rows: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int, str]] = set()
    for row in rows_with_columns:
        text = str(row.get("text") or "").strip()
        page = row.get("page")
        box = _normalize_box(row.get("box"))
        leading_anchor = _match_reference_anchor_at_line_start(
            text,
            include_rejected=True,
        )
        anchor_numbers = _extract_inline_anchor_numbers(text)
        in_zone = _row_in_any_segment(row, bibliography_segments)
        header_footer = _is_header_footer_row(row, artifact_info)
        override_payload = {"accepted": False, "reasons": []}
        if header_footer and not anchor_numbers:
            row_id = str(row.get("id") or "")
            row_neighborhood = row_context.get(row_id) or {}
            override_payload = _strong_bibliography_continuation_row(
                row=row,
                previous_row=row_neighborhood.get("previous_row"),
                current_anchor=row_neighborhood.get("current_anchor"),
                next_anchor=row_neighborhood.get("next_anchor"),
                in_bibliography_zone=in_zone,
            )
            if override_payload.get("accepted"):
                header_footer = False
        reason = "accepted"
        included = bool(in_zone and text and box is not None)
        if not in_zone:
            included = False
            reason = "outside_bibliography_segments"
        elif not text:
            included = False
            reason = "empty_text"
        elif box is None:
            included = False
            reason = "invalid_box"
        elif header_footer and not anchor_numbers:
            included = False
            reason = "header_footer_noise"

        debug_rows.append(
            {
                "id": str(row.get("id") or ""),
                "page": page,
                "box": _serialize_box(box),
                "text": text,
                "column_id": row.get("column_id"),
                "anchor_index": anchor_numbers[0] if anchor_numbers else None,
                "anchor_style": (
                    leading_anchor.get("anchor_style")
                    if leading_anchor and leading_anchor.get("accepted")
                    else None
                ),
                "anchor_candidate_index": (
                    leading_anchor.get("index") if leading_anchor else None
                ),
                "anchor_candidate_style": (
                    leading_anchor.get("anchor_style") if leading_anchor else None
                ),
                "anchor_rejected_reason": (
                    leading_anchor.get("anchor_rejected_reason")
                    if leading_anchor and not leading_anchor.get("accepted")
                    else None
                ),
                "header_footer_noise_overridden": bool(
                    override_payload.get("accepted")
                ),
                "noise_override": (
                    "bibliography_continuation_context"
                    if override_payload.get("accepted")
                    else None
                ),
                "noise_override_reasons": list(override_payload.get("reasons") or []),
                "in_bibliography_zone": in_zone,
                "included": included,
                "reason": reason,
            }
        )
        if not included:
            continue

        dedupe_key = (
            int(page),
            int(round(float(box[1]) * 10000)),
            _normalize_text(text)[:180],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected_rows.append(
            {
                "id": str(row.get("id") or f"row-{page}-{len(selected_rows) + 1}"),
                "text": text,
                "page": int(page),
                "box": box,
                "x0": float(box[0]),
                "y0": float(box[1]),
                "x1": float(box[0]) + float(box[2]),
                "y1": float(box[1]) + float(box[3]),
                "width": float(box[2]),
                "height": float(box[3]),
                "column_id": row.get("column_id") or "left",
                "column_split_x": row.get("column_split_x"),
                "header_footer_noise_overridden": bool(
                    override_payload.get("accepted")
                ),
                "noise_override": (
                    "bibliography_continuation_context"
                    if override_payload.get("accepted")
                    else None
                ),
                "noise_override_reasons": list(override_payload.get("reasons") or []),
            }
        )

    exploded: List[Dict[str, Any]] = []
    for row in selected_rows:
        exploded.extend(_split_reference_row_on_anchors(row))
    return {"rows": exploded, "debug_rows": debug_rows}


def _build_paragraph_phase_payload(
    paragraphs: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    page_splits: Dict[int, Optional[float]],
    bibliography_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    paragraph_records: List[Dict[str, Any]] = []
    for paragraph in paragraphs:
        page = paragraph.get("page")
        box = _normalize_box(paragraph.get("box"))
        if not isinstance(page, int) or box is None:
            continue
        if not _row_in_any_segment({"page": page, "box": box}, bibliography_segments):
            continue
        split = page_splits.get(page)
        x_center = float(box[0]) + float(box[2]) / 2.0
        if split is None:
            column_id = "left"
        else:
            column_id = "left" if x_center < split else "right"
        paragraph_records.append(
            {
                "id": str(paragraph.get("id") or ""),
                "page": page,
                "column_id": column_id,
                "box": _serialize_box(box),
                "text": str(paragraph.get("text") or ""),
            }
        )

    row_text = " ".join(str(row.get("text") or "") for row in bibliography_rows)
    paragraph_text = " ".join(item["text"] for item in paragraph_records)
    inconsistencies: List[str] = []
    if row_text and paragraph_text:
        row_tokens = _tokenize(row_text)
        paragraph_tokens = _tokenize(paragraph_text)
        overlap = len(row_tokens.intersection(paragraph_tokens)) / max(
            len(row_tokens), 1
        )
        if overlap < 0.45:
            inconsistencies.append("paragraph_text_diverges_from_rows")
    return {
        "paragraphs": paragraph_records,
        "ordered_text": paragraph_text[:4000],
        "inconsistencies": inconsistencies,
    }


def _index_tokens_by_page(
    tokens: Sequence[Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    indexed: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for token in tokens:
        page = token.get("page")
        box = _normalize_box(token.get("box"))
        text = str(token.get("text") or "")
        if not isinstance(page, int) or box is None or not text:
            continue
        indexed[page].append({"text": text, "box": box, "page": page})
    for page in list(indexed.keys()):
        indexed[page].sort(
            key=lambda item: (float(item["box"][1]), float(item["box"][0]))
        )
    return indexed


def _tokens_for_row(
    row: Dict[str, Any],
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    if row.get("split_segment"):
        return []
    page = row.get("page")
    box = _normalize_box(row.get("box"))
    if not isinstance(page, int) or box is None:
        return []
    matched: List[Dict[str, Any]] = []
    row_y0 = float(box[1])
    row_y1 = float(box[1]) + float(box[3])
    for token in tokens_by_page.get(page, []):
        token_box = token["box"]
        token_center_x, token_center_y = _box_center(token_box)
        if (
            row_y0 - 0.004 <= token_center_y <= row_y1 + 0.004
            and float(box[0]) - 0.003
            <= token_center_x
            <= float(box[0]) + float(box[2]) + 0.003
        ):
            matched.append(token)
    matched.sort(key=lambda item: (float(item["box"][1]), float(item["box"][0])))
    return matched


def _merge_text_fragments(parts: Sequence[str]) -> str:
    merged = ""
    for part in parts:
        chunk = re.sub(r"\s+", " ", str(part or "")).strip()
        if not chunk:
            continue
        if not merged:
            merged = chunk
            continue
        if merged.endswith("-") and chunk[:1].isalnum():
            merged = f"{merged[:-1]}{chunk}"
            continue
        if re.search(
            r"(https?://|doi\.org/|10\.\d{4,9}/)\Z", merged, flags=re.IGNORECASE
        ):
            merged = f"{merged}{chunk}"
            continue
        merged = f"{merged} {chunk}"

    merged = re.sub(r"\s+([,.;:)\]])", r"\1", merged)
    merged = re.sub(r"([\[(])\s+", r"\1", merged)
    merged = re.sub(r"https?\s*:\s*//", "https://", merged, flags=re.IGNORECASE)
    merged = re.sub(r"doi\.org/\s+", "doi.org/", merged, flags=re.IGNORECASE)
    merged = re.sub(r"(10\.)\s+(\d)", r"\1\2", merged)
    merged = re.sub(r"(10\.\d{4,9}/)\s+([A-Za-z0-9])", r"\1\2", merged)
    return re.sub(r"\s+", " ", merged).strip()


def _apply_regex_substitution(
    text: str,
    pattern: Any,
    replacement: Any,
    *,
    cleanups: set[str],
    cleanup_name: str,
    flags: int = 0,
) -> str:
    if hasattr(pattern, "sub"):
        updated = pattern.sub(replacement, text)
    else:
        updated = re.sub(pattern, replacement, text, flags=flags)
    if updated != text:
        cleanups.add(cleanup_name)
    return updated


def _repair_reference_urls_and_dois(
    text: str,
    *,
    cleanups: Optional[set[str]] = None,
) -> str:
    cleanup_set = cleanups if isinstance(cleanups, set) else set()
    current = str(text or "")
    previous = None
    while current != previous:
        previous = current
        current = _apply_regex_substitution(
            current,
            r"https?\s*:\s*//",
            lambda match: (
                "https://"
                if str(match.group(0) or "").lower().startswith("https")
                else "http://"
            ),
            cleanups=cleanup_set,
            cleanup_name="url_scheme_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"doi\.org/\s+",
            "doi.org/",
            cleanups=cleanup_set,
            cleanup_name="doi_url_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"(https?://\S+)\s+([A-Za-z0-9/_?&%#.=:+~-]+)",
            r"\1\2",
            cleanups=cleanup_set,
            cleanup_name="url_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"(doi\.org/[-._;()/:A-Za-z0-9]+)\s+([A-Za-z0-9._;()/:+-]+)",
            r"\1\2",
            cleanups=cleanup_set,
            cleanup_name="doi_url_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\s+([A-Za-z0-9._;()/:+-]+)",
            r"\1\2",
            cleanups=cleanup_set,
            cleanup_name="doi_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"(10\.)\s+(\d)",
            r"\1\2",
            cleanups=cleanup_set,
            cleanup_name="doi_spacing",
        )
    current = _apply_regex_substitution(
        current,
        r"\s+([,.;:)\]])",
        r"\1",
        cleanups=cleanup_set,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"([\[(])\s+",
        r"\1",
        cleanups=cleanup_set,
        cleanup_name="punctuation_spacing",
    )
    return re.sub(r"\s+", " ", current).strip()


def _normalize_reference_fragment_text(text: str) -> Dict[str, Any]:
    cleanups: set[str] = set()
    current = re.sub(r"\s+", " ", str(text or "")).strip()
    current = _repair_reference_urls_and_dois(current, cleanups=cleanups)
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-zÀ-ÿ]{2})-\s+(?=[a-zà-ÿ]{2})",
        "",
        cleanups=cleanups,
        cleanup_name="line_break_hyphen",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Z]{2})-\s+(?=[A-Z]{2})",
        "",
        cleanups=cleanups,
        cleanup_name="line_break_hyphen",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[,;])(?=\S)",
        " ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-z0-9])\.(?=[A-ZÀ-ß0-9])",
        ". ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _repair_reference_urls_and_dois(current, cleanups=cleanups)
    return {
        "text": re.sub(r"\s+", " ", current).strip(),
        "cleanups_applied": sorted(cleanups),
    }


def _split_glued_reference_words(
    text: str,
    *,
    cleanups: set[str],
) -> str:
    current = str(text or "")
    previous = None
    while current != previous:
        previous = current
        current = _apply_regex_substitution(
            current,
            r"(?<=[A-Za-zÀ-ÿ0-9])\.(?=(?:https?://|doi\.org/|10\.))",
            ". ",
            cleanups=cleanups,
            cleanup_name="doi_url_spacing",
            flags=re.IGNORECASE,
        )
        current = _apply_regex_substitution(
            current,
            r"(?<=[A-Za-zÀ-ÿ]{2})-(?=[a-zà-ÿ]{2})",
            "",
            cleanups=cleanups,
            cleanup_name="line_break_hyphen",
        )
        current = _apply_regex_substitution(
            current,
            r"(?<=[A-Za-zÀ-ÿ]{4})-(?=[A-ZÀ-ß][a-zà-ÿ]{3,})",
            " ",
            cleanups=cleanups,
            cleanup_name="line_break_hyphen",
        )
        current = _apply_regex_substitution(
            current,
            r'(?<=[A-Za-zÀ-ÿ])"(?=[A-Za-zÀ-ÿ])',
            ' "',
            cleanups=cleanups,
            cleanup_name="word_spacing",
        )
        current = _apply_regex_substitution(
            current,
            r'(?<=")(?=[A-Za-zÀ-ÿ])',
            " ",
            cleanups=cleanups,
            cleanup_name="word_spacing",
        )
        current = _apply_regex_substitution(
            current,
            r'"\s+([^"]+?)\s+"',
            r'"\1"',
            cleanups=cleanups,
            cleanup_name="punctuation_spacing",
        )
        current = _apply_regex_substitution(
            current,
            r'"\s+([^"]+?)"',
            r'"\1"',
            cleanups=cleanups,
            cleanup_name="punctuation_spacing",
        )
        current = _apply_regex_substitution(
            current,
            r'"([^"]+?)\s+"',
            r'"\1"',
            cleanups=cleanups,
            cleanup_name="punctuation_spacing",
        )
        current = _apply_regex_substitution(
            current,
            r"\b([A-Z]{2,4})([A-Z]?[a-zà-ÿ]{4,})\b",
            r"\1 \2",
            cleanups=cleanups,
            cleanup_name="word_spacing",
        )
        for connector in ("and", "for", "in", "of", "the", "to", "with"):
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Za-zÀ-ÿ]{{4,}}){connector}(?=[A-ZÀ-ß])",
                rf"\1 {connector}",
                cleanups=cleanups,
                cleanup_name="word_spacing",
            )
        for connector in REFERENCE_GLUE_SUFFIX_CONNECTORS:
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Za-zÀ-ÿ]{{4,}}){connector}\b",
                rf"\1 {connector}",
                cleanups=cleanups,
                cleanup_name="word_spacing",
                flags=re.IGNORECASE,
            )
        for connector in ("in", "of", "to"):
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Z]{{2,4}}){connector}(?=[A-ZÀ-ß])",
                rf"\1 {connector} ",
                cleanups=cleanups,
                cleanup_name="word_spacing",
            )
        for connector in ("in", "of", "to"):
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Za-zÀ-ÿ]{{3,}}){connector}\s+(?=[A-ZÀ-ß])",
                rf"\1 {connector} ",
                cleanups=cleanups,
                cleanup_name="word_spacing",
            )
        for connector in REFERENCE_MIDDLE_CONNECTORS:
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Za-zÀ-ÿ]{{5,}}){connector}([A-Za-zÀ-ÿ]{{3,}})\b",
                rf"\1 {connector} \2",
                cleanups=cleanups,
                cleanup_name="word_spacing",
                flags=re.IGNORECASE,
            )
        current = _apply_regex_substitution(
            current,
            r"\b([A-Za-zÀ-ÿ]{4,})isnext\b",
            r"\1 is next",
            cleanups=cleanups,
            cleanup_name="word_spacing",
            flags=re.IGNORECASE,
        )
        for suffix in REFERENCE_SUFFIX_SPLITS:
            current = _apply_regex_substitution(
                current,
                rf"\b([A-Za-zÀ-ÿ]{{5,}}){suffix}\b",
                rf"\1 {suffix}",
                cleanups=cleanups,
                cleanup_name="word_spacing",
                flags=re.IGNORECASE,
            )
    return re.sub(r"\s+", " ", current).strip()


def _normalize_reference_author_section(
    text: str,
    *,
    cleanups: set[str],
) -> str:
    current = str(text or "")
    current = _apply_regex_substitution(
        current,
        r"(?<=[,;])(?=\S)",
        " ",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[a-zà-ÿ])and(?=[A-ZÀ-ß])",
        " and ",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=\band)(?=[A-ZÀ-ß])",
        " ",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-zÀ-ÿ])\.(?=[A-ZÀ-ß0-9])",
        ". ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[a-zà-ÿ])(?=[A-ZÀ-ß])",
        " ",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=\b[A-Z])(?=[A-Z][a-zà-ÿ]{2,})",
        " ",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bMc\s+([A-Z])",
        r"Mc\1",
        cleanups=cleanups,
        cleanup_name="author_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\b([A-Z])\.([A-Z])",
        r"\1. \2",
        cleanups=cleanups,
        cleanup_name="author_initial_spacing",
    )
    return re.sub(r"\s+", " ", current).strip()


def _normalize_reference_body_section(
    text: str,
    *,
    cleanups: set[str],
) -> str:
    current = str(text or "")
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-zÀ-ÿ]{2})-\s+(?=[a-zà-ÿ]{2})",
        "",
        cleanups=cleanups,
        cleanup_name="line_break_hyphen",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Z]{2})-\s+(?=[A-Z]{2})",
        "",
        cleanups=cleanups,
        cleanup_name="line_break_hyphen",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[,;])(?=\S)",
        " ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-z0-9])\.(?=[A-ZÀ-ß0-9])",
        ". ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bACM(?=[A-Z])",
        "ACM ",
        cleanups=cleanups,
        cleanup_name="publisher_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bIEEE(?=[A-Z])",
        "IEEE ",
        cleanups=cleanups,
        cleanup_name="publisher_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bIATED(?=[A-Z])",
        "IATED ",
        cleanups=cleanups,
        cleanup_name="publisher_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bSIGCSE(?=[A-Z])",
        "SIGCSE ",
        cleanups=cleanups,
        cleanup_name="publisher_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\bCS(?=[A-Z])",
        "CS ",
        cleanups=cleanups,
        cleanup_name="publisher_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[a-zà-ÿ])(?=[A-ZÀ-ß])",
        " ",
        cleanups=cleanups,
        cleanup_name="word_spacing",
    )
    for pattern in (
        (r"(?<=[a-zà-ÿ])and(?=[A-ZÀ-ß])", " and "),
        (r"(?<=[a-zà-ÿ])of(?=[A-ZÀ-ß0-9])", " of "),
        (r"(?<=[a-zà-ÿ])in(?=[A-ZÀ-ß0-9])", " in "),
        (r"(?<=[a-zà-ÿ])the(?=[A-ZÀ-ß0-9])", " the "),
        (r"(?<=[a-zà-ÿ])to(?=[A-ZÀ-ß])", " to "),
        (r"(?<=[a-zà-ÿ])for(?=[A-ZÀ-ß])", " for "),
        (r"(?<=[a-zà-ÿ])with(?=[A-ZÀ-ß])", " with "),
    ):
        current = _apply_regex_substitution(
            current,
            pattern[0],
            pattern[1],
            cleanups=cleanups,
            cleanup_name="word_spacing",
        )
    current = _apply_regex_substitution(
        current,
        r":(?=[A-Za-zÀ-ÿ])",
        ": ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r":\s+A(?=[a-zà-ÿ]{5,})",
        ": A ",
        cleanups=cleanups,
        cleanup_name="word_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"(?<=[A-Za-zÀ-ÿ])\((?=[A-Za-z0-9])",
        " (",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\)\.(?=[A-Za-zÀ-ÿ])",
        "). ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _split_glued_reference_words(current, cleanups=cleanups)
    return re.sub(r"\s+", " ", current).strip()


def _normalize_reference_text_candidate(text: str) -> Dict[str, Any]:
    cleanups: set[str] = set()
    current = re.sub(r"\s+", " ", str(text or "")).strip()
    current = _repair_reference_urls_and_dois(current, cleanups=cleanups)
    year_match = REFERENCE_YEAR_RE.search(current)
    if year_match:
        author_prefix = _normalize_reference_author_section(
            current[: year_match.start()].strip(),
            cleanups=cleanups,
        )
        year_value = year_match.group(0)
        body_suffix = _normalize_reference_body_section(
            current[year_match.end() :].lstrip(" ."),
            cleanups=cleanups,
        )
        current = (
            f"{author_prefix} {year_value}".strip() if author_prefix else year_value
        )
        if body_suffix:
            current = f"{current}. {body_suffix}"
    else:
        current = _normalize_reference_body_section(current, cleanups=cleanups)
    current = _repair_reference_urls_and_dois(current, cleanups=cleanups)
    current = _apply_regex_substitution(
        current,
        r"\bPh\.\s+D\.",
        "Ph.D.",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\s+([,.;:)\]])",
        r"\1",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"([\[(])\s+",
        r"\1",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    return {
        "text": re.sub(r"\s+", " ", current).strip(),
        "cleanups_applied": sorted(cleanups),
    }


def _reference_text_quality_metrics(text: str) -> Dict[str, Any]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    return {
        "word_count": len(REFERENCE_WORD_RE.findall(normalized)),
        "glued_fragments": len(REFERENCE_GLUE_RE.findall(normalized)),
        "has_doi_or_url": bool(
            re.search(r"https?://\S+", normalized, flags=re.IGNORECASE)
            or DOI_REGEX.search(normalized)
        ),
        "broken_url_like": bool(
            re.search(r"https?://\S+\s+[A-Za-zÀ-ÿ]", normalized, flags=re.IGNORECASE)
            or re.search(
                r"10\.\d{4,9}/\S+\s+[A-Za-z0-9]", normalized, flags=re.IGNORECASE
            )
        ),
        "trailing_after_doi": bool(REFERENCE_TRAILING_AFTER_DOI_RE.search(normalized)),
        "fragment_after_pages": bool(
            REFERENCE_FRAGMENT_AFTER_PAGES_RE.search(normalized)
        ),
        "trailing_venue_fragment": bool(
            REFERENCE_TRAILING_VENUE_FRAGMENT_RE.search(normalized)
        ),
    }


def _reference_text_quality_score(text: str) -> float:
    metrics = _reference_text_quality_metrics(text)
    score = 0.52
    score += min(float(metrics["word_count"]) * 0.008, 0.18)
    if metrics["has_doi_or_url"]:
        score += 0.06
    if metrics["glued_fragments"] == 0:
        score += 0.04
    score -= min(float(metrics["glued_fragments"]) * 0.08, 0.24)
    if metrics["broken_url_like"]:
        score -= 0.38
    if metrics["trailing_after_doi"]:
        score -= 0.28
    if metrics["fragment_after_pages"]:
        score -= 0.18
    if metrics["trailing_venue_fragment"]:
        score -= 0.24
    return round(max(0.0, min(score, 1.0)), 3)


def _reference_text_order_similarity(left: str, right: str) -> float:
    left_compact = REFERENCE_COMPARE_NORMALIZE_RE.sub("", str(left or "")).lower()
    right_compact = REFERENCE_COMPARE_NORMALIZE_RE.sub("", str(right or "")).lower()
    if not left_compact or not right_compact:
        return 0.0
    return round(
        SequenceMatcher(None, left_compact[:2200], right_compact[:2200]).ratio(),
        3,
    )


def _reference_cleanup_signature(text: str) -> str:
    return REFERENCE_COMPARE_NORMALIZE_RE.sub("", str(text or "")).lower()


def _reference_edit_word_key(value: str) -> str:
    return _reference_cleanup_signature(value)


def _reference_edit_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-zÀ-ÿ]{2,}", str(text or ""))


def _reference_edit_bigram_keys(text: str) -> set[str]:
    words = _reference_edit_words(text)
    bigrams: set[str] = set()
    for left, right in zip(words, words[1:]):
        left_key = _reference_edit_word_key(left)
        right_key = _reference_edit_word_key(right)
        if left_key and right_key:
            bigrams.add(f"{left_key} {right_key}")
    return bigrams


def _build_reference_edit_evidence(texts: Sequence[str]) -> Dict[str, Any]:
    words: set[str] = set()
    bigrams: set[str] = set()
    normalized_texts: List[str] = []
    for text in texts:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            continue
        normalized_lower = normalized.lower()
        normalized_texts.append(normalized_lower)
        for word in _reference_edit_words(normalized):
            word_key = _reference_edit_word_key(word)
            if word_key:
                words.add(word_key)
        bigrams.update(_reference_edit_bigram_keys(normalized))
    return {
        "words": words,
        "bigrams": bigrams,
        "texts": normalized_texts,
    }


def _evidence_contains_phrase(evidence: Dict[str, Any], phrase: str) -> bool:
    normalized_phrase = re.sub(r"\s+", " ", str(phrase or "")).strip().lower()
    if not normalized_phrase:
        return False
    for candidate in evidence.get("texts") or []:
        if normalized_phrase in candidate:
            return True
    return False


def _looks_like_glued_artifact_word(word: str) -> bool:
    candidate = str(word or "")
    lowered = candidate.lower()
    if not candidate or len(candidate) < 5:
        return False
    if re.search(r"[a-zà-ÿ][A-ZÀ-ß]", candidate):
        return True
    if re.match(r"^[A-Z]{2,}[A-Z]?[a-zà-ÿ]{2,}$", candidate):
        return True
    if re.search(r"\d", candidate):
        return True
    for suffix in REFERENCE_SUFFIX_SPLITS:
        suffix_key = _reference_edit_word_key(suffix)
        if (
            suffix_key
            and lowered.endswith(suffix_key)
            and len(lowered) > len(suffix_key) + 4
        ):
            return True
    for connector in REFERENCE_GLUE_SUFFIX_CONNECTORS:
        if lowered.endswith(connector) and len(lowered) > len(connector) + 4:
            return True
    return False


def _detect_new_reference_word_splits(
    text: str,
    *,
    evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    words = _reference_edit_words(text)
    hits: List[Dict[str, Any]] = []
    for left, right in zip(words, words[1:]):
        left_key = _reference_edit_word_key(left)
        right_key = _reference_edit_word_key(right)
        if not left_key or not right_key:
            continue
        combined = f"{left}{right}"
        combined_key = _reference_edit_word_key(combined)
        bigram_key = f"{left_key} {right_key}"
        if combined_key not in (evidence.get("words") or set()):
            continue
        if bigram_key in (evidence.get("bigrams") or set()):
            continue
        if _looks_like_glued_artifact_word(combined):
            continue
        hits.append(
            {
                "left": left,
                "right": right,
                "combined": combined,
                "bigram_key": bigram_key,
            }
        )
    return hits


def _classify_local_reference_edit(
    before_segment: str,
    after_segment: str,
    *,
    before_window: str = "",
    after_window: str = "",
) -> str:
    context = " ".join(
        part
        for part in (
            str(before_window or ""),
            str(before_segment or ""),
            str(after_segment or ""),
            str(after_window or ""),
        )
        if str(part or "").strip()
    )
    compact_before = _reference_cleanup_signature(before_segment)
    compact_after = _reference_cleanup_signature(after_segment)
    if DOI_URL_REGEX.search(context):
        return "doi_url_spacing"
    if DOI_REGEX.search(context):
        return "doi_spacing"
    if re.search(r"https?://", context, flags=re.IGNORECASE):
        return "url_spacing"
    if "-" in str(before_segment or "") and compact_before == compact_after:
        return "line_break_hyphen"
    if compact_before == compact_after:
        if any(
            symbol in context
            for symbol in ("(", ")", "[", "]", '"', "”", "’", "'", ".", ",", ";", ":")
        ):
            return "punctuation_spacing"
        if re.search(r"\b(?:ACM|IEEE|IATED|SIGCSE|CS)\b", context):
            return "publisher_spacing"
        if re.search(r"\b[A-Z]\.\s*[A-Z]\b", context):
            return "author_initial_spacing"
        return "word_spacing"
    if re.search(r"\b(?:ACM|IEEE|IATED|SIGCSE|CS)\b", context):
        return "publisher_spacing"
    return "word_spacing"


def _has_strong_local_spacing_pattern(before_window: str, after_window: str) -> bool:
    before_compact = _reference_cleanup_signature(before_window)
    after_compact = _reference_cleanup_signature(after_window)
    if not before_compact or before_compact != after_compact:
        return False
    if re.search(r"[a-zà-ÿ][A-ZÀ-ß]", before_window):
        return True
    if re.search(r"\b[A-Z]{2,}[A-Z]?[a-zà-ÿ]{2,}\b", before_window):
        return True
    lowered = before_compact.lower()
    for suffix in REFERENCE_SUFFIX_SPLITS:
        suffix_key = _reference_edit_word_key(suffix)
        if (
            suffix_key
            and lowered.endswith(suffix_key)
            and len(lowered) > len(suffix_key) + 4
        ):
            return True
    for connector in REFERENCE_GLUE_SUFFIX_CONNECTORS:
        connector_key = _reference_edit_word_key(connector)
        if (
            connector_key
            and lowered.endswith(connector_key)
            and len(lowered) > len(connector_key) + 4
        ):
            return True
    return False


def _local_edit_supported_by_evidence(
    *,
    before_window: str,
    after_window: str,
    evidence: Dict[str, Any],
) -> bool:
    before_bigrams = _reference_edit_bigram_keys(before_window)
    after_bigrams = _reference_edit_bigram_keys(after_window)
    if (after_bigrams - before_bigrams).intersection(evidence.get("bigrams") or set()):
        return True
    normalized_after = re.sub(r"\s+", " ", str(after_window or "")).strip()
    normalized_before = re.sub(r"\s+", " ", str(before_window or "")).strip()
    if normalized_after and normalized_after != normalized_before:
        if _evidence_contains_phrase(evidence, normalized_after):
            return True
    return False


def _apply_validated_reference_local_edits(
    *,
    base_text: str,
    candidate_text: str,
    row_evidence_texts: Sequence[str],
    token_evidence_texts: Sequence[str],
    edit_scope: str,
) -> Dict[str, Any]:
    base_value = re.sub(r"\s+", " ", str(base_text or "")).strip()
    candidate_value = re.sub(r"\s+", " ", str(candidate_text or "")).strip()
    if not base_value:
        return {
            "text": candidate_value,
            "edits": [],
            "cleanups_applied": [],
            "new_word_split_detected": False,
            "lexical_degradation_detected": False,
            "accepted_local_edit_count": 0,
            "rejected_local_edit_count": 0,
        }
    row_evidence = _build_reference_edit_evidence(
        list(row_evidence_texts) + [base_value]
    )
    token_evidence = _build_reference_edit_evidence(list(token_evidence_texts))
    combined_evidence = _build_reference_edit_evidence(
        list(row_evidence_texts) + list(token_evidence_texts) + [base_value]
    )
    output_parts: List[str] = []
    edits: List[Dict[str, Any]] = []
    accepted_cleanups: set[str] = set()
    accepted_count = 0
    rejected_count = 0
    new_word_split_detected = False
    lexical_degradation_detected = False

    for tag, i1, i2, j1, j2 in SequenceMatcher(
        None, base_value, candidate_value
    ).get_opcodes():
        if tag == "equal":
            output_parts.append(base_value[i1:i2])
            continue
        before_segment = base_value[i1:i2]
        after_segment = candidate_value[j1:j2]
        prefix = base_value[max(0, i1 - 48) : i1]
        suffix = base_value[i2 : min(len(base_value), i2 + 48)]
        left_char = prefix[-1:] if prefix else ""
        right_char = suffix[:1] if suffix else ""
        before_window = f"{prefix}{before_segment}{suffix}"
        after_window = f"{prefix}{after_segment}{suffix}"
        edit_type = _classify_local_reference_edit(
            before_segment,
            after_segment,
            before_window=before_window,
            after_window=after_window,
        )
        if (
            str(after_segment or "").isspace()
            and left_char.isalpha()
            and right_char.isalpha()
        ):
            edit_type = "word_spacing"
        elif (
            str(before_segment or "").isspace()
            and left_char.isalpha()
            and right_char.isalpha()
        ):
            edit_type = "word_spacing"
        new_split_hits = _detect_new_reference_word_splits(
            after_window,
            evidence=combined_evidence,
        )
        previous_split_hits = {
            hit.get("bigram_key")
            for hit in _detect_new_reference_word_splits(
                before_window,
                evidence=combined_evidence,
            )
        }
        new_split_hits = [
            hit
            for hit in new_split_hits
            if hit.get("bigram_key") not in previous_split_hits
        ]
        would_break_valid_word = bool(new_split_hits)
        supported_by_rows = _local_edit_supported_by_evidence(
            before_window=before_window,
            after_window=after_window,
            evidence=row_evidence,
        )
        supported_by_tokens = _local_edit_supported_by_evidence(
            before_window=before_window,
            after_window=after_window,
            evidence=token_evidence,
        )
        would_change_backbone_signature = bool(
            _reference_cleanup_signature(before_segment)
            != _reference_cleanup_signature(after_segment)
        )
        strong_pattern = _has_strong_local_spacing_pattern(before_window, after_window)
        accept_edit = False
        reason = "unsupported_local_edit"
        if would_break_valid_word:
            reason = "rejected_new_word_split"
        elif edit_type in {
            "line_break_hyphen",
            "doi_spacing",
            "doi_url_spacing",
            "url_spacing",
            "url_scheme_spacing",
            "punctuation_spacing",
            "author_initial_spacing",
        }:
            accept_edit = True
            reason = "accepted_safe_cleanup"
        elif would_change_backbone_signature:
            reason = "rejected_signature_change"
        elif supported_by_tokens:
            accept_edit = True
            reason = "accepted_supported_by_tokens"
        elif supported_by_rows:
            accept_edit = True
            reason = "accepted_supported_by_rows"
        elif (
            edit_type in {"author_spacing", "publisher_spacing", "word_spacing"}
            and strong_pattern
        ):
            accept_edit = True
            reason = "accepted_strong_spacing_pattern"

        if accept_edit:
            output_parts.append(after_segment)
            accepted_cleanups.add(edit_type)
            accepted_count += 1
        else:
            output_parts.append(before_segment)
            rejected_count += 1
            if would_break_valid_word:
                new_word_split_detected = True
                lexical_degradation_detected = True

        edits.append(
            {
                "scope": edit_scope,
                "type": edit_type,
                "before": before_segment,
                "after": after_segment,
                "status": "accepted" if accept_edit else "rejected",
                "reason": reason,
                "supported_by_rows": supported_by_rows,
                "supported_by_tokens": supported_by_tokens,
                "would_break_valid_word": would_break_valid_word,
                "would_change_backbone_signature": would_change_backbone_signature,
            }
        )

    return {
        "text": re.sub(r"\s+", " ", "".join(output_parts)).strip(),
        "edits": edits,
        "cleanups_applied": sorted(accepted_cleanups),
        "new_word_split_detected": new_word_split_detected,
        "lexical_degradation_detected": lexical_degradation_detected,
        "accepted_local_edit_count": accepted_count,
        "rejected_local_edit_count": rejected_count,
    }


def _evaluate_reference_backbone_guard(
    backbone_text: str,
    candidate_text: str,
) -> Dict[str, Any]:
    if not str(candidate_text or "").strip():
        return {
            "signature_match": False,
            "cleanup_only": False,
            "order_similarity": 0.0,
            "order_penalty": 0.46,
            "eligible": False,
            "reasons": ["empty_candidate"],
        }
    if str(backbone_text or "") == str(candidate_text or ""):
        return {
            "signature_match": True,
            "cleanup_only": True,
            "order_similarity": 1.0,
            "order_penalty": 0.0,
            "eligible": True,
            "reasons": ["rows_raw_backbone"],
        }
    backbone_signature = _reference_cleanup_signature(backbone_text)
    candidate_signature = _reference_cleanup_signature(candidate_text)
    signature_match = bool(
        backbone_signature
        and candidate_signature
        and backbone_signature == candidate_signature
    )
    order_similarity = _reference_text_order_similarity(backbone_text, candidate_text)
    backbone_metrics = _reference_text_quality_metrics(backbone_text)
    candidate_metrics = _reference_text_quality_metrics(candidate_text)
    order_penalty = 0.0
    reasons: List[str] = []
    if not signature_match:
        order_penalty += 0.22
        reasons.append("backbone_signature_changed")
    if order_similarity < 0.985:
        order_penalty += min((0.985 - order_similarity) * 2.4, 0.34)
        reasons.append("order_similarity_below_backbone")
    if candidate_metrics.get("fragment_after_pages") and not backbone_metrics.get(
        "fragment_after_pages"
    ):
        order_penalty += 0.22
        reasons.append("pages_fragment_reordered")
    if candidate_metrics.get("trailing_venue_fragment") and not backbone_metrics.get(
        "trailing_venue_fragment"
    ):
        order_penalty += 0.24
        reasons.append("venue_fragment_reordered")
    if candidate_metrics.get("trailing_after_doi") and not backbone_metrics.get(
        "trailing_after_doi"
    ):
        order_penalty += 0.24
        reasons.append("doi_tail_reordered")
    cleanup_only = bool(signature_match and order_similarity >= 0.995)
    eligible = bool(
        signature_match and order_similarity >= 0.985 and order_penalty <= 0.18
    )
    if not reasons:
        reasons.append("backbone_preserved")
    return {
        "signature_match": signature_match,
        "cleanup_only": cleanup_only,
        "order_similarity": round(order_similarity, 3),
        "order_penalty": round(min(order_penalty, 0.95), 3),
        "eligible": eligible,
        "reasons": reasons,
    }


def _pick_preferred_reference_fragment(
    raw_fragment: str,
    token_fragment: str,
) -> Dict[str, Any]:
    raw_score = _reference_text_quality_score(raw_fragment)
    token_score = _reference_text_quality_score(token_fragment)
    order_similarity = _reference_text_order_similarity(raw_fragment, token_fragment)
    if (
        token_fragment
        and token_fragment != raw_fragment
        and order_similarity >= 0.9
        and token_score >= raw_score + 0.08
    ):
        return {
            "text": token_fragment,
            "source": "rows_tokens",
            "reason": "token_fragment_preferred",
            "raw_score": raw_score,
            "token_score": token_score,
            "order_similarity": order_similarity,
        }
    return {
        "text": raw_fragment,
        "source": "rows_raw",
        "reason": (
            "raw_fragment_preserved_order"
            if token_fragment and order_similarity < 0.9
            else "raw_fragment_preserved"
        ),
        "raw_score": raw_score,
        "token_score": token_score,
        "order_similarity": order_similarity,
    }


def _apply_token_local_cleanups_preserving_row_order(
    row_variants: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    selected_parts: List[str] = []
    row_decisions: List[Dict[str, Any]] = []
    cleanups_applied: set[str] = set()
    rows_with_token_cleanup = 0
    for row_variant in row_variants:
        raw_text = str(row_variant.get("raw_text") or "").strip()
        token_text = str(row_variant.get("token_text") or "").strip()
        raw_score = _reference_text_quality_score(raw_text)
        token_score = _reference_text_quality_score(token_text or raw_text)
        token_available = bool(row_variant.get("token_available"))
        guard = _evaluate_reference_backbone_guard(raw_text, token_text or raw_text)
        selected_text = raw_text
        selected_source = "rows_raw"
        selection_reason = "raw_backbone_preserved"
        if (
            token_available
            and token_text
            and token_text != raw_text
            and guard["cleanup_only"]
            and token_score >= raw_score - 0.03
        ):
            selected_text = token_text
            selected_source = "rows_tokens_local_cleanup"
            selection_reason = "token_local_cleanup_preserving_row_order"
            rows_with_token_cleanup += 1
            cleanups_applied.update(row_variant.get("token_cleanups_applied") or [])
        else:
            cleanups_applied.update(row_variant.get("raw_cleanups_applied") or [])
            if (
                token_available
                and token_text
                and token_text != raw_text
                and not guard["eligible"]
            ):
                selection_reason = "token_cleanup_rejected_backbone_guard"
        selected_parts.append(selected_text)
        row_decisions.append(
            {
                "raw_text": raw_text,
                "token_text": token_text or raw_text,
                "selected_text": selected_text,
                "selected_source": selected_source,
                "selection_reason": selection_reason,
                "token_available": token_available,
                "raw_score": round(raw_score, 3),
                "token_score": round(token_score, 3),
                "order_similarity_to_rows": guard.get("order_similarity"),
                "backbone_signature_match": guard.get("signature_match"),
                "backbone_cleanup_only": guard.get("cleanup_only"),
                "backbone_eligible": guard.get("eligible"),
                "order_penalty": guard.get("order_penalty"),
                "order_guard_reasons": guard.get("reasons") or [],
            }
        )
    backbone_seed_text = _merge_text_fragments(selected_parts)
    normalized_backbone = _normalize_reference_text_candidate(backbone_seed_text)
    validated_backbone = _apply_validated_reference_local_edits(
        base_text=backbone_seed_text,
        candidate_text=str(normalized_backbone.get("text") or backbone_seed_text),
        row_evidence_texts=[
            str(row_variant.get("raw_text") or "")
            for row_variant in row_variants
            if str(row_variant.get("raw_text") or "").strip()
        ],
        token_evidence_texts=[
            str(row_variant.get("token_text") or "")
            for row_variant in row_variants
            if str(row_variant.get("token_text") or "").strip()
        ],
        edit_scope="rows_backbone",
    )
    cleanups_applied.update(validated_backbone.get("cleanups_applied") or [])
    return {
        "seed_text": backbone_seed_text,
        "candidate_text": str(normalized_backbone.get("text") or "").strip(),
        "text": str(validated_backbone.get("text") or backbone_seed_text).strip(),
        "per_row_selected": row_decisions,
        "backbone_local_edits": validated_backbone.get("edits") or [],
        "new_word_split_detected": bool(
            validated_backbone.get("new_word_split_detected")
        ),
        "lexical_degradation_detected": bool(
            validated_backbone.get("lexical_degradation_detected")
        ),
        "accepted_local_edit_count": int(
            validated_backbone.get("accepted_local_edit_count") or 0
        ),
        "rejected_local_edit_count": int(
            validated_backbone.get("rejected_local_edit_count") or 0
        ),
        "cleanups_applied": sorted(
            str(name).strip() for name in cleanups_applied if str(name).strip()
        ),
        "rows_with_token_cleanup": rows_with_token_cleanup,
    }


def _select_reference_text_candidate(
    *,
    candidates: Sequence[Dict[str, Any]],
    reference_doi: str,
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    source_bias = {
        "rows_raw": 0.08,
        "rows_hybrid": 0.04,
        "rows_tokens": -0.08,
    }
    evaluations: List[Dict[str, Any]] = []
    best_evaluation: Optional[Dict[str, Any]] = None
    evaluation_by_source: Dict[str, Dict[str, Any]] = {}
    seen_keys: set[Tuple[str, str]] = set()
    raw_backbone_text = ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("source") or "").strip() == "rows_raw":
            raw_backbone_text = str(candidate.get("text") or "").strip()
            break
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("source") or "").strip() or "rows_raw"
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue
        dedupe_key = (source, text)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        preview_match = _match_reference_against_crossref(
            reference_text=text,
            reference_doi=reference_doi,
            crossref_context=crossref_context,
            allow_doi_lookup=False,
        )
        quality_score = float(
            candidate.get("quality_score")
            if candidate.get("quality_score") is not None
            else _reference_text_quality_score(text)
        )
        order_guard = _evaluate_reference_backbone_guard(
            raw_backbone_text or text,
            text,
        )
        combined_score = round(
            quality_score
            + source_bias.get(source, 0.0)
            + 0.18 * float(preview_match.get("score") or 0.0)
            + 0.08 * float(preview_match.get("doi_match_score") or 0.0),
            3,
        )
        combined_score = round(
            combined_score - float(order_guard.get("order_penalty") or 0.0),
            3,
        )
        evaluation = {
            "source": source,
            "text": text,
            "quality_score": round(quality_score, 3),
            "crossref_preview_score": round(
                float(preview_match.get("score") or 0.0),
                3,
            ),
            "doi_preview_score": round(
                float(preview_match.get("doi_match_score") or 0.0),
                3,
            ),
            "combined_score": combined_score,
            "cleanups_applied": candidate.get("cleanups_applied") or [],
            "order_similarity_to_rows": order_guard.get("order_similarity"),
            "backbone_signature_match": order_guard.get("signature_match"),
            "backbone_cleanup_only": order_guard.get("cleanup_only"),
            "backbone_eligible": order_guard.get("eligible"),
            "order_penalty": order_guard.get("order_penalty"),
            "order_guard_reasons": order_guard.get("reasons") or [],
        }
        evaluations.append(evaluation)
        evaluation_by_source[source] = evaluation
        if (
            best_evaluation is None
            or combined_score > best_evaluation["combined_score"]
        ):
            best_evaluation = evaluation

    if best_evaluation is None:
        return {
            "source": "rows_raw",
            "text": "",
            "candidate_scores": evaluations,
            "cleanups_applied": [],
        }

    raw_evaluation = evaluation_by_source.get("rows_raw") or best_evaluation
    hybrid_evaluation = evaluation_by_source.get("rows_hybrid")

    selected_evaluation = raw_evaluation
    if (
        hybrid_evaluation is not None
        and hybrid_evaluation.get("backbone_eligible")
        and str(hybrid_evaluation.get("text") or "")
        != str(raw_evaluation.get("text") or "")
        and hybrid_evaluation["combined_score"]
        >= raw_evaluation["combined_score"] - 0.01
    ):
        selected_evaluation = hybrid_evaluation
    for evaluation in evaluations:
        if evaluation is selected_evaluation:
            continue
        if not evaluation.get("backbone_eligible"):
            continue
        if evaluation.get("source") != "rows_hybrid":
            continue
        if evaluation["combined_score"] >= selected_evaluation["combined_score"] + 0.02:
            selected_evaluation = evaluation

    return {
        "source": selected_evaluation["source"],
        "text": selected_evaluation["text"],
        "candidate_scores": evaluations,
        "cleanups_applied": selected_evaluation.get("cleanups_applied") or [],
        "order_similarity_to_rows": selected_evaluation.get("order_similarity_to_rows"),
        "backbone_source": raw_evaluation.get("source"),
        "backbone_text": raw_evaluation.get("text"),
    }


def _reconstruct_reference_text_from_rows_and_tokens(
    rows: Sequence[Dict[str, Any]],
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    raw_text_seed = _clean_reference_text(rows)
    per_row_before: List[str] = []
    per_row_after: List[str] = []
    per_row_selected: List[Dict[str, Any]] = []
    token_rows_used = 0
    row_variants: List[Dict[str, Any]] = []
    candidate_cleanups: set[str] = set()
    for row in rows:
        row_text = str(row.get("text") or "").strip()
        normalized_row = _normalize_reference_fragment_text(row_text)
        normalized_row_text = str(normalized_row.get("text") or row_text)
        per_row_before.append(normalized_row_text)
        row_tokens = _tokens_for_row(row, tokens_by_page)
        reconstructed = normalized_row_text
        if row_tokens:
            token_rows_used += 1
            token_fragment = _merge_text_fragments(
                [token["text"] for token in row_tokens]
            )
            reconstructed_payload = _normalize_reference_fragment_text(token_fragment)
            reconstructed = str(
                reconstructed_payload.get("text") or normalized_row_text
            )
        else:
            reconstructed_payload = {
                "text": normalized_row_text,
                "cleanups_applied": [],
            }
        per_row_after.append(reconstructed or normalized_row_text)
        row_variants.append(
            {
                "raw_text": normalized_row_text,
                "token_text": reconstructed or normalized_row_text,
                "token_available": bool(row_tokens),
                "raw_cleanups_applied": normalized_row.get("cleanups_applied") or [],
                "token_cleanups_applied": reconstructed_payload.get("cleanups_applied")
                or [],
            }
        )

    backbone_payload = _apply_token_local_cleanups_preserving_row_order(row_variants)
    per_row_selected = list(backbone_payload.get("per_row_selected") or [])
    raw_text = str(
        backbone_payload.get("text")
        or backbone_payload.get("seed_text")
        or raw_text_seed
        or ""
    ).strip()
    token_seed_text = _merge_text_fragments(per_row_after)
    token_text_candidate = _normalize_reference_text_candidate(token_seed_text)
    token_edit_payload = _apply_validated_reference_local_edits(
        base_text=raw_text,
        candidate_text=str(token_text_candidate.get("text") or raw_text),
        row_evidence_texts=[
            text
            for text in list(per_row_before)
            + [str(backbone_payload.get("seed_text") or ""), raw_text]
            if str(text or "").strip()
        ],
        token_evidence_texts=[
            text
            for text in list(per_row_after) + [token_seed_text]
            if str(text or "").strip()
        ],
        edit_scope="tokens",
    )
    hybrid_text_candidate = _normalize_reference_text_candidate(
        token_edit_payload.get("text") or raw_text
    )
    candidate_cleanups.update(backbone_payload.get("cleanups_applied") or [])
    candidate_cleanups.update(token_edit_payload.get("cleanups_applied") or [])
    token_text = str(token_text_candidate.get("text") or raw_text)
    hybrid_text = str(token_edit_payload.get("text") or raw_text)
    final_text = hybrid_text or raw_text
    confidence = round(token_rows_used / max(len(rows), 1), 3)
    return {
        "raw_text": raw_text,
        "token_text": token_text,
        "hybrid_text": hybrid_text,
        "final_text": final_text,
        "token_cleanup_confidence": confidence,
        "token_rows_used": token_rows_used,
        "per_row_before": per_row_before,
        "per_row_after": per_row_after,
        "per_row_selected": per_row_selected,
        "backbone_local_edits": backbone_payload.get("backbone_local_edits") or [],
        "local_token_edits": token_edit_payload.get("edits") or [],
        "new_word_split_detected": bool(
            backbone_payload.get("new_word_split_detected")
            or token_edit_payload.get("new_word_split_detected")
        ),
        "lexical_degradation_detected": bool(
            backbone_payload.get("lexical_degradation_detected")
            or token_edit_payload.get("lexical_degradation_detected")
        ),
        "accepted_local_edit_count": int(
            backbone_payload.get("accepted_local_edit_count") or 0
        )
        + int(token_edit_payload.get("accepted_local_edit_count") or 0),
        "rejected_local_edit_count": int(
            backbone_payload.get("rejected_local_edit_count") or 0
        )
        + int(token_edit_payload.get("rejected_local_edit_count") or 0),
        "selected_candidate_source": (
            "rows_hybrid"
            if str(hybrid_text or "") != str(raw_text or "")
            and int(token_edit_payload.get("accepted_local_edit_count") or 0) > 0
            else "rows_raw"
        ),
        "backbone_text": raw_text,
        "backbone_source": "rows_raw",
        "cleanups_applied": sorted(candidate_cleanups),
        "candidates": [
            {
                "source": "rows_raw",
                "text": raw_text,
                "quality_score": _reference_text_quality_score(raw_text),
                "cleanups_applied": sorted(
                    {
                        str(name).strip()
                        for name in list(backbone_payload.get("cleanups_applied") or [])
                        if str(name).strip()
                    }
                ),
            },
            {
                "source": "rows_tokens",
                "text": token_text,
                "quality_score": _reference_text_quality_score(token_text),
                "cleanups_applied": token_text_candidate.get("cleanups_applied") or [],
            },
            {
                "source": "rows_hybrid",
                "text": hybrid_text,
                "quality_score": _reference_text_quality_score(hybrid_text),
                "cleanups_applied": sorted(
                    {
                        str(name).strip()
                        for name in list(
                            hybrid_text_candidate.get("cleanups_applied") or []
                        )
                        + list(backbone_payload.get("cleanups_applied") or [])
                        + list(token_edit_payload.get("cleanups_applied") or [])
                        if str(name).strip()
                    }
                ),
            },
        ],
    }


def _score_crossref_candidate(
    reference_text: str,
    reference_doi: str,
    candidate: Dict[str, Any],
) -> float:
    candidate_doi = _normalize_doi(candidate.get("doi"))
    if reference_doi and candidate_doi and reference_doi == candidate_doi:
        return 1.0
    local_norm = _normalize_text(reference_text)
    candidate_text = _normalize_text(
        candidate.get("raw_text")
        or candidate.get("title")
        or " ".join(candidate.get("authors") or [])
    )
    if not local_norm or not candidate_text:
        return 0.0
    local_tokens = _tokenize(local_norm)
    candidate_tokens = _tokenize(candidate_text)
    overlap = 0.0
    if local_tokens and candidate_tokens:
        overlap = len(local_tokens.intersection(candidate_tokens)) / max(
            len(candidate_tokens), 1
        )
    score = overlap * 0.7
    title = _normalize_text(candidate.get("title") or "")
    if title and title in local_norm:
        score = max(score, 0.88)
    year = str(candidate.get("year") or "").strip()
    if year and year in local_norm:
        score += 0.06
    return round(max(0.0, min(score, 0.98)), 3)


def _match_reference_against_crossref(
    *,
    reference_text: str,
    reference_doi: str,
    crossref_context: Dict[str, Any],
    allow_doi_lookup: bool = True,
) -> Dict[str, Any]:
    candidates = crossref_context.get("crossref_reference_candidates") or []
    best_match = None
    best_score = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        score = _score_crossref_candidate(reference_text, reference_doi, candidate)
        if score > best_score:
            best_score = score
            best_match = candidate
    doi_match_score = 0.0
    if reference_doi:
        if best_match and _normalize_doi(best_match.get("doi")) == reference_doi:
            doi_match_score = 1.0
        elif allow_doi_lookup and bool(crossref_context.get("crossref_available")):
            try:
                looked_up = crossref_fetch_work_by_doi(reference_doi, timeout=5)
            except Exception:  # pragma: no cover - defensive guard
                looked_up = None
            if isinstance(looked_up, dict):
                doi_match_score = 1.0
                if best_match is None:
                    best_match = {
                        "doi": _normalize_doi(looked_up.get("doi")),
                        "title": str(looked_up.get("title") or "").strip(),
                        "authors": looked_up.get("authors") or [],
                        "year": looked_up.get("year"),
                        "venue": looked_up.get("venue"),
                        "raw_text": str(looked_up.get("title") or "").strip(),
                        "source": "crossref_doi_lookup",
                    }
                    best_score = max(best_score, 0.82)
    return {
        "score": round(best_score, 3),
        "doi_match_score": round(doi_match_score, 3),
        "match": best_match,
    }


def _compute_row_continuity_score(rows: Sequence[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    if len(rows) == 1:
        return 0.72
    penalties = 0.0
    previous = rows[0]
    for row in rows[1:]:
        previous_page = previous.get("page")
        current_page = row.get("page")
        if previous_page != current_page:
            penalties += 0.18
        previous_y1 = _to_float(previous.get("y1"))
        current_y0 = _to_float(row.get("y0"))
        if previous_y1 is not None and current_y0 is not None:
            gap = float(current_y0) - float(previous_y1)
            if gap > 0.07:
                penalties += min(gap * 2.4, 0.26)
        if previous.get("column_id") != row.get("column_id"):
            penalties += 0.28
        previous = row
    return round(max(0.0, min(1.0, 1.0 - penalties)), 3)


def _build_reference_decision(
    *,
    expected_index: int,
    rows: Sequence[Dict[str, Any]],
    reference_text: str,
    block_diagnostics: Dict[str, Any],
    token_reconstruction: Dict[str, Any],
    crossref_match: Dict[str, Any],
    bibliography_segments: Sequence[Dict[str, Any]],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    first_row = rows[0] if rows else {}
    first_text = str(first_row.get("text") or "")
    leading_anchor = _match_reference_anchor_at_line_start(first_text)
    starts_with_anchor = bool(
        leading_anchor
        and leading_anchor.get("accepted")
        and int(leading_anchor.get("index") or 0) == int(expected_index or 0)
    )
    inside_bibliography_zone = bool(
        rows and all(_row_in_any_segment(row, bibliography_segments) for row in rows)
    )
    expected_column = first_row.get("column_id") if rows else None
    inside_expected_column = bool(
        rows and all(row.get("column_id") == expected_column for row in rows)
    )
    has_nested_anchor = bool(block_diagnostics.get("has_nested_anchor"))
    header_noise_score = _score_header_noise(reference_text)
    row_continuity_score = _compute_row_continuity_score(rows)
    token_cleanup_confidence = float(
        token_reconstruction.get("token_cleanup_confidence") or 0.0
    )
    selected_candidate_source = (
        str(token_reconstruction.get("selected_candidate_source") or "rows_raw").strip()
        or "rows_raw"
    )
    selected_candidate_quality = 0.0
    for candidate_score in token_reconstruction.get("candidate_scores") or []:
        if not isinstance(candidate_score, dict):
            continue
        if (
            str(candidate_score.get("source") or "").strip()
            == selected_candidate_source
        ):
            selected_candidate_quality = float(
                candidate_score.get("quality_score") or 0.0
            )
            break
    cleanup_applied = bool(
        token_reconstruction.get("cleanups_applied")
        or selected_candidate_source in {"rows_tokens", "rows_hybrid"}
    )
    new_word_split_detected = bool(token_reconstruction.get("new_word_split_detected"))
    lexical_degradation_detected = bool(
        token_reconstruction.get("lexical_degradation_detected")
    )
    accepted_local_edit_count = int(
        token_reconstruction.get("accepted_local_edit_count") or 0
    )
    rejected_local_edit_count = int(
        token_reconstruction.get("rejected_local_edit_count") or 0
    )
    crossref_match_score = float(crossref_match.get("score") or 0.0)
    doi_match_score = float(crossref_match.get("doi_match_score") or 0.0)
    validation_reason = str(validation.get("reason") or "").strip() or None
    validation_hard_failure = validation_reason in {
        "contains_header_footer_noise",
        "empty_local_text",
        "mixed_rows_multiple_references",
        "short_or_empty_reference",
    }
    final_score = 0.0
    final_score += 0.18 if inside_bibliography_zone else -0.35
    final_score += 0.16 if inside_expected_column else -0.32
    final_score += 0.18 if starts_with_anchor else -0.25
    final_score += 0.14 * row_continuity_score
    final_score += 0.12 * crossref_match_score
    final_score += 0.08 * doi_match_score
    final_score += 0.08 * token_cleanup_confidence
    final_score += 0.04 * selected_candidate_quality
    final_score -= 0.28 * header_noise_score
    if has_nested_anchor:
        final_score -= 0.34
    if validation_hard_failure:
        final_score -= 0.12
    final_score = round(max(0.0, min(1.0, final_score)), 3)
    strong_structural_evidence = bool(
        inside_bibliography_zone
        and inside_expected_column
        and starts_with_anchor
        and not has_nested_anchor
        and row_continuity_score >= 0.9
        and selected_candidate_quality >= 0.62
        and len(reference_text or "") >= 72
    )

    if header_noise_score >= 0.95:
        classification = "rejected_noise"
        accepted = False
        reason = "header_noise_detected"
    elif has_nested_anchor:
        classification = "fallback_needed"
        accepted = False
        reason = "mixed_rows_multiple_references"
    elif validation_hard_failure:
        classification = "fallback_needed"
        accepted = False
        reason = validation_reason or "validation_failed"
    elif strong_structural_evidence and final_score >= 0.62:
        classification = (
            "accepted_with_cleanup" if cleanup_applied else "accepted_structured"
        )
        accepted = True
        reason = "strong_structural_evidence"
    elif final_score >= 0.72 and cleanup_applied:
        classification = "accepted_with_cleanup"
        accepted = True
        reason = "token_cleanup_applied"
    elif final_score >= 0.72:
        classification = "accepted_structured"
        accepted = True
        reason = "rows_structure_consistent"
    elif final_score >= 0.5:
        classification = "fallback_needed"
        accepted = False
        reason = "low_structural_score"
    else:
        classification = "rejected_noise"
        accepted = False
        reason = "insufficient_reference_evidence"

    if validation_reason and accepted and validation_hard_failure:
        reason = validation_reason
    return {
        "inside_bibliography_zone": inside_bibliography_zone,
        "inside_expected_column": inside_expected_column,
        "starts_with_anchor": starts_with_anchor,
        "expected_anchor_index": expected_index,
        "has_nested_anchor": has_nested_anchor,
        "header_noise_score": round(header_noise_score, 3),
        "crossref_match_score": round(crossref_match_score, 3),
        "doi_match_score": round(doi_match_score, 3),
        "row_continuity_score": round(row_continuity_score, 3),
        "token_cleanup_confidence": round(token_cleanup_confidence, 3),
        "selected_candidate_quality": round(selected_candidate_quality, 3),
        "validation_warning": None if validation_hard_failure else validation_reason,
        "cleanup_applied": cleanup_applied,
        "selected_candidate_source": selected_candidate_source,
        "new_word_split_detected": new_word_split_detected,
        "lexical_degradation_detected": lexical_degradation_detected,
        "accepted_local_edit_count": accepted_local_edit_count,
        "rejected_local_edit_count": rejected_local_edit_count,
        "final_score": final_score,
        "accepted": accepted,
        "classification": classification,
        "reason": reason,
    }


def _coerce_reference_validation_payload(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "match_score": 0.0,
            "mixed_reference_score": 0.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": None,
        }
    return {
        "match_score": round(float(value.get("match_score") or 0.0), 3),
        "mixed_reference_score": round(
            float(value.get("mixed_reference_score") or 0.0),
            3,
        ),
        "has_nested_anchor": bool(value.get("has_nested_anchor")),
        "accepted": bool(value.get("accepted")),
        "reason": value.get("reason"),
    }


def _sync_reference_validation_with_final_decision(
    validation: Any,
    final_decision: Any,
) -> Dict[str, Any]:
    normalized_validation = _coerce_reference_validation_payload(validation)
    normalized_decision = (
        dict(final_decision)
        if isinstance(final_decision, dict)
        else {
            "accepted": False,
            "classification": "fallback_needed",
            "reason": "missing_final_decision",
            "final_score": 0.0,
        }
    )
    synced = dict(normalized_validation)
    synced["intermediate_accepted"] = bool(normalized_validation.get("accepted"))
    synced["intermediate_reason"] = normalized_validation.get("reason")
    synced["accepted"] = bool(normalized_decision.get("accepted"))
    synced["reason"] = (
        None
        if normalized_decision.get("accepted")
        else normalized_decision.get("reason")
    )
    synced["final_classification"] = normalized_decision.get("classification")
    synced["final_score"] = round(
        float(normalized_decision.get("final_score") or 0.0),
        3,
    )
    return synced


def is_numbered_bibliography(lines: Sequence[Dict[str, Any]]) -> bool:
    if len(lines) < 6:
        return False
    numbers: List[int] = []
    for line in lines:
        anchor = _match_reference_anchor_at_line_start(str(line.get("text") or ""))
        if not anchor or not anchor.get("accepted"):
            continue
        try:
            number = int(anchor.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if number > 0:
            numbers.append(number)
    if len(numbers) < 3:
        return False

    unique_numbers = sorted(set(numbers))
    if len(unique_numbers) < 3:
        return False
    if unique_numbers[0] > 10:
        return False

    density = len(numbers) / max(len(lines), 1)
    if density < 0.08:
        return False

    if len(unique_numbers) >= 4:
        contiguous_pairs = sum(
            1
            for i in range(len(unique_numbers) - 1)
            if unique_numbers[i + 1] == unique_numbers[i] + 1
        )
        continuity = contiguous_pairs / max(len(unique_numbers) - 1, 1)
        if continuity < 0.45:
            return False
    return True


def split_bibliography_columns(
    lines: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if len(lines) < 8:
        return list(lines), []
    x_values = sorted(
        float(line["box"][0]) for line in lines if _normalize_box(line.get("box"))
    )
    if len(x_values) < 8:
        return list(lines), []

    max_gap = 0.0
    split_threshold: Optional[float] = None
    for left_x, right_x in zip(x_values, x_values[1:]):
        gap = right_x - left_x
        if gap > max_gap:
            max_gap = gap
            split_threshold = (left_x + right_x) / 2.0

    if split_threshold is None or max_gap < 0.14:
        return list(lines), []

    left_column: List[Dict[str, Any]] = []
    right_column: List[Dict[str, Any]] = []
    for line in lines:
        box = _normalize_box(line.get("box"))
        if box is None:
            continue
        if float(box[0]) < split_threshold:
            left_column.append(line)
        else:
            right_column.append(line)

    if len(left_column) < 3 or len(right_column) < 3:
        return list(lines), []
    balance_ratio = min(len(left_column), len(right_column)) / max(
        len(left_column),
        len(right_column),
    )
    if balance_ratio < 0.18:
        return list(lines), []

    left_median = _median([float(item["box"][0]) for item in left_column])
    right_median = _median([float(item["box"][0]) for item in right_column])
    if right_median - left_median < 0.16:
        return list(lines), []
    return left_column, right_column


def _sort_bibliography_lines_reading_flow(
    lines: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for line in lines:
        page = line.get("page")
        box = _normalize_box(line.get("box"))
        if not isinstance(page, int) or box is None:
            continue
        by_page[page].append(
            {
                "id": str(line.get("id") or ""),
                "text": str(line.get("text") or ""),
                "page": page,
                "box": box,
            }
        )

    ordered: List[Dict[str, Any]] = []
    for page in sorted(by_page.keys()):
        page_lines = by_page[page]
        left_column, right_column = split_bibliography_columns(page_lines)
        if right_column:
            ordered.extend(sorted(left_column, key=_line_sort_key))
            ordered.extend(sorted(right_column, key=_line_sort_key))
        else:
            ordered.extend(sorted(page_lines, key=_line_sort_key))
    return ordered


def detect_reference_anchors_from_rows(
    rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    anchors: List[Dict[str, Any]] = []
    for position, row in enumerate(rows):
        text = str(row.get("text") or "")
        anchor = _match_reference_anchor_at_line_start(text)
        if not anchor or not anchor.get("accepted"):
            continue
        try:
            index = int(anchor.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if index <= 0:
            continue
        anchors.append(
            {
                "index": index,
                "page": row.get("page"),
                "column_id": row.get("column_id"),
                "position": int(row.get("flow_position", position)),
                "anchor_style": anchor.get("anchor_style"),
                "row": row,
                "line": row,  # Compatibilidad con llamadas legacy.
            }
        )
    for idx, anchor in enumerate(anchors):
        previous_index = int(anchors[idx - 1]["index"]) if idx > 0 else None
        next_index = int(anchors[idx + 1]["index"]) if idx + 1 < len(anchors) else None
        anchor["sequence_supported"] = bool(
            previous_index == anchor["index"] - 1 or next_index == anchor["index"] + 1
        )
    return anchors


def extract_numbered_anchors(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Alias de compatibilidad para el flujo legacy.
    return detect_reference_anchors_from_rows(lines)


def _format_reference_anchor_prefix(index: Any, anchor_style: str) -> str:
    try:
        anchor_index = int(index)
    except (TypeError, ValueError):
        return str(index or "")
    if anchor_style == "bracketed":
        return f"[{anchor_index}]"
    if anchor_style == "dotted":
        return f"{anchor_index}."
    if anchor_style == "suffix_paren":
        return f"{anchor_index})"
    if anchor_style == "wrapped_paren":
        return f"({anchor_index})"
    return str(anchor_index)


def _dominant_anchor_style_from_counts(style_counts: Dict[str, int]) -> str:
    ranked = [
        (style, int(style_counts.get(style) or 0))
        for style in NUMERIC_ANCHOR_STYLES
        if int(style_counts.get(style) or 0) > 0
    ]
    if not ranked:
        return "unknown"
    if len(ranked) == 1:
        return ranked[0][0]

    ranked.sort(key=lambda item: (-item[1], NUMERIC_ANCHOR_STYLES.index(item[0])))
    top_style, top_count = ranked[0]
    second_count = ranked[1][1]
    if top_count >= max(2, second_count + 1):
        return top_style
    return "unknown"


def _clean_reference_text(lines: Sequence[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for line in lines:
        text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
        if not text:
            continue
        if _is_reference_noise_text(text):
            continue
        if parts and parts[-1].endswith("-") and text and text[0].islower():
            parts[-1] = f"{parts[-1][:-1]}{text}"
        else:
            parts.append(text)

    merged = " ".join(parts)
    merged = re.sub(r"\s+([,.;:)\]])", r"\1", merged)
    merged = re.sub(r"([\[(])\s+", r"\1", merged)
    merged = re.sub(r"https?\s*:\s*//", "https://", merged, flags=re.IGNORECASE)
    merged = re.sub(r"doi\.org/\s+", "doi.org/", merged, flags=re.IGNORECASE)
    merged = re.sub(r"(doi\.org/10\.)\s+(\d)", r"\1\2", merged, flags=re.IGNORECASE)
    merged = re.sub(r"(10\.\d{4,9}/)\s+([A-Za-z0-9])", r"\1\2", merged)
    merged = re.sub(r"(10\.\d{4,9}/[^\s]+)\s+([A-Za-z0-9])", r"\1\2", merged)
    return re.sub(r"\s+", " ", merged).strip()


def _is_reference_header_like(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    if not HEADER_LIKE_REFERENCE_RE.search(text or ""):
        return False
    has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", text or ""))
    has_doi = bool(_extract_doi(text or ""))
    return not has_year and not has_doi


def _is_valid_reference_block(
    *,
    expected_index: int,
    lines: Sequence[Dict[str, Any]],
    text: str,
) -> bool:
    if not lines:
        return False
    first_line = str(lines[0].get("text") or "")
    first_anchor = _match_reference_anchor_at_line_start(first_line)
    if not first_anchor or not first_anchor.get("accepted"):
        return False
    try:
        first_index = int(first_anchor.get("index") or 0)
    except (TypeError, ValueError):
        return False
    if first_index != expected_index:
        return False

    extra_line_anchors = sum(
        1
        for line in lines[1:]
        if _match_reference_anchor_at_line_start(str(line.get("text") or ""))
    )
    if extra_line_anchors > 0:
        return False

    if len(text) < 24:
        return False
    if _is_reference_noise_text(text):
        return False
    if _is_reference_header_like(text):
        return False

    anchor_mentions = _extract_inline_anchor_numbers(text)
    foreign_anchor_mentions = [
        value for value in anchor_mentions if value != expected_index
    ]
    if len(foreign_anchor_mentions) >= 2:
        return False
    return True


def _default_reference_validation(
    *,
    text: str,
    expected_index: int,
) -> Dict[str, Any]:
    if _is_reference_noise_text(text):
        return {
            "match_score": 0.0,
            "mixed_reference_score": 1.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": "contains_header_footer_noise",
        }
    anchor_mentions = _extract_inline_anchor_numbers(text)
    foreign_anchors = [value for value in anchor_mentions if value != expected_index]
    has_nested = len(foreign_anchors) > 0
    mixed_score = 0.72 if has_nested else 0.12
    accepted = bool(len(text) >= 24 and not has_nested)
    reason = (
        None
        if accepted
        else (
            "mixed_rows_multiple_references"
            if has_nested
            else "short_or_empty_reference"
        )
    )
    return {
        "match_score": 0.0,
        "mixed_reference_score": round(mixed_score, 3),
        "has_nested_anchor": has_nested,
        "accepted": accepted,
        "reason": reason,
    }


def _build_reference_validation(
    *,
    text: str,
    expected_index: int,
    metadata: Optional[Dict[str, Any]],
    metadata_by_index: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    if _is_reference_noise_text(text):
        return {
            "match_score": 0.0,
            "mixed_reference_score": 1.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": "contains_header_footer_noise",
        }
    if not isinstance(metadata, dict):
        return _default_reference_validation(text=text, expected_index=expected_index)
    metadata_signals = {
        "doi": metadata.get("doi"),
        "title": metadata.get("title"),
        "authors": metadata.get("authors"),
        "year": metadata.get("year"),
        "venue": metadata.get("venue"),
    }
    has_metadata = any(bool(value) for value in metadata_signals.values())
    if not has_metadata:
        return _default_reference_validation(text=text, expected_index=expected_index)
    candidate_doi = _normalize_doi(metadata.get("doi"))
    has_rich_metadata = any(
        bool(metadata_signals[key]) for key in ("title", "authors", "year", "venue")
    )
    if candidate_doi and len(candidate_doi) < 12 and not has_rich_metadata:
        return _default_reference_validation(text=text, expected_index=expected_index)
    other_candidates = [
        (idx, candidate)
        for idx, candidate in metadata_by_index.items()
        if idx != expected_index and isinstance(candidate, dict)
    ]
    result = validate_reference_against_metadata(
        text,
        metadata,
        expected_index=expected_index,
        other_metadata_candidates=other_candidates,
    )
    if _is_reference_noise_text(text):
        result["accepted"] = False
        result["reason"] = "contains_header_footer_noise"
    return result


def build_reference_rows_between_anchors(
    *,
    ordered_rows: Sequence[Dict[str, Any]],
    current_anchor: Dict[str, Any],
    next_anchor: Optional[Dict[str, Any]],
    artifact_info: Dict[str, Any],
    include_diagnostics: bool = False,
) -> Any:
    start = int(current_anchor.get("position", 0))
    end = len(ordered_rows)
    if next_anchor is not None:
        candidate_end = int(next_anchor.get("position", end))
        if candidate_end > start:
            end = candidate_end
    if start < 0 or start >= len(ordered_rows):
        empty = {
            "rows": [],
            "row_decisions": [],
            "cut_reasons": ["invalid_anchor_position"],
            "has_nested_anchor": False,
            "nested_anchor_indices": [],
        }
        return empty if include_diagnostics else []

    expected_index = int(current_anchor.get("index") or 0)
    expected_column = current_anchor.get("column_id")
    anchor_page = current_anchor.get("page")
    anchor_x0 = _to_float((current_anchor.get("row") or current_anchor).get("x0"))
    selected_rows: List[Dict[str, Any]] = []
    row_decisions: List[Dict[str, Any]] = []
    cut_reasons: List[str] = []
    nested_anchor_indices: List[int] = []
    for position in range(start, min(end, len(ordered_rows))):
        row = ordered_rows[position]
        row_box = _normalize_box(row.get("box"))
        text = str(row.get("text") or "").strip()
        if not text:
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "box": row_box,
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "empty_text",
                }
            )
            continue
        is_anchor_row = position == start
        inline_anchor_numbers = _extract_inline_anchor_numbers(text)
        noise_override_payload = {"accepted": False, "reasons": []}
        foreign_inline_anchors = [
            value for value in inline_anchor_numbers if value != expected_index
        ]
        if foreign_inline_anchors and not is_anchor_row:
            nested_anchor_indices.extend(foreign_inline_anchors)
            cut_reasons.append(f"nested_anchor:{foreign_inline_anchors[0]}")
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "box": row_box,
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "nested_anchor_detected",
                    "inline_anchor_numbers": inline_anchor_numbers,
                }
            )
            break
        if not is_anchor_row and _match_reference_anchor_at_line_start(text):
            cut_reasons.append("next_anchor_row")
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "box": row_box,
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "next_anchor_row",
                    "inline_anchor_numbers": inline_anchor_numbers,
                }
            )
            break
        if not is_anchor_row and _is_header_footer_row(row, artifact_info):
            previous_row = (
                selected_rows[-1]
                if selected_rows
                else (current_anchor.get("row") or current_anchor)
            )
            noise_override_payload = _strong_bibliography_continuation_row(
                row=row,
                previous_row=previous_row,
                current_anchor=current_anchor,
                next_anchor=next_anchor,
                in_bibliography_zone=True,
            )
            if not noise_override_payload.get("accepted"):
                row_decisions.append(
                    {
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
                        "box": row_box,
                        "column_id": row.get("column_id"),
                        "text": text,
                        "included": False,
                        "reason": "header_footer_noise",
                        "inline_anchor_numbers": inline_anchor_numbers,
                    }
                )
                continue

        row_column = row.get("column_id")
        if (
            not is_anchor_row
            and expected_column in {"left", "right"}
            and row_column in {"left", "right"}
            and row_column != expected_column
        ):
            cut_reasons.append("column_change")
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "box": row_box,
                    "column_id": row_column,
                    "text": text,
                    "included": False,
                    "reason": "column_change",
                    "inline_anchor_numbers": inline_anchor_numbers,
                }
            )
            break

        if (
            not is_anchor_row
            and isinstance(anchor_page, int)
            and row.get("page") == anchor_page
        ):
            row_x0 = _to_float(row.get("x0"))
            if (
                anchor_x0 is not None
                and row_x0 is not None
                and abs(float(row_x0) - float(anchor_x0)) > 0.18
            ):
                row_decisions.append(
                    {
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
                        "box": row_box,
                        "column_id": row_column,
                        "text": text,
                        "included": False,
                        "reason": "unexpected_horizontal_shift",
                        "inline_anchor_numbers": inline_anchor_numbers,
                    }
                )
                continue

        if selected_rows:
            previous = selected_rows[-1]
            previous_page = previous.get("page")
            current_page = row.get("page")
            if isinstance(previous_page, int) and isinstance(current_page, int):
                if current_page < previous_page:
                    cut_reasons.append("page_order_reversed")
                    break
                if current_page == previous_page:
                    previous_y1 = _to_float(previous.get("y1"))
                    current_y0 = _to_float(row.get("y0"))
                    if previous_y1 is not None and current_y0 is not None:
                        gap = float(current_y0) - float(previous_y1)
                        if gap > 0.085:
                            cut_reasons.append(f"vertical_gap:{round(gap, 4)}")
                            row_decisions.append(
                                {
                                    "row_id": str(row.get("id") or ""),
                                    "page": current_page,
                                    "box": row_box,
                                    "column_id": row_column,
                                    "text": text,
                                    "included": False,
                                    "reason": "vertical_gap",
                                    "gap": round(gap, 4),
                                    "inline_anchor_numbers": inline_anchor_numbers,
                                }
                            )
                            break
                elif current_page - previous_page > 1:
                    cut_reasons.append("page_jump")
                    break
                elif (_to_float(row.get("y0")) or 1.0) > 0.36:
                    cut_reasons.append("late_page_continuation")
                    break

        selected_rows.append(row)
        row_decisions.append(
            {
                "row_id": str(row.get("id") or ""),
                "page": row.get("page"),
                "box": row_box,
                "column_id": row_column,
                "text": text,
                "included": True,
                "reason": "selected",
                "inline_anchor_numbers": inline_anchor_numbers,
                "header_footer_noise_overridden": bool(
                    noise_override_payload.get("accepted")
                ),
                "noise_override": (
                    "bibliography_continuation_context"
                    if noise_override_payload.get("accepted")
                    else None
                ),
                "noise_override_reasons": list(
                    noise_override_payload.get("reasons") or []
                ),
            }
        )
        if len(selected_rows) >= 14:
            cut_reasons.append("row_limit")
            break

    diagnostics = {
        "rows": selected_rows,
        "row_decisions": row_decisions,
        "cut_reasons": cut_reasons,
        "has_nested_anchor": bool(nested_anchor_indices),
        "nested_anchor_indices": sorted(set(nested_anchor_indices)),
    }
    return diagnostics if include_diagnostics else selected_rows


def build_references_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    metadata_by_index: Optional[Dict[int, Dict[str, Any]]] = None,
    bibliography_segments: Optional[Sequence[Dict[str, Any]]] = None,
    token_items: Optional[Sequence[Dict[str, Any]]] = None,
    crossref_context: Optional[Dict[str, Any]] = None,
    row_debug_collector: Optional[List[Dict[str, Any]]] = None,
    token_debug_collector: Optional[List[Dict[str, Any]]] = None,
) -> Dict[int, Dict[str, Any]]:
    ordered_rows = build_bibliography_reading_flow(rows)
    if len(ordered_rows) < 4:
        return {}

    artifact_info = _build_repeating_page_artifacts(ordered_rows)
    anchors = detect_reference_anchors_from_rows(ordered_rows)
    if len(anchors) < 2:
        return {}

    metadata_by_index = metadata_by_index or {}
    first_anchor_by_index: Dict[int, Dict[str, Any]] = {}
    for anchor in anchors:
        index = int(anchor.get("index") or 0)
        if index <= 0 or index in first_anchor_by_index:
            continue
        first_anchor_by_index[index] = anchor
    if len(first_anchor_by_index) < 2:
        return {}

    tokens_by_page = _index_tokens_by_page(token_items or [])
    bibliography_segments = list(bibliography_segments or [])
    crossref_context = crossref_context or {}
    parsed: Dict[int, Dict[str, Any]] = {}
    ordered_indices = sorted(first_anchor_by_index.keys())
    all_anchor_positions = sorted(
        int(anchor.get("position", -1))
        for anchor in first_anchor_by_index.values()
        if int(anchor.get("position", -1)) >= 0
    )
    for index in ordered_indices:
        anchor = first_anchor_by_index[index]
        start_position = int(anchor.get("position", -1))
        if start_position < 0:
            continue
        next_anchor = first_anchor_by_index.get(index + 1)
        if next_anchor is None:
            for position in all_anchor_positions:
                if position > start_position:
                    next_anchor = {"position": position}
                    break

        block_result = build_reference_rows_between_anchors(
            ordered_rows=ordered_rows,
            current_anchor=anchor,
            next_anchor=next_anchor,
            artifact_info=artifact_info,
            include_diagnostics=True,
        )
        block_rows = block_result.get("rows") or []
        if not block_rows:
            continue
        token_reconstruction = _reconstruct_reference_text_from_rows_and_tokens(
            block_rows,
            tokens_by_page,
        )
        reference_doi_seed = (
            _extract_doi(token_reconstruction.get("raw_text"))
            or _extract_doi(token_reconstruction.get("hybrid_text"))
            or _extract_doi(token_reconstruction.get("token_text"))
            or ""
        )
        selected_candidate = _select_reference_text_candidate(
            candidates=token_reconstruction.get("candidates") or [],
            reference_doi=reference_doi_seed,
            crossref_context=crossref_context,
        )
        selected_candidate_source = (
            str(
                selected_candidate.get("source")
                or token_reconstruction.get("selected_candidate_source")
                or "rows_raw"
            ).strip()
            or "rows_raw"
        )
        token_reconstruction["selected_candidate_source"] = selected_candidate_source
        token_reconstruction["candidate_scores"] = (
            selected_candidate.get("candidate_scores") or []
        )
        token_reconstruction["order_similarity_to_rows"] = selected_candidate.get(
            "order_similarity_to_rows"
        )
        token_reconstruction["order_guard_reasons"] = (
            selected_candidate.get("order_guard_reasons") or []
        )
        token_reconstruction["backbone_source"] = selected_candidate.get(
            "backbone_source"
        ) or token_reconstruction.get("backbone_source")
        token_reconstruction["backbone_text"] = str(
            selected_candidate.get("backbone_text")
            or token_reconstruction.get("backbone_text")
            or token_reconstruction.get("hybrid_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        token_reconstruction["cleanups_applied"] = sorted(
            {
                str(name).strip()
                for name in list(token_reconstruction.get("cleanups_applied") or [])
                + list(selected_candidate.get("cleanups_applied") or [])
                if str(name).strip()
            }
        )
        token_reconstruction["final_text"] = str(
            selected_candidate.get("text")
            or token_reconstruction.get("hybrid_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        block_text = str(token_reconstruction.get("final_text") or "").strip()
        if not _is_valid_reference_block(
            expected_index=index,
            lines=block_rows,
            text=block_text,
        ):
            continue
        union_box = _union_boxes(
            [row["box"] for row in block_rows if _normalize_box(row.get("box"))]
        )
        local_validation = _build_reference_validation(
            text=block_text,
            expected_index=index,
            metadata=metadata_by_index.get(index),
            metadata_by_index=metadata_by_index,
        )
        intermediate_validation = _coerce_reference_validation_payload(local_validation)
        crossref_match = _match_reference_against_crossref(
            reference_text=block_text,
            reference_doi=_extract_doi(block_text),
            crossref_context=crossref_context,
        )
        decision = _build_reference_decision(
            expected_index=index,
            rows=block_rows,
            reference_text=block_text,
            block_diagnostics=block_result,
            token_reconstruction=token_reconstruction,
            crossref_match=crossref_match,
            bibliography_segments=bibliography_segments,
            validation=local_validation,
        )
        merged_validation = {
            "match_score": round(
                max(
                    float(local_validation.get("match_score") or 0.0),
                    float(crossref_match.get("score") or 0.0),
                    float(crossref_match.get("doi_match_score") or 0.0),
                ),
                3,
            ),
            "mixed_reference_score": round(
                max(
                    float(local_validation.get("mixed_reference_score") or 0.0),
                    1.0 if decision["has_nested_anchor"] else 0.0,
                ),
                3,
            ),
            "has_nested_anchor": bool(decision["has_nested_anchor"]),
            "accepted": bool(decision["accepted"]),
            "reason": None if decision["accepted"] else decision["reason"],
        }
        final_decision = dict(decision)
        local_validation = _sync_reference_validation_with_final_decision(
            merged_validation,
            final_decision,
        )
        structure_source = (
            selected_candidate_source
            if selected_candidate_source.startswith("rows")
            else "rows"
        )
        parsed[index] = {
            "text": block_text,
            "text_raw": token_reconstruction.get("raw_text"),
            "page": block_rows[0].get("page"),
            "box": union_box,
            "rows": block_rows,
            "local_row_count": len(block_rows),
            "local_anchor_detected": True,
            "structure_source": structure_source,
            "reference_validation": local_validation,
            "validation_intermediate": intermediate_validation,
            "column_id": anchor.get("column_id"),
            "anchor_position": start_position,
            "anchor_style": anchor.get("anchor_style"),
            "scores": final_decision,
            "final_decision": final_decision,
            "crossref_match": crossref_match,
            "token_reconstruction": {
                "raw_text": token_reconstruction.get("raw_text"),
                "token_text": token_reconstruction.get("token_text"),
                "hybrid_text": token_reconstruction.get("hybrid_text"),
                "final_text": token_reconstruction.get("final_text"),
                "selected_candidate_source": selected_candidate_source,
                "order_similarity_to_rows": token_reconstruction.get(
                    "order_similarity_to_rows"
                ),
                "order_guard_reasons": token_reconstruction.get("order_guard_reasons")
                or [],
                "backbone_source": token_reconstruction.get("backbone_source"),
                "backbone_text": token_reconstruction.get("backbone_text"),
                "cleanups_applied": token_reconstruction.get("cleanups_applied") or [],
                "candidate_scores": token_reconstruction.get("candidate_scores") or [],
                "token_cleanup_confidence": token_reconstruction.get(
                    "token_cleanup_confidence"
                ),
                "token_rows_used": token_reconstruction.get("token_rows_used"),
                "backbone_local_edits": token_reconstruction.get("backbone_local_edits")
                or [],
                "local_token_edits": token_reconstruction.get("local_token_edits")
                or [],
                "new_word_split_detected": bool(
                    token_reconstruction.get("new_word_split_detected")
                ),
                "lexical_degradation_detected": bool(
                    token_reconstruction.get("lexical_degradation_detected")
                ),
                "accepted_local_edit_count": int(
                    token_reconstruction.get("accepted_local_edit_count") or 0
                ),
                "rejected_local_edit_count": int(
                    token_reconstruction.get("rejected_local_edit_count") or 0
                ),
            },
            "anomalies": {
                "cut_reasons": block_result.get("cut_reasons") or [],
                "nested_anchor_indices": block_result.get("nested_anchor_indices")
                or [],
            },
        }
        if isinstance(row_debug_collector, list):
            row_debug_collector.append(
                {
                    "reference_index": index,
                    "current_anchor_index": index,
                    "next_anchor_index": _to_int((next_anchor or {}).get("index")),
                    "row_decisions": block_result.get("row_decisions") or [],
                    "cut_reasons": block_result.get("cut_reasons") or [],
                    "nested_anchor_indices": block_result.get("nested_anchor_indices")
                    or [],
                    "validation_intermediate": intermediate_validation,
                    "final_decision": final_decision,
                }
            )
        if isinstance(token_debug_collector, list):
            token_debug_collector.append(
                {
                    "reference_index": index,
                    "before": token_reconstruction.get("raw_text"),
                    "after": token_reconstruction.get("final_text"),
                    "before_full": token_reconstruction.get("raw_text"),
                    "token_full": token_reconstruction.get("token_text"),
                    "hybrid_full": token_reconstruction.get("hybrid_text"),
                    "selected_candidate_source": selected_candidate_source,
                    "order_similarity_to_rows": token_reconstruction.get(
                        "order_similarity_to_rows"
                    ),
                    "order_guard_reasons": token_reconstruction.get(
                        "order_guard_reasons"
                    )
                    or [],
                    "backbone_source": token_reconstruction.get("backbone_source"),
                    "backbone_text": token_reconstruction.get("backbone_text"),
                    "candidate_scores": token_reconstruction.get("candidate_scores")
                    or [],
                    "cleanups_applied": token_reconstruction.get("cleanups_applied")
                    or [],
                    "per_row_before": token_reconstruction.get("per_row_before") or [],
                    "per_row_after": token_reconstruction.get("per_row_after") or [],
                    "per_row_selected": token_reconstruction.get("per_row_selected")
                    or [],
                    "backbone_local_edits": token_reconstruction.get(
                        "backbone_local_edits"
                    )
                    or [],
                    "local_token_edits": token_reconstruction.get("local_token_edits")
                    or [],
                    "new_word_split_detected": bool(
                        token_reconstruction.get("new_word_split_detected")
                    ),
                    "lexical_degradation_detected": bool(
                        token_reconstruction.get("lexical_degradation_detected")
                    ),
                    "accepted_local_edit_count": int(
                        token_reconstruction.get("accepted_local_edit_count") or 0
                    ),
                    "rejected_local_edit_count": int(
                        token_reconstruction.get("rejected_local_edit_count") or 0
                    ),
                    "token_cleanup_confidence": token_reconstruction.get(
                        "token_cleanup_confidence"
                    ),
                    "doi_after_cleanup": _extract_doi(block_text) or None,
                }
            )
    return parsed


def _strip_numeric_anchor_prefix(text: str) -> str:
    value = str(text or "")
    bracketed_match = BRACKETED_REFERENCE_LINE_RE.match(value)
    if bracketed_match:
        return value[bracketed_match.end() :].lstrip()
    for candidate_pattern in (
        DOTTED_REFERENCE_CANDIDATE_RE,
        SUFFIX_PAREN_REFERENCE_CANDIDATE_RE,
        WRAPPED_PAREN_REFERENCE_CANDIDATE_RE,
    ):
        candidate_match = candidate_pattern.match(value)
        if candidate_match:
            return str(candidate_match.group(2) or "").lstrip()
    return value.strip()


def _match_marker_only_numeric_anchor(text: str) -> Optional[Dict[str, Any]]:
    value = str(text or "")
    for pattern, style in (
        (MARKER_ONLY_BRACKETED_REFERENCE_RE, "bracketed"),
        (MARKER_ONLY_DOTTED_REFERENCE_RE, "dotted"),
        (MARKER_ONLY_SUFFIX_PAREN_REFERENCE_RE, "suffix_paren"),
        (MARKER_ONLY_WRAPPED_PAREN_REFERENCE_RE, "wrapped_paren"),
    ):
        match = pattern.match(value)
        if not match:
            continue
        try:
            index = int(match.group(1))
        except (TypeError, ValueError):
            return None
        if index <= 0 or (
            style in {"suffix_paren", "wrapped_paren"} and 1900 <= index <= 2099
        ):
            return None
        return {
            "index": index,
            "anchor_style": style,
            "accepted": True,
            "anchor_rejected_reason": None,
        }
    return None


def _row_geometry_edges(
    row: Dict[str, Any],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    box = _normalize_box(row.get("box"))
    x0 = _to_float(row.get("x0"))
    y0 = _to_float(row.get("y0"))
    x1 = _to_float(row.get("x1"))
    y1 = _to_float(row.get("y1"))
    if box is not None:
        if x0 is None:
            x0 = float(box[0])
        if y0 is None:
            y0 = float(box[1])
        if x1 is None:
            x1 = float(box[0]) + float(box[2])
        if y1 is None:
            y1 = float(box[1]) + float(box[3])
    return x0, y0, x1, y1


def _estimate_numeric_body_x0_reference_v3(
    ordered_rows: Sequence[Dict[str, Any]],
) -> Optional[float]:
    x0_values: List[float] = []
    for row in ordered_rows:
        text = str(row.get("text") or "").strip()
        if not text or _row_is_section_transition_v2(text):
            continue
        if not _has_v2_bibliographic_body_signal(_strip_numeric_anchor_prefix(text)):
            continue
        marker_only = _match_marker_only_numeric_anchor(text)
        x0, _, x1, _ = _row_geometry_edges(row)
        if x0 is None:
            continue
        if marker_only and x1 is not None and float(x1) - float(x0) <= 0.16:
            continue
        x0_values.append(float(x0))
    if not x0_values:
        return None
    return float(_median(x0_values))


def _build_marker_only_anchor_link_map_v3(
    ordered_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    body_x0_reference = _estimate_numeric_body_x0_reference_v3(ordered_rows)
    marker_rows_total = 0
    linked_rows: List[Dict[str, Any]] = []
    link_failures: List[Dict[str, Any]] = []

    for position, row in enumerate(ordered_rows):
        text = str(row.get("text") or "").strip()
        marker_only = _match_marker_only_numeric_anchor(text)
        if not marker_only:
            continue
        marker_rows_total += 1
        normalized_marker = re.sub(r"\s+", "", text)
        if len(normalized_marker) > 9:
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": _to_int(marker_only.get("index")),
                    "page": _to_int(row.get("page")),
                    "reason": "marker_not_short_enough",
                }
            )
            continue
        if _has_v2_bibliographic_body_signal(_strip_numeric_anchor_prefix(text)):
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": _to_int(marker_only.get("index")),
                    "page": _to_int(row.get("page")),
                    "reason": "marker_row_has_inline_body",
                }
            )
            continue
        anchor_x0, anchor_y0, anchor_x1, anchor_y1 = _row_geometry_edges(row)
        if None in (anchor_x0, anchor_y0, anchor_x1, anchor_y1):
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": _to_int(marker_only.get("index")),
                    "page": _to_int(row.get("page")),
                    "reason": "marker_row_missing_geometry",
                }
            )
            continue

        marker_width = float(anchor_x1) - float(anchor_x0)
        if marker_width > 0.15:
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": _to_int(marker_only.get("index")),
                    "page": _to_int(row.get("page")),
                    "reason": "marker_row_too_wide",
                }
            )
            continue
        if body_x0_reference is not None:
            if float(anchor_x0) >= float(body_x0_reference) - 0.05:
                link_failures.append(
                    {
                        "row_id": str(row.get("id") or ""),
                        "index": _to_int(marker_only.get("index")),
                        "page": _to_int(row.get("page")),
                        "reason": "marker_not_in_left_gutter_band",
                    }
                )
                continue
            if float(anchor_x1) >= float(body_x0_reference) - 0.008:
                link_failures.append(
                    {
                        "row_id": str(row.get("id") or ""),
                        "index": _to_int(marker_only.get("index")),
                        "page": _to_int(row.get("page")),
                        "reason": "marker_without_horizontal_gap_to_body_band",
                    }
                )
                continue
        elif float(anchor_x0) > 0.3:
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": _to_int(marker_only.get("index")),
                    "page": _to_int(row.get("page")),
                    "reason": "marker_not_in_left_half_without_body_band_reference",
                }
            )
            continue

        anchor_page = _to_int(row.get("page"))
        anchor_index = _to_int(marker_only.get("index"))
        if anchor_page is None or anchor_index is None or anchor_index <= 0:
            continue
        best_link: Optional[Dict[str, Any]] = None
        scan_limit = min(len(ordered_rows), position + 10)
        for body_position in range(position + 1, scan_limit):
            candidate_row = ordered_rows[body_position]
            if _to_int(candidate_row.get("page")) != anchor_page:
                break
            candidate_text = str(candidate_row.get("text") or "").strip()
            if not candidate_text:
                continue
            if _row_is_section_transition_v2(candidate_text):
                if body_position - position <= 2:
                    continue
                break
            if _match_marker_only_numeric_anchor(candidate_text):
                continue
            candidate_anchor = _match_reference_anchor_at_line_start(
                candidate_text,
                include_rejected=True,
            )
            if candidate_anchor and candidate_anchor.get("accepted"):
                candidate_index = _to_int(candidate_anchor.get("index"))
                if candidate_index not in (None, anchor_index):
                    break
            if not _has_v2_bibliographic_body_signal(candidate_text):
                continue
            body_x0, body_y0, body_x1, body_y1 = _row_geometry_edges(candidate_row)
            if None in (body_x0, body_y0, body_x1, body_y1):
                continue
            horizontal_gap = float(body_x0) - float(anchor_x1)
            if horizontal_gap < 0.004:
                continue
            overlap = max(
                0.0,
                min(float(anchor_y1), float(body_y1))
                - max(float(anchor_y0), float(body_y0)),
            )
            marker_height = max(float(anchor_y1) - float(anchor_y0), 1e-4)
            body_height = max(float(body_y1) - float(body_y0), 1e-4)
            overlap_ratio = overlap / max(min(marker_height, body_height), 1e-4)
            delta_y = abs(float(body_y0) - float(anchor_y0))
            vertical_gap = abs(float(body_y0) - float(anchor_y1))
            right_band_alignment = bool(
                horizontal_gap >= 0.012
                and (overlap_ratio >= 0.2 or delta_y <= 0.035 or vertical_gap <= 0.03)
            )
            immediate_fallback = bool(
                body_position == position + 1
                and horizontal_gap >= 0.006
                and delta_y <= 0.09
            )
            if not right_band_alignment and not immediate_fallback:
                continue

            score = 0.24
            reasons: List[str] = []
            if right_band_alignment:
                score += 0.23
                reasons.append("same_page_right_band")
            else:
                score += 0.08
                reasons.append("next_row_fallback_alignment")
            if overlap_ratio >= 0.35:
                score += 0.13
                reasons.append("vertical_overlap_strong")
            elif overlap_ratio >= 0.2:
                score += 0.08
                reasons.append("vertical_overlap")
            elif delta_y <= 0.03:
                score += 0.07
                reasons.append("small_delta_y")
            if body_position == position + 1:
                score += 0.07
                reasons.append("immediate_next_row")
            if body_x0_reference is not None:
                offset_from_body_band = abs(float(body_x0) - float(body_x0_reference))
                if offset_from_body_band <= 0.09:
                    score += 0.11
                    reasons.append("aligned_with_body_band")
                elif offset_from_body_band <= 0.16:
                    score += 0.05
                    reasons.append("near_body_band")
                else:
                    score -= 0.07
                    reasons.append("off_body_band")
            if row.get("reading_lane_id") and row.get(
                "reading_lane_id"
            ) == candidate_row.get("reading_lane_id"):
                score += 0.05
                reasons.append("same_reading_lane")
            if len(candidate_text) >= 72:
                score += 0.03
                reasons.append("long_body_row")
            confidence = round(max(0.0, min(0.98, 0.38 + float(score))), 3)
            link_payload = {
                "anchor_position": position,
                "anchor_row_id": str(row.get("id") or ""),
                "anchor_page": anchor_page,
                "index": anchor_index,
                "body_start_position": body_position,
                "body_start_row_id": str(candidate_row.get("id") or ""),
                "body_start_page": _to_int(candidate_row.get("page")),
                "body_start_x0": float(body_x0),
                "marker_x1": float(anchor_x1),
                "horizontal_gap": round(horizontal_gap, 4),
                "vertical_overlap_ratio": round(overlap_ratio, 4),
                "delta_y": round(delta_y, 4),
                "score": round(float(score), 3),
                "confidence": confidence,
                "link_reason": ",".join(reasons),
                "reasons": reasons,
            }
            if best_link is None or float(link_payload["score"]) > float(
                best_link.get("score") or 0.0
            ):
                best_link = link_payload
        if best_link is None:
            link_failures.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "index": anchor_index,
                    "page": anchor_page,
                    "reason": "body_start_not_found_to_right",
                }
            )
            continue
        linked_rows.append(best_link)

    marker_gaps = [
        float(link.get("horizontal_gap"))
        for link in linked_rows
        if _to_float(link.get("horizontal_gap")) is not None
    ]
    body_x0_values = [
        float(link.get("body_start_x0"))
        for link in linked_rows
        if _to_float(link.get("body_start_x0")) is not None
    ]
    layout_confirmed = False
    layout_confirmation_reason = "insufficient_marker_links_for_layout"
    if len(linked_rows) >= 2:
        median_gap = _median(marker_gaps) if marker_gaps else 0.0
        body_band_spread = (
            float(max(body_x0_values) - min(body_x0_values))
            if len(body_x0_values) >= 2
            else 0.0
        )
        if median_gap >= 0.03 and body_band_spread <= 0.2:
            layout_confirmed = True
            layout_confirmation_reason = "repeated_marker_only_left_gutter_pattern"
        elif median_gap < 0.03:
            layout_confirmation_reason = "marker_body_gap_too_small"
        else:
            layout_confirmation_reason = "body_start_band_not_coherent"

    linked_by_position = {
        int(link.get("anchor_position")): link
        for link in linked_rows
        if _to_int(link.get("anchor_position")) is not None
    }
    return {
        "layout_confirmed": layout_confirmed,
        "layout_confirmation_reason": layout_confirmation_reason,
        "body_x0_reference": body_x0_reference,
        "marker_rows_total": marker_rows_total,
        "linked_rows_total": len(linked_rows),
        "linked_rows": linked_rows,
        "linked_by_position": linked_by_position,
        "link_failures": link_failures,
    }


def _has_v2_bibliographic_body_signal(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return False
    alpha_words = REFERENCE_WORD_RE.findall(value)
    return bool(
        _has_bibliographic_lead_signal(value)
        or _extract_doi(value)
        or REFERENCE_YEAR_RE.search(value)
        or len(alpha_words) >= 6
        or len(value) >= 72
    )


def _row_is_section_transition_v2(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    return bool(
        _is_reference_heading_text(value)
        or _is_reference_header_like(value)
        or re.match(
            r"^\s*(?:appendix|appendices|annex|supplement(?:ary)?|acknowledg(?:e)?ments?)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _reference_needs_continuation_v2(rows: Sequence[Dict[str, Any]]) -> bool:
    text = _clean_reference_text(rows)
    if not text:
        return True
    compact = text.strip()
    if len(compact) < 64:
        return True
    if compact.endswith(("-", ":", ",", ";", "/", "(")):
        return True
    if re.search(
        r"\b(?:and|for|from|of|the|through|with)\s*$",
        compact,
        flags=re.IGNORECASE,
    ):
        return True
    quality = _reference_text_quality_metrics(compact)
    return bool(
        quality.get("broken_url_like")
        or quality.get("trailing_after_doi")
        or quality.get("fragment_after_pages")
    )


def _detect_numeric_anchor_candidates_v2(
    ordered_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for position, row in enumerate(ordered_rows):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        next_row = (
            ordered_rows[position + 1] if position + 1 < len(ordered_rows) else None
        )
        next_text = str((next_row or {}).get("text") or "").strip()
        accepted_anchor = _match_reference_anchor_at_line_start(text)
        anchor_candidate = _match_reference_anchor_at_line_start(
            text,
            include_rejected=True,
        )
        marker_only = _match_marker_only_numeric_anchor(text)
        body_text = _strip_numeric_anchor_prefix(text)
        weak_split_body = bool(
            next_row
            and row.get("page") == next_row.get("page")
            and _has_v2_bibliographic_body_signal(next_text)
        )
        if accepted_anchor and accepted_anchor.get("accepted"):
            confidence = (
                0.98 if accepted_anchor.get("anchor_style") == "bracketed" else 0.94
            )
            if not _has_v2_bibliographic_body_signal(body_text) and weak_split_body:
                confidence = round(confidence - 0.08, 3)
            candidates.append(
                {
                    "index": int(accepted_anchor.get("index") or 0),
                    "anchor_style": accepted_anchor.get("anchor_style"),
                    "confidence": confidence,
                    "strength": "strong",
                    "reason": (
                        "accepted_anchor_with_split_body"
                        if weak_split_body
                        and not _has_v2_bibliographic_body_signal(body_text)
                        else "accepted_anchor"
                    ),
                    "page": row.get("page"),
                    "position": int(row.get("flow_position", position)),
                    "row_id": str(row.get("id") or ""),
                    "row": row,
                    "body_inline": body_text,
                    "body_in_next_row": bool(
                        weak_split_body
                        and not _has_v2_bibliographic_body_signal(body_text)
                    ),
                }
            )
            continue
        if marker_only and weak_split_body:
            candidates.append(
                {
                    "index": int(marker_only.get("index") or 0),
                    "anchor_style": marker_only.get("anchor_style"),
                    "confidence": 0.79,
                    "strength": "weak",
                    "reason": "marker_only_anchor_followed_by_body_row",
                    "page": row.get("page"),
                    "position": int(row.get("flow_position", position)),
                    "row_id": str(row.get("id") or ""),
                    "row": row,
                    "body_inline": "",
                    "body_in_next_row": True,
                }
            )
            continue
        if (
            anchor_candidate
            and not anchor_candidate.get("accepted")
            and anchor_candidate.get("anchor_rejected_reason")
            == "weak_bibliographic_signal"
            and weak_split_body
        ):
            candidates.append(
                {
                    "index": int(anchor_candidate.get("index") or 0),
                    "anchor_style": anchor_candidate.get("anchor_style"),
                    "confidence": 0.74,
                    "strength": "weak",
                    "reason": "recovered_split_anchor_from_following_row",
                    "page": row.get("page"),
                    "position": int(row.get("flow_position", position)),
                    "row_id": str(row.get("id") or ""),
                    "row": row,
                    "body_inline": body_text,
                    "body_in_next_row": True,
                }
            )
    candidates.sort(
        key=lambda item: (
            int(item.get("position") or 0),
            -float(item.get("confidence") or 0.0),
        )
    )
    for idx, candidate in enumerate(candidates):
        previous_index = _to_int(candidates[idx - 1].get("index")) if idx > 0 else None
        next_index = (
            _to_int(candidates[idx + 1].get("index"))
            if idx + 1 < len(candidates)
            else None
        )
        candidate["sequence_supported"] = bool(
            previous_index == int(candidate.get("index") or 0) - 1
            or next_index == int(candidate.get("index") or 0) + 1
        )
    return candidates


def _group_rows_into_reading_bands_v2(
    page_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    bands: List[Dict[str, Any]] = []
    for row in sorted(
        page_rows,
        key=lambda item: (
            float(item.get("x0") or 0.0),
            float(item.get("y0") or 0.0),
            float(item.get("x1") or 0.0),
        ),
    ):
        row_box = _normalize_box(row.get("box"))
        if row_box is None:
            continue
        row_x0 = float(row.get("x0") or row_box[0])
        row_x1 = float(row.get("x1") or (row_box[0] + row_box[2]))
        best_band: Optional[Dict[str, Any]] = None
        best_distance: Optional[float] = None
        for band in bands:
            band_x0 = float(band.get("x0_median") or 0.0)
            band_x1 = float(band.get("x1_median") or 0.0)
            overlap = max(0.0, min(row_x1, band_x1) - max(row_x0, band_x0))
            union = max(row_x1, band_x1) - min(row_x0, band_x0)
            overlap_ratio = overlap / union if union > 0 else 0.0
            distance = abs(row_x0 - band_x0)
            if overlap_ratio < 0.14 and distance > 0.12:
                continue
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_band = band
        if best_band is None:
            best_band = {
                "rows": [],
                "x0_values": [],
                "x1_values": [],
            }
            bands.append(best_band)
        best_band["rows"].append(row)
        best_band["x0_values"].append(row_x0)
        best_band["x1_values"].append(row_x1)
        best_band["x0_median"] = _median(best_band["x0_values"])
        best_band["x1_median"] = _median(best_band["x1_values"])

    out: List[Dict[str, Any]] = []
    for band_index, band in enumerate(
        sorted(
            bands,
            key=lambda item: (
                float(item.get("x0_median") or 0.0),
                min(float(row.get("y0") or 0.0) for row in item.get("rows") or [{}]),
            ),
        )
    ):
        band_rows = sorted(band.get("rows") or [], key=_line_sort_key)
        band_box = _union_boxes(
            [row.get("box") for row in band_rows if _normalize_box(row.get("box"))]
        )
        if not band_rows or band_box is None:
            continue
        out.append(
            {
                "band_index": band_index,
                "rows": band_rows,
                "box": band_box,
                "x0_median": round(float(band.get("x0_median") or band_box[0]), 4),
                "x1_median": round(
                    float(band.get("x1_median") or (band_box[0] + band_box[2])),
                    4,
                ),
            }
        )
    return out


def _build_numeric_bibliography_territory_v2(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rows_with_columns = _assign_column_ids(rows)
    page_splits = _collect_page_split_map(rows_with_columns)
    heading_candidates = _detect_reference_heading_candidates(
        rows_with_columns,
        sections,
        page_splits,
    )
    pre_reading_flow = build_bibliography_reading_flow(rows_with_columns)
    pre_anchor_candidates = _detect_numeric_anchor_candidates_v2(pre_reading_flow)
    max_page = max(
        (
            int(row.get("page"))
            for row in rows_with_columns
            if isinstance(row.get("page"), int)
        ),
        default=-1,
    )
    tail_page_span = max(3, int((max_page + 1) * 0.35))
    tail_start_page = max(0, max_page - tail_page_span + 1)
    tail_heading_candidates = [
        candidate
        for candidate in heading_candidates
        if int(candidate.get("page") or -1) >= tail_start_page
    ]
    tail_anchor_candidates = [
        candidate
        for candidate in pre_anchor_candidates
        if int(candidate.get("page") or -1) >= tail_start_page
    ]
    tail_bibliography_pages = sorted(
        {
            int(item.get("page"))
            for item in bibliography_items
            if isinstance(item.get("page"), int)
            and int(item.get("page")) >= tail_start_page
        }
    )
    start_page_candidates = [candidate["page"] for candidate in tail_heading_candidates]
    start_page_candidates.extend(
        candidate.get("page") for candidate in tail_anchor_candidates[:6]
    )
    if not start_page_candidates and tail_bibliography_pages:
        start_page_candidates.append(tail_bibliography_pages[0])
    if not start_page_candidates:
        start_page_candidates.extend(
            candidate["page"] for candidate in heading_candidates
        )
        start_page_candidates.extend(
            candidate.get("page") for candidate in pre_anchor_candidates[:6]
        )
    valid_start_pages = [
        int(page)
        for page in start_page_candidates
        if isinstance(page, int) and page >= 0
    ]
    start_page = min(valid_start_pages) if valid_start_pages else None
    heading_pool = tail_heading_candidates or heading_candidates
    selected_heading = None
    if heading_pool:
        selected_heading = min(
            heading_pool,
            key=lambda item: (
                abs(int(item["page"]) - int(start_page or item["page"])),
                item["box"][1],
                item["box"][0],
            ),
        )
        if start_page is None:
            start_page = selected_heading["page"]

    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    anchor_row_ids = {
        str(candidate.get("row_id") or "")
        for candidate in pre_anchor_candidates
        if str(candidate.get("row_id") or "").strip()
    }
    heading_bottom_by_page: Dict[int, float] = {}
    if isinstance(selected_heading, dict):
        heading_box = _normalize_box(selected_heading.get("box"))
        heading_page = _to_int(selected_heading.get("page"))
        if heading_box is not None and isinstance(heading_page, int):
            heading_bottom_by_page[heading_page] = round(
                float(heading_box[1]) + float(heading_box[3]),
                4,
            )

    territory_rows: List[Dict[str, Any]] = []
    territory_zones: List[Dict[str, Any]] = []
    reading_units: List[Dict[str, Any]] = []
    grouped_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows_with_columns:
        page = _to_int(row.get("page"))
        text = str(row.get("text") or "").strip()
        box = _normalize_box(row.get("box"))
        if not isinstance(page, int) or start_page is None or page < start_page:
            continue
        if not text or box is None:
            continue
        if (
            page in heading_bottom_by_page
            and float(box[1]) + float(box[3]) < float(heading_bottom_by_page[page])
            and str(row.get("id") or "") not in anchor_row_ids
        ):
            continue
        if (
            _is_header_footer_row(row, artifact_info)
            and str(row.get("id") or "") not in anchor_row_ids
        ):
            continue
        grouped_by_page[page].append(row)

    for page in sorted(grouped_by_page.keys()):
        page_rows = grouped_by_page.get(page) or []
        page_bands = _group_rows_into_reading_bands_v2(page_rows)
        accepted_bands: List[Dict[str, Any]] = []
        for band in page_bands:
            band_rows = band.get("rows") or []
            band_box = _normalize_box(band.get("box"))
            if not band_rows or band_box is None:
                continue
            band_anchor_candidates = [
                candidate
                for candidate in pre_anchor_candidates
                if str(candidate.get("row_id") or "")
                in {str(row.get("id") or "") for row in band_rows}
            ]
            band_overlap = max(
                (
                    _overlap_ratio(item.get("box"), band_box)
                    for item in bibliography_items
                    if _to_int(item.get("page")) == page
                    and _normalize_box(item.get("box")) is not None
                ),
                default=0.0,
            )
            bibliography_signal_rows = sum(
                1
                for row in band_rows
                if _has_v2_bibliographic_body_signal(str(row.get("text") or ""))
                or str(row.get("id") or "") in anchor_row_ids
            )
            bibliography_density = bibliography_signal_rows / max(len(band_rows), 1)
            score = 0.0
            if band_anchor_candidates:
                score += 0.38
            if band_overlap >= 0.18:
                score += min(band_overlap, 0.24)
            score += min(bibliography_density * 0.32, 0.32)
            if page in heading_bottom_by_page:
                score += 0.08
            if len(band_rows) >= 3:
                score += 0.08
            accepted = bool(
                score >= 0.28
                or band_overlap >= 0.24
                or (page == start_page and band_anchor_candidates)
            )
            reading_unit_id = f"v2-unit-{page}-{int(band.get('band_index') or 0)}"
            accepted_bands.append(
                {
                    "id": reading_unit_id,
                    "page": page,
                    "band_index": int(band.get("band_index") or 0),
                    "box": band_box,
                    "rows": band_rows,
                    "anchor_indices": sorted(
                        {
                            int(candidate.get("index"))
                            for candidate in band_anchor_candidates
                            if _to_int(candidate.get("index")) not in (None, 0)
                        }
                    ),
                    "anchor_total": len(band_anchor_candidates),
                    "bibliography_density": round(bibliography_density, 3),
                    "layer_overlap": round(band_overlap, 3),
                    "confidence": round(min(score, 0.98), 3),
                    "accepted": accepted,
                }
            )
        accepted_bands = [band for band in accepted_bands if band.get("accepted")]
        accepted_bands.sort(
            key=lambda band: (
                (
                    0
                    if (page in heading_bottom_by_page and band.get("anchor_total"))
                    else 1
                ),
                min(band.get("anchor_indices") or [10**9]),
                float((_normalize_box(band.get("box")) or [0.0])[0]),
            )
        )
        for order_index, band in enumerate(accepted_bands):
            band_box = _normalize_box(band.get("box"))
            if band_box is None:
                continue
            territory_zones.append(
                {
                    "id": band["id"],
                    "page": page,
                    "box": band_box,
                    "confidence": band.get("confidence"),
                    "anchor_indices": band.get("anchor_indices") or [],
                    "anchor_total": band.get("anchor_total"),
                    "bibliography_density": band.get("bibliography_density"),
                    "layer_overlap": band.get("layer_overlap"),
                    "source_signals": [
                        part
                        for part, enabled in (
                            ("anchors", bool(band.get("anchor_total"))),
                            (
                                "bibliography_layer",
                                float(band.get("layer_overlap") or 0.0) >= 0.18,
                            ),
                            ("heading", page in heading_bottom_by_page),
                            (
                                "bibliographic_density",
                                float(band.get("bibliography_density") or 0.0) >= 0.45,
                            ),
                        )
                        if enabled
                    ],
                    "row_ids": [
                        str(row.get("id") or "") for row in band.get("rows") or []
                    ],
                }
            )
            reading_units.append(
                {
                    "id": band["id"],
                    "page": page,
                    "order_on_page": order_index,
                    "band_index": band.get("band_index"),
                    "box": band_box,
                    "anchor_indices": band.get("anchor_indices") or [],
                    "bibliography_density": band.get("bibliography_density"),
                    "confidence": band.get("confidence"),
                    "row_ids": [
                        str(row.get("id") or "") for row in band.get("rows") or []
                    ],
                }
            )
            for row in band.get("rows") or []:
                next_row = dict(row)
                next_row["reading_unit_id"] = band["id"]
                next_row["reading_unit_order_on_page"] = order_index
                next_row["column_id_v2"] = f"band_{page}_{order_index}"
                territory_rows.append(next_row)

    territory_rows.sort(
        key=lambda row: (
            int(row.get("page") or 0),
            int(row.get("reading_unit_order_on_page") or 0),
            float(row.get("y0") or 0.0),
            float(row.get("x0") or 0.0),
        )
    )
    ordered_rows: List[Dict[str, Any]] = []
    for flow_position, row in enumerate(territory_rows):
        next_row = dict(row)
        next_row["flow_position"] = flow_position
        ordered_rows.append(next_row)

    bibliography_anchor = None
    if territory_zones:
        first_zone = min(
            territory_zones,
            key=lambda item: (
                int(item.get("page") or 0),
                float((_normalize_box(item.get("box")) or [0.0, 0.0])[1]),
                float((_normalize_box(item.get("box")) or [0.0])[0]),
            ),
        )
        first_box = _normalize_box(first_zone.get("box"))
        if first_box is not None:
            bibliography_anchor = (
                int(first_zone.get("page") or 0),
                float(first_box[1]),
            )

    return {
        "rows_with_columns": rows_with_columns,
        "page_splits": page_splits,
        "heading_candidates": heading_candidates,
        "selected_heading": selected_heading,
        "start_page": start_page,
        "territory_zones": territory_zones,
        "reading_units": reading_units,
        "ordered_rows": ordered_rows,
        "bibliography_anchor": bibliography_anchor,
        "anchor_candidates_scan": pre_anchor_candidates,
    }


def _reconcile_numeric_anchor_candidates_v2(
    *,
    anchor_candidates: Sequence[Dict[str, Any]],
    expected_indices: Sequence[int],
) -> Dict[str, Any]:
    candidates_by_index: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in anchor_candidates:
        index = _to_int(candidate.get("index"))
        if index is None or index <= 0:
            continue
        candidates_by_index[index].append(dict(candidate))
    selected_anchors: List[Dict[str, Any]] = []
    duplicate_indices: List[int] = []
    reconciliation_actions: List[Dict[str, Any]] = []
    for index in sorted(candidates_by_index.keys()):
        ranked_candidates = sorted(
            candidates_by_index[index],
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                0 if str(item.get("strength") or "") == "strong" else 1,
                int(item.get("position") or 0),
            ),
        )
        selected = dict(ranked_candidates[0])
        selected["resolution"] = "selected"
        selected_anchors.append(selected)
        if len(ranked_candidates) > 1:
            duplicate_indices.append(index)
            for duplicate in ranked_candidates[1:]:
                reconciliation_actions.append(
                    {
                        "action": "drop_duplicate_anchor",
                        "index": index,
                        "row_id": duplicate.get("row_id"),
                        "confidence": duplicate.get("confidence"),
                        "reason": "lower_ranked_duplicate_anchor_candidate",
                    }
                )
    selected_anchors.sort(
        key=lambda item: (
            int(item.get("index") or 0),
            int(item.get("position") or 0),
        )
    )
    selected_index_set = {
        int(anchor.get("index"))
        for anchor in selected_anchors
        if _to_int(anchor.get("index")) not in (None, 0)
    }
    normalized_expected = sorted(
        {
            int(index)
            for index in expected_indices
            if isinstance(index, int) and int(index) > 0
        }
    )
    missing_indices = [
        index for index in normalized_expected if index not in selected_index_set
    ]
    inferred_anchors = [
        {
            "index": index,
            "confidence": 0.0,
            "strength": "inferred_missing",
            "reason": "missing_from_detected_anchor_sequence",
        }
        for index in missing_indices
    ]
    reconciliation_actions.extend(
        {
            "action": "mark_missing_anchor",
            "index": index,
            "reason": "expected_index_not_detected_in_v2_anchor_sequence",
        }
        for index in missing_indices
    )
    anchor_sequence = [
        {
            "index": int(anchor.get("index") or 0),
            "page": anchor.get("page"),
            "position": anchor.get("position"),
            "row_id": anchor.get("row_id"),
            "anchor_style": anchor.get("anchor_style"),
            "strength": anchor.get("strength"),
            "confidence": round(float(anchor.get("confidence") or 0.0), 3),
            "body_in_next_row": bool(anchor.get("body_in_next_row")),
            "sequence_supported": bool(anchor.get("sequence_supported")),
            "reason": anchor.get("reason"),
        }
        for anchor in selected_anchors
    ]
    return {
        "selected_anchors": selected_anchors,
        "anchor_sequence": anchor_sequence,
        "missing_indices": missing_indices,
        "duplicate_indices": sorted(set(duplicate_indices)),
        "inferred_anchors": inferred_anchors,
        "reconciliation_actions": reconciliation_actions,
    }


def _compute_row_continuity_score_v2(rows: Sequence[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    if len(rows) == 1:
        return 0.78
    penalties = 0.0
    previous = rows[0]
    for row in rows[1:]:
        previous_page = _to_int(previous.get("page"))
        current_page = _to_int(row.get("page"))
        if previous_page is None or current_page is None:
            penalties += 0.16
        elif current_page < previous_page:
            penalties += 0.42
        elif current_page == previous_page:
            previous_y1 = _to_float(previous.get("y1"))
            current_y0 = _to_float(row.get("y0"))
            if previous_y1 is not None and current_y0 is not None:
                gap = float(current_y0) - float(previous_y1)
                if gap > 0.1:
                    penalties += min(gap * 1.8, 0.18)
        elif current_page - previous_page == 1:
            penalties += 0.06
            current_y0 = _to_float(row.get("y0"))
            if current_y0 is not None and float(current_y0) > 0.52:
                penalties += 0.08
        else:
            penalties += 0.26
        if previous.get("reading_unit_id") != row.get("reading_unit_id"):
            penalties += 0.08
        previous = row
    return round(max(0.0, min(1.0, 1.0 - penalties)), 3)


def _score_same_reference_row_v2(
    *,
    row: Dict[str, Any],
    previous_row: Dict[str, Any],
    current_rows: Sequence[Dict[str, Any]],
) -> float:
    text = str(row.get("text") or "").strip()
    if not text:
        return -0.6
    if _row_is_section_transition_v2(text):
        return -0.5
    score = 0.0
    if _has_v2_bibliographic_body_signal(text):
        score += 0.18
    else:
        score -= 0.04

    previous_page = _to_int(previous_row.get("page"))
    current_page = _to_int(row.get("page"))
    previous_y1 = _to_float(previous_row.get("y1"))
    current_y0 = _to_float(row.get("y0"))
    if previous_page is not None and current_page is not None:
        if current_page == previous_page:
            if previous_y1 is not None and current_y0 is not None:
                gap = float(current_y0) - float(previous_y1)
                if gap <= 0.045:
                    score += 0.24
                elif gap <= 0.11:
                    score += 0.14
                elif gap <= 0.18 and _reference_needs_continuation_v2(current_rows):
                    score += 0.05
                else:
                    score -= 0.12
            row_x0 = _to_float(row.get("x0"))
            previous_x0 = _to_float(previous_row.get("x0"))
            if row_x0 is not None and previous_x0 is not None:
                if abs(float(row_x0) - float(previous_x0)) <= 0.12:
                    score += 0.08
                elif row.get("reading_unit_id") != previous_row.get("reading_unit_id"):
                    score += (
                        0.04
                        if _reference_needs_continuation_v2(current_rows)
                        else -0.04
                    )
        elif current_page - previous_page == 1:
            if current_y0 is not None and float(current_y0) <= 0.22:
                score += 0.22
            elif current_y0 is not None and float(current_y0) <= 0.4:
                score += 0.12
            else:
                score -= 0.06
            if _reference_needs_continuation_v2(current_rows):
                score += 0.1
        else:
            score -= 0.4
    if row.get("reading_unit_id") == previous_row.get("reading_unit_id"):
        score += 0.04
    return round(score, 3)


def _score_stop_reference_row_v2(
    *,
    row: Dict[str, Any],
    previous_row: Dict[str, Any],
    current_rows: Sequence[Dict[str, Any]],
    competing_anchor: Optional[Dict[str, Any]],
) -> Tuple[float, str]:
    text = str(row.get("text") or "").strip()
    if competing_anchor and int(competing_anchor.get("index") or 0) > 0:
        competing_index = int(competing_anchor.get("index") or 0)
        return (
            0.98 if str(competing_anchor.get("strength") or "") == "strong" else 0.86,
            f"competing_anchor:{competing_index}",
        )
    if _row_is_section_transition_v2(text):
        return 0.84, "section_transition"
    if _is_header_footer_row(row, {"repeated_text_keys": set()}):
        return 0.62, "header_footer_noise"
    previous_page = _to_int(previous_row.get("page"))
    current_page = _to_int(row.get("page"))
    previous_y1 = _to_float(previous_row.get("y1"))
    current_y0 = _to_float(row.get("y0"))
    if (
        previous_page is not None
        and current_page is not None
        and current_page == previous_page
        and previous_y1 is not None
        and current_y0 is not None
    ):
        gap = float(current_y0) - float(previous_y1)
        if gap > 0.16 and not _reference_needs_continuation_v2(current_rows):
            return min(0.74, round(0.48 + gap, 3)), "vertical_gap"
    if (
        previous_page is not None
        and current_page is not None
        and current_page - previous_page == 1
        and current_y0 is not None
        and float(current_y0) > 0.58
        and not _reference_needs_continuation_v2(current_rows)
    ):
        return 0.72, "late_page_boundary"
    return 0.18, "same_reference_more_likely"


def _build_reference_rows_between_anchors_v2(
    *,
    ordered_rows: Sequence[Dict[str, Any]],
    current_anchor: Dict[str, Any],
    next_anchor: Optional[Dict[str, Any]],
    anchor_candidates_by_position: Dict[int, Dict[str, Any]],
    artifact_info: Dict[str, Any],
) -> Dict[str, Any]:
    start = _to_int(current_anchor.get("position"))
    if start is None:
        start = -1
    if start < 0 or start >= len(ordered_rows):
        return {
            "rows": [],
            "row_decisions": [],
            "rows_discarded": [],
            "cut_reasons": ["invalid_anchor_position"],
            "closure_reason": "invalid_anchor_position",
            "continuation_between_pages": False,
            "issues": ["invalid_anchor_position"],
            "body_start": None,
            "body_end": None,
        }
    selected_rows: List[Dict[str, Any]] = []
    row_decisions: List[Dict[str, Any]] = []
    rows_discarded: List[Dict[str, Any]] = []
    cut_reasons: List[str] = []
    continuation_between_pages = False
    closure_reason = "reading_flow_exhausted"
    expected_index = int(current_anchor.get("index") or 0)
    next_anchor_position = len(ordered_rows)
    if isinstance(next_anchor, dict):
        next_position = _to_int(next_anchor.get("position"))
        if next_position is not None:
            next_anchor_position = next_position
    for position in range(start, len(ordered_rows)):
        row = ordered_rows[position]
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        is_anchor_row = position == start
        competing_anchor = None
        if not is_anchor_row:
            candidate = anchor_candidates_by_position.get(position)
            if candidate and int(candidate.get("index") or 0) != expected_index:
                competing_anchor = candidate
        if is_anchor_row:
            selected_rows.append(row)
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": text,
                    "included": True,
                    "reason": "anchor_row",
                    "same_reference_score": 1.0,
                    "stop_score": 0.0,
                }
            )
            continue
        if position >= next_anchor_position and competing_anchor is not None:
            closure_reason = "next_resolved_anchor"
            cut_reasons.append("next_resolved_anchor")
            rows_discarded.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": _short_debug_text(text),
                    "reason": "next_resolved_anchor",
                }
            )
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": text,
                    "included": False,
                    "reason": "next_resolved_anchor",
                }
            )
            break
        previous_row = selected_rows[-1]
        same_reference_score = _score_same_reference_row_v2(
            row=row,
            previous_row=previous_row,
            current_rows=selected_rows,
        )
        stop_score, stop_reason = _score_stop_reference_row_v2(
            row=row,
            previous_row=previous_row,
            current_rows=selected_rows,
            competing_anchor=competing_anchor,
        )
        if (
            _is_header_footer_row(row, artifact_info)
            and stop_reason == "same_reference_more_likely"
        ):
            stop_score = max(stop_score, 0.62)
            stop_reason = "header_footer_noise"
        if stop_score > same_reference_score + 0.12:
            closure_reason = stop_reason
            cut_reasons.append(stop_reason)
            rows_discarded.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": _short_debug_text(text),
                    "reason": stop_reason,
                }
            )
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": text,
                    "included": False,
                    "reason": stop_reason,
                    "same_reference_score": same_reference_score,
                    "stop_score": stop_score,
                }
            )
            break
        if _to_int(previous_row.get("page")) != _to_int(row.get("page")):
            continuation_between_pages = True
        selected_rows.append(row)
        row_decisions.append(
            {
                "row_id": str(row.get("id") or ""),
                "page": row.get("page"),
                "text": text,
                "included": True,
                "reason": (
                    "page_continuation"
                    if _to_int(previous_row.get("page")) != _to_int(row.get("page"))
                    else "same_reference_growth"
                ),
                "same_reference_score": same_reference_score,
                "stop_score": stop_score,
            }
        )
        if len(selected_rows) >= 28:
            closure_reason = "row_limit"
            cut_reasons.append("row_limit")
            break

    issues: List[str] = []
    if continuation_between_pages:
        issues.append("page_continuation")
    page_count = len(
        {
            _to_int(row.get("page"))
            for row in selected_rows
            if _to_int(row.get("page")) is not None
        }
    )
    if page_count > 1:
        issues.append("multi_page_reference")
    if len(selected_rows) < 2:
        issues.append("suspiciously_short_reference")
    if len(selected_rows) >= 18:
        issues.append("suspiciously_long_reference")
    body_start = (
        str((selected_rows[0] or {}).get("id") or "") if selected_rows else None
    )
    body_end = str((selected_rows[-1] or {}).get("id") or "") if selected_rows else None
    return {
        "rows": selected_rows,
        "row_decisions": row_decisions,
        "rows_discarded": rows_discarded,
        "cut_reasons": cut_reasons,
        "closure_reason": closure_reason,
        "continuation_between_pages": continuation_between_pages,
        "issues": issues,
        "body_start": body_start,
        "body_end": body_end,
    }


def _build_reference_decision_v2(
    *,
    expected_index: int,
    rows: Sequence[Dict[str, Any]],
    reference_text: str,
    block_diagnostics: Dict[str, Any],
    token_reconstruction: Dict[str, Any],
    crossref_match: Dict[str, Any],
    territory_zones: Sequence[Dict[str, Any]],
    validation: Dict[str, Any],
) -> Dict[str, Any]:
    first_row = rows[0] if rows else {}
    first_text = str(first_row.get("text") or "")
    leading_anchor = _match_reference_anchor_at_line_start(
        first_text, include_rejected=True
    )
    starts_with_anchor = bool(
        leading_anchor
        and int(leading_anchor.get("index") or 0) == int(expected_index or 0)
    )
    row_ids = {
        str(row.get("id") or "") for row in rows if str(row.get("id") or "").strip()
    }
    territory_row_ids = {
        str(row_id)
        for zone in territory_zones
        for row_id in (zone.get("row_ids") or [])
        if str(row_id).strip()
    }
    inside_bibliography_zone = bool(row_ids and row_ids.issubset(territory_row_ids))
    inside_expected_column = bool(rows)
    has_nested_anchor = bool(
        any(
            candidate
            for candidate in detect_reference_anchors_from_rows(rows[1:])
            if int(candidate.get("index") or 0) != int(expected_index or 0)
        )
    )
    header_noise_score = _score_header_noise(reference_text)
    row_continuity_score = _compute_row_continuity_score_v2(rows)
    token_cleanup_confidence = float(
        token_reconstruction.get("token_cleanup_confidence") or 0.0
    )
    selected_candidate_source = (
        str(token_reconstruction.get("selected_candidate_source") or "rows_raw").strip()
        or "rows_raw"
    )
    selected_candidate_quality = 0.0
    for candidate_score in token_reconstruction.get("candidate_scores") or []:
        if not isinstance(candidate_score, dict):
            continue
        if (
            str(candidate_score.get("source") or "").strip()
            == selected_candidate_source
        ):
            selected_candidate_quality = float(
                candidate_score.get("quality_score") or 0.0
            )
            break
    cleanup_applied = bool(
        token_reconstruction.get("cleanups_applied")
        or selected_candidate_source in {"rows_tokens", "rows_hybrid"}
    )
    crossref_match_score = float(crossref_match.get("score") or 0.0)
    doi_match_score = float(crossref_match.get("doi_match_score") or 0.0)
    validation_reason = str(validation.get("reason") or "").strip() or None
    validation_hard_failure = validation_reason in {
        "contains_header_footer_noise",
        "empty_local_text",
        "mixed_rows_multiple_references",
        "short_or_empty_reference",
    }
    continuation_between_pages = bool(
        block_diagnostics.get("continuation_between_pages")
    )
    final_score = 0.0
    final_score += 0.2 if inside_bibliography_zone else -0.3
    final_score += 0.18 if starts_with_anchor else -0.22
    final_score += 0.18 * row_continuity_score
    final_score += 0.12 * crossref_match_score
    final_score += 0.08 * doi_match_score
    final_score += 0.08 * token_cleanup_confidence
    final_score += 0.05 * selected_candidate_quality
    final_score += 0.06 if continuation_between_pages else 0.0
    final_score -= 0.28 * header_noise_score
    if has_nested_anchor:
        final_score -= 0.34
    if validation_hard_failure:
        final_score -= 0.12
    final_score = round(max(0.0, min(1.0, final_score)), 3)

    if header_noise_score >= 0.95:
        classification = "rejected_noise"
        accepted = False
        reason = "header_noise_detected"
    elif has_nested_anchor:
        classification = "fallback_needed"
        accepted = False
        reason = "mixed_rows_multiple_references"
    elif validation_hard_failure:
        classification = "fallback_needed"
        accepted = False
        reason = validation_reason or "validation_failed"
    elif final_score >= 0.66:
        classification = (
            "accepted_with_cleanup" if cleanup_applied else "accepted_structured"
        )
        accepted = True
        reason = (
            "continuous_growth_across_reading_territory"
            if continuation_between_pages
            else "rows_structure_consistent_v2"
        )
    elif final_score >= 0.5:
        classification = "fallback_needed"
        accepted = False
        reason = "low_structural_score_v2"
    else:
        classification = "rejected_noise"
        accepted = False
        reason = "insufficient_reference_evidence_v2"
    return {
        "inside_bibliography_zone": inside_bibliography_zone,
        "inside_expected_column": inside_expected_column,
        "starts_with_anchor": starts_with_anchor,
        "expected_anchor_index": expected_index,
        "has_nested_anchor": has_nested_anchor,
        "header_noise_score": round(header_noise_score, 3),
        "crossref_match_score": round(crossref_match_score, 3),
        "doi_match_score": round(doi_match_score, 3),
        "row_continuity_score": round(row_continuity_score, 3),
        "token_cleanup_confidence": round(token_cleanup_confidence, 3),
        "selected_candidate_quality": round(selected_candidate_quality, 3),
        "cleanup_applied": cleanup_applied,
        "selected_candidate_source": selected_candidate_source,
        "final_score": final_score,
        "accepted": accepted,
        "classification": classification,
        "reason": reason,
        "continuation_between_pages": continuation_between_pages,
    }


def _build_numeric_pipeline_metrics(
    *,
    expected_indices: Sequence[int],
    reference_entries: Sequence[Dict[str, Any]],
    detected_anchor_indices: Sequence[int],
    duplicate_indices: Sequence[int],
) -> Dict[str, Any]:
    expected_total = len(expected_indices)
    serialized_indices = sorted(
        {
            int(entry.get("index"))
            for entry in reference_entries
            if _to_int(entry.get("index")) not in (None, 0)
            and str(entry.get("structure_source") or "").strip()
            != "raw_reference_fallback"
        }
    )
    missing_indices = [
        int(index)
        for index in expected_indices
        if int(index) not in set(serialized_indices)
    ]
    references_total = len(reference_entries)
    source_counter = Counter(
        str(entry.get("structure_source") or "").strip() for entry in reference_entries
    )
    accepted_total = sum(
        1
        for entry in reference_entries
        if bool((entry.get("final_decision") or {}).get("accepted"))
    )
    max_reference_index_detected = max(
        list(detected_anchor_indices)
        + [int(index) for index in serialized_indices]
        + [0]
    )
    coverage_ratio = (
        round(len(serialized_indices) / float(expected_total), 3)
        if expected_total > 0
        else 0.0
    )
    return {
        "references_total": references_total,
        "max_reference_index_detected": max_reference_index_detected,
        "coverage_ratio": coverage_ratio,
        "pct_structure_source_rows_raw": (
            round(
                (source_counter.get("rows_raw", 0) / float(references_total)) * 100.0,
                2,
            )
            if references_total
            else 0.0
        ),
        "pct_structure_source_raw_reference_fallback": (
            round(
                (
                    source_counter.get("raw_reference_fallback", 0)
                    / float(references_total)
                )
                * 100.0,
                2,
            )
            if references_total
            else 0.0
        ),
        "pct_accepted": (
            round((accepted_total / float(references_total)) * 100.0, 2)
            if references_total
            else 0.0
        ),
        "missing_indices": missing_indices,
        "duplicate_indices": sorted(
            {int(index) for index in duplicate_indices if int(index) > 0}
        ),
        "expected_indices": [int(index) for index in expected_indices],
        "serialized_indices": serialized_indices,
        "detected_anchor_indices": sorted(
            {int(index) for index in detected_anchor_indices if int(index) > 0}
        ),
    }


def _reference_has_tail_noise_v2(reference: Dict[str, Any]) -> bool:
    normalized_text = _normalize_text(str(reference.get("text") or ""))
    if not normalized_text:
        return False
    return any(
        marker in normalized_text for marker in REFERENCE_DIAGNOSTIC_TAIL_NOISE_MARKERS
    )


def _build_numeric_reference_comparison_v2(
    *,
    current_entries: Sequence[Dict[str, Any]],
    experimental_entries: Sequence[Dict[str, Any]],
    current_metrics: Dict[str, Any],
    experimental_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    current_by_index = {
        int(entry.get("index")): entry
        for entry in current_entries
        if _to_int(entry.get("index")) not in (None, 0)
    }
    experimental_by_index = {
        int(entry.get("index")): entry
        for entry in experimental_entries
        if _to_int(entry.get("index")) not in (None, 0)
    }
    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []
    all_indices = sorted(
        set(current_by_index.keys()) | set(experimental_by_index.keys())
    )
    for index in all_indices:
        current_entry = current_by_index.get(index) or {}
        experimental_entry = experimental_by_index.get(index) or {}
        current_decision = (
            current_entry.get("final_decision")
            if isinstance(current_entry.get("final_decision"), dict)
            else {}
        )
        experimental_decision = (
            experimental_entry.get("final_decision")
            if isinstance(experimental_entry.get("final_decision"), dict)
            else {}
        )
        current_pages = sorted(
            {
                int(row.get("page"))
                for row in (current_entry.get("rows") or [])
                if _to_int(row.get("page")) not in (None, -1)
            }
        )
        experimental_pages = sorted(
            {
                int(row.get("page"))
                for row in (experimental_entry.get("rows") or [])
                if _to_int(row.get("page")) not in (None, -1)
            }
        )
        current_fallback = (
            str(current_entry.get("structure_source") or "").strip()
            == "raw_reference_fallback"
        )
        experimental_fallback = (
            str(experimental_entry.get("structure_source") or "").strip()
            == "raw_reference_fallback"
        )
        current_tail_noise = _reference_has_tail_noise_v2(current_entry)
        experimental_tail_noise = _reference_has_tail_noise_v2(experimental_entry)
        current_mixed = bool(
            (current_entry.get("reference_validation") or {}).get("has_nested_anchor")
        )
        experimental_mixed = bool(
            (experimental_entry.get("reference_validation") or {}).get(
                "has_nested_anchor"
            )
        )
        if bool(current_decision.get("accepted")) and not bool(
            experimental_decision.get("accepted")
        ):
            regressions.append(
                {
                    "index": index,
                    "type": "accepted_reference_lost",
                    "current_reason": current_decision.get("reason"),
                    "experimental_reason": experimental_decision.get("reason"),
                }
            )
        if not current_fallback and experimental_fallback:
            regressions.append(
                {
                    "index": index,
                    "type": "new_raw_fallback",
                    "current_source": current_entry.get("structure_source"),
                    "experimental_source": experimental_entry.get("structure_source"),
                }
            )
        if len(current_pages) > 1 and len(experimental_pages) < len(current_pages):
            regressions.append(
                {
                    "index": index,
                    "type": "page_continuation_lost",
                    "current_pages": current_pages,
                    "experimental_pages": experimental_pages,
                }
            )
        if not current_tail_noise and experimental_tail_noise:
            regressions.append({"index": index, "type": "new_tail_noise"})
        if not current_mixed and experimental_mixed:
            regressions.append({"index": index, "type": "new_reference_contamination"})
        if not bool(current_decision.get("accepted")) and bool(
            experimental_decision.get("accepted")
        ):
            improvements.append(
                {
                    "index": index,
                    "type": "accepted_reference_recovered",
                    "current_reason": current_decision.get("reason"),
                    "experimental_reason": experimental_decision.get("reason"),
                }
            )
        if current_fallback and not experimental_fallback:
            improvements.append(
                {
                    "index": index,
                    "type": "fallback_removed",
                    "current_source": current_entry.get("structure_source"),
                    "experimental_source": experimental_entry.get("structure_source"),
                }
            )
        if len(current_pages) < len(experimental_pages) and len(experimental_pages) > 1:
            improvements.append(
                {
                    "index": index,
                    "type": "page_continuation_recovered",
                    "current_pages": current_pages,
                    "experimental_pages": experimental_pages,
                }
            )
        if current_tail_noise and not experimental_tail_noise:
            improvements.append({"index": index, "type": "tail_noise_removed"})

    metric_deltas = {}
    for metric_name in (
        "references_total",
        "max_reference_index_detected",
        "coverage_ratio",
        "pct_structure_source_rows_raw",
        "pct_structure_source_raw_reference_fallback",
        "pct_accepted",
    ):
        current_value = current_metrics.get(metric_name)
        experimental_value = experimental_metrics.get(metric_name)
        if isinstance(current_value, (int, float)) and isinstance(
            experimental_value,
            (int, float),
        ):
            metric_deltas[metric_name] = round(
                float(experimental_value) - float(current_value),
                3,
            )
    status = "neutral"
    if regressions:
        status = "regression_detected"
    elif improvements:
        status = "improved_without_regression"
    return {
        "status": status,
        "promotion_ready": bool(improvements) and not regressions,
        "regressions": regressions[:80],
        "improvements": improvements[:80],
        "metric_deltas": metric_deltas,
        "regression_total": len(regressions),
        "improvement_total": len(improvements),
    }


def _build_experimental_reference_entries_v2(
    *,
    references: Sequence[Dict[str, Any]],
    parsed_references: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for fallback_idx, ref in enumerate(references, start=1):
        if not isinstance(ref, dict):
            continue
        index = _entry_index(ref)
        if index is None:
            entries.append(
                {
                    "id": f"reference-entry-v2-unlabeled-{fallback_idx}",
                    "ref_id": f"ref-v2-unlabeled-{fallback_idx}",
                    "index": None,
                    "text": str(ref.get("raw") or ref.get("text") or ""),
                    "page": None,
                    "box": None,
                    "doi": _normalize_doi(ref.get("doi")) or None,
                    "structure_source": "raw_reference_fallback",
                    "local_row_count": 0,
                    "local_anchor_detected": False,
                    "reference_validation": {
                        "match_score": 0.0,
                        "mixed_reference_score": 0.0,
                        "has_nested_anchor": False,
                        "accepted": False,
                        "reason": "fallback_without_rows_structure",
                    },
                    "validation_intermediate": {
                        "match_score": 0.0,
                        "mixed_reference_score": 0.0,
                        "has_nested_anchor": False,
                        "accepted": False,
                        "reason": "fallback_without_rows_structure",
                    },
                    "scores": {
                        "accepted": False,
                        "classification": "fallback_needed",
                        "reason": "fallback_without_rows_structure",
                        "final_score": 0.0,
                    },
                    "final_decision": {
                        "accepted": False,
                        "classification": "fallback_needed",
                        "reason": "fallback_without_rows_structure",
                        "final_score": 0.0,
                    },
                    "crossref_match": {
                        "score": 0.0,
                        "doi_match_score": 0.0,
                        "match": None,
                    },
                    "token_reconstruction": {
                        "final_text": str(ref.get("raw") or ref.get("text") or "")
                    },
                    "anomalies": {"cut_reasons": [], "nested_anchor_indices": []},
                    "rows": [],
                }
            )
            continue
        parsed = parsed_references.get(index)
        if parsed is None:
            fallback_text = str(ref.get("raw") or ref.get("text") or "")
            entries.append(
                {
                    "id": f"reference-entry-v2-ref-{index}",
                    "ref_id": f"ref-{index}",
                    "index": index,
                    "text": fallback_text,
                    "page": None,
                    "box": None,
                    "doi": _normalize_doi(ref.get("doi")) or None,
                    "structure_source": "raw_reference_fallback",
                    "local_row_count": 0,
                    "local_anchor_detected": False,
                    "reference_validation": {
                        "match_score": 0.0,
                        "mixed_reference_score": 0.0,
                        "has_nested_anchor": False,
                        "accepted": False,
                        "reason": "fallback_without_rows_structure",
                    },
                    "validation_intermediate": {
                        "match_score": 0.0,
                        "mixed_reference_score": 0.0,
                        "has_nested_anchor": False,
                        "accepted": False,
                        "reason": "fallback_without_rows_structure",
                    },
                    "scores": {
                        "accepted": False,
                        "classification": "fallback_needed",
                        "reason": "fallback_without_rows_structure",
                        "final_score": 0.0,
                    },
                    "final_decision": {
                        "accepted": False,
                        "classification": "fallback_needed",
                        "reason": "fallback_without_rows_structure",
                        "final_score": 0.0,
                    },
                    "crossref_match": {
                        "score": 0.0,
                        "doi_match_score": 0.0,
                        "match": None,
                    },
                    "token_reconstruction": {"final_text": fallback_text},
                    "anomalies": {
                        "cut_reasons": ["missing_anchor_after_v2_reconciliation"],
                        "nested_anchor_indices": [],
                    },
                    "rows": [],
                }
            )
            continue
        entry = dict(parsed)
        entry["id"] = f"reference-entry-v2-ref-{index}"
        entry["ref_id"] = f"ref-{index}"
        entries.append(entry)
    return entries


def _run_numeric_reference_pipeline_v2(
    *,
    references: Sequence[Dict[str, Any]],
    metadata_by_index: Dict[int, Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
    current_reference_entries: Sequence[Dict[str, Any]],
    current_numeric_metrics: Dict[str, Any],
    crossref_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    expected_indices = sorted(
        {
            int(index)
            for index in metadata_by_index.keys()
            if isinstance(index, int) and int(index) > 0
        }
    )
    if not expected_indices:
        return None
    territory_phase = _build_numeric_bibliography_territory_v2(
        rows=rows,
        sections=sections,
        bibliography_items=bibliography_items,
    )
    ordered_rows = territory_phase.get("ordered_rows") or []
    anchor_candidates = _detect_numeric_anchor_candidates_v2(ordered_rows)
    anchor_reconciliation = _reconcile_numeric_anchor_candidates_v2(
        anchor_candidates=anchor_candidates,
        expected_indices=expected_indices,
    )
    selected_anchors = anchor_reconciliation.get("selected_anchors") or []
    anchor_candidates_by_position = {
        int(candidate.get("position")): candidate
        for candidate in anchor_candidates
        if _to_int(candidate.get("position")) is not None
    }
    tokens_by_page = _index_tokens_by_page(token_items or [])
    artifact_info = _build_repeating_page_artifacts(ordered_rows)
    parsed: Dict[int, Dict[str, Any]] = {}
    reference_debug: List[Dict[str, Any]] = []

    for anchor_index, anchor in enumerate(selected_anchors):
        index = int(anchor.get("index") or 0)
        next_anchor = (
            selected_anchors[anchor_index + 1]
            if anchor_index + 1 < len(selected_anchors)
            else None
        )
        block_result = _build_reference_rows_between_anchors_v2(
            ordered_rows=ordered_rows,
            current_anchor=anchor,
            next_anchor=next_anchor,
            anchor_candidates_by_position=anchor_candidates_by_position,
            artifact_info=artifact_info,
        )
        block_rows = block_result.get("rows") or []
        if not block_rows:
            reference_debug.append(
                {
                    "index": index,
                    "anchor_detected": {
                        "index": index,
                        "style": anchor.get("anchor_style"),
                        "confidence": round(float(anchor.get("confidence") or 0.0), 3),
                        "strength": anchor.get("strength"),
                        "page": anchor.get("page"),
                        "row_id": anchor.get("row_id"),
                    },
                    "body_start": block_result.get("body_start"),
                    "body_end": block_result.get("body_end"),
                    "rows_included": [],
                    "rows_discarded": block_result.get("rows_discarded") or [],
                    "continuation_between_pages": False,
                    "closure_reason": block_result.get("closure_reason"),
                    "issues": list(block_result.get("issues") or [])
                    + ["empty_reference_after_growth"],
                }
            )
            continue

        token_reconstruction = _reconstruct_reference_text_from_rows_and_tokens(
            block_rows,
            tokens_by_page,
        )
        reference_doi_seed = (
            _extract_doi(token_reconstruction.get("raw_text"))
            or _extract_doi(token_reconstruction.get("hybrid_text"))
            or _extract_doi(token_reconstruction.get("token_text"))
            or ""
        )
        selected_candidate = _select_reference_text_candidate(
            candidates=token_reconstruction.get("candidates") or [],
            reference_doi=reference_doi_seed,
            crossref_context=crossref_context,
        )
        selected_candidate_source = (
            str(
                selected_candidate.get("source")
                or token_reconstruction.get("selected_candidate_source")
                or "rows_raw"
            ).strip()
            or "rows_raw"
        )
        token_reconstruction["selected_candidate_source"] = selected_candidate_source
        token_reconstruction["candidate_scores"] = (
            selected_candidate.get("candidate_scores") or []
        )
        token_reconstruction["order_similarity_to_rows"] = selected_candidate.get(
            "order_similarity_to_rows"
        )
        token_reconstruction["order_guard_reasons"] = (
            selected_candidate.get("order_guard_reasons") or []
        )
        token_reconstruction["backbone_source"] = selected_candidate.get(
            "backbone_source"
        ) or token_reconstruction.get("backbone_source")
        token_reconstruction["backbone_text"] = str(
            selected_candidate.get("backbone_text")
            or token_reconstruction.get("backbone_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        token_reconstruction["final_text"] = str(
            selected_candidate.get("text")
            or token_reconstruction.get("hybrid_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        block_text = str(token_reconstruction.get("final_text") or "").strip()
        validation = _build_reference_validation(
            text=block_text,
            expected_index=index,
            metadata=metadata_by_index.get(index),
            metadata_by_index=metadata_by_index,
        )
        crossref_match = _match_reference_against_crossref(
            reference_text=block_text,
            reference_doi=_extract_doi(block_text),
            crossref_context=crossref_context,
        )
        final_decision = _build_reference_decision_v2(
            expected_index=index,
            rows=block_rows,
            reference_text=block_text,
            block_diagnostics=block_result,
            token_reconstruction=token_reconstruction,
            crossref_match=crossref_match,
            territory_zones=territory_phase.get("territory_zones") or [],
            validation=validation,
        )
        validation = _sync_reference_validation_with_final_decision(
            validation,
            final_decision,
        )
        parsed[index] = {
            "text": block_text,
            "text_raw": token_reconstruction.get("raw_text"),
            "page": block_rows[0].get("page"),
            "box": _union_boxes(
                [row["box"] for row in block_rows if _normalize_box(row.get("box"))]
            ),
            "rows": block_rows,
            "local_row_count": len(block_rows),
            "local_anchor_detected": True,
            "structure_source": (
                selected_candidate_source
                if selected_candidate_source.startswith("rows")
                else "rows_raw"
            ),
            "reference_validation": validation,
            "validation_intermediate": _coerce_reference_validation_payload(validation),
            "column_id": block_rows[0].get("column_id_v2"),
            "anchor_position": anchor.get("position"),
            "anchor_style": anchor.get("anchor_style"),
            "scores": final_decision,
            "final_decision": final_decision,
            "crossref_match": crossref_match,
            "token_reconstruction": token_reconstruction,
            "anomalies": {
                "cut_reasons": list(block_result.get("cut_reasons") or []),
                "nested_anchor_indices": [],
            },
        }
        reference_debug.append(
            {
                "index": index,
                "anchor_detected": {
                    "index": index,
                    "style": anchor.get("anchor_style"),
                    "confidence": round(float(anchor.get("confidence") or 0.0), 3),
                    "strength": anchor.get("strength"),
                    "page": anchor.get("page"),
                    "row_id": anchor.get("row_id"),
                    "body_in_next_row": bool(anchor.get("body_in_next_row")),
                },
                "body_start": block_result.get("body_start"),
                "body_end": block_result.get("body_end"),
                "rows_included": [
                    {
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
                        "reading_unit_id": row.get("reading_unit_id"),
                        "text": _short_debug_text(row.get("text")),
                    }
                    for row in block_rows
                ],
                "rows_discarded": block_result.get("rows_discarded") or [],
                "continuation_between_pages": bool(
                    block_result.get("continuation_between_pages")
                ),
                "closure_reason": block_result.get("closure_reason"),
                "issues": block_result.get("issues") or [],
                "accepted": bool(final_decision.get("accepted")),
                "selected_candidate_source": selected_candidate_source,
            }
        )

    experimental_entries = _build_experimental_reference_entries_v2(
        references=references,
        parsed_references=parsed,
    )
    experimental_metrics = _build_numeric_pipeline_metrics(
        expected_indices=expected_indices,
        reference_entries=experimental_entries,
        detected_anchor_indices=[
            int(candidate.get("index"))
            for candidate in anchor_candidates
            if _to_int(candidate.get("index")) not in (None, 0)
        ],
        duplicate_indices=anchor_reconciliation.get("duplicate_indices") or [],
    )
    comparison = _build_numeric_reference_comparison_v2(
        current_entries=current_reference_entries,
        experimental_entries=experimental_entries,
        current_metrics=current_numeric_metrics,
        experimental_metrics=experimental_metrics,
    )
    return {
        "pipeline_name": NUMERIC_REFERENCE_PIPELINE_V2_NAME,
        "run_mode": NUMERIC_REFERENCE_PIPELINE_V2_RUN_MODE,
        "enabled": True,
        "selected_as_default": False,
        "phases": {
            "territory": {
                "start_page": territory_phase.get("start_page"),
                "selected_heading": (
                    {
                        "page": territory_phase["selected_heading"].get("page"),
                        "text": territory_phase["selected_heading"].get("text"),
                        "column_id": territory_phase["selected_heading"].get(
                            "column_id"
                        ),
                        "box": _serialize_box(
                            territory_phase["selected_heading"].get("box")
                        ),
                    }
                    if isinstance(territory_phase.get("selected_heading"), dict)
                    else None
                ),
                "zones": [
                    {
                        "id": zone.get("id"),
                        "page": zone.get("page"),
                        "box": _serialize_box(zone.get("box")),
                        "confidence": zone.get("confidence"),
                        "source_signals": zone.get("source_signals") or [],
                        "anchor_indices": zone.get("anchor_indices") or [],
                    }
                    for zone in territory_phase.get("territory_zones") or []
                ],
            },
            "reading_order": {
                "units": [
                    {
                        "id": unit.get("id"),
                        "page": unit.get("page"),
                        "order_on_page": unit.get("order_on_page"),
                        "box": _serialize_box(unit.get("box")),
                        "anchor_indices": unit.get("anchor_indices") or [],
                        "bibliography_density": unit.get("bibliography_density"),
                        "confidence": unit.get("confidence"),
                    }
                    for unit in territory_phase.get("reading_units") or []
                ],
            },
            "anchors": {
                "candidates": [
                    {
                        "index": candidate.get("index"),
                        "page": candidate.get("page"),
                        "position": candidate.get("position"),
                        "row_id": candidate.get("row_id"),
                        "style": candidate.get("anchor_style"),
                        "strength": candidate.get("strength"),
                        "confidence": round(
                            float(candidate.get("confidence") or 0.0), 3
                        ),
                        "reason": candidate.get("reason"),
                        "body_in_next_row": bool(candidate.get("body_in_next_row")),
                    }
                    for candidate in anchor_candidates
                ],
                "sequence": anchor_reconciliation.get("anchor_sequence") or [],
                "missing_indices": anchor_reconciliation.get("missing_indices") or [],
                "duplicate_indices": anchor_reconciliation.get("duplicate_indices")
                or [],
                "inferred_anchors": anchor_reconciliation.get("inferred_anchors") or [],
            },
            "reconciliation": {
                "actions": anchor_reconciliation.get("reconciliation_actions") or [],
            },
        },
        "reference_debug": reference_debug,
        "references": experimental_entries,
        "metrics": experimental_metrics,
        "comparison_vs_current": comparison,
    }


def _serialize_row_geometry_v3(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    page = _to_int(row.get("page"))
    box = _normalize_box(row.get("box"))
    if not isinstance(page, int) or box is None:
        return None
    return {
        "row_id": str(row.get("id") or ""),
        "page": page,
        "box": _serialize_box(box),
    }


def _coerce_geometry_box_v3(value: Any) -> Optional[List[float]]:
    normalized = _normalize_box(value)
    if normalized is not None:
        return normalized
    if isinstance(value, dict):
        x0 = _to_float(value.get("x0"))
        y0 = _to_float(value.get("y0"))
        x1 = _to_float(value.get("x1"))
        y1 = _to_float(value.get("y1"))
        if None not in (x0, y0, x1, y1):
            return _box_from_corners(
                float(x0),
                float(y0),
                float(x1),
                float(y1),
            )
    return None


def _build_reference_geometry_payload_v3(
    rows: Sequence[Dict[str, Any]],
    *,
    geometry_source: str,
) -> Dict[str, Any]:
    row_ids = [
        str(row.get("id") or "") for row in rows if str(row.get("id") or "").strip()
    ]
    row_boxes: List[Dict[str, Any]] = []
    page_box_map: Dict[int, List[List[float]]] = defaultdict(list)
    for row in rows:
        serialized = _serialize_row_geometry_v3(row)
        if serialized is None:
            continue
        row_boxes.append(serialized)
        page = int(serialized["page"])
        box = _coerce_geometry_box_v3(serialized["box"])
        if box is not None:
            page_box_map[page].append(box)
    page_boxes: List[Dict[str, Any]] = []
    for page in sorted(page_box_map.keys()):
        union_box = _union_boxes(page_box_map[page])
        if union_box is None:
            continue
        page_boxes.append({"page": int(page), "box": _serialize_box(union_box)})
    union_box = _union_boxes(
        [
            _coerce_geometry_box_v3(item.get("box"))
            for item in row_boxes
            if _coerce_geometry_box_v3(item.get("box")) is not None
        ]
    )
    pages_involved = sorted(
        {
            int(item.get("page"))
            for item in row_boxes
            if _to_int(item.get("page")) is not None
        }
    )
    return {
        "row_ids": row_ids,
        "rows": [dict(row) for row in rows],
        "row_boxes": row_boxes,
        "page_boxes": page_boxes,
        "union_box": _serialize_box(union_box),
        "pages_involved": pages_involved,
        "geometry_source": str(geometry_source or "rows_growth_v3"),
    }


def _detect_numeric_anchor_candidates_v3(
    ordered_rows: Sequence[Dict[str, Any]],
    *,
    debug_collector: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    marker_layout = _build_marker_only_anchor_link_map_v3(ordered_rows)
    marker_layout_confirmed = bool(marker_layout.get("layout_confirmed"))
    marker_links_by_position = (
        marker_layout.get("linked_by_position") or {} if marker_layout_confirmed else {}
    )
    if isinstance(debug_collector, dict):
        debug_collector["marker_only_anchor_audit"] = {
            "layout_confirmed": marker_layout_confirmed,
            "layout_confirmation_reason": marker_layout.get(
                "layout_confirmation_reason"
            ),
            "body_x0_reference": marker_layout.get("body_x0_reference"),
            "marker_rows_total": int(marker_layout.get("marker_rows_total") or 0),
            "linked_rows_total": int(marker_layout.get("linked_rows_total") or 0),
            "linked_rows": marker_layout.get("linked_rows") or [],
            "link_failures": marker_layout.get("link_failures") or [],
        }

    candidates: List[Dict[str, Any]] = []
    for position, row in enumerate(ordered_rows):
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        row_id = str(row.get("id") or "")
        page = _to_int(row.get("page"))
        next_row = (
            ordered_rows[position + 1] if position + 1 < len(ordered_rows) else None
        )
        next_position = _to_int((next_row or {}).get("flow_position"))
        if next_row is not None and next_position is None:
            next_position = position + 1
        next_row_id = str((next_row or {}).get("id") or "")
        next_text = str((next_row or {}).get("text") or "").strip()
        next_same_page = bool(
            next_row is not None and _to_int(next_row.get("page")) == page
        )
        body_inline = _strip_numeric_anchor_prefix(text)
        body_inline_signal = _has_v2_bibliographic_body_signal(body_inline)
        body_in_next_row_signal = bool(
            next_same_page
            and next_text
            and _has_v2_bibliographic_body_signal(next_text)
            and not _row_is_section_transition_v2(next_text)
        )
        accepted = _match_reference_anchor_at_line_start(text)
        candidate = _match_reference_anchor_at_line_start(text, include_rejected=True)
        marker_only = _match_marker_only_numeric_anchor(text)

        selected: Optional[Dict[str, Any]] = None
        if accepted and accepted.get("accepted"):
            index = _to_int(accepted.get("index"))
            if index is None or index <= 0:
                continue
            style = str(accepted.get("anchor_style") or "unknown")
            strength = (
                "strong"
                if body_inline_signal
                else ("medium" if body_in_next_row_signal else "weak")
            )
            confidence = {
                "strong": 0.97,
                "medium": 0.91,
                "weak": 0.79,
            }[strength]
            if style == "bracketed":
                confidence += 0.01
            body_start_position = int(position)
            body_start_row_id = row_id
            layout_type = "inline_anchor_same_row"
            anchor_to_body_link_reason = "inline_body_same_row"
            if not body_inline_signal and body_in_next_row_signal:
                body_start_position = int(
                    next_position if next_position is not None else position + 1
                )
                body_start_row_id = next_row_id
                layout_type = "inline_anchor_next_row"
                anchor_to_body_link_reason = "inline_anchor_body_in_next_row"
            selected = {
                "index": int(index),
                "style": style,
                "anchor_style": style,
                "confidence": round(min(confidence, 0.99), 3),
                "strength": strength,
                "row_id": row_id,
                "anchor_row_id": row_id,
                "body_start_row_id": body_start_row_id,
                "row": row,
                "page": page,
                "position": int(row.get("flow_position", position)),
                "body_start_position": body_start_position,
                "anchor_type": "inline",
                "layout_type": layout_type,
                "anchor_to_body_link_reason": anchor_to_body_link_reason,
                "used_marker_only_anchor": False,
                "body_in_next_row": bool(
                    body_in_next_row_signal and not body_inline_signal
                ),
                "reason": (
                    "accepted_anchor_inline_body"
                    if body_inline_signal
                    else (
                        "accepted_anchor_body_in_next_row"
                        if body_in_next_row_signal
                        else "accepted_anchor_without_body_signal"
                    )
                ),
            }
        elif marker_only and marker_links_by_position.get(position):
            marker_link = marker_links_by_position.get(position) or {}
            index = _to_int(marker_only.get("index"))
            if index is None or index <= 0:
                continue
            linked_body_position = _to_int(marker_link.get("body_start_position"))
            linked_body_row_id = str(marker_link.get("body_start_row_id") or "")
            if (
                linked_body_position is None
                or linked_body_position <= position
                or not linked_body_row_id
            ):
                continue
            link_confidence = float(marker_link.get("confidence") or 0.79)
            link_reason = str(marker_link.get("link_reason") or "").strip() or (
                "same_page_right_band"
            )
            selected = {
                "index": int(index),
                "style": str(marker_only.get("anchor_style") or "unknown"),
                "anchor_style": str(marker_only.get("anchor_style") or "unknown"),
                "confidence": round(max(0.72, min(link_confidence, 0.96)), 3),
                "strength": (
                    "medium" if linked_body_position == position + 1 else "strong"
                ),
                "row_id": row_id,
                "anchor_row_id": row_id,
                "body_start_row_id": linked_body_row_id,
                "row": row,
                "page": page,
                "position": int(row.get("flow_position", position)),
                "body_start_position": int(linked_body_position),
                "anchor_type": "marker_only",
                "layout_type": "marker_only_left_gutter",
                "anchor_to_body_link_reason": link_reason,
                "used_marker_only_anchor": True,
                "body_in_next_row": bool(linked_body_position == position + 1),
                "reason": "marker_only_left_gutter_anchor_linked_to_body_start",
            }
        elif marker_only and body_in_next_row_signal:
            index = _to_int(marker_only.get("index"))
            if index is None or index <= 0:
                continue
            selected = {
                "index": int(index),
                "style": str(marker_only.get("anchor_style") or "unknown"),
                "anchor_style": str(marker_only.get("anchor_style") or "unknown"),
                "confidence": 0.75,
                "strength": "weak",
                "row_id": row_id,
                "anchor_row_id": row_id,
                "body_start_row_id": next_row_id,
                "row": row,
                "page": page,
                "position": int(row.get("flow_position", position)),
                "body_start_position": int(
                    next_position if next_position is not None else position + 1
                ),
                "anchor_type": "marker_only",
                "layout_type": "marker_only_next_row_fallback",
                "anchor_to_body_link_reason": "fallback_next_row_body_signal",
                "used_marker_only_anchor": True,
                "body_in_next_row": True,
                "reason": "marker_only_anchor_followed_by_body_row",
            }
        elif (
            candidate
            and not candidate.get("accepted")
            and str(candidate.get("anchor_rejected_reason") or "")
            == "weak_bibliographic_signal"
            and body_in_next_row_signal
        ):
            index = _to_int(candidate.get("index"))
            if index is None or index <= 0:
                continue
            selected = {
                "index": int(index),
                "style": str(candidate.get("anchor_style") or "unknown"),
                "anchor_style": str(candidate.get("anchor_style") or "unknown"),
                "confidence": 0.71,
                "strength": "weak",
                "row_id": row_id,
                "anchor_row_id": row_id,
                "body_start_row_id": next_row_id,
                "row": row,
                "page": page,
                "position": int(row.get("flow_position", position)),
                "body_start_position": int(
                    next_position if next_position is not None else position + 1
                ),
                "anchor_type": "inline_recovered",
                "layout_type": "recovered_split_anchor_next_row",
                "anchor_to_body_link_reason": "recovered_from_following_body_row",
                "used_marker_only_anchor": False,
                "body_in_next_row": True,
                "reason": "recovered_split_anchor_from_following_row",
            }

        if selected is None:
            continue
        candidates.append(selected)

    candidates.sort(
        key=lambda item: (
            int(item.get("position") or 0),
            -float(item.get("confidence") or 0.0),
        )
    )
    for idx, candidate in enumerate(candidates):
        previous_index = _to_int(candidates[idx - 1].get("index")) if idx > 0 else None
        next_index = (
            _to_int(candidates[idx + 1].get("index"))
            if idx + 1 < len(candidates)
            else None
        )
        candidate["sequence_supported"] = bool(
            previous_index == int(candidate.get("index") or 0) - 1
            or next_index == int(candidate.get("index") or 0) + 1
        )
    return candidates


def _build_numeric_bibliography_territory_v3(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    return _build_numeric_bibliography_territory_layers_rows_v3(
        rows=rows,
        sections=sections,
        bibliography_items=bibliography_items,
    )


def _build_numeric_bibliography_territory_layers_rows_v3(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rows_with_columns = _assign_column_ids(rows)
    page_splits = _collect_page_split_map(rows_with_columns)
    heading_candidates = _detect_reference_heading_candidates(
        rows_with_columns,
        sections,
        page_splits,
    )
    pre_flow = build_bibliography_reading_flow(rows_with_columns)
    pre_anchor_scan = _detect_numeric_anchor_candidates_v3(pre_flow)

    max_page = max(
        (
            int(row.get("page"))
            for row in rows_with_columns
            if isinstance(row.get("page"), int)
        ),
        default=-1,
    )
    tail_page_span = max(3, int((max_page + 1) * 0.35))
    tail_start_page = max(0, max_page - tail_page_span + 1)
    tail_heading_candidates = [
        candidate
        for candidate in heading_candidates
        if int(candidate.get("page") or -1) >= tail_start_page
    ]
    tail_anchor_candidates = [
        candidate
        for candidate in pre_anchor_scan
        if int(candidate.get("page") or -1) >= tail_start_page
    ]
    bibliography_layer_pages = sorted(
        {
            int(item.get("page"))
            for item in bibliography_items
            if isinstance(item.get("page"), int)
        }
    )
    tail_bibliography_pages = [
        page for page in bibliography_layer_pages if int(page) >= tail_start_page
    ]

    heading_counts_by_page: Counter[int] = Counter(
        int(candidate.get("page"))
        for candidate in tail_heading_candidates
        if _to_int(candidate.get("page")) is not None
    )
    anchor_counts_by_page: Counter[int] = Counter(
        int(candidate.get("page"))
        for candidate in tail_anchor_candidates
        if _to_int(candidate.get("page")) is not None
    )
    start_page_pool = sorted(
        set(heading_counts_by_page.keys())
        | set(anchor_counts_by_page.keys())
        | set(tail_bibliography_pages)
    )
    if not start_page_pool:
        start_page_pool = sorted(
            {
                int(candidate.get("page"))
                for candidate in heading_candidates
                if _to_int(candidate.get("page")) is not None
            }
            | {
                int(candidate.get("page"))
                for candidate in pre_anchor_scan
                if _to_int(candidate.get("page")) is not None
            }
            | set(bibliography_layer_pages)
        )
    start_page_scores: List[Tuple[float, int]] = []
    for candidate_page in start_page_pool:
        score = 0.0
        if candidate_page in tail_bibliography_pages:
            score += 0.55
        if heading_counts_by_page.get(candidate_page):
            score += 0.22 + min(
                0.08 * int(heading_counts_by_page.get(candidate_page) or 0),
                0.16,
            )
        if anchor_counts_by_page.get(candidate_page):
            score += min(
                0.1 * int(anchor_counts_by_page.get(candidate_page) or 0), 0.28
            )
        if candidate_page + 1 in tail_bibliography_pages:
            score += 0.08
        if candidate_page - 1 in tail_bibliography_pages:
            score += 0.04
        start_page_scores.append((score, int(candidate_page)))
    start_page_scores.sort(key=lambda item: (-float(item[0]), int(item[1])))
    start_page = start_page_scores[0][1] if start_page_scores else None

    selected_heading = None
    heading_pool = tail_heading_candidates or heading_candidates
    if heading_pool:
        selected_heading = min(
            heading_pool,
            key=lambda item: (
                abs(
                    int(item.get("page") or 0)
                    - int(
                        start_page if start_page is not None else item.get("page") or 0
                    )
                ),
                float((_normalize_box(item.get("box")) or [0.0, 0.0])[1]),
                float((_normalize_box(item.get("box")) or [0.0])[0]),
            ),
        )
        if start_page is None:
            start_page = _to_int(selected_heading.get("page"))

    heading_bottom_by_page: Dict[int, float] = {}
    if isinstance(selected_heading, dict):
        heading_page = _to_int(selected_heading.get("page"))
        heading_box = _normalize_box(selected_heading.get("box"))
        if isinstance(heading_page, int) and heading_box is not None:
            heading_bottom_by_page[heading_page] = round(
                float(heading_box[1]) + float(heading_box[3]),
                4,
            )

    bibliography_layer_by_page: Dict[int, List[List[float]]] = defaultdict(list)
    for item in bibliography_items:
        page = _to_int(item.get("page"))
        box = _normalize_box(item.get("box"))
        if isinstance(page, int) and box is not None:
            bibliography_layer_by_page[page].append(box)

    anchor_candidate_by_row_id: Dict[str, Dict[str, Any]] = {}
    for candidate in pre_anchor_scan:
        row_id = str(candidate.get("row_id") or "").strip()
        if not row_id:
            continue
        existing = anchor_candidate_by_row_id.get(row_id)
        if existing is None or float(candidate.get("confidence") or 0.0) > float(
            existing.get("confidence") or 0.0
        ):
            anchor_candidate_by_row_id[row_id] = candidate

    noise_regions: List[Dict[str, Any]] = []
    section_transition_pages: List[int] = []
    for section in sections:
        page = _to_int(section.get("page"))
        text = str(section.get("text") or "").strip()
        box = _normalize_box(section.get("box"))
        if page is None or start_page is None or page < start_page or not text:
            continue
        is_transition = bool(
            _row_is_section_transition_v2(text) and not _is_reference_heading_text(text)
        )
        noise_score = float(_score_header_noise(text))
        if is_transition:
            section_transition_pages.append(page)
        if is_transition or noise_score >= 0.72:
            noise_regions.append(
                {
                    "page": page,
                    "text": _short_debug_text(text, limit=160),
                    "box": _serialize_box(box),
                    "noise_score": round(noise_score, 3),
                    "reason": (
                        "section_transition"
                        if is_transition
                        else "high_noise_section_signal"
                    ),
                }
            )

    max_anchor_page = max(
        (
            int(candidate.get("page"))
            for candidate in pre_anchor_scan
            if _to_int(candidate.get("page")) is not None
            and int(candidate.get("page")) >= int(start_page or 0)
        ),
        default=int(start_page or 0),
    )
    max_layer_page = max(
        [page for page in bibliography_layer_pages if page >= int(start_page or 0)]
        or [int(start_page or 0)]
    )
    window_end_soft = max(int(start_page or 0), max_anchor_page, max_layer_page)
    if section_transition_pages:
        transition_candidates = [
            page
            for page in section_transition_pages
            if page >= int(start_page or 0) + 1
        ]
        if transition_candidates:
            window_end_soft = min(window_end_soft, min(transition_candidates))
    window_page_limit = int(window_end_soft or 0) + 1

    window_init_by_page: Dict[int, List[float]] = {}
    for page in range(int(start_page or 0), int(window_end_soft or 0) + 1):
        page_union = _union_boxes(bibliography_layer_by_page.get(page) or [])
        if page_union is not None:
            window_init_by_page[page] = page_union

    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    selected_by_row_id: Dict[str, Dict[str, Any]] = {}
    rejected_candidates: List[Dict[str, Any]] = []
    scored_rows: List[Dict[str, Any]] = []
    rows_rejection_reasons_counter: Counter[str] = Counter()
    for row in rows_with_columns:
        page = _to_int(row.get("page"))
        if start_page is None or page is None or page < start_page:
            continue
        text = str(row.get("text") or "").strip()
        box = _normalize_box(row.get("box"))
        if not text or box is None:
            continue
        row_id = str(row.get("id") or "")
        anchor_candidate = anchor_candidate_by_row_id.get(row_id) or {}
        has_anchor = bool(anchor_candidate)
        has_bibliographic_body = _has_v2_bibliographic_body_signal(text)
        doi_signal = bool(_extract_doi(text))
        year_signal = bool(REFERENCE_YEAR_RE.search(text))
        section_transition = bool(
            _row_is_section_transition_v2(text) and not _is_reference_heading_text(text)
        )
        header_footer_noise = bool(_is_header_footer_row(row, artifact_info))
        row_noise_score = float(_score_header_noise(text))
        layer_overlap = max(
            (
                _overlap_ratio(layer_box, box)
                for layer_box in (bibliography_layer_by_page.get(page) or [])
            ),
            default=0.0,
        )
        in_window_page_range = bool(page <= window_page_limit)
        page_window_box = window_init_by_page.get(page)
        in_window_geometry = True
        if page_window_box is not None:
            in_window_geometry = bool(
                _contains_box(page_window_box, box)
                or _overlap_ratio(page_window_box, box) >= 0.12
            )
        if page in heading_bottom_by_page and not has_anchor:
            heading_bottom = float(heading_bottom_by_page[page])
            if float(box[1]) + float(box[3]) < heading_bottom:
                in_window_geometry = False
        in_initial_window = bool(in_window_page_range and in_window_geometry)

        row_score = 0.0
        row_signals: List[str] = []
        if has_anchor:
            row_score += 0.48
            row_signals.append("anchor_visible")
        if has_bibliographic_body:
            row_score += 0.26
            row_signals.append("bibliographic_body")
        if doi_signal:
            row_score += 0.09
            row_signals.append("doi_signal")
        if year_signal:
            row_score += 0.05
            row_signals.append("year_signal")
        if len(text) >= 72:
            row_score += 0.04
            row_signals.append("long_row")
        if layer_overlap >= 0.12:
            row_score += min(layer_overlap, 0.18)
            row_signals.append("bibliography_layer_overlap")
        if in_initial_window:
            row_score += 0.05
            row_signals.append("inside_window")
        if not in_window_page_range:
            row_score -= 0.24
            row_signals.append("outside_soft_end_page")
        if not in_window_geometry:
            row_score -= 0.18
            row_signals.append("outside_window_geometry")
        if section_transition:
            row_score -= 0.55
            row_signals.append("section_transition")
        if header_footer_noise and not has_anchor:
            row_score -= 0.32
            row_signals.append("header_footer_noise")
        if row_noise_score >= 0.74 and not (doi_signal or year_signal):
            row_score -= 0.2
            row_signals.append("high_noise_score")

        row_payload = dict(row)
        row_payload["territory_score"] = round(float(row_score), 3)
        row_payload["territory_signals"] = row_signals
        row_payload["layer_overlap"] = round(float(layer_overlap), 3)
        row_payload["in_initial_window"] = bool(in_initial_window)
        row_payload["rescued_outside_initial_window"] = False
        if has_anchor:
            row_payload["anchor_index"] = _to_int(anchor_candidate.get("index"))
            row_payload["anchor_style"] = anchor_candidate.get(
                "anchor_style"
            ) or anchor_candidate.get("style")

        accept = False
        rejection_reason = "low_bibliographic_score"
        if section_transition and not has_anchor:
            rejection_reason = "section_transition"
        elif header_footer_noise and not has_anchor and not has_bibliographic_body:
            rejection_reason = "header_footer_noise"
        elif has_anchor and in_initial_window:
            accept = True
            rejection_reason = "accepted_anchor_in_window"
        elif in_initial_window and row_score >= 0.22:
            accept = True
            rejection_reason = "accepted_scored_in_window"
        elif has_anchor:
            rejection_reason = "anchor_outside_initial_window"
        elif row_score >= 0.52:
            rejection_reason = "strong_bibliographic_signal_outside_window"

        if accept:
            selected_by_row_id[row_id] = row_payload
            scored_rows.append(row_payload)
            continue
        rejected_candidates.append(
            {
                "row": row_payload,
                "reason": rejection_reason,
                "header_footer_noise": header_footer_noise,
                "section_transition": section_transition,
                "has_anchor": has_anchor,
                "has_bibliographic_body": has_bibliographic_body,
                "doi_signal": doi_signal,
                "outside_initial_window": not bool(in_initial_window),
            }
        )

    def _is_near_selected_row(candidate_row: Dict[str, Any]) -> bool:
        candidate_page = _to_int(candidate_row.get("page"))
        candidate_column = str(candidate_row.get("column_id") or "")
        candidate_y0 = _to_float(candidate_row.get("y0"))
        candidate_y1 = _to_float(candidate_row.get("y1"))
        if candidate_page is None:
            return False
        for row in selected_by_row_id.values():
            row_page = _to_int(row.get("page"))
            row_column = str(row.get("column_id") or "")
            if row_page is None:
                continue
            if candidate_column and row_column and candidate_column != row_column:
                continue
            if row_page == candidate_page:
                row_y0 = _to_float(row.get("y0"))
                row_y1 = _to_float(row.get("y1"))
                if (
                    candidate_y0 is not None
                    and row_y1 is not None
                    and abs(float(candidate_y0) - float(row_y1)) <= 0.085
                ):
                    return True
                if (
                    candidate_y1 is not None
                    and row_y0 is not None
                    and abs(float(candidate_y1) - float(row_y0)) <= 0.085
                ):
                    return True
            if row_page == candidate_page - 1:
                row_y1 = _to_float(row.get("y1"))
                if (
                    row_y1 is not None
                    and candidate_y0 is not None
                    and float(row_y1) >= 0.76
                    and float(candidate_y0) <= 0.24
                ):
                    return True
        return False

    rescued_rows_outside_initial_window: List[Dict[str, Any]] = []
    bibliography_rows_rejected: List[Dict[str, Any]] = []
    for candidate in rejected_candidates:
        row = dict(candidate.get("row") or {})
        row_id = str(row.get("id") or "")
        reason = str(candidate.get("reason") or "rejected")
        rescue_reason = None
        if bool(candidate.get("outside_initial_window")) and not bool(
            candidate.get("section_transition")
        ):
            if reason == "anchor_outside_initial_window":
                rescue_reason = "anchor_outside_initial_window"
            elif (
                bool(candidate.get("has_anchor"))
                and float(row.get("territory_score") or 0.0) >= 0.12
            ):
                rescue_reason = "anchor_and_minimum_score_outside_window"
            elif (
                bool(candidate.get("has_bibliographic_body"))
                and not bool(candidate.get("header_footer_noise"))
                and _is_near_selected_row(row)
            ):
                rescue_reason = "continuity_with_selected_rows"
            elif bool(candidate.get("doi_signal")) and _is_near_selected_row(row):
                rescue_reason = "doi_row_continuity"
        if rescue_reason:
            row["rescued_outside_initial_window"] = True
            row["rescue_reason"] = rescue_reason
            selected_by_row_id[row_id] = row
            scored_rows.append(row)
            rescued_rows_outside_initial_window.append(
                {
                    "row_id": row_id,
                    "page": row.get("page"),
                    "reason": rescue_reason,
                    "text": _short_debug_text(row.get("text"), limit=160),
                }
            )
            continue
        rows_rejection_reasons_counter[reason] += 1
        bibliography_rows_rejected.append(
            {
                "row_id": row_id,
                "page": row.get("page"),
                "column_id": row.get("column_id"),
                "box": _serialize_box(_normalize_box(row.get("box"))),
                "reason": reason,
                "signals": row.get("territory_signals") or [],
                "score": row.get("territory_score"),
                "in_initial_window": bool(row.get("in_initial_window")),
                "text": _short_debug_text(row.get("text"), limit=180),
            }
        )

    rows_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in scored_rows:
        page = _to_int(row.get("page"))
        if isinstance(page, int):
            rows_by_page[page].append(row)

    territory_rows: List[Dict[str, Any]] = []
    territory_zones: List[Dict[str, Any]] = []
    reading_lanes: List[Dict[str, Any]] = []
    lane_rows_map: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for page in sorted(rows_by_page.keys()):
        for row in rows_by_page.get(page) or []:
            lane_rows_map[(page, str(row.get("column_id") or "left"))].append(row)

    lane_order_map: Dict[Tuple[int, str], int] = {}
    for page in sorted({key[0] for key in lane_rows_map.keys()}):
        page_lane_keys = [key for key in lane_rows_map.keys() if key[0] == page]
        page_lane_keys.sort(
            key=lambda key: (
                0 if key[1] == "left" else (1 if key[1] == "right" else 2),
                _median(
                    [
                        float(row.get("x0") or 0.0)
                        for row in lane_rows_map.get(key) or []
                    ]
                ),
            )
        )
        for order_on_page, lane_key in enumerate(page_lane_keys):
            lane_order_map[lane_key] = order_on_page

    for lane_key in sorted(
        lane_rows_map.keys(),
        key=lambda key: (key[0], lane_order_map.get(key, 0)),
    ):
        page, column_id = lane_key
        lane_rows = sorted(lane_rows_map.get(lane_key) or [], key=_line_sort_key)
        lane_box = _union_boxes(
            [
                _normalize_box(row.get("box"))
                for row in lane_rows
                if _normalize_box(row.get("box")) is not None
            ]
        )
        if lane_box is None:
            continue
        lane_order = lane_order_map.get(lane_key, 0)
        lane_id = f"v3-lane-{page}-{lane_order}"
        zone_id = f"v3-zone-{page}-{lane_order}"
        lane_confidence = round(
            _median([float(row.get("territory_score") or 0.0) for row in lane_rows]),
            3,
        )
        lane_anchor_total = sum(
            1 for row in lane_rows if _to_int(row.get("anchor_index")) not in (None, 0)
        )
        reading_lanes.append(
            {
                "id": lane_id,
                "page": page,
                "column_id": column_id,
                "order_on_page": lane_order,
                "box": _serialize_box(lane_box),
                "confidence": lane_confidence,
                "anchor_total": lane_anchor_total,
                "row_ids": [
                    str(row.get("id") or "")
                    for row in lane_rows
                    if str(row.get("id") or "").strip()
                ],
            }
        )
        territory_zones.append(
            {
                "id": zone_id,
                "page": page,
                "column_id": column_id,
                "box": _serialize_box(lane_box),
                "confidence": lane_confidence,
                "source_signals": [
                    signal
                    for signal, enabled in (
                        ("anchors", lane_anchor_total > 0),
                        (
                            "bibliography_layer",
                            bool(bibliography_layer_by_page.get(page)),
                        ),
                        (
                            "rescued_rows",
                            any(
                                bool(row.get("rescued_outside_initial_window"))
                                for row in lane_rows
                            ),
                        ),
                    )
                    if enabled
                ],
                "row_ids": [
                    str(row.get("id") or "")
                    for row in lane_rows
                    if str(row.get("id") or "").strip()
                ],
            }
        )
        for row in lane_rows:
            next_row = dict(row)
            next_row["reading_lane_id"] = lane_id
            next_row["reading_lane_order_on_page"] = lane_order
            next_row["territory_zone_id"] = zone_id
            territory_rows.append(next_row)

    territory_rows.sort(
        key=lambda row: (
            int(row.get("page") or 0),
            int(row.get("reading_lane_order_on_page") or 0),
            float(row.get("y0") or 0.0),
            float(row.get("x0") or 0.0),
        )
    )
    ordered_bibliography_rows: List[Dict[str, Any]] = []
    for flow_position, row in enumerate(territory_rows):
        next_row = dict(row)
        next_row["flow_position"] = flow_position
        ordered_bibliography_rows.append(next_row)

    territory_union_box = _union_boxes(
        [
            _normalize_box(zone.get("box"))
            for zone in territory_zones
            if _normalize_box(zone.get("box")) is not None
        ]
    )
    bibliography_window_init = {
        "start_page": start_page,
        "pages": [
            {"page": page, "box": _serialize_box(box)}
            for page, box in sorted(
                window_init_by_page.items(), key=lambda item: item[0]
            )
        ],
    }
    bibliography_territory = {
        "bibliography_start_page": start_page,
        "bibliography_window_init": bibliography_window_init,
        "bibliography_window_end_soft": window_end_soft,
        "bibliography_noise_regions": noise_regions,
        "selected_heading": (
            {
                "page": _to_int(selected_heading.get("page")),
                "text": str(selected_heading.get("text") or ""),
                "box": _serialize_box(_normalize_box(selected_heading.get("box"))),
                "source": selected_heading.get("source"),
            }
            if isinstance(selected_heading, dict)
            else None
        ),
        "zone_count": len(territory_zones),
        "row_count": len(ordered_bibliography_rows),
        "union_box": _serialize_box(territory_union_box),
        "confidence": (
            round(
                _median(
                    [float(zone.get("confidence") or 0.0) for zone in territory_zones]
                ),
                3,
            )
            if territory_zones
            else 0.0
        ),
    }

    bibliography_rows_selected = [
        {
            "row_id": str(row.get("id") or ""),
            "page": row.get("page"),
            "column_id": row.get("column_id"),
            "box": _serialize_box(_normalize_box(row.get("box"))),
            "score": row.get("territory_score"),
            "signals": row.get("territory_signals") or [],
            "in_initial_window": bool(row.get("in_initial_window")),
            "rescued_outside_initial_window": bool(
                row.get("rescued_outside_initial_window")
            ),
            "rescue_reason": row.get("rescue_reason"),
            "anchor_index": row.get("anchor_index"),
            "anchor_style": row.get("anchor_style"),
            "text": _short_debug_text(row.get("text"), limit=180),
        }
        for row in ordered_bibliography_rows
    ]
    rows_rejection_reasons = dict(
        sorted(rows_rejection_reasons_counter.items(), key=lambda item: item[0])
    )

    bibliography_anchor = None
    if ordered_bibliography_rows:
        first_row = ordered_bibliography_rows[0]
        first_page = _to_int(first_row.get("page"))
        first_y = _to_float(first_row.get("y0"))
        if isinstance(first_page, int) and first_y is not None:
            bibliography_anchor = (first_page, float(first_y))

    return {
        "rows_with_columns": rows_with_columns,
        "page_splits": page_splits,
        "heading_candidates": heading_candidates,
        "selected_heading": selected_heading,
        "start_page": start_page,
        "bibliography_start_page": start_page,
        "bibliography_anchor": bibliography_anchor,
        "bibliography_window_init": bibliography_window_init,
        "bibliography_window_end_soft": window_end_soft,
        "bibliography_noise_regions": noise_regions,
        "bibliography_rows_selected": bibliography_rows_selected,
        "bibliography_rows_rejected": bibliography_rows_rejected,
        "rows_rejection_reasons": rows_rejection_reasons,
        "rescued_rows_outside_initial_window": rescued_rows_outside_initial_window,
        "bibliography_territory": bibliography_territory,
        "territory_rows": territory_rows,
        "territory_zones": territory_zones,
        "reading_lanes": reading_lanes,
        "ordered_bibliography_rows": ordered_bibliography_rows,
    }


def _reconcile_numeric_anchor_candidates_v3(
    *,
    anchor_candidates: Sequence[Dict[str, Any]],
    expected_indices: Sequence[int],
) -> Dict[str, Any]:
    normalized_expected = sorted(
        {
            int(index)
            for index in expected_indices
            if _to_int(index) is not None and int(index) > 0
        }
    )
    candidates_by_index: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in anchor_candidates:
        index = _to_int(candidate.get("index"))
        if index is None or index <= 0:
            continue
        candidates_by_index[index].append(dict(candidate))

    selected_detected: Dict[int, Dict[str, Any]] = {}
    duplicate_indices: List[int] = []
    reconciliation_actions: List[Dict[str, Any]] = []
    for index in sorted(candidates_by_index.keys()):
        ranked = sorted(
            candidates_by_index[index],
            key=lambda item: (
                -float(item.get("confidence") or 0.0),
                0 if str(item.get("strength") or "") == "strong" else 1,
                int(item.get("position") or 0),
            ),
        )
        best_candidate = dict(ranked[0])
        if index in normalized_expected:
            selected_detected[index] = best_candidate
        else:
            reconciliation_actions.append(
                {
                    "action": "ignore_unexpected_anchor",
                    "index": index,
                    "row_id": best_candidate.get("row_id"),
                    "reason": "index_not_present_in_expected_sequence",
                }
            )
        if len(ranked) > 1:
            duplicate_indices.append(index)
            for dropped in ranked[1:]:
                reconciliation_actions.append(
                    {
                        "action": "drop_duplicate_anchor",
                        "index": index,
                        "row_id": dropped.get("row_id"),
                        "confidence": dropped.get("confidence"),
                        "reason": "lower_ranked_duplicate_anchor_candidate",
                    }
                )

    selected_anchors = [
        selected_detected[index]
        for index in normalized_expected
        if index in selected_detected
    ]
    selected_anchors.sort(
        key=lambda item: (
            int(item.get("index") or 0),
            int(item.get("position") or 0),
        )
    )
    monotonic_anchors: List[Dict[str, Any]] = []
    last_position: Optional[int] = None
    for anchor in selected_anchors:
        position = _to_int(anchor.get("position"))
        if position is None:
            continue
        if last_position is not None and position <= last_position:
            if float(anchor.get("confidence") or 0.0) < 0.86:
                reconciliation_actions.append(
                    {
                        "action": "drop_non_monotonic_anchor",
                        "index": anchor.get("index"),
                        "row_id": anchor.get("row_id"),
                        "reason": "non_monotonic_position_and_low_confidence",
                    }
                )
                continue
            reconciliation_actions.append(
                {
                    "action": "keep_non_monotonic_anchor",
                    "index": anchor.get("index"),
                    "row_id": anchor.get("row_id"),
                    "reason": "non_monotonic_position_but_high_confidence",
                }
            )
        monotonic_anchors.append(anchor)
        last_position = position

    selected_index_set = {
        int(anchor.get("index"))
        for anchor in monotonic_anchors
        if _to_int(anchor.get("index")) not in (None, 0)
    }
    missing_indices = [
        index for index in normalized_expected if index not in selected_index_set
    ]
    inferred_anchors = [
        {
            "index": index,
            "confidence": 0.0,
            "strength": "inferred_missing",
            "reason": "expected_index_without_detected_anchor",
        }
        for index in missing_indices
    ]
    reconciliation_actions.extend(
        {
            "action": "mark_missing_anchor",
            "index": index,
            "reason": "expected_index_not_detected",
        }
        for index in missing_indices
    )
    selected_anchor_by_index = {
        int(anchor.get("index")): anchor
        for anchor in monotonic_anchors
        if _to_int(anchor.get("index")) not in (None, 0)
    }
    anchor_sequence: List[Dict[str, Any]] = []
    for index in normalized_expected:
        anchor = selected_anchor_by_index.get(index)
        if anchor is None:
            anchor_sequence.append(
                {
                    "index": index,
                    "status": "missing",
                    "page": None,
                    "position": None,
                    "row_id": None,
                    "anchor_row_id": None,
                    "body_start_row_id": None,
                    "body_start_position": None,
                    "style": None,
                    "anchor_style": None,
                    "anchor_type": None,
                    "layout_type": None,
                    "strength": "inferred_missing",
                    "confidence": 0.0,
                    "used_marker_only_anchor": False,
                    "anchor_to_body_link_reason": None,
                    "body_in_next_row": False,
                }
            )
            continue
        anchor_sequence.append(
            {
                "index": index,
                "status": "detected",
                "page": anchor.get("page"),
                "position": anchor.get("position"),
                "row_id": anchor.get("row_id"),
                "anchor_row_id": anchor.get("anchor_row_id") or anchor.get("row_id"),
                "body_start_row_id": anchor.get("body_start_row_id"),
                "body_start_position": anchor.get("body_start_position"),
                "style": anchor.get("style"),
                "anchor_style": anchor.get("anchor_style") or anchor.get("style"),
                "anchor_type": anchor.get("anchor_type"),
                "layout_type": anchor.get("layout_type"),
                "strength": anchor.get("strength"),
                "confidence": round(float(anchor.get("confidence") or 0.0), 3),
                "used_marker_only_anchor": bool(anchor.get("used_marker_only_anchor")),
                "anchor_to_body_link_reason": anchor.get("anchor_to_body_link_reason"),
                "body_in_next_row": bool(anchor.get("body_in_next_row")),
            }
        )
    return {
        "selected_anchors": monotonic_anchors,
        "anchor_sequence": anchor_sequence,
        "missing_indices": missing_indices,
        "duplicate_indices": sorted(
            {
                int(index)
                for index in duplicate_indices
                if _to_int(index) is not None and int(index) > 0
            }
        ),
        "inferred_anchors": inferred_anchors,
        "reconciliation_actions": reconciliation_actions,
    }


def _score_reference_row_hypotheses_v3(
    *,
    row: Dict[str, Any],
    previous_row: Dict[str, Any],
    current_rows: Sequence[Dict[str, Any]],
    current_index: int,
    competing_anchor: Optional[Dict[str, Any]],
    territory_row_ids: set[str],
) -> Dict[str, Any]:
    text = str(row.get("text") or "").strip()
    row_id = str(row.get("id") or "")
    same_score = 0.26
    next_score = 0.1
    outside_score = 0.08
    evidence: List[str] = []

    if row_id and row_id not in territory_row_ids:
        outside_score += 0.42
        evidence.append("outside_territory_row")
    if _row_is_section_transition_v2(text):
        outside_score += 0.52
        same_score -= 0.38
        evidence.append("section_transition")
    if _is_header_footer_row(row, {"repeated_text_keys": set()}):
        outside_score += 0.35
        same_score -= 0.2
        evidence.append("header_footer_noise")
    if _has_v2_bibliographic_body_signal(text):
        same_score += 0.24
        evidence.append("bibliographic_body")
    else:
        outside_score += 0.07
    if competing_anchor and int(competing_anchor.get("index") or 0) > 0:
        competing_strength = str(competing_anchor.get("strength") or "")
        next_score += 0.82 if competing_strength == "strong" else 0.7
        evidence.append(f"competing_anchor:{int(competing_anchor.get('index') or 0)}")
    foreign_anchors = [
        value
        for value in _extract_inline_anchor_numbers(text)
        if int(value) != int(current_index or 0)
    ]
    if foreign_anchors:
        next_score += 0.52
        evidence.append(f"foreign_inline_anchor:{foreign_anchors[0]}")
    leading_anchor = _match_reference_anchor_at_line_start(text, include_rejected=True)
    if (
        leading_anchor
        and leading_anchor.get("accepted")
        and int(leading_anchor.get("index") or 0) != int(current_index or 0)
    ):
        next_score += 0.78
        evidence.append("leading_foreign_anchor")

    previous_page = _to_int(previous_row.get("page"))
    current_page = _to_int(row.get("page"))
    previous_y1 = _to_float(previous_row.get("y1"))
    current_y0 = _to_float(row.get("y0"))
    if previous_page is not None and current_page is not None:
        if current_page == previous_page:
            if previous_y1 is not None and current_y0 is not None:
                gap = float(current_y0) - float(previous_y1)
                if gap <= 0.05:
                    same_score += 0.18
                    evidence.append("tight_vertical_gap")
                elif gap <= 0.12:
                    same_score += 0.1
                elif gap > 0.2:
                    outside_score += 0.22
                    evidence.append("large_vertical_gap")
            current_x0 = _to_float(row.get("x0"))
            previous_x0 = _to_float(previous_row.get("x0"))
            if current_x0 is not None and previous_x0 is not None:
                shift = abs(float(current_x0) - float(previous_x0))
                if shift > 0.2:
                    outside_score += 0.1
                elif shift <= 0.1:
                    same_score += 0.06
        elif current_page - previous_page == 1:
            needs_continuation = _reference_needs_continuation_v2(current_rows)
            if (
                current_y0 is not None
                and float(current_y0) <= 0.25
                and needs_continuation
            ):
                same_score += 0.24
                evidence.append("cross_page_continuation")
            elif current_y0 is not None and float(current_y0) <= 0.35:
                same_score += 0.12
            else:
                outside_score += 0.15
        else:
            outside_score += 0.3
            evidence.append("page_jump")

    if row.get("reading_lane_id") == previous_row.get("reading_lane_id"):
        same_score += 0.08
    else:
        next_score += 0.05

    return {
        "same_reference": round(same_score, 3),
        "next_reference": round(next_score, 3),
        "outside_bibliography": round(outside_score, 3),
        "evidence": evidence,
    }


def _grow_reference_rows_from_anchor_v3(
    *,
    ordered_rows: Sequence[Dict[str, Any]],
    current_anchor: Dict[str, Any],
    next_anchor: Optional[Dict[str, Any]],
    anchor_candidates_by_position: Dict[int, Dict[str, Any]],
    territory_row_ids: set[str],
    artifact_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    start = _to_int(current_anchor.get("position"))
    if start is None or start < 0 or start >= len(ordered_rows):
        return {
            "rows": [],
            "row_decisions": [],
            "rows_discarded": [],
            "cut_reasons": ["invalid_anchor_position"],
            "closure_reason": "invalid_anchor_position",
            "boundary_start_reason": "invalid_anchor_position",
            "boundary_end_reason": "invalid_anchor_position",
            "continuation_between_pages": False,
            "has_nested_anchor": False,
            "nested_anchor_indices": [],
            "issues": ["invalid_anchor_position"],
            "anchor_row_id": None,
            "body_start_row_id": None,
            "body_start_position": None,
            "anchor_type": str(current_anchor.get("anchor_type") or "unknown"),
            "layout_type": str(current_anchor.get("layout_type") or "unknown"),
            "used_marker_only_anchor": bool(
                current_anchor.get("used_marker_only_anchor")
            ),
            "anchor_to_body_link_reason": current_anchor.get(
                "anchor_to_body_link_reason"
            ),
            "body_start": None,
            "body_end": None,
        }

    artifact_info = (
        artifact_info
        if isinstance(artifact_info, dict)
        else {"repeated_text_keys": set()}
    )
    anchor_row = ordered_rows[start]
    anchor_row_id = str(
        (anchor_row or {}).get("id") or current_anchor.get("anchor_row_id") or ""
    )
    anchor_type = str(current_anchor.get("anchor_type") or "inline")
    layout_type = str(current_anchor.get("layout_type") or "inline_anchor_same_row")
    used_marker_only_anchor = bool(
        current_anchor.get("used_marker_only_anchor")
        or anchor_type == "marker_only"
        or layout_type == "marker_only_left_gutter"
    )
    anchor_to_body_link_reason = (
        str(current_anchor.get("anchor_to_body_link_reason") or "").strip() or None
    )
    body_start_position = _to_int(current_anchor.get("body_start_position"))
    if body_start_position is None or body_start_position < start:
        body_start_position = start
    if body_start_position >= len(ordered_rows):
        body_start_position = start
    body_start_row = ordered_rows[body_start_position]
    body_start_row_id = str((body_start_row or {}).get("id") or anchor_row_id)
    body_scan_start = start + 1
    boundary_start_reason = "anchor_detected"
    if body_start_position > start:
        body_scan_start = body_start_position
        boundary_start_reason = (
            "marker_only_anchor_linked_body_start"
            if used_marker_only_anchor
            else "anchor_linked_body_start"
        )
    elif used_marker_only_anchor:
        boundary_start_reason = "marker_only_anchor_without_body_link"

    selected_rows: List[Dict[str, Any]] = [anchor_row]
    row_decisions: List[Dict[str, Any]] = [
        {
            "row_id": anchor_row_id,
            "page": anchor_row.get("page"),
            "included": True,
            "reason": (
                "anchor_row_marker_only" if used_marker_only_anchor else "anchor_row"
            ),
            "same_reference_score": 1.0,
            "next_reference_score": 0.0,
            "outside_bibliography_score": 0.0,
            "evidence": (
                ["anchor_row", f"layout_type:{layout_type}"]
                if used_marker_only_anchor
                else ["anchor_row"]
            ),
        }
    ]
    rows_discarded: List[Dict[str, Any]] = []
    cut_reasons: List[str] = []
    continuation_between_pages = False
    expected_index = int(current_anchor.get("index") or 0)
    nested_anchor_indices: List[int] = []
    next_anchor_position: Optional[int] = None
    next_anchor_index: Optional[int] = None
    next_anchor_body_start_position: Optional[int] = None
    next_anchor_type = str((next_anchor or {}).get("anchor_type") or "")
    next_anchor_layout_type = str((next_anchor or {}).get("layout_type") or "")
    if isinstance(next_anchor, dict):
        next_anchor_position = _to_int(next_anchor.get("position"))
        next_anchor_index = _to_int(next_anchor.get("index"))
        next_anchor_body_start_position = _to_int(
            next_anchor.get("body_start_position")
        )
    has_resolved_next_anchor = bool(
        next_anchor_position is not None and int(next_anchor_position) > start
    )
    scan_end = (
        int(next_anchor_position) if has_resolved_next_anchor else len(ordered_rows)
    )
    closure_reason = (
        "next_anchor_boundary_n_plus_1"
        if has_resolved_next_anchor
        else "reading_flow_exhausted_without_next_anchor"
    )
    if (
        has_resolved_next_anchor
        and next_anchor_body_start_position is not None
        and int(next_anchor_body_start_position) > int(next_anchor_position)
    ):
        scan_end = min(int(next_anchor_body_start_position), len(ordered_rows))
        closure_reason = "next_anchor_body_start_boundary_n_plus_1"
    boundary_end_reason = closure_reason

    if body_scan_start > start + 1:
        for skipped_position in range(start + 1, min(body_scan_start, scan_end)):
            skipped_row = ordered_rows[skipped_position]
            skipped_text = str(skipped_row.get("text") or "").strip()
            row_decisions.append(
                {
                    "row_id": str(skipped_row.get("id") or ""),
                    "page": skipped_row.get("page"),
                    "included": False,
                    "reason": "before_linked_body_start_skipped",
                    "same_reference_score": None,
                    "next_reference_score": None,
                    "outside_bibliography_score": None,
                    "evidence": ["waiting_for_linked_body_start"],
                }
            )
            if skipped_text:
                rows_discarded.append(
                    {
                        "row_id": str(skipped_row.get("id") or ""),
                        "page": skipped_row.get("page"),
                        "text": _short_debug_text(skipped_text),
                        "reason": "before_linked_body_start_skipped",
                    }
                )

    loop_start = max(start + 1, body_scan_start)
    for position in range(loop_start, scan_end):
        row = ordered_rows[position]
        text = str(row.get("text") or "").strip()
        if not text:
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "included": False,
                    "reason": "empty_text_skipped",
                    "same_reference_score": None,
                    "next_reference_score": None,
                    "outside_bibliography_score": None,
                    "evidence": [],
                }
            )
            continue

        row_id = str(row.get("id") or "")
        competing_anchor = None
        candidate = anchor_candidates_by_position.get(position)
        if candidate and int(candidate.get("index") or 0) != expected_index:
            competing_anchor = candidate
            candidate_index = int(candidate.get("index") or 0)
            is_expected_next_marker_row = bool(
                has_resolved_next_anchor
                and next_anchor_position is not None
                and int(position) == int(next_anchor_position)
                and next_anchor_index is not None
                and int(candidate_index) == int(next_anchor_index)
                and next_anchor_body_start_position is not None
                and int(next_anchor_body_start_position) > int(next_anchor_position)
                and (
                    str(candidate.get("anchor_type") or "") == "marker_only"
                    or str(candidate.get("layout_type") or "")
                    == "marker_only_left_gutter"
                    or next_anchor_type == "marker_only"
                    or next_anchor_layout_type == "marker_only_left_gutter"
                )
            )
            if is_expected_next_marker_row:
                rows_discarded.append(
                    {
                        "row_id": row_id,
                        "page": row.get("page"),
                        "text": _short_debug_text(text),
                        "reason": "next_anchor_marker_row_skipped_until_body_start",
                    }
                )
                row_decisions.append(
                    {
                        "row_id": row_id,
                        "page": row.get("page"),
                        "included": False,
                        "reason": "next_anchor_marker_row_skipped_until_body_start",
                        "same_reference_score": None,
                        "next_reference_score": None,
                        "outside_bibliography_score": None,
                        "evidence": ["next_anchor_marker_only_layout_boundary"],
                    }
                )
                continue
            nested_anchor_indices.append(candidate_index)

        previous_row = selected_rows[-1]
        scores = None
        same_score = None
        next_score = None
        outside_score = None
        stop_reason = None
        is_section_transition = bool(
            _row_is_section_transition_v2(text)
            and not _has_v2_bibliographic_body_signal(text)
        )
        has_bibliographic_body = bool(_has_v2_bibliographic_body_signal(text))
        if competing_anchor is not None:
            if has_resolved_next_anchor:
                stop_reason = "unexpected_anchor_before_next_anchor"
            else:
                stop_reason = "next_anchor_detected_without_resolved_n_plus_1"
        elif is_section_transition:
            stop_reason = (
                "section_transition_before_next_anchor"
                if has_resolved_next_anchor
                else "section_transition_after_anchor_without_next"
            )
        elif not has_resolved_next_anchor:
            scores = _score_reference_row_hypotheses_v3(
                row=row,
                previous_row=previous_row,
                current_rows=selected_rows,
                current_index=expected_index,
                competing_anchor=competing_anchor,
                territory_row_ids=territory_row_ids,
            )
            same_score = float(scores.get("same_reference") or 0.0)
            next_score = float(scores.get("next_reference") or 0.0)
            outside_score = float(scores.get("outside_bibliography") or 0.0)
            if (
                outside_score >= same_score + 0.26
                and outside_score >= next_score
                and not has_bibliographic_body
            ):
                stop_reason = "outside_bibliography_after_anchor_without_next"
            else:
                previous_page = _to_int(previous_row.get("page"))
                current_page = _to_int(row.get("page"))
                if (
                    previous_page is not None
                    and current_page is not None
                    and current_page - previous_page > 1
                ):
                    stop_reason = "page_jump_after_anchor_without_next"
                elif (
                    previous_page is not None
                    and current_page is not None
                    and current_page - previous_page == 1
                    and _to_float(row.get("y0")) is not None
                    and float(_to_float(row.get("y0")) or 0.0) > 0.58
                    and not _reference_needs_continuation_v2(selected_rows)
                ):
                    stop_reason = "late_page_continuation_without_next_anchor"

        if stop_reason is not None:
            closure_reason = stop_reason
            boundary_end_reason = stop_reason
            cut_reasons.append(boundary_end_reason)
            rows_discarded.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "text": _short_debug_text(text),
                    "reason": stop_reason,
                }
            )
            row_decisions.append(
                {
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "included": False,
                    "reason": stop_reason,
                    "same_reference_score": (
                        round(float(same_score), 3)
                        if isinstance(same_score, (int, float))
                        else None
                    ),
                    "next_reference_score": (
                        round(float(next_score), 3)
                        if isinstance(next_score, (int, float))
                        else None
                    ),
                    "outside_bibliography_score": (
                        round(float(outside_score), 3)
                        if isinstance(outside_score, (int, float))
                        else None
                    ),
                    "evidence": (
                        (scores.get("evidence") or [])
                        if isinstance(scores, dict)
                        else []
                    ),
                }
            )
            break

        if (
            _is_header_footer_row(row, artifact_info)
            and not has_bibliographic_body
            and competing_anchor is None
        ):
            rows_discarded.append(
                {
                    "row_id": row_id,
                    "page": row.get("page"),
                    "text": _short_debug_text(text),
                    "reason": "header_footer_noise_skipped",
                }
            )
            row_decisions.append(
                {
                    "row_id": row_id,
                    "page": row.get("page"),
                    "included": False,
                    "reason": "header_footer_noise_skipped",
                    "same_reference_score": (
                        round(float(same_score), 3)
                        if isinstance(same_score, (int, float))
                        else None
                    ),
                    "next_reference_score": (
                        round(float(next_score), 3)
                        if isinstance(next_score, (int, float))
                        else None
                    ),
                    "outside_bibliography_score": (
                        round(float(outside_score), 3)
                        if isinstance(outside_score, (int, float))
                        else None
                    ),
                    "evidence": (
                        (scores.get("evidence") or [])
                        if isinstance(scores, dict)
                        else []
                    ),
                }
            )
            continue

        if (
            has_resolved_next_anchor
            and row_id
            and row_id not in territory_row_ids
            and not has_bibliographic_body
        ):
            rows_discarded.append(
                {
                    "row_id": row_id,
                    "page": row.get("page"),
                    "text": _short_debug_text(text),
                    "reason": "outside_territory_skipped_before_next_anchor",
                }
            )
            row_decisions.append(
                {
                    "row_id": row_id,
                    "page": row.get("page"),
                    "included": False,
                    "reason": "outside_territory_skipped_before_next_anchor",
                    "same_reference_score": None,
                    "next_reference_score": None,
                    "outside_bibliography_score": None,
                    "evidence": ["outside_territory_row"],
                }
            )
            continue

        if _to_int(previous_row.get("page")) != _to_int(row.get("page")):
            continuation_between_pages = True
        selected_rows.append(row)
        row_decisions.append(
            {
                "row_id": str(row.get("id") or ""),
                "page": row.get("page"),
                "included": True,
                "reason": (
                    "page_continuation"
                    if _to_int(previous_row.get("page")) != _to_int(row.get("page"))
                    else "same_reference_growth"
                ),
                "same_reference_score": (
                    round(float(same_score), 3)
                    if isinstance(same_score, (int, float))
                    else None
                ),
                "next_reference_score": (
                    round(float(next_score), 3)
                    if isinstance(next_score, (int, float))
                    else None
                ),
                "outside_bibliography_score": (
                    round(float(outside_score), 3)
                    if isinstance(outside_score, (int, float))
                    else None
                ),
                "evidence": (
                    (scores.get("evidence") or []) if isinstance(scores, dict) else []
                ),
            }
        )
        if len(selected_rows) >= 80:
            closure_reason = "row_limit"
            boundary_end_reason = "row_limit"
            cut_reasons.append("row_limit")
            break

    has_nested_anchor = bool(
        int(index) > 0 for index in nested_anchor_indices if _to_int(index) is not None
    )
    issues: List[str] = []
    if continuation_between_pages:
        issues.append("page_continuation")
    if len(selected_rows) < 2:
        issues.append("suspiciously_short_reference")
    if len(selected_rows) >= 24:
        issues.append("suspiciously_long_reference")
    body_start = body_start_row_id if body_start_row_id else None
    body_end = str((selected_rows[-1] or {}).get("id") or "") if selected_rows else None
    return {
        "rows": selected_rows,
        "row_decisions": row_decisions,
        "rows_discarded": rows_discarded,
        "cut_reasons": cut_reasons,
        "closure_reason": closure_reason,
        "boundary_start_reason": boundary_start_reason,
        "boundary_end_reason": boundary_end_reason,
        "continuation_between_pages": continuation_between_pages,
        "has_nested_anchor": has_nested_anchor,
        "nested_anchor_indices": sorted(
            {
                int(index)
                for index in nested_anchor_indices
                if _to_int(index) is not None and int(index) > 0
            }
        ),
        "issues": issues,
        "anchor_row_id": anchor_row_id or None,
        "body_start_row_id": body_start_row_id or None,
        "body_start_position": body_start_position,
        "anchor_type": anchor_type,
        "layout_type": layout_type,
        "used_marker_only_anchor": used_marker_only_anchor,
        "anchor_to_body_link_reason": anchor_to_body_link_reason,
        "body_start": body_start,
        "body_end": body_end,
    }


def _build_experimental_reference_entries_v3(
    *,
    references: Sequence[Dict[str, Any]],
    parsed_references: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    def _fallback_entry(
        *,
        index: Optional[int],
        text: str,
        doi: Optional[str],
        reason: str,
        cut_reasons: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        if index is None:
            entry_id = f"reference-entry-v3-unlabeled-{len(entries) + 1}"
            ref_id = f"ref-v3-unlabeled-{len(entries) + 1}"
        else:
            entry_id = f"reference-entry-v3-ref-{index}"
            ref_id = f"ref-{index}"
        return {
            "id": entry_id,
            "ref_id": ref_id,
            "index": index,
            "text": text,
            "page": None,
            "box": None,
            "rows": [],
            "row_ids": [],
            "row_boxes": [],
            "page_boxes": [],
            "union_box": None,
            "pages_involved": [],
            "anchor_row_id": None,
            "body_start_row_id": None,
            "layout_type": None,
            "anchor_type": None,
            "used_marker_only_anchor": False,
            "anchor_to_body_link_reason": None,
            "continuation_between_pages": False,
            "boundary_start_reason": None,
            "boundary_end_reason": reason,
            "geometry_source": "raw_reference_fallback",
            "doi": doi,
            "structure_source": "raw_reference_fallback",
            "local_row_count": 0,
            "local_anchor_detected": False,
            "reference_validation": {
                "match_score": 0.0,
                "mixed_reference_score": 0.0,
                "has_nested_anchor": False,
                "accepted": False,
                "reason": reason,
            },
            "validation_intermediate": {
                "match_score": 0.0,
                "mixed_reference_score": 0.0,
                "has_nested_anchor": False,
                "accepted": False,
                "reason": reason,
            },
            "scores": {
                "accepted": False,
                "classification": "fallback_needed",
                "reason": reason,
                "final_score": 0.0,
            },
            "final_decision": {
                "accepted": False,
                "classification": "fallback_needed",
                "reason": reason,
                "final_score": 0.0,
            },
            "crossref_match": {
                "score": 0.0,
                "doi_match_score": 0.0,
                "match": None,
            },
            "token_reconstruction": {"final_text": text},
            "anomalies": {
                "cut_reasons": list(cut_reasons or []),
                "nested_anchor_indices": [],
            },
        }

    entries: List[Dict[str, Any]] = []
    indexed_references: Dict[int, Dict[str, Any]] = {}
    unindexed_references: List[Dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        index = _entry_index(ref)
        if index is None:
            unindexed_references.append(ref)
            continue
        if index not in indexed_references:
            indexed_references[index] = ref

    parsed_indices = sorted(
        {
            int(index)
            for index in parsed_references.keys()
            if _to_int(index) not in (None, 0)
        }
    )
    ordered_indices = sorted(set(parsed_indices) | set(indexed_references.keys()))

    for index in ordered_indices:
        seed_ref = indexed_references.get(index)
        if seed_ref is None and unindexed_references:
            seed_ref = unindexed_references.pop(0)
        parsed = parsed_references.get(index)
        if parsed is None:
            fallback_text = str(
                (seed_ref or {}).get("raw") or (seed_ref or {}).get("text") or ""
            )
            entries.append(
                _fallback_entry(
                    index=index,
                    text=fallback_text,
                    doi=_normalize_doi((seed_ref or {}).get("doi")) or None,
                    reason="fallback_without_rows_structure",
                    cut_reasons=["missing_anchor_after_v3_reconciliation"],
                )
            )
            continue
        entry = dict(parsed)
        entry["index"] = index
        if not _normalize_doi(entry.get("doi")) and _normalize_doi(
            (seed_ref or {}).get("doi")
        ):
            entry["doi"] = _normalize_doi((seed_ref or {}).get("doi"))
        entry["id"] = f"reference-entry-v3-ref-{index}"
        entry["ref_id"] = f"ref-{index}"
        entries.append(entry)

    for ref in unindexed_references:
        text = str(ref.get("raw") or ref.get("text") or "")
        entries.append(
            _fallback_entry(
                index=None,
                text=text,
                doi=_normalize_doi(ref.get("doi")) or None,
                reason="fallback_without_rows_structure",
            )
        )
    return entries


def _build_numeric_pipeline_metrics_v3(
    *,
    expected_indices: Sequence[int],
    reference_entries: Sequence[Dict[str, Any]],
    detected_anchor_indices: Sequence[int],
    duplicate_indices: Sequence[int],
) -> Dict[str, Any]:
    expected_total = len(expected_indices)
    serialized_indices = sorted(
        {
            int(entry.get("index"))
            for entry in reference_entries
            if _to_int(entry.get("index")) not in (None, 0)
            and "fallback" not in str(entry.get("structure_source") or "")
        }
    )
    references_total = len(reference_entries)
    accepted_total = sum(
        1
        for entry in reference_entries
        if bool((entry.get("final_decision") or {}).get("accepted"))
    )
    fallback_total = sum(
        1
        for entry in reference_entries
        if "fallback" in str(entry.get("structure_source") or "")
    )
    continuation_total = sum(
        1
        for entry in reference_entries
        if bool(entry.get("continuation_between_pages"))
    )
    contamination_total = sum(
        1
        for entry in reference_entries
        if bool((entry.get("reference_validation") or {}).get("has_nested_anchor"))
    )
    marker_only_anchor_total = sum(
        1
        for entry in reference_entries
        if str(entry.get("anchor_type") or "") == "marker_only"
    )
    marker_only_layout_total = sum(
        1
        for entry in reference_entries
        if str(entry.get("layout_type") or "") == "marker_only_left_gutter"
    )
    marker_only_linked_total = sum(
        1
        for entry in reference_entries
        if bool(entry.get("used_marker_only_anchor"))
        and bool(str(entry.get("body_start_row_id") or "").strip())
    )
    rows_per_reference = [
        len(entry.get("rows") or [])
        for entry in reference_entries
        if _to_int(entry.get("index")) not in (None, 0)
    ]
    truncated_total = sum(
        1
        for entry in reference_entries
        if str(entry.get("text") or "").rstrip().endswith("-")
        or len(str(entry.get("text") or "").strip()) < 40
    )
    geometry_complete_total = sum(
        1
        for entry in reference_entries
        if (
            _to_int(entry.get("index")) not in (None, 0)
            and _coerce_geometry_box_v3(entry.get("union_box") or entry.get("box"))
            is not None
            and len(entry.get("page_boxes") or []) > 0
        )
    )
    missing_indices = [
        int(index)
        for index in expected_indices
        if int(index) not in set(serialized_indices)
    ]
    coverage_ratio = (
        round(len(serialized_indices) / float(expected_total), 3)
        if expected_total > 0
        else 0.0
    )
    return {
        "references_total": references_total,
        "expected_indices": [int(index) for index in expected_indices],
        "serialized_indices": serialized_indices,
        "detected_anchor_indices": sorted(
            {
                int(index)
                for index in detected_anchor_indices
                if _to_int(index) not in (None, 0)
            }
        ),
        "missing_indices": missing_indices,
        "duplicate_indices": sorted(
            {
                int(index)
                for index in duplicate_indices
                if _to_int(index) not in (None, 0)
            }
        ),
        "coverage_ratio": coverage_ratio,
        "pct_accepted": (
            round((accepted_total / float(references_total)) * 100.0, 2)
            if references_total
            else 0.0
        ),
        "fallback_total": fallback_total,
        "references_truncated_total": truncated_total,
        "continuation_between_pages_total": continuation_total,
        "contamination_total": contamination_total,
        "marker_only_anchor_total": marker_only_anchor_total,
        "marker_only_layout_total": marker_only_layout_total,
        "marker_only_linked_total": marker_only_linked_total,
        "geometry_complete_total": geometry_complete_total,
        "rows_per_reference_stats": {
            "min": min(rows_per_reference) if rows_per_reference else 0,
            "max": max(rows_per_reference) if rows_per_reference else 0,
            "avg": (
                round(
                    sum(rows_per_reference) / float(len(rows_per_reference)),
                    3,
                )
                if rows_per_reference
                else 0.0
            ),
        },
    }


def _build_numeric_reference_comparison_v3(
    *,
    current_entries: Sequence[Dict[str, Any]],
    experimental_entries: Sequence[Dict[str, Any]],
    current_metrics: Dict[str, Any],
    experimental_metrics: Dict[str, Any],
) -> Dict[str, Any]:
    def _entry_uses_fallback(entry: Dict[str, Any]) -> bool:
        return "fallback" in str(entry.get("structure_source") or "")

    def _entry_has_continuation(entry: Dict[str, Any]) -> bool:
        return bool(entry.get("continuation_between_pages"))

    def _entry_is_truncated(entry: Dict[str, Any]) -> bool:
        text = str(entry.get("text") or "").strip()
        return bool(text.endswith("-") or len(text) < 40)

    def _entry_has_geometry(entry: Dict[str, Any]) -> bool:
        box = _coerce_geometry_box_v3(entry.get("union_box") or entry.get("box"))
        page_boxes = entry.get("page_boxes") or []
        return bool(box is not None and len(page_boxes) > 0)

    current_by_index = {
        int(entry.get("index")): entry
        for entry in current_entries
        if _to_int(entry.get("index")) not in (None, 0)
    }
    experimental_by_index = {
        int(entry.get("index")): entry
        for entry in experimental_entries
        if _to_int(entry.get("index")) not in (None, 0)
    }
    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []
    all_indices = sorted(
        set(current_by_index.keys()) | set(experimental_by_index.keys())
    )
    for index in all_indices:
        current_entry = current_by_index.get(index) or {}
        experimental_entry = experimental_by_index.get(index) or {}
        current_decision = (
            current_entry.get("final_decision")
            if isinstance(current_entry.get("final_decision"), dict)
            else {}
        )
        experimental_decision = (
            experimental_entry.get("final_decision")
            if isinstance(experimental_entry.get("final_decision"), dict)
            else {}
        )
        current_rows = len(current_entry.get("rows") or [])
        experimental_rows = len(experimental_entry.get("rows") or [])
        if bool(current_decision.get("accepted")) and not bool(
            experimental_decision.get("accepted")
        ):
            regressions.append(
                {
                    "index": index,
                    "type": "accepted_reference_lost",
                    "current_reason": current_decision.get("reason"),
                    "experimental_reason": experimental_decision.get("reason"),
                }
            )
        if (not _entry_uses_fallback(current_entry)) and _entry_uses_fallback(
            experimental_entry
        ):
            regressions.append({"index": index, "type": "new_raw_fallback"})
        if _entry_has_continuation(current_entry) and not _entry_has_continuation(
            experimental_entry
        ):
            regressions.append({"index": index, "type": "page_continuation_lost"})
        if _entry_has_geometry(current_entry) and not _entry_has_geometry(
            experimental_entry
        ):
            regressions.append({"index": index, "type": "geometry_lost"})
        if not bool(
            (current_entry.get("reference_validation") or {}).get("has_nested_anchor")
        ) and bool(
            (experimental_entry.get("reference_validation") or {}).get(
                "has_nested_anchor"
            )
        ):
            regressions.append({"index": index, "type": "new_reference_contamination"})
        if current_rows >= 4 and experimental_rows <= max(1, current_rows // 2):
            regressions.append({"index": index, "type": "rows_sharply_reduced"})
        if _entry_is_truncated(experimental_entry) and not _entry_is_truncated(
            current_entry
        ):
            regressions.append({"index": index, "type": "new_truncation"})

        if not bool(current_decision.get("accepted")) and bool(
            experimental_decision.get("accepted")
        ):
            improvements.append(
                {"index": index, "type": "accepted_reference_recovered"}
            )
        if _entry_uses_fallback(current_entry) and not _entry_uses_fallback(
            experimental_entry
        ):
            improvements.append({"index": index, "type": "fallback_removed"})
        if not _entry_has_continuation(current_entry) and _entry_has_continuation(
            experimental_entry
        ):
            improvements.append({"index": index, "type": "page_continuation_recovered"})
        if not _entry_has_geometry(current_entry) and _entry_has_geometry(
            experimental_entry
        ):
            improvements.append({"index": index, "type": "geometry_recovered"})
        if _entry_is_truncated(current_entry) and not _entry_is_truncated(
            experimental_entry
        ):
            improvements.append({"index": index, "type": "truncation_fixed"})
        if bool(
            (current_entry.get("reference_validation") or {}).get("has_nested_anchor")
        ) and not bool(
            (experimental_entry.get("reference_validation") or {}).get(
                "has_nested_anchor"
            )
        ):
            improvements.append({"index": index, "type": "contamination_removed"})

    metric_deltas: Dict[str, Any] = {}
    for metric_name in (
        "coverage_ratio",
        "pct_accepted",
        "fallback_total",
        "references_truncated_total",
        "continuation_between_pages_total",
        "contamination_total",
        "geometry_complete_total",
    ):
        current_value = current_metrics.get(metric_name)
        experimental_value = experimental_metrics.get(metric_name)
        if isinstance(current_value, (int, float)) and isinstance(
            experimental_value,
            (int, float),
        ):
            metric_deltas[metric_name] = round(
                float(experimental_value) - float(current_value),
                3,
            )

    status = "neutral"
    if regressions:
        status = "regression_detected"
    elif improvements:
        status = "improved_without_regression"
    return {
        "status": status,
        "promotion_ready": bool(improvements) and not regressions,
        "regressions": regressions[:120],
        "improvements": improvements[:120],
        "metric_deltas": metric_deltas,
        "regression_total": len(regressions),
        "improvement_total": len(improvements),
    }


def _run_numeric_reference_pipeline_v3(
    *,
    references: Sequence[Dict[str, Any]],
    metadata_by_index: Dict[int, Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
    current_reference_entries: Sequence[Dict[str, Any]],
    current_numeric_metrics: Dict[str, Any],
    crossref_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    expected_indices = sorted(
        {
            int(index)
            for index in metadata_by_index.keys()
            if isinstance(index, int) and int(index) > 0
        }
    )
    if not expected_indices:
        return None

    territory_phase = _build_numeric_bibliography_territory_v3(
        rows=rows,
        sections=sections,
        bibliography_items=bibliography_items,
    )
    ordered_rows = territory_phase.get("ordered_bibliography_rows") or []
    anchor_detection_debug: Dict[str, Any] = {}
    anchor_candidates = _detect_numeric_anchor_candidates_v3(
        ordered_rows,
        debug_collector=anchor_detection_debug,
    )
    anchor_reconciliation = _reconcile_numeric_anchor_candidates_v3(
        anchor_candidates=anchor_candidates,
        expected_indices=expected_indices,
    )
    selected_anchors = anchor_reconciliation.get("selected_anchors") or []
    anchor_candidates_by_position: Dict[int, Dict[str, Any]] = {}
    for candidate in anchor_candidates:
        position = _to_int(candidate.get("position"))
        if position is None:
            continue
        existing = anchor_candidates_by_position.get(position)
        if existing is None or float(candidate.get("confidence") or 0.0) > float(
            existing.get("confidence") or 0.0
        ):
            anchor_candidates_by_position[position] = candidate

    territory_row_ids = {
        str(row.get("id") or "")
        for row in ordered_rows
        if str(row.get("id") or "").strip()
    }
    artifact_info = _build_repeating_page_artifacts(
        territory_phase.get("rows_with_columns") or ordered_rows
    )
    tokens_by_page = _index_tokens_by_page(token_items or [])
    parsed: Dict[int, Dict[str, Any]] = {}
    reference_debug: List[Dict[str, Any]] = []

    for anchor_idx, anchor in enumerate(selected_anchors):
        index = int(anchor.get("index") or 0)
        next_anchor = (
            selected_anchors[anchor_idx + 1]
            if anchor_idx + 1 < len(selected_anchors)
            else None
        )
        growth = _grow_reference_rows_from_anchor_v3(
            ordered_rows=ordered_rows,
            current_anchor=anchor,
            next_anchor=next_anchor,
            anchor_candidates_by_position=anchor_candidates_by_position,
            territory_row_ids=territory_row_ids,
            artifact_info=artifact_info,
        )
        block_rows = growth.get("rows") or []
        if not block_rows:
            reference_debug.append(
                {
                    "index": index,
                    "anchor_detected": {
                        "index": index,
                        "style": anchor.get("style"),
                        "anchor_style": anchor.get("anchor_style")
                        or anchor.get("style"),
                        "anchor_type": anchor.get("anchor_type"),
                        "layout_type": anchor.get("layout_type"),
                        "confidence": round(float(anchor.get("confidence") or 0.0), 3),
                        "strength": anchor.get("strength"),
                        "page": anchor.get("page"),
                        "row_id": anchor.get("row_id"),
                        "anchor_row_id": anchor.get("anchor_row_id")
                        or anchor.get("row_id"),
                        "body_start_row_id": anchor.get("body_start_row_id"),
                        "body_start_position": anchor.get("body_start_position"),
                        "body_in_next_row": bool(anchor.get("body_in_next_row")),
                        "anchor_to_body_link_reason": anchor.get(
                            "anchor_to_body_link_reason"
                        ),
                        "used_marker_only_anchor": bool(
                            anchor.get("used_marker_only_anchor")
                        ),
                    },
                    "used_marker_only_anchor": bool(
                        anchor.get("used_marker_only_anchor")
                    ),
                    "anchor_row_id": anchor.get("anchor_row_id")
                    or anchor.get("row_id"),
                    "body_start_row_id": anchor.get("body_start_row_id"),
                    "layout_type": anchor.get("layout_type"),
                    "anchor_to_body_link_reason": anchor.get(
                        "anchor_to_body_link_reason"
                    ),
                    "body_start": growth.get("body_start"),
                    "body_end": growth.get("body_end"),
                    "rows_included": [],
                    "rows_discarded": growth.get("rows_discarded") or [],
                    "continuation_between_pages": False,
                    "closure_reason": growth.get("closure_reason"),
                    "boundary_start_reason": growth.get("boundary_start_reason"),
                    "boundary_end_reason": growth.get("boundary_end_reason"),
                    "issues": list(growth.get("issues") or [])
                    + ["empty_reference_after_growth"],
                }
            )
            continue

        token_reconstruction = _reconstruct_reference_text_from_rows_and_tokens(
            block_rows,
            tokens_by_page,
        )
        reference_doi_seed = (
            _extract_doi(token_reconstruction.get("raw_text"))
            or _extract_doi(token_reconstruction.get("hybrid_text"))
            or _extract_doi(token_reconstruction.get("token_text"))
            or ""
        )
        selected_candidate = _select_reference_text_candidate(
            candidates=token_reconstruction.get("candidates") or [],
            reference_doi=reference_doi_seed,
            crossref_context=crossref_context,
        )
        selected_candidate_source = (
            str(
                selected_candidate.get("source")
                or token_reconstruction.get("selected_candidate_source")
                or "rows_raw"
            ).strip()
            or "rows_raw"
        )
        token_reconstruction["selected_candidate_source"] = selected_candidate_source
        token_reconstruction["candidate_scores"] = (
            selected_candidate.get("candidate_scores") or []
        )
        token_reconstruction["order_similarity_to_rows"] = selected_candidate.get(
            "order_similarity_to_rows"
        )
        token_reconstruction["order_guard_reasons"] = (
            selected_candidate.get("order_guard_reasons") or []
        )
        token_reconstruction["backbone_source"] = selected_candidate.get(
            "backbone_source"
        ) or token_reconstruction.get("backbone_source")
        token_reconstruction["backbone_text"] = str(
            selected_candidate.get("backbone_text")
            or token_reconstruction.get("backbone_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        token_reconstruction["final_text"] = str(
            selected_candidate.get("text")
            or token_reconstruction.get("hybrid_text")
            or token_reconstruction.get("raw_text")
            or ""
        ).strip()
        block_text = str(token_reconstruction.get("final_text") or "").strip()
        validation = _build_reference_validation(
            text=block_text,
            expected_index=index,
            metadata=metadata_by_index.get(index),
            metadata_by_index=metadata_by_index,
        )
        crossref_match = _match_reference_against_crossref(
            reference_text=block_text,
            reference_doi=_extract_doi(block_text),
            crossref_context=crossref_context,
        )
        final_decision = _build_reference_decision_v2(
            expected_index=index,
            rows=block_rows,
            reference_text=block_text,
            block_diagnostics=growth,
            token_reconstruction=token_reconstruction,
            crossref_match=crossref_match,
            territory_zones=territory_phase.get("territory_zones") or [],
            validation=validation,
        )
        validation = _sync_reference_validation_with_final_decision(
            validation,
            final_decision,
        )
        geometry_payload = _build_reference_geometry_payload_v3(
            block_rows,
            geometry_source="rows_growth_v3",
        )
        parsed[index] = {
            "index": index,
            "text": block_text,
            "text_raw": token_reconstruction.get("raw_text"),
            "page": _to_int((block_rows[0] or {}).get("page")),
            "box": _coerce_geometry_box_v3(geometry_payload.get("union_box")),
            "rows": block_rows,
            "row_ids": geometry_payload.get("row_ids") or [],
            "row_boxes": geometry_payload.get("row_boxes") or [],
            "page_boxes": geometry_payload.get("page_boxes") or [],
            "union_box": geometry_payload.get("union_box"),
            "pages_involved": geometry_payload.get("pages_involved") or [],
            "anchor_row_id": growth.get("anchor_row_id")
            or anchor.get("anchor_row_id")
            or anchor.get("row_id"),
            "body_start_row_id": growth.get("body_start_row_id")
            or anchor.get("body_start_row_id")
            or anchor.get("row_id"),
            "layout_type": growth.get("layout_type") or anchor.get("layout_type"),
            "anchor_type": growth.get("anchor_type") or anchor.get("anchor_type"),
            "used_marker_only_anchor": bool(
                growth.get("used_marker_only_anchor")
                or anchor.get("used_marker_only_anchor")
            ),
            "anchor_to_body_link_reason": growth.get("anchor_to_body_link_reason")
            or anchor.get("anchor_to_body_link_reason"),
            "continuation_between_pages": bool(
                growth.get("continuation_between_pages")
            ),
            "boundary_start_reason": growth.get("boundary_start_reason"),
            "boundary_end_reason": growth.get("boundary_end_reason"),
            "geometry_source": geometry_payload.get("geometry_source"),
            "local_row_count": len(block_rows),
            "local_anchor_detected": True,
            "structure_source": (
                selected_candidate_source
                if selected_candidate_source.startswith("rows")
                else "rows_raw"
            ),
            "reference_validation": validation,
            "validation_intermediate": _coerce_reference_validation_payload(validation),
            "column_id": block_rows[0].get("column_id_v2")
            or block_rows[0].get("column_id"),
            "anchor_position": anchor.get("position"),
            "anchor_style": anchor.get("anchor_style") or anchor.get("style"),
            "scores": final_decision,
            "final_decision": final_decision,
            "crossref_match": crossref_match,
            "token_reconstruction": token_reconstruction,
            "anomalies": {
                "cut_reasons": list(growth.get("cut_reasons") or []),
                "nested_anchor_indices": list(
                    growth.get("nested_anchor_indices") or []
                ),
            },
        }
        reference_debug.append(
            {
                "index": index,
                "anchor_detected": {
                    "index": index,
                    "style": anchor.get("style"),
                    "anchor_style": anchor.get("anchor_style") or anchor.get("style"),
                    "anchor_type": anchor.get("anchor_type"),
                    "layout_type": anchor.get("layout_type"),
                    "confidence": round(float(anchor.get("confidence") or 0.0), 3),
                    "strength": anchor.get("strength"),
                    "page": anchor.get("page"),
                    "row_id": anchor.get("row_id"),
                    "anchor_row_id": anchor.get("anchor_row_id")
                    or anchor.get("row_id"),
                    "body_start_row_id": anchor.get("body_start_row_id"),
                    "body_start_position": anchor.get("body_start_position"),
                    "position": anchor.get("position"),
                    "body_in_next_row": bool(anchor.get("body_in_next_row")),
                    "anchor_to_body_link_reason": anchor.get(
                        "anchor_to_body_link_reason"
                    ),
                    "used_marker_only_anchor": bool(
                        anchor.get("used_marker_only_anchor")
                    ),
                },
                "used_marker_only_anchor": bool(
                    growth.get("used_marker_only_anchor")
                    or anchor.get("used_marker_only_anchor")
                ),
                "anchor_row_id": growth.get("anchor_row_id")
                or anchor.get("anchor_row_id")
                or anchor.get("row_id"),
                "body_start_row_id": growth.get("body_start_row_id")
                or anchor.get("body_start_row_id")
                or anchor.get("row_id"),
                "layout_type": growth.get("layout_type") or anchor.get("layout_type"),
                "anchor_to_body_link_reason": growth.get("anchor_to_body_link_reason")
                or anchor.get("anchor_to_body_link_reason"),
                "body_start": growth.get("body_start"),
                "body_end": growth.get("body_end"),
                "rows_included": [
                    {
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
                        "reading_lane_id": row.get("reading_lane_id"),
                        "text": _short_debug_text(row.get("text")),
                    }
                    for row in block_rows
                ],
                "rows_discarded": growth.get("rows_discarded") or [],
                "continuation_between_pages": bool(
                    growth.get("continuation_between_pages")
                ),
                "closure_reason": growth.get("closure_reason"),
                "boundary_start_reason": growth.get("boundary_start_reason"),
                "boundary_end_reason": growth.get("boundary_end_reason"),
                "issues": growth.get("issues") or [],
                "accepted": bool(final_decision.get("accepted")),
                "selected_candidate_source": selected_candidate_source,
            }
        )

    experimental_entries = _build_experimental_reference_entries_v3(
        references=references,
        parsed_references=parsed,
    )
    experimental_metrics = _build_numeric_pipeline_metrics_v3(
        expected_indices=expected_indices,
        reference_entries=experimental_entries,
        detected_anchor_indices=[
            int(candidate.get("index"))
            for candidate in anchor_candidates
            if _to_int(candidate.get("index")) not in (None, 0)
        ],
        duplicate_indices=anchor_reconciliation.get("duplicate_indices") or [],
    )
    comparison = _build_numeric_reference_comparison_v3(
        current_entries=current_reference_entries,
        experimental_entries=experimental_entries,
        current_metrics=current_numeric_metrics,
        experimental_metrics=experimental_metrics,
    )
    return {
        "pipeline_name": NUMERIC_REFERENCE_PIPELINE_V3_NAME,
        "run_mode": NUMERIC_REFERENCE_PIPELINE_V3_RUN_MODE,
        "enabled": True,
        "selected_as_default": False,
        "phases": {
            "phase_0_crossref_validation": {
                "article_doi": crossref_context.get("article_doi"),
                "crossref_available": bool(crossref_context.get("crossref_available")),
                "crossref_reference_count": int(
                    crossref_context.get("crossref_reference_count") or 0
                ),
                "crossref_reference_candidates_total": len(
                    crossref_context.get("crossref_reference_candidates") or []
                ),
            },
            "phase_1_bibliography_territory": {
                "bibliography_start_page": territory_phase.get(
                    "bibliography_start_page"
                ),
                "bibliography_window_init": territory_phase.get(
                    "bibliography_window_init"
                ),
                "bibliography_window_end_soft": territory_phase.get(
                    "bibliography_window_end_soft"
                ),
                "bibliography_noise_regions": territory_phase.get(
                    "bibliography_noise_regions"
                )
                or [],
                "bibliography_territory": territory_phase.get("bibliography_territory"),
                "territory_zones": territory_phase.get("territory_zones") or [],
            },
            "phase_2_bibliography_rows_selection": {
                "bibliography_rows_selected": territory_phase.get(
                    "bibliography_rows_selected"
                )
                or [],
                "bibliography_rows_rejected": territory_phase.get(
                    "bibliography_rows_rejected"
                )
                or [],
                "rows_rejection_reasons": territory_phase.get("rows_rejection_reasons")
                or {},
                "rescued_rows_outside_initial_window": territory_phase.get(
                    "rescued_rows_outside_initial_window"
                )
                or [],
            },
            "phase_3_reading_order_rows": {
                "reading_lanes": territory_phase.get("reading_lanes") or [],
                "ordered_bibliography_rows": [
                    {
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
                        "flow_position": row.get("flow_position"),
                        "reading_lane_id": row.get("reading_lane_id"),
                        "box": _serialize_box(_normalize_box(row.get("box"))),
                        "text": _short_debug_text(row.get("text"), limit=140),
                    }
                    for row in ordered_rows
                ],
            },
            "phase_4_numeric_anchors": {
                "candidates": [
                    {
                        "index": candidate.get("index"),
                        "anchor_style": candidate.get("anchor_style")
                        or candidate.get("style"),
                        "style": candidate.get("style"),
                        "anchor_type": candidate.get("anchor_type"),
                        "layout_type": candidate.get("layout_type"),
                        "confidence": round(
                            float(candidate.get("confidence") or 0.0), 3
                        ),
                        "strength": candidate.get("strength"),
                        "row_id": candidate.get("row_id"),
                        "anchor_row_id": candidate.get("anchor_row_id")
                        or candidate.get("row_id"),
                        "body_start_row_id": candidate.get("body_start_row_id"),
                        "body_start_position": candidate.get("body_start_position"),
                        "position": candidate.get("position"),
                        "page": candidate.get("page"),
                        "body_in_next_row": bool(candidate.get("body_in_next_row")),
                        "anchor_to_body_link_reason": candidate.get(
                            "anchor_to_body_link_reason"
                        ),
                        "used_marker_only_anchor": bool(
                            candidate.get("used_marker_only_anchor")
                        ),
                        "reason": candidate.get("reason"),
                        "sequence_supported": bool(candidate.get("sequence_supported")),
                    }
                    for candidate in anchor_candidates
                ],
                "marker_only_anchor_audit": (
                    anchor_detection_debug.get("marker_only_anchor_audit") or {}
                ),
                "anchor_sequence": anchor_reconciliation.get("anchor_sequence") or [],
                "missing_indices": anchor_reconciliation.get("missing_indices") or [],
                "duplicate_indices": anchor_reconciliation.get("duplicate_indices")
                or [],
                "inferred_anchors": anchor_reconciliation.get("inferred_anchors") or [],
                "actions": anchor_reconciliation.get("reconciliation_actions") or [],
            },
            "phase_5_reference_segmentation": {
                "references": reference_debug,
            },
            "phase_6_token_refinement": {
                "references": [
                    {
                        "index": entry.get("index"),
                        "selected_candidate_source": (
                            (entry.get("token_reconstruction") or {}).get(
                                "selected_candidate_source"
                            )
                        ),
                        "cleanups_applied": (
                            (entry.get("token_reconstruction") or {}).get(
                                "cleanups_applied"
                            )
                            or []
                        ),
                        "accepted_local_edit_count": int(
                            (
                                (entry.get("token_reconstruction") or {}).get(
                                    "accepted_local_edit_count"
                                )
                                or 0
                            )
                        ),
                        "rejected_local_edit_count": int(
                            (
                                (entry.get("token_reconstruction") or {}).get(
                                    "rejected_local_edit_count"
                                )
                                or 0
                            )
                        ),
                    }
                    for entry in experimental_entries
                    if _to_int(entry.get("index")) not in (None, 0)
                ]
            },
            "phase_7_aux_validation": {
                "comparison_vs_current_status": comparison.get("status"),
                "comparison_vs_current": comparison,
                "current_metrics": current_numeric_metrics,
                "experimental_metrics": experimental_metrics,
            },
            "geometry": {
                "references": [
                    {
                        "index": entry.get("index"),
                        "anchor_row_id": entry.get("anchor_row_id"),
                        "body_start_row_id": entry.get("body_start_row_id"),
                        "layout_type": entry.get("layout_type"),
                        "anchor_type": entry.get("anchor_type"),
                        "used_marker_only_anchor": bool(
                            entry.get("used_marker_only_anchor")
                        ),
                        "anchor_to_body_link_reason": entry.get(
                            "anchor_to_body_link_reason"
                        ),
                        "row_ids": entry.get("row_ids") or [],
                        "rows": entry.get("rows") or [],
                        "row_boxes": entry.get("row_boxes") or [],
                        "page_boxes": entry.get("page_boxes") or [],
                        "union_box": entry.get("union_box"),
                        "pages_involved": entry.get("pages_involved") or [],
                        "continuation_between_pages": bool(
                            entry.get("continuation_between_pages")
                        ),
                        "boundary_start_reason": entry.get("boundary_start_reason"),
                        "boundary_end_reason": entry.get("boundary_end_reason"),
                        "geometry_source": entry.get("geometry_source"),
                    }
                    for entry in experimental_entries
                    if _to_int(entry.get("index")) not in (None, 0)
                ]
            },
        },
        "reference_debug": reference_debug,
        "references": experimental_entries,
        "metrics": experimental_metrics,
        "comparison_vs_current": comparison,
    }


def _build_references_from_lines_legacy(
    lines: Sequence[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    ordered_lines = _sort_bibliography_lines_reading_flow(lines)
    if len(ordered_lines) < 4:
        return {}

    anchors = extract_numbered_anchors(ordered_lines)
    if len(anchors) < 2:
        return {}

    first_anchor_by_index: Dict[int, Dict[str, Any]] = {}
    for anchor in anchors:
        index = int(anchor["index"])
        if index <= 0 or index in first_anchor_by_index:
            continue
        first_anchor_by_index[index] = anchor
    if len(first_anchor_by_index) < 2:
        return {}

    anchor_positions = sorted(
        int(anchor["position"]) for anchor in first_anchor_by_index.values()
    )
    parsed: Dict[int, Dict[str, Any]] = {}
    for index in sorted(first_anchor_by_index.keys()):
        anchor = first_anchor_by_index[index]
        start = int(anchor["position"])

        next_anchor = first_anchor_by_index.get(index + 1)
        if next_anchor and int(next_anchor["position"]) > start:
            end = int(next_anchor["position"])
        else:
            end = len(ordered_lines)
            for position in anchor_positions:
                if position > start:
                    end = position
                    break

        block_lines = ordered_lines[start:end]
        if not block_lines:
            continue
        block_text = _clean_reference_text(block_lines)
        if not _is_valid_reference_block(
            expected_index=index,
            lines=block_lines,
            text=block_text,
        ):
            continue

        union_box = _union_boxes(
            [line["box"] for line in block_lines if _normalize_box(line.get("box"))]
        )
        parsed[index] = {
            "text": block_text,
            "page": block_lines[0].get("page"),
            "box": union_box,
            "rows": block_lines,
            "local_row_count": len(block_lines),
            "local_anchor_detected": True,
            "structure_source": "rows_legacy",
            "reference_validation": _default_reference_validation(
                text=block_text,
                expected_index=index,
            ),
        }
    return parsed


def build_references_from_lines(
    lines: Sequence[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    # Mantiene compatibilidad con el fallback previo.
    return _build_references_from_lines_legacy(lines)


def _normalize_citation_marker(value: str) -> str:
    if not value:
        return ""
    compact = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return compact.replace("\u2013", "-").replace("\u2014", "-")


def _candidate_pages(
    page_hint: Optional[int],
    available_pages: Sequence[int],
) -> List[int]:
    known_pages = sorted(
        {int(page) for page in available_pages if isinstance(page, int) and page >= 0}
    )
    if page_hint is None:
        return known_pages

    ordered: List[int] = []
    for page in (page_hint, page_hint - 1, page_hint + 1):
        if page < 0:
            continue
        if page in known_pages and page not in ordered:
            ordered.append(page)
    if ordered:
        return ordered
    return known_pages


def _find_citation_marker_box(
    snippet_text: str,
    page_hint: Optional[int],
    tokens: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    marker_variants = {
        _normalize_citation_marker(match.group(0))
        for match in INLINE_CITATION_REGEX.finditer(snippet_text or "")
    }
    marker_variants = {value for value in marker_variants if value}
    if not marker_variants:
        return None

    tokens_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for token in tokens:
        page = token.get("page")
        if not isinstance(page, int):
            continue
        token_text = _normalize_citation_marker(str(token.get("text") or ""))
        if not token_text:
            continue
        tokens_by_page[page].append(token)

    page_candidates = _candidate_pages(page_hint, list(tokens_by_page.keys()))
    if not page_candidates:
        return None

    best: Optional[Dict[str, Any]] = None
    best_rank: Optional[Tuple[int, float]] = None
    max_window = 8

    for page_priority, page in enumerate(page_candidates):
        page_tokens = tokens_by_page.get(page) or []
        if not page_tokens:
            continue
        ordered_tokens = sorted(
            page_tokens, key=lambda item: (float(item["box"][1]), float(item["box"][0]))
        )
        for marker in marker_variants:
            marker_length = len(marker)
            for start in range(len(ordered_tokens)):
                combined = ""
                candidate_boxes: List[Sequence[float]] = []
                previous_box: Optional[Sequence[float]] = None
                for offset in range(max_window):
                    token_index = start + offset
                    if token_index >= len(ordered_tokens):
                        break
                    token = ordered_tokens[token_index]
                    token_piece = _normalize_citation_marker(
                        str(token.get("text") or "")
                    )
                    if not token_piece:
                        continue
                    current_box = token["box"]
                    if previous_box is not None:
                        # Avoid mixing tokens from different lines.
                        if abs(float(current_box[1]) - float(previous_box[1])) > 0.02:
                            break
                    previous_box = current_box
                    combined += token_piece
                    candidate_boxes.append(current_box)
                    if len(combined) > marker_length + 2:
                        break
                    if combined == marker:
                        merged_box = _union_boxes(candidate_boxes)
                        if not merged_box:
                            break
                        area = _box_area(merged_box)
                        rank = (page_priority, area)
                        if best_rank is None or rank < best_rank:
                            best_rank = rank
                            best = {
                                "id": f"token-marker-{page}-{start}",
                                "text": marker,
                                "page": page,
                                "box": merged_box,
                            }
                        break

    return best


def _pick_best_text_box(
    snippet_text: str,
    page_hint: Optional[int],
    tokens: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    paragraphs: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    marker_anchor = _find_citation_marker_box(snippet_text, page_hint, tokens)
    if marker_anchor is not None:
        return marker_anchor

    normalized_snippet = _normalize_text(snippet_text)
    if not normalized_snippet:
        return None

    snippet_tokens = _tokenize(normalized_snippet)
    available_pages = [
        item.get("page")
        for item in rows + paragraphs
        if isinstance(item.get("page"), int)
    ]
    page_candidates = _candidate_pages(page_hint, available_pages)
    if page_hint is None and not page_candidates:
        page_candidates = [None]

    def _best_item_in_pool(
        pool: Sequence[Dict[str, Any]],
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        best_item: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for item in pool:
            item_text = _normalize_text(item.get("text", ""))
            if not item_text:
                continue
            score = 0.0
            if normalized_snippet in item_text:
                score += 2.5
            elif item_text in normalized_snippet:
                score += 1.5

            item_tokens = _tokenize(item_text)
            if snippet_tokens and item_tokens:
                overlap = len(snippet_tokens.intersection(item_tokens))
                score += overlap / max(len(snippet_tokens), 1)

            if score > best_score:
                best_score = score
                best_item = item
        return best_item, best_score

    best_rank: Optional[Tuple[int, int, float]] = None
    best_match: Optional[Dict[str, Any]] = None
    pool_specs = [("rows", rows), ("paragraphs", paragraphs)]

    for page_priority, candidate_page in enumerate(page_candidates):
        for pool_priority, (_, source_pool) in enumerate(pool_specs):
            if candidate_page is None:
                candidate_pool = list(source_pool)
            else:
                candidate_pool = [
                    item for item in source_pool if item.get("page") == candidate_page
                ]
            if not candidate_pool:
                continue
            match_item, match_score = _best_item_in_pool(candidate_pool)
            if match_item is None or match_score < 0.15:
                continue
            rank = (page_priority, pool_priority, -match_score)
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_match = match_item

    return best_match


def _pick_context_paragraph(
    mention_box: Sequence[float],
    page_paragraphs: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not page_paragraphs:
        return None

    containing = [
        paragraph
        for paragraph in page_paragraphs
        if _contains_box(paragraph["box"], mention_box)
    ]
    if containing:
        return min(containing, key=lambda paragraph: _box_area(paragraph["box"]))

    iou_candidates: List[Tuple[float, Dict[str, Any]]] = []
    for paragraph in page_paragraphs:
        iou = _box_iou(paragraph["box"], mention_box)
        if iou >= 0.08:
            iou_candidates.append((iou, paragraph))
    if iou_candidates:
        iou_candidates.sort(key=lambda item: (-item[0], _box_area(item[1]["box"])))
        return iou_candidates[0][1]

    overlap_candidates: List[Tuple[float, Dict[str, Any]]] = []
    for paragraph in page_paragraphs:
        overlap = _overlap_ratio(paragraph["box"], mention_box)
        if overlap >= 0.2:
            overlap_candidates.append((overlap, paragraph))
    if overlap_candidates:
        overlap_candidates.sort(key=lambda item: (-item[0], _box_area(item[1]["box"])))
        return overlap_candidates[0][1]

    return None


def _debug_normalize_box(raw: Any) -> Optional[List[float]]:
    """Normaliza un box que puede venir como lista [x,y,w,h] o dict {x0,y0,x1,y1}."""
    if isinstance(raw, (list, tuple)):
        return _normalize_box(raw)
    if isinstance(raw, dict):
        return _box_from_corners(
            float(raw.get("x0") or 0),
            float(raw.get("y0") or 0),
            float(raw.get("x1") or 0),
            float(raw.get("y1") or 0),
        )
    return None


def _build_reference_debug_steps(
    *,
    rows_with_columns: List[Dict[str, Any]],
    page_splits: Dict[int, Optional[float]],
    heading_candidates: List[Dict[str, Any]],
    selected_heading: Optional[Dict[str, Any]],
    bibliography_segments: List[Dict[str, Any]],
    bibliography_rows_debug: List[Dict[str, Any]],
    row_phase_details: List[Dict[str, Any]],
    reference_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Transforma datos intermedios del pipeline en reference_debug_steps normalizado.

    Cada paso tiene: key, label, source, kind, items.
    Ítems tipo 'boxes': {id, page, box, label, meta}
    Ítems tipo 'vertical_guides': {page, x, label}
    """
    steps: List[Dict[str, Any]] = []

    # ── 1. assign_column_ids ────────────────────────────────────────────────
    col_items: List[Dict[str, Any]] = []
    for i, row in enumerate(rows_with_columns):
        box = _normalize_box(row.get("box"))
        if box is None:
            continue
        column_id = str(row.get("column_id") or "left")
        col_items.append(
            {
                "id": f"col-{i}",
                "page": row.get("page"),
                "box": box,
                "label": f"[{column_id}] {str(row.get('text') or '')[:40]}",
                "meta": {"column_id": column_id},
            }
        )
    steps.append(
        {
            "key": "assign_column_ids",
            "label": "Columnas asignadas",
            "source": "_assign_column_ids",
            "kind": "boxes",
            "items": col_items,
        }
    )

    # ── 2. detect_page_column_split ─────────────────────────────────────────
    guide_items: List[Dict[str, Any]] = []
    for page, split_x in sorted(page_splits.items()):
        if split_x is None:
            continue
        guide_items.append(
            {
                "page": page,
                "x": float(split_x),
                "label": f"p.{page + 1} x={split_x:.3f}",
            }
        )
    steps.append(
        {
            "key": "detect_page_column_split",
            "label": "Split vertical por página",
            "source": "_detect_page_column_split",
            "kind": "vertical_guides",
            "items": guide_items,
        }
    )

    # ── 3. detect_reference_heading_candidates ──────────────────────────────
    cand_items: List[Dict[str, Any]] = []
    for i, cand in enumerate(heading_candidates):
        box = _normalize_box(cand.get("box"))
        if box is None:
            continue
        cand_items.append(
            {
                "id": f"hcand-{i}",
                "page": cand.get("page"),
                "box": box,
                "label": str(cand.get("text") or ""),
                "meta": {
                    "source": cand.get("source"),
                    "column_id": cand.get("column_id"),
                },
            }
        )
    steps.append(
        {
            "key": "detect_reference_heading_candidates",
            "label": "Candidatos a heading",
            "source": "_detect_reference_heading_candidates",
            "kind": "boxes",
            "items": cand_items,
        }
    )

    # ── 4. selected_heading ─────────────────────────────────────────────────
    sel_items: List[Dict[str, Any]] = []
    if isinstance(selected_heading, dict):
        box = _normalize_box(selected_heading.get("box"))
        if box is not None:
            sel_items.append(
                {
                    "id": "selected-heading-0",
                    "page": selected_heading.get("page"),
                    "box": box,
                    "label": str(selected_heading.get("text") or ""),
                    "meta": {
                        "source": selected_heading.get("source"),
                        "column_id": selected_heading.get("column_id"),
                    },
                }
            )
    steps.append(
        {
            "key": "selected_heading",
            "label": "Heading seleccionado",
            "source": "_build_bibliography_segments",
            "kind": "boxes",
            "items": sel_items,
        }
    )

    # ── 5. bibliography_segments ────────────────────────────────────────────
    seg_items: List[Dict[str, Any]] = []
    for i, seg in enumerate(bibliography_segments):
        box = _normalize_box(seg.get("box"))
        if box is None:
            continue
        seg_items.append(
            {
                "id": f"seg-{i}",
                "page": seg.get("page"),
                "box": box,
                "label": (
                    f"col={seg.get('column_id')} "
                    f"conf={float(seg.get('confidence') or 0.0):.2f}"
                ),
                "meta": {
                    "column_id": seg.get("column_id"),
                    "confidence": seg.get("confidence"),
                    "source": seg.get("source"),
                    "segment_top_source": seg.get("segment_top_source"),
                },
            }
        )
    steps.append(
        {
            "key": "bibliography_segments",
            "label": "Segmentos de bibliografía",
            "source": "_build_bibliography_segments",
            "kind": "boxes",
            "items": seg_items,
        }
    )

    # ── 6. rows_in_bibliography_zone ────────────────────────────────────────
    zone_items: List[Dict[str, Any]] = []
    for i, row in enumerate(bibliography_rows_debug):
        if not row.get("included"):
            continue
        box = _debug_normalize_box(row.get("box"))
        if box is None:
            continue
        zone_items.append(
            {
                "id": f"brow-{i}",
                "page": row.get("page"),
                "box": box,
                "label": str(row.get("text") or "")[:60],
                "meta": {
                    "column_id": row.get("column_id"),
                    "anchor_index": row.get("anchor_index"),
                    "anchor_style": row.get("anchor_style"),
                    "anchor_candidate_index": row.get("anchor_candidate_index"),
                    "anchor_candidate_style": row.get("anchor_candidate_style"),
                    "anchor_rejected_reason": row.get("anchor_rejected_reason"),
                },
            }
        )
    steps.append(
        {
            "key": "rows_in_bibliography_zone",
            "label": "Rows en bibliografía",
            "source": "_collect_bibliography_rows_from_segments",
            "kind": "boxes",
            "items": zone_items,
        }
    )

    # ── 7. reference_anchors ────────────────────────────────────────────────
    anchor_items: List[Dict[str, Any]] = []
    for i, row in enumerate(bibliography_rows_debug):
        anchor_index = row.get("anchor_index")
        candidate_index = row.get("anchor_candidate_index")
        candidate_style = row.get("anchor_candidate_style")
        rejected_reason = row.get("anchor_rejected_reason")
        if not row.get("included"):
            continue
        box = _debug_normalize_box(row.get("box"))
        if box is None:
            continue
        if anchor_index is not None:
            anchor_style = str(row.get("anchor_style") or "unknown")
            anchor_prefix = _format_reference_anchor_prefix(anchor_index, anchor_style)
            anchor_items.append(
                {
                    "id": f"anchor-{anchor_index}",
                    "page": row.get("page"),
                    "box": box,
                    "label": f"{anchor_prefix} {str(row.get('text') or '')[:40]}",
                    "meta": {
                        "anchor_index": anchor_index,
                        "anchor_style": anchor_style,
                        "column_id": row.get("column_id"),
                    },
                }
            )
            continue
        candidate_text = str(row.get("text") or "")
        show_rejected_candidate = bool(
            rejected_reason == "doi_like"
            or (
                rejected_reason == "weak_bibliographic_signal"
                and len(candidate_text) >= 24
            )
        )
        if (
            candidate_style in {"dotted", "suffix_paren", "wrapped_paren"}
            and candidate_index is not None
            and rejected_reason
            and show_rejected_candidate
        ):
            anchor_items.append(
                {
                    "id": f"anchor-rejected-{candidate_index}-{i}",
                    "page": row.get("page"),
                    "box": box,
                    "label": (
                        "reject "
                        f"{_format_reference_anchor_prefix(candidate_index, str(candidate_style or 'unknown'))} "
                        f"{candidate_text[:36]}"
                    ),
                    "meta": {
                        "anchor_candidate_index": candidate_index,
                        "anchor_style": candidate_style,
                        "anchor_rejected_reason": rejected_reason,
                        "column_id": row.get("column_id"),
                    },
                }
            )
    steps.append(
        {
            "key": "reference_anchors",
            "label": "Anchors de referencia",
            "source": "detect_reference_anchors_from_rows",
            "kind": "boxes",
            "items": anchor_items,
        }
    )

    # ── 8. reference_block_rows ─────────────────────────────────────────────
    block_items: List[Dict[str, Any]] = []
    for block in row_phase_details:
        ref_idx = block.get("reference_index")
        for decision in block.get("row_decisions") or []:
            if not decision.get("included"):
                continue
            box = _normalize_box(decision.get("box"))
            if box is None:
                continue
            row_id = str(decision.get("row_id") or "")
            block_items.append(
                {
                    "id": f"blk-{ref_idx}-{row_id}",
                    "page": decision.get("page"),
                    "box": box,
                    "label": f"[{ref_idx}] {str(decision.get('text') or '')[:40]}",
                    "meta": {"reference_index": ref_idx, "row_id": row_id},
                }
            )
    steps.append(
        {
            "key": "reference_block_rows",
            "label": "Rows por referencia",
            "source": "build_reference_rows_between_anchors",
            "kind": "boxes",
            "items": block_items,
        }
    )

    # ── 9. accepted_references ──────────────────────────────────────────────
    acc_items: List[Dict[str, Any]] = []
    for entry in reference_entries:
        final_decision = entry.get("final_decision") or {}
        if not final_decision.get("accepted"):
            continue
        box = _normalize_box(entry.get("box"))
        page = entry.get("page")
        if box is None or page is None:
            continue
        acc_items.append(
            {
                "id": str(entry.get("ref_id") or f"acc-{entry.get('index')}"),
                "page": page,
                "box": box,
                "label": f"[{entry.get('index')}] {str(entry.get('text') or '')[:50]}",
                "meta": {"index": entry.get("index"), "doi": entry.get("doi")},
            }
        )
    steps.append(
        {
            "key": "accepted_references",
            "label": "Referencias aceptadas",
            "source": "_build_reference_decision",
            "kind": "boxes",
            "items": acc_items,
        }
    )

    # ── 10. rejected_references ─────────────────────────────────────────────
    rej_items: List[Dict[str, Any]] = []
    for entry in reference_entries:
        final_decision = entry.get("final_decision") or {}
        if final_decision.get("accepted") is True:
            continue
        box = _normalize_box(entry.get("box"))
        page = entry.get("page")
        if box is None or page is None:
            continue
        rej_items.append(
            {
                "id": str(entry.get("ref_id") or f"rej-{entry.get('index')}"),
                "page": page,
                "box": box,
                "label": f"[{entry.get('index')}] {str(entry.get('text') or '')[:50]}",
                "meta": {"index": entry.get("index"), "doi": entry.get("doi")},
            }
        )
    steps.append(
        {
            "key": "rejected_references",
            "label": "Referencias rechazadas",
            "source": "_build_reference_decision",
            "kind": "boxes",
            "items": rej_items,
        }
    )

    return steps


def _short_debug_text(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _base_row_id(value: Any) -> str:
    row_id = str(value or "").strip()
    if "::seg-" in row_id:
        row_id = row_id.split("::seg-", 1)[0]
    return row_id


def _unique_preserve_order(values: Sequence[Any]) -> List[Any]:
    seen: set[Any] = set()
    ordered: List[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _ordered_counter_dict(counter: Counter) -> Dict[str, int]:
    return {
        str(reason): int(count)
        for reason, count in sorted(
            counter.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )
    }


def _anchor_window_from_context(context: Dict[str, Any]) -> Optional[List[int]]:
    if not isinstance(context, dict):
        return None
    indices: List[int] = []
    previous_anchor = context.get("current_anchor") or {}
    next_anchor = context.get("next_anchor") or {}
    previous_index = _to_int(previous_anchor.get("index"))
    next_index = _to_int(next_anchor.get("index"))
    if isinstance(previous_index, int) and previous_index > 0:
        indices.append(previous_index)
    if isinstance(next_index, int) and next_index > 0 and next_index not in indices:
        indices.append(next_index)
    return indices or None


def _build_raw_row_metadata_map(
    raw_rows: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    metadata_by_row_id: Dict[str, Dict[str, Any]] = {}
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        row_id = _base_row_id(item.get("id"))
        if not row_id:
            continue
        payload: Dict[str, Any] = {}
        if item.get("section_id") not in (None, ""):
            payload["section_id"] = item.get("section_id")
        elif isinstance(item.get("section"), dict) and item["section"].get(
            "id"
        ) not in (None, ""):
            payload["section_id"] = item["section"].get("id")
        if item.get("paragraph_id") not in (None, ""):
            payload["paragraph_id"] = item.get("paragraph_id")
        elif isinstance(item.get("paragraph"), dict) and item["paragraph"].get(
            "id"
        ) not in (None, ""):
            payload["paragraph_id"] = item["paragraph"].get("id")
        metadata_by_row_id[row_id] = payload
    return metadata_by_row_id


def _build_document_diagnostics(
    *,
    bibliography_rows_debug: Sequence[Dict[str, Any]],
    bibliography_lines: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    selected_heading: Optional[Dict[str, Any]],
    start_page: Optional[int],
) -> Dict[str, Any]:
    scoped_rows = [
        row
        for row in bibliography_rows_debug
        if start_page is None
        or _to_int(row.get("page")) is None
        or int(row.get("page")) >= int(start_page)
    ]
    included_rows = [row for row in scoped_rows if row.get("included")]
    total_rows = len(scoped_rows)
    anchor_style_counts = {
        style: sum(
            1
            for row in included_rows
            if str(row.get("anchor_style") or "").strip() == style
        )
        for style in NUMERIC_ANCHOR_STYLES
    }
    bracketed_anchor_rows = anchor_style_counts["bracketed"]
    dotted_anchor_rows = anchor_style_counts["dotted"]
    suffix_paren_anchor_rows = anchor_style_counts["suffix_paren"]
    wrapped_paren_anchor_rows = anchor_style_counts["wrapped_paren"]
    numeric_anchor_rows = sum(anchor_style_counts.values())
    anchor_style_detected = _dominant_anchor_style_from_counts(anchor_style_counts)
    author_year_signal_count = sum(
        1
        for row in included_rows
        if _has_bibliographic_lead_signal(str(row.get("text") or ""))
    )
    bibliography_density = (
        round(len(included_rows) / total_rows, 3) if total_rows else 0.0
    )
    rejected_dotted_anchor_candidates = sum(
        1
        for row in scoped_rows
        if str(row.get("anchor_candidate_style") or "").strip() == "dotted"
        and row.get("anchor_rejected_reason")
    )
    detected_numeric = is_numbered_bibliography(bibliography_lines)
    if detected_numeric:
        reference_style_detected = "numeric"
        reference_style_confidence = min(
            0.99,
            round(
                0.62
                + min(numeric_anchor_rows, 6) * 0.05
                + min(len(bibliography_segments), 4) * 0.04,
                3,
            ),
        )
    elif author_year_signal_count >= max(3, numeric_anchor_rows):
        reference_style_detected = "non_numeric"
        reference_style_confidence = min(
            0.95,
            round(
                0.42
                + min(author_year_signal_count, 8) * 0.05
                + (0.08 if selected_heading else 0.0)
                + min(bibliography_density, 1.0) * 0.12,
                3,
            ),
        )
    else:
        reference_style_detected = "weak_or_unknown"
        reference_style_confidence = min(
            0.65,
            round(
                0.18
                + min(
                    numeric_anchor_rows
                    + author_year_signal_count
                    + len(bibliography_segments),
                    8,
                )
                * 0.04,
                3,
            ),
        )
    return {
        "reference_style_detected": reference_style_detected,
        "reference_style_confidence": reference_style_confidence,
        "anchor_style_detected": anchor_style_detected,
        "reference_style_signals": {
            "bracketed_anchor_rows": int(bracketed_anchor_rows),
            "dotted_anchor_rows": int(dotted_anchor_rows),
            "suffix_paren_anchor_rows": int(suffix_paren_anchor_rows),
            "wrapped_paren_anchor_rows": int(wrapped_paren_anchor_rows),
            "author_year_signal_count": int(author_year_signal_count),
            "bibliography_density": bibliography_density,
            "rejected_dotted_anchor_candidates": int(rejected_dotted_anchor_candidates),
            "bibliography_segment_count": int(len(bibliography_segments)),
            "selected_heading_detected": bool(selected_heading),
        },
    }


def _phase_diagnostic_payload(
    *,
    status: str,
    reason: str,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "evidence": evidence,
    }


def _build_phase_diagnostics(
    *,
    bibliography_phase: Dict[str, Any],
    bibliography_rows_phase: Dict[str, Any],
    bibliography_lines: Sequence[Dict[str, Any]],
    row_phase_details: Sequence[Dict[str, Any]],
    reference_entries: Sequence[Dict[str, Any]],
    document_diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    selected_heading = bibliography_phase.get("selected_heading")
    heading_candidates = bibliography_phase.get("heading_candidates") or []
    bibliography_segments = bibliography_phase.get("bibliography_segments") or []
    debug_rows = bibliography_rows_phase.get("debug_rows") or []
    start_page = _to_int(bibliography_phase.get("start_page"))
    scoped_debug_rows = [
        row
        for row in debug_rows
        if start_page is None
        or _to_int(row.get("page")) is None
        or int(row.get("page")) >= int(start_page)
    ]
    style_detected = str(
        document_diagnostics.get("reference_style_detected") or "weak_or_unknown"
    )
    detected_anchor_indices = _unique_preserve_order(
        sorted(
            {
                int(anchor.get("index"))
                for anchor in detect_reference_anchors_from_rows(bibliography_lines)
                if _to_int(anchor.get("index")) not in (None, 0)
            }
        )
    )
    rejected_anchor_candidates = sum(
        1 for row in scoped_debug_rows if row.get("anchor_rejected_reason")
    )
    included_rows = sum(1 for row in scoped_debug_rows if row.get("included"))
    total_rows = len(scoped_debug_rows)
    total_segment_rows = sum(
        int(segment.get("row_count") or 0) for segment in bibliography_segments
    )
    block_count = len(row_phase_details)
    selected_block_rows = sum(
        1
        for detail in row_phase_details
        for decision in (detail.get("row_decisions") or [])
        if decision.get("included")
    )
    dropped_block_rows = sum(
        1
        for detail in row_phase_details
        for decision in (detail.get("row_decisions") or [])
        if decision.get("included") is False
    )
    block_nested_anchor_count = sum(
        1 for detail in row_phase_details if detail.get("nested_anchor_indices")
    )
    total_references = len(reference_entries)
    accepted_references = sum(
        1
        for entry in reference_entries
        if bool((entry.get("final_decision") or {}).get("accepted"))
    )
    fallback_references = sum(
        1
        for entry in reference_entries
        if "fallback" in str(entry.get("structure_source") or "")
    )
    phase_diagnostics: Dict[str, Any] = {}

    if isinstance(selected_heading, dict):
        phase_diagnostics["selected_heading"] = _phase_diagnostic_payload(
            status="ok",
            reason="reference_heading_selected",
            evidence={
                "candidate_count": len(heading_candidates),
                "selected_page": selected_heading.get("page"),
                "selected_column_id": selected_heading.get("column_id"),
                "selected_text": _short_debug_text(
                    selected_heading.get("text"), limit=120
                ),
            },
        )
    elif heading_candidates:
        phase_diagnostics["selected_heading"] = _phase_diagnostic_payload(
            status="weak",
            reason="heading_candidates_found_but_not_selected",
            evidence={"candidate_count": len(heading_candidates)},
        )
    else:
        phase_diagnostics["selected_heading"] = _phase_diagnostic_payload(
            status="failed",
            reason="no_reference_heading_detected",
            evidence={"candidate_count": 0},
        )

    if not bibliography_segments:
        segment_status = "failed"
        segment_reason = "no_bibliography_segments_built"
    elif len(bibliography_segments) == 1 or total_segment_rows < 3:
        segment_status = "weak"
        segment_reason = "bibliography_segments_sparse"
    else:
        segment_status = "ok"
        segment_reason = "bibliography_segments_built"
    phase_diagnostics["bibliography_segments"] = _phase_diagnostic_payload(
        status=segment_status,
        reason=segment_reason,
        evidence={
            "segment_count": len(bibliography_segments),
            "total_segment_rows": total_segment_rows,
            "pages": _unique_preserve_order(
                sorted(
                    {
                        int(segment.get("page"))
                        for segment in bibliography_segments
                        if isinstance(segment.get("page"), int)
                    }
                )
            ),
            "start_page": bibliography_phase.get("start_page"),
        },
    )

    rows_density = round(included_rows / total_rows, 3) if total_rows else 0.0
    if included_rows == 0:
        rows_status = "failed"
        rows_reason = "no_rows_inside_bibliography_zone"
    elif included_rows < 3:
        rows_status = "weak"
        rows_reason = "bibliography_zone_rows_sparse"
    else:
        rows_status = "ok"
        rows_reason = "rows_collected_inside_bibliography_zone"
    phase_diagnostics["rows_in_bibliography_zone"] = _phase_diagnostic_payload(
        status=rows_status,
        reason=rows_reason,
        evidence={
            "rows_considered": total_rows,
            "rows_included": included_rows,
            "rows_rejected": max(0, total_rows - included_rows),
            "rows_density": rows_density,
        },
    )

    if style_detected == "numeric":
        if len(detected_anchor_indices) >= 2:
            anchor_status = "ok"
            anchor_reason = "numeric_reference_anchors_detected"
        elif len(detected_anchor_indices) == 1:
            anchor_status = "weak"
            anchor_reason = "single_numeric_reference_anchor_detected"
        else:
            anchor_status = "failed"
            anchor_reason = "no_stable_numeric_reference_anchors_detected"
    elif len(detected_anchor_indices) >= 2:
        anchor_status = "ok"
        anchor_reason = "reference_anchors_detected"
    else:
        anchor_status = "weak"
        anchor_reason = "document_looks_non_numeric_or_anchor_signal_weak"
    phase_diagnostics["reference_anchors"] = _phase_diagnostic_payload(
        status=anchor_status,
        reason=anchor_reason,
        evidence={
            "detected_anchor_total": len(detected_anchor_indices),
            "detected_anchor_indices": detected_anchor_indices[:40],
            "rejected_anchor_candidates": rejected_anchor_candidates,
            "reference_style_detected": style_detected,
        },
    )

    if style_detected == "numeric" and block_count == 0:
        block_status = "failed"
        block_reason = "no_reference_blocks_built"
    elif block_count == 0:
        block_status = "weak"
        block_reason = "reference_blocks_not_built"
    elif dropped_block_rows > 0 or block_nested_anchor_count > 0:
        block_status = "weak"
        block_reason = "reference_block_rows_trimmed_or_split"
    else:
        block_status = "ok"
        block_reason = "reference_blocks_built"
    phase_diagnostics["reference_block_rows"] = _phase_diagnostic_payload(
        status=block_status,
        reason=block_reason,
        evidence={
            "reference_block_count": block_count,
            "selected_block_rows": selected_block_rows,
            "dropped_block_rows": dropped_block_rows,
            "blocks_with_nested_anchor": block_nested_anchor_count,
        },
    )

    if total_references == 0 or accepted_references == 0:
        final_status = "failed"
        final_reason = "no_references_accepted"
    elif accepted_references < total_references or fallback_references > 0:
        final_status = "weak"
        final_reason = "references_partially_accepted_or_fallback_used"
    else:
        final_status = "ok"
        final_reason = "references_accepted"
    phase_diagnostics["final_decision"] = _phase_diagnostic_payload(
        status=final_status,
        reason=final_reason,
        evidence={
            "references_total": total_references,
            "accepted_total": accepted_references,
            "rejected_total": max(0, total_references - accepted_references),
            "fallback_total": fallback_references,
        },
    )

    ordered_phases = [
        "selected_heading",
        "bibliography_segments",
        "rows_in_bibliography_zone",
        "reference_anchors",
        "reference_block_rows",
        "final_decision",
    ]
    first_failure_phase = None
    first_failure_reason = None
    for phase_name in ordered_phases:
        payload = phase_diagnostics.get(phase_name) or {}
        if payload.get("status") == "failed":
            first_failure_phase = phase_name
            first_failure_reason = payload.get("reason")
            break
    if first_failure_phase is None:
        for phase_name in ordered_phases:
            payload = phase_diagnostics.get(phase_name) or {}
            if payload.get("status") == "weak":
                first_failure_phase = phase_name
                first_failure_reason = payload.get("reason")
                break
    phase_diagnostics["first_failure_phase"] = first_failure_phase
    phase_diagnostics["first_failure_reason"] = first_failure_reason
    return phase_diagnostics


def _build_row_rejection_audit(
    *,
    bibliography_rows_debug: Sequence[Dict[str, Any]],
    row_phase_details: Sequence[Dict[str, Any]],
    rows_with_columns: Sequence[Dict[str, Any]],
    raw_row_metadata_map: Dict[str, Dict[str, Any]],
    start_page: Optional[int],
) -> Dict[str, Any]:
    row_context = _build_same_column_row_context(rows_with_columns)
    rejection_counter: Counter = Counter()
    rejected_rows: List[Dict[str, Any]] = []

    for row in bibliography_rows_debug:
        if row.get("included"):
            continue
        row_page = _to_int(row.get("page"))
        if (
            isinstance(start_page, int)
            and isinstance(row_page, int)
            and row_page < start_page
        ):
            continue
        row_id = str(row.get("id") or "")
        base_row_id = _base_row_id(row_id)
        context = row_context.get(base_row_id) or {}
        raw_metadata = raw_row_metadata_map.get(base_row_id) or {}
        reason = str(row.get("reason") or "rejected").strip() or "rejected"
        rejection_counter[reason] += 1
        rejected_rows.append(
            {
                "row_id": row_id,
                "page": row.get("page"),
                "column_id": row.get("column_id"),
                "text": _short_debug_text(row.get("text")),
                "rejected_reason": reason,
                "phase": "rows_in_bibliography_zone",
                "inside_bibliography_zone": bool(row.get("in_bibliography_zone")),
                "neighbor_previous_row_id": (
                    str((context.get("previous_row") or {}).get("id") or "") or None
                ),
                "neighbor_next_row_id": (
                    str((context.get("next_row") or {}).get("id") or "") or None
                ),
                "between_anchor_indices": _anchor_window_from_context(context),
                "section_id": raw_metadata.get("section_id"),
                "paragraph_id": raw_metadata.get("paragraph_id"),
            }
        )

    for detail in row_phase_details:
        reference_index = _to_int(detail.get("reference_index"))
        next_anchor_index = _to_int(detail.get("next_anchor_index"))
        for decision in detail.get("row_decisions") or []:
            if decision.get("included") is not False:
                continue
            row_id = str(decision.get("row_id") or "")
            base_row_id = _base_row_id(row_id)
            context = row_context.get(base_row_id) or {}
            raw_metadata = raw_row_metadata_map.get(base_row_id) or {}
            reason = str(decision.get("reason") or "rejected").strip() or "rejected"
            rejection_counter[reason] += 1
            anchor_window: List[int] = []
            if isinstance(reference_index, int) and reference_index > 0:
                anchor_window.append(reference_index)
            if (
                isinstance(next_anchor_index, int)
                and next_anchor_index > 0
                and next_anchor_index not in anchor_window
            ):
                anchor_window.append(next_anchor_index)
            if not anchor_window:
                context_window = _anchor_window_from_context(context)
                if context_window:
                    anchor_window = context_window
            rejected_rows.append(
                {
                    "row_id": row_id,
                    "page": decision.get("page"),
                    "column_id": decision.get("column_id"),
                    "text": _short_debug_text(decision.get("text")),
                    "rejected_reason": reason,
                    "phase": "reference_block_rows",
                    "inside_bibliography_zone": True,
                    "neighbor_previous_row_id": (
                        str((context.get("previous_row") or {}).get("id") or "") or None
                    ),
                    "neighbor_next_row_id": (
                        str((context.get("next_row") or {}).get("id") or "") or None
                    ),
                    "between_anchor_indices": anchor_window or None,
                    "section_id": raw_metadata.get("section_id"),
                    "paragraph_id": raw_metadata.get("paragraph_id"),
                }
            )

    return {
        "total_rejected_rows": len(rejected_rows),
        "counts_by_reason": _ordered_counter_dict(rejection_counter),
        "relevant_rows": rejected_rows[:ROW_REJECTION_AUDIT_LIMIT],
        "truncated": len(rejected_rows) > ROW_REJECTION_AUDIT_LIMIT,
    }


def _infer_reference_failure_stage(
    *,
    entry: Dict[str, Any],
    detail: Dict[str, Any],
    raw_row_ids: Sequence[str],
    dropped_row_ids: Sequence[str],
    cut_reasons: Sequence[str],
    nested_anchor_indices: Sequence[int],
) -> Tuple[str, str]:
    final_decision = (
        entry.get("final_decision")
        if isinstance(entry.get("final_decision"), dict)
        else {}
    )
    validation_intermediate = (
        detail.get("validation_intermediate")
        if isinstance(detail.get("validation_intermediate"), dict)
        else (
            entry.get("validation_intermediate")
            if isinstance(entry.get("validation_intermediate"), dict)
            else {}
        )
    )
    structure_source = str(entry.get("structure_source") or "").strip()
    if "fallback" in structure_source and not raw_row_ids:
        return "fallback", str(final_decision.get("reason") or structure_source)
    if not raw_row_ids:
        return "reference_anchors", "no_rows_captured_for_reference_block"
    if cut_reasons or nested_anchor_indices or dropped_row_ids:
        return (
            "reference_block_rows",
            str(
                (cut_reasons[0] if cut_reasons else None)
                or ("nested_anchor_detected" if nested_anchor_indices else None)
                or ("dropped_rows_detected" if dropped_row_ids else None)
                or "reference_block_rows_trimmed"
            ),
        )
    if validation_intermediate.get("accepted") is False and validation_intermediate.get(
        "reason"
    ):
        return "reference_validation", str(validation_intermediate.get("reason"))
    if final_decision.get("accepted") is False:
        return "final_decision", str(
            final_decision.get("reason") or "rejected_in_final_decision"
        )
    if structure_source and not structure_source.startswith("rows_raw"):
        return "final_decision", f"structure_source={structure_source}"
    return "final_decision", "diagnostic_flags_present"


def _build_reference_failure_audit(
    *,
    reference_entries: Sequence[Dict[str, Any]],
    row_phase_details: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    details_by_index: Dict[int, Dict[str, Any]] = {}
    for detail in row_phase_details:
        reference_index = _to_int(detail.get("reference_index"))
        if isinstance(reference_index, int) and reference_index > 0:
            details_by_index[reference_index] = detail

    problematic_references: List[Dict[str, Any]] = []
    for entry in reference_entries:
        reference_index = _to_int(entry.get("index"))
        if not isinstance(reference_index, int) or reference_index <= 0:
            continue
        detail = details_by_index.get(reference_index) or {}
        final_decision = (
            entry.get("final_decision")
            if isinstance(entry.get("final_decision"), dict)
            else {}
        )
        accepted = bool(final_decision.get("accepted"))
        structure_source = str(entry.get("structure_source") or "").strip()
        row_decisions = detail.get("row_decisions") or []
        raw_row_ids = _unique_preserve_order(
            [
                str(item.get("row_id") or "")
                for item in row_decisions
                if str(item.get("row_id") or "").strip()
            ]
        )
        kept_row_ids = _unique_preserve_order(
            [
                str(item.get("row_id") or "")
                for item in row_decisions
                if item.get("included") and str(item.get("row_id") or "").strip()
            ]
        )
        dropped_row_ids = _unique_preserve_order(
            [
                str(item.get("row_id") or "")
                for item in row_decisions
                if item.get("included") is False
                and str(item.get("row_id") or "").strip()
            ]
        )
        cut_reasons = _unique_preserve_order(
            [
                str(reason).strip()
                for reason in list(detail.get("cut_reasons") or [])
                + list((entry.get("anomalies") or {}).get("cut_reasons") or [])
                if str(reason).strip()
            ]
        )
        nested_anchor_indices = sorted(
            {
                int(index)
                for index in list(detail.get("nested_anchor_indices") or [])
                + list(
                    (entry.get("anomalies") or {}).get("nested_anchor_indices") or []
                )
                if _to_int(index) not in (None, 0)
            }
        )
        next_anchor_index = _to_int(detail.get("next_anchor_index"))
        missing_expected_continuations = bool(
            any(
                str(reason).startswith(
                    ("vertical_gap", "page_jump", "late_page_continuation")
                )
                for reason in cut_reasons
            )
            or (
                isinstance(next_anchor_index, int)
                and next_anchor_index > 0
                and next_anchor_index > reference_index + 1
            )
        )
        problematic = bool(
            not accepted
            or "fallback" in structure_source
            or dropped_row_ids
            or cut_reasons
            or nested_anchor_indices
            or missing_expected_continuations
        )
        if not problematic:
            continue
        failure_stage, failure_reason = _infer_reference_failure_stage(
            entry=entry,
            detail=detail,
            raw_row_ids=raw_row_ids,
            dropped_row_ids=dropped_row_ids,
            cut_reasons=cut_reasons,
            nested_anchor_indices=nested_anchor_indices,
        )
        problematic_references.append(
            {
                "index": reference_index,
                "status": "failed" if not accepted else "weak",
                "structure_source": structure_source,
                "accepted": accepted,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "raw_row_ids": raw_row_ids,
                "kept_row_ids": kept_row_ids,
                "dropped_row_ids": dropped_row_ids,
                "cut_reasons": cut_reasons,
                "nested_anchor_indices": nested_anchor_indices,
                "missing_expected_continuations": missing_expected_continuations,
            }
        )

    problematic_references.sort(
        key=lambda item: (
            0 if str(item.get("status")) == "failed" else 1,
            int(item.get("index") or 0),
        )
    )
    return {
        "problematic_total": len(problematic_references),
        "problematic_references": problematic_references[
            :REFERENCE_FAILURE_AUDIT_LIMIT
        ],
        "truncated": len(problematic_references) > REFERENCE_FAILURE_AUDIT_LIMIT,
    }


def _build_numeric_coverage_summary(
    *,
    metadata_by_index: Dict[int, Dict[str, Any]],
    bibliography_lines: Sequence[Dict[str, Any]],
    reference_entries: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    detected_anchor_indices_all = [
        int(anchor.get("index"))
        for anchor in detect_reference_anchors_from_rows(bibliography_lines)
        if _to_int(anchor.get("index")) not in (None, 0)
    ]
    detected_anchor_indices = sorted(set(detected_anchor_indices_all))
    serialized_indices_all = [
        int(entry.get("index"))
        for entry in reference_entries
        if _to_int(entry.get("index")) not in (None, 0)
    ]
    serialized_indices = sorted(set(serialized_indices_all))
    expected_indices = sorted(metadata_by_index.keys())
    if not expected_indices:
        expected_indices = sorted(
            set(detected_anchor_indices) | set(serialized_indices)
        )
    failed_indices = sorted(
        {
            int(entry.get("index"))
            for entry in reference_entries
            if _to_int(entry.get("index")) not in (None, 0)
            and not bool((entry.get("final_decision") or {}).get("accepted"))
        }
    )
    missing_indices = sorted(
        index for index in expected_indices if index not in set(serialized_indices)
    )
    duplicate_indices = sorted(
        {
            index
            for index, count in Counter(detected_anchor_indices_all).items()
            if int(count) > 1
        }
        | {
            index
            for index, count in Counter(serialized_indices_all).items()
            if int(count) > 1
        }
    )
    return {
        "expected_indices": expected_indices,
        "detected_anchor_indices": detected_anchor_indices,
        "serialized_indices": serialized_indices,
        "failed_indices": failed_indices,
        "missing_indices": missing_indices,
        "duplicate_indices": duplicate_indices,
        "expected_total": len(expected_indices),
        "detected_anchor_total": len(detected_anchor_indices),
        "serialized_total": len(serialized_indices),
        "missing_total": len(missing_indices),
        "duplicate_total": len(duplicate_indices),
    }


def _build_contamination_diagnostics(
    *,
    bibliography_phase: Dict[str, Any],
    global_alerts: Dict[str, Any],
    reference_entries: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    appendix_like_re = re.compile(
        r"\b(?:appendix|appendices|supplement(?:ary)?|annex|acknowledg(?:e)?ments?)\b",
        re.IGNORECASE,
    )
    candidate_noise_sections = bibliography_phase.get("candidate_noise_sections") or []
    appendix_sections = [
        section
        for section in candidate_noise_sections
        if appendix_like_re.search(str(section.get("text") or ""))
    ]
    start_page = _to_int(bibliography_phase.get("start_page"))
    mixed_body_rows = [
        row
        for row in (global_alerts.get("body_text_mixed_in_bibliography") or [])
        if start_page is None
        or _to_int(row.get("page")) is None
        or int(row.get("page")) >= int(start_page)
    ]
    appendix_mixed_rows = [
        row
        for row in mixed_body_rows
        if appendix_like_re.search(str(row.get("text") or ""))
    ]
    tail_noise_samples: List[Dict[str, Any]] = []
    for entry in reference_entries:
        normalized_text = _normalize_text(str(entry.get("text") or ""))
        if not normalized_text:
            continue
        matched_marker = None
        for marker in REFERENCE_DIAGNOSTIC_TAIL_NOISE_MARKERS:
            if marker in normalized_text:
                matched_marker = marker
                break
        if not matched_marker:
            continue
        tail_noise_samples.append(
            {
                "index": entry.get("index"),
                "marker": matched_marker,
                "text": _short_debug_text(entry.get("text"), limit=180),
            }
        )
    return {
        "appendix_contamination_detected": bool(
            appendix_sections or appendix_mixed_rows
        ),
        "tail_noise_detected": bool(tail_noise_samples),
        "appendix_like_sections_count": len(appendix_sections),
        "mixed_body_rows_count": len(mixed_body_rows),
        "tail_noise_reference_count": len(tail_noise_samples),
        "appendix_samples": [
            {
                "page": section.get("page"),
                "text": _short_debug_text(section.get("text"), limit=160),
            }
            for section in appendix_sections[:6]
        ],
        "body_text_samples": [
            {
                "page": row.get("page"),
                "reason": row.get("reason"),
                "text": _short_debug_text(row.get("text"), limit=160),
            }
            for row in mixed_body_rows[:6]
        ],
        "tail_noise_samples": tail_noise_samples[:6],
    }


def _build_start_page_column_decision(
    *,
    bibliography_phase: Dict[str, Any],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    start_page = _to_int(bibliography_phase.get("start_page"))
    if not isinstance(start_page, int) or start_page < 0:
        return None
    rows_with_columns = bibliography_phase.get("rows_with_columns") or []
    start_page_rows = [
        row for row in rows_with_columns if _to_int(row.get("page")) == start_page
    ]
    selected_heading = (
        bibliography_phase.get("selected_heading")
        if isinstance(bibliography_phase.get("selected_heading"), dict)
        else None
    )
    selected_heading_box = (
        _normalize_box(selected_heading.get("box"))
        if isinstance(selected_heading, dict)
        else None
    )
    heading_page = _to_int((selected_heading or {}).get("page"))
    heading_column_id = str((selected_heading or {}).get("column_id") or "left")
    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    grouped_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in start_page_rows:
        grouped_rows[str(row.get("column_id") or "left")].append(row)
    anchors_on_start_page = detect_reference_anchors_from_rows(
        build_bibliography_reading_flow(start_page_rows)
    )
    anchor_columns = {
        str(anchor.get("column_id") or "left")
        for anchor in anchors_on_start_page
        if isinstance(anchor.get("page"), int) and int(anchor.get("page")) == start_page
    }
    accepted_segments = {
        str(segment.get("column_id") or "left"): segment
        for segment in bibliography_segments
        if _to_int(segment.get("page")) == start_page
    }
    column_ids = sorted(set(grouped_rows.keys()) | set(accepted_segments.keys()))
    column_decisions: List[Dict[str, Any]] = []
    for column_id in column_ids:
        column_rows = sorted(grouped_rows.get(column_id) or [], key=_line_sort_key)
        accepted_segment = accepted_segments.get(column_id)
        if accepted_segment is not None:
            top_source = accepted_segment.get("segment_top_source")
            top_y = None
            if (
                top_source == "heading_bottom"
                and selected_heading_box is not None
                and heading_page == start_page
                and column_id == heading_column_id
            ):
                top_y = round(
                    float(selected_heading_box[1]) + float(selected_heading_box[3]),
                    4,
                )
            elif column_rows:
                row_tops = [
                    _to_float(row.get("y0"))
                    for row in column_rows
                    if _to_float(row.get("y0")) is not None
                ]
                if row_tops:
                    top_y = round(min(row_tops), 4)
            if top_y is None:
                accepted_box = _normalize_box(accepted_segment.get("box"))
                if accepted_box is not None:
                    top_y = round(float(accepted_box[1]), 4)
            if top_source == "heading_bottom":
                reason = "accepted_using_selected_heading_boundary"
            else:
                reason = "accepted_using_column_rows_extent"
            column_decisions.append(
                {
                    "page": start_page,
                    "column_id": column_id,
                    "accepted": True,
                    "top_y": top_y,
                    "top_source": top_source,
                    "reason": reason,
                }
            )
            continue

        top_y = None
        if (
            selected_heading_box is not None
            and heading_page == start_page
            and column_id == heading_column_id
        ):
            top_y = round(
                float(selected_heading_box[1]) + float(selected_heading_box[3]),
                4,
            )
            top_source = "heading_bottom"
        elif column_rows:
            row_tops = [
                _to_float(row.get("y0"))
                for row in column_rows
                if _to_float(row.get("y0")) is not None
            ]
            top_y = round(min(row_tops), 4) if row_tops else None
            top_source = "column_rows_min_y"
        else:
            top_source = None

        if column_id not in anchor_columns and anchor_columns:
            reason = "column_without_anchor_on_start_page"
        elif (
            selected_heading is not None
            and heading_page == start_page
            and not anchor_columns
            and column_id != heading_column_id
        ):
            reason = "column_excluded_by_selected_heading"
        elif (
            selected_heading_box is not None
            and heading_page == start_page
            and column_id == heading_column_id
            and column_rows
            and all(
                (_to_float(row.get("y1")) or 0.0) < float(selected_heading_box[1])
                for row in column_rows
            )
        ):
            reason = "rows_above_selected_heading"
        elif not column_rows:
            reason = "column_without_rows"
        else:
            usable_rows = [
                row
                for row in column_rows
                if not _is_header_footer_row(row, artifact_info)
                or _match_reference_anchor_at_line_start(str(row.get("text") or ""))
            ]
            reason = (
                "no_rows_after_noise_filter"
                if not usable_rows
                else "column_not_selected"
            )
        column_decisions.append(
            {
                "page": start_page,
                "column_id": column_id,
                "accepted": False,
                "top_y": top_y,
                "top_source": top_source,
                "reason": reason,
            }
        )
    return {"page": start_page, "columns": column_decisions}


def build_references_data(
    *,
    references: Sequence[Dict[str, Any]],
    snippets: Sequence[Dict[str, Any]],
    layers: Dict[str, Any],
    references_numbered: bool = False,
    article_doi: str = "",
    source_filename: str = "",
    engine_used: str = "",
    debug_reference_detection: bool = False,
) -> Dict[str, Any]:
    logger.info(
        f"build_references_data: {len(references)} referencias, {len(snippets)} snippets. references_numbered={references_numbered}"
    )

    bibliography_items = _layer_items(layers, "bibliographies")
    token_items = _layer_items(layers, "tokens")
    row_items = _layer_items(layers, "rows")
    paragraph_items = _layer_items(layers, "paragraphs")
    section_items = _layer_items(layers, "sections")

    logger.debug(
        "Capas cargadas: %s bibliographies, %s tokens, %s rows, %s paragraphs, %s sections",
        len(bibliography_items),
        len(token_items),
        len(row_items),
        len(paragraph_items),
        len(section_items),
    )

    bibliography_phase = _build_bibliography_segments(
        rows=row_items,
        sections=section_items,
        bibliography_items=bibliography_items,
    )
    bibliography_segments = bibliography_phase.get("bibliography_segments") or []
    bibliography_anchor = bibliography_phase.get("bibliography_anchor")
    bibliography_rows_phase = _collect_bibliography_rows_from_segments(
        bibliography_phase.get("rows_with_columns") or [],
        bibliography_segments,
    )
    bibliography_lines = bibliography_rows_phase.get("rows") or []
    paragraph_phase = _build_paragraph_phase_payload(
        paragraph_items,
        bibliography_segments,
        bibliography_phase.get("page_splits") or {},
        bibliography_lines,
    )
    bibliography_start_page_zero_based = (
        bibliography_anchor[0] if bibliography_anchor is not None else None
    )
    crossref_context = _prepare_crossref_context(
        article_doi=article_doi,
        row_items=row_items,
        bibliography_start_page=bibliography_start_page_zero_based,
    )
    if bibliography_anchor is not None:
        logger.info(
            "Detección de bibliografía: página inicio %s",
            bibliography_anchor[0] + 1,
        )
    else:
        logger.warning("No se detectó un anchor bibliográfico estable.")

    line_based_references: Dict[int, Dict[str, Any]] = {}
    metadata_by_index: Dict[int, Dict[str, Any]] = {}
    row_phase_details: List[Dict[str, Any]] = []
    token_phase_details: List[Dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        idx = _entry_index(ref)
        if idx is None or idx <= 0:
            continue
        metadata_by_index[idx] = ref
    indexed_input_references = sum(
        1
        for ref in references
        if isinstance(ref, dict) and _entry_index(ref) is not None
    )
    if is_numbered_bibliography(bibliography_lines):
        min_required = 2 if indexed_input_references <= 6 else 3
        candidate_row_references = build_references_from_rows(
            bibliography_lines,
            metadata_by_index=metadata_by_index,
            bibliography_segments=bibliography_segments,
            token_items=token_items,
            crossref_context=crossref_context,
            row_debug_collector=row_phase_details,
            token_debug_collector=token_phase_details,
        )
        if len(candidate_row_references) >= min_required:
            line_based_references = candidate_row_references
        else:
            candidate_line_references = build_references_from_lines(bibliography_lines)
            if len(candidate_line_references) >= min_required:
                line_based_references = candidate_line_references

    reference_entries: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    contexts: List[Dict[str, Any]] = []

    references_by_index: Dict[int, str] = {}
    references_by_doi: Dict[str, str] = {}
    used_bibliography_ids: set[str] = set()
    fallback_geometry_candidates = bibliography_segments or bibliography_items

    for fallback_idx, ref in enumerate(references, start=1):
        if not isinstance(ref, dict):
            continue
        idx = _entry_index(ref)
        if idx is not None:
            ref_id = f"ref-{idx}"
            references_by_index[idx] = ref_id
        else:
            ref_id = f"ref-unlabeled-{fallback_idx}"
        doi_value = _normalize_doi(str(ref.get("doi") or ""))
        if doi_value:
            references_by_doi[doi_value] = ref_id

        raw_text = str(ref.get("raw") or ref.get("text") or "")
        line_reference = line_based_references.get(idx) if idx is not None else None
        structure_source = "fallback"
        local_row_count = 0
        local_anchor_detected = False
        reference_validation: Dict[str, Any] = {
            "match_score": 0.0,
            "mixed_reference_score": 0.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": "fallback_without_rows_structure",
        }
        validation_intermediate: Dict[str, Any] = {
            "match_score": 0.0,
            "mixed_reference_score": 0.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": "fallback_without_rows_structure",
        }
        decision_scores: Dict[str, Any] = {
            "inside_bibliography_zone": False,
            "inside_expected_column": False,
            "starts_with_anchor": False,
            "expected_anchor_index": idx,
            "has_nested_anchor": False,
            "header_noise_score": round(_score_header_noise(raw_text), 3),
            "crossref_match_score": 0.0,
            "doi_match_score": 0.0,
            "row_continuity_score": 0.0,
            "token_cleanup_confidence": 0.0,
            "cleanup_applied": False,
            "selected_candidate_source": structure_source,
            "final_score": 0.0,
            "accepted": False,
            "classification": "fallback_needed",
            "reason": "fallback_without_rows_structure",
        }
        final_decision: Dict[str, Any] = dict(decision_scores)
        crossref_match_payload: Dict[str, Any] = {
            "score": 0.0,
            "doi_match_score": 0.0,
            "match": None,
        }
        token_payload: Dict[str, Any] = {
            "raw_text": raw_text,
            "token_text": raw_text,
            "hybrid_text": raw_text,
            "final_text": raw_text,
            "selected_candidate_source": structure_source,
            "cleanups_applied": [],
            "candidate_scores": [],
            "token_cleanup_confidence": 0.0,
            "token_rows_used": 0,
            "order_guard_reasons": [],
            "backbone_source": "rows_raw",
            "backbone_text": raw_text,
            "backbone_local_edits": [],
            "local_token_edits": [],
            "new_word_split_detected": False,
            "lexical_degradation_detected": False,
            "accepted_local_edit_count": 0,
            "rejected_local_edit_count": 0,
        }
        anomalies: Dict[str, Any] = {"cut_reasons": [], "nested_anchor_indices": []}
        text_candidate_raw = raw_text
        if line_reference is not None:
            line_page = line_reference.get("page")
            page = line_page if isinstance(line_page, int) and line_page >= 0 else None
            box = _normalize_box(line_reference.get("box"))
            text = str(line_reference.get("text") or raw_text)
            text_candidate_raw = str(line_reference.get("text_raw") or raw_text)
            doi_from_text = _extract_doi(text)
            if doi_from_text and (not doi_value or len(doi_from_text) > len(doi_value)):
                doi_value = doi_from_text
            structure_source = str(line_reference.get("structure_source") or "rows")
            local_row_count = int(
                line_reference.get("local_row_count")
                or len(line_reference.get("rows") or [])
                or 0
            )
            local_anchor_detected = bool(line_reference.get("local_anchor_detected"))
            candidate_validation = line_reference.get("reference_validation")
            if isinstance(candidate_validation, dict):
                reference_validation = {
                    "match_score": float(
                        candidate_validation.get("match_score") or 0.0
                    ),
                    "mixed_reference_score": float(
                        candidate_validation.get("mixed_reference_score") or 0.0
                    ),
                    "has_nested_anchor": bool(
                        candidate_validation.get("has_nested_anchor")
                    ),
                    "accepted": bool(candidate_validation.get("accepted")),
                    "reason": candidate_validation.get("reason"),
                }
                validation_intermediate = {
                    "match_score": float(
                        candidate_validation.get("match_score") or 0.0
                    ),
                    "mixed_reference_score": float(
                        candidate_validation.get("mixed_reference_score") or 0.0
                    ),
                    "has_nested_anchor": bool(
                        candidate_validation.get("has_nested_anchor")
                    ),
                    "accepted": bool(
                        candidate_validation.get("intermediate_accepted")
                        if candidate_validation.get("intermediate_accepted") is not None
                        else candidate_validation.get("accepted")
                    ),
                    "reason": (
                        candidate_validation.get("intermediate_reason")
                        if candidate_validation.get("intermediate_reason") is not None
                        else candidate_validation.get("reason")
                    ),
                }
            if isinstance(line_reference.get("scores"), dict):
                decision_scores = dict(line_reference.get("scores") or {})
            if isinstance(line_reference.get("final_decision"), dict):
                final_decision = dict(line_reference.get("final_decision") or {})
            else:
                final_decision = dict(decision_scores)
            if isinstance(line_reference.get("crossref_match"), dict):
                crossref_match_payload = dict(
                    line_reference.get("crossref_match") or {}
                )
            if isinstance(line_reference.get("token_reconstruction"), dict):
                token_payload = dict(line_reference.get("token_reconstruction") or {})
            if isinstance(line_reference.get("anomalies"), dict):
                anomalies = dict(line_reference.get("anomalies") or {})
            if TRACE_REFERENCES:
                logger.debug(
                    f"Referencia {ref_id} reconstruida desde rows "
                    f"(source={structure_source}, rows={local_row_count})"
                )
        else:
            best_candidate: Optional[Dict[str, Any]] = None
            best_score = 0.0
            for candidate in fallback_geometry_candidates:
                candidate_id = str(candidate.get("id") or candidate.get("page") or "")
                if candidate_id in used_bibliography_ids:
                    continue
                score = _reference_match_score(
                    raw_text,
                    idx or 0,
                    doi_value,
                    str(candidate.get("text") or ""),
                )
                if score > best_score:
                    best_score = score
                    best_candidate = candidate

            if best_candidate and best_score >= 0.35:
                candidate_id = str(
                    best_candidate.get("id") or best_candidate.get("page") or ""
                )
                if candidate_id:
                    used_bibliography_ids.add(candidate_id)
                page = best_candidate["page"]
                box = _normalize_box(best_candidate.get("box"))
                text = str(best_candidate.get("text") or raw_text)
                doi_from_text = _extract_doi(text)
                if doi_from_text and (
                    not doi_value or len(doi_from_text) > len(doi_value)
                ):
                    doi_value = doi_from_text
                structure_source = "bibliography_box_fallback"
                decision_scores.update(
                    {
                        "inside_bibliography_zone": True,
                        "final_score": round(min(best_score / 5.0, 0.52), 3),
                        "selected_candidate_source": structure_source,
                        "reason": "bibliography_box_fallback",
                    }
                )
                final_decision = dict(decision_scores)
                if TRACE_REFERENCES:
                    logger.debug(
                        f"Referencia {ref_id} emparejada con caja de bibliografía "
                        f"(score: {best_score:.2f})"
                    )
            else:
                page = None
                box = None
                text = raw_text
                doi_from_text = _extract_doi(text)
                if doi_from_text and (
                    not doi_value or len(doi_from_text) > len(doi_value)
                ):
                    doi_value = doi_from_text
                structure_source = "raw_reference_fallback"
                decision_scores.update(
                    {
                        "selected_candidate_source": structure_source,
                        "reason": "raw_reference_fallback",
                    }
                )
                final_decision = dict(decision_scores)
                if TRACE_REFERENCES:
                    logger.debug(
                        f"Referencia {ref_id} sin caja de bibliografía emparejada."
                    )

        if text:
            crossref_match_payload = _match_reference_against_crossref(
                reference_text=text,
                reference_doi=doi_value,
                crossref_context=crossref_context,
            )
            decision_scores["crossref_match_score"] = round(
                float(crossref_match_payload.get("score") or 0.0),
                3,
            )
            decision_scores["doi_match_score"] = round(
                float(crossref_match_payload.get("doi_match_score") or 0.0),
                3,
            )
            final_decision["crossref_match_score"] = decision_scores[
                "crossref_match_score"
            ]
            final_decision["doi_match_score"] = decision_scores["doi_match_score"]

        final_decision = dict(final_decision or decision_scores)
        final_decision.setdefault("cleanup_applied", False)
        final_decision.setdefault("selected_candidate_source", structure_source)
        final_decision.setdefault("accepted", False)
        final_decision.setdefault("classification", "fallback_needed")
        final_decision.setdefault("reason", "fallback_without_rows_structure")
        final_decision.setdefault("final_score", 0.0)
        decision_scores = dict(final_decision)
        reference_validation = _sync_reference_validation_with_final_decision(
            reference_validation,
            final_decision,
        )

        reference_entries.append(
            {
                "id": f"reference-entry-{ref_id}",
                "ref_id": ref_id,
                "index": idx,
                "text": text,
                "text_candidate_raw": text_candidate_raw,
                "page": page,
                "box": box,
                "doi": doi_value or None,
                "structure_source": structure_source,
                "local_row_count": max(0, local_row_count),
                "local_anchor_detected": bool(local_anchor_detected),
                "reference_validation": reference_validation,
                "validation_intermediate": validation_intermediate,
                "scores": decision_scores,
                "final_decision": final_decision,
                "crossref_match": crossref_match_payload,
                "token_reconstruction": token_payload,
                "anomalies": anomalies,
            }
        )

    reference_debug_steps = _build_reference_debug_steps(
        rows_with_columns=bibliography_phase.get("rows_with_columns") or [],
        page_splits=bibliography_phase.get("page_splits") or {},
        heading_candidates=bibliography_phase.get("heading_candidates") or [],
        selected_heading=bibliography_phase.get("selected_heading"),
        bibliography_segments=bibliography_segments,
        bibliography_rows_debug=bibliography_rows_phase.get("debug_rows") or [],
        row_phase_details=row_phase_details,
        reference_entries=reference_entries,
    )

    contexts_seen: set[Tuple[str, int, str]] = set()
    seen_mentions: set[Tuple[Any, ...]] = set()
    mention_text_key_max_len = 220
    bibliography_zone_items = bibliography_segments or bibliography_items

    for snippet_idx, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        snippet_text = str(snippet.get("snippet") or snippet.get("text") or "")
        if not snippet_text:
            continue

        ref_ids: List[str] = []
        doi_in_snippet = _extract_doi(snippet_text)
        if doi_in_snippet and doi_in_snippet in references_by_doi:
            ref_ids.append(references_by_doi[doi_in_snippet])

        if references_numbered:
            for number in _parse_citation_numbers(snippet_text):
                ref_id = references_by_index.get(number)
                if ref_id:
                    ref_ids.append(ref_id)

        # Dedupe preservando orden.
        seen_ref_ids: set[str] = set()
        dedup_ref_ids: List[str] = []
        for ref_id in ref_ids:
            if ref_id in seen_ref_ids:
                continue
            seen_ref_ids.add(ref_id)
            dedup_ref_ids.append(ref_id)
        if not dedup_ref_ids:
            if TRACE_REFERENCES:
                logger.debug(
                    f"Descartando snippet {snippet_idx}: sin ref_ids resueltas. '{snippet_text[:50]}'"
                )
            continue

        page_hint = _normalize_page_zero_based(snippet.get("page"))
        mention_anchor = _pick_best_text_box(
            snippet_text,
            page_hint,
            token_items,
            row_items,
            paragraph_items,
        )
        mention_page = (
            mention_anchor["page"] if mention_anchor is not None else page_hint
        )
        mention_box = mention_anchor["box"] if mention_anchor is not None else None
        mention_y = _to_float(mention_box[1]) if mention_box is not None else None

        if mention_y is not None and mention_y < 0.05:
            continue
        if mention_y is not None and mention_y > 0.95:
            continue
        if is_inside_bibliography(
            {"page": mention_page, "box": mention_box},
            bibliography_zone_items,
        ):
            if TRACE_REFERENCES:
                logger.debug(
                    f"Descartando snippet {snippet_idx}: está dentro de la bibliografía."
                )
            continue
        if is_after_bibliography(mention_page, mention_y, bibliography_anchor):
            if TRACE_REFERENCES:
                logger.debug(
                    f"Descartando snippet {snippet_idx}: es posterior al inicio de bibliografía."
                )
            continue

        for mention_pos, ref_id in enumerate(dedup_ref_ids, start=1):
            quantized_mention_box = _quantize_box(mention_box)
            if quantized_mention_box is not None:
                dedup_key: Tuple[Any, ...] = (
                    "box",
                    ref_id,
                    mention_page,
                    quantized_mention_box,
                )
            else:
                dedup_key = (
                    "text",
                    ref_id,
                    mention_page,
                    _normalize_mention_text(snippet_text)[:mention_text_key_max_len],
                )

            if dedup_key in seen_mentions:
                continue
            seen_mentions.add(dedup_key)

            mention_id = f"citation-mention-{snippet_idx}-{mention_pos}-{ref_id}"
            mention_item = {
                "id": mention_id,
                "ref_id": ref_id,
                "text": snippet_text,
                "page": mention_page,
                "box": mention_box,
            }
            citations.append(mention_item)

            if mention_page is None or mention_box is None:
                continue
            page_paragraphs = [
                item for item in paragraph_items if item["page"] == mention_page
            ]
            if not page_paragraphs:
                continue

            best_context = _pick_context_paragraph(mention_box, page_paragraphs)
            if best_context is None:
                continue

            rounded_box = ",".join(f"{value:.4f}" for value in best_context["box"])
            seen_key = (ref_id, mention_page, rounded_box)
            if seen_key in contexts_seen:
                continue
            contexts_seen.add(seen_key)

            contexts.append(
                {
                    "id": f"citation-context-{mention_id}",
                    "ref_id": ref_id,
                    "text": str(best_context.get("text") or snippet_text),
                    "page": best_context["page"],
                    "box": best_context["box"],
                }
            )

    # Limpieza final: solo entradas con página/caja válidas para overlays.
    def _clean_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned: List[Dict[str, Any]] = []
        for item in items:
            page = item.get("page")
            box = _normalize_box(item.get("box"))
            next_item = dict(item)
            next_item["page"] = page if isinstance(page, int) and page >= 0 else None
            next_item["box"] = box
            cleaned.append(next_item)
        return cleaned

    reference_entries = _clean_items(reference_entries)
    citations = _clean_items(citations)
    contexts = _clean_items(contexts)
    max_reference_index = max(references_by_index.keys(), default=0)
    if max_reference_index <= 0:
        max_reference_index = len(reference_entries)
    bibliography_start_page = (
        bibliography_anchor[0] + 1 if bibliography_anchor is not None else None
    )
    anchors_out_of_sequence: List[Dict[str, int]] = []
    sorted_reference_indices = [
        int(entry.get("index"))
        for entry in reference_entries
        if isinstance(entry.get("index"), int)
    ]
    for previous, current in zip(
        sorted_reference_indices, sorted_reference_indices[1:]
    ):
        if current != previous + 1:
            anchors_out_of_sequence.append(
                {"expected": previous + 1, "actual": current}
            )

    references_mixed = [
        str(entry.get("ref_id") or "")
        for entry in reference_entries
        if bool((entry.get("reference_validation") or {}).get("has_nested_anchor"))
    ]
    crossed_columns = [
        str(entry.get("ref_id") or "")
        for entry in reference_entries
        if isinstance(entry.get("scores"), dict)
        and entry["scores"].get("inside_expected_column") is False
    ]
    truncated_references = [
        str(entry.get("ref_id") or "")
        for entry in reference_entries
        if str(entry.get("text") or "").rstrip().endswith("-")
        or len(str(entry.get("text") or "").strip()) < 40
    ]
    tokens_in_bibliography = [
        token
        for token in token_items
        if _row_in_any_segment(token, bibliography_zone_items)
    ]
    repeated_headers = sorted(
        _build_repeating_page_artifacts(
            bibliography_phase.get("rows_with_columns") or []
        ).get("repeated_text_keys", set())
    )
    bibliography_noise_candidates = [
        row
        for row in (bibliography_rows_phase.get("debug_rows") or [])
        if not row.get("included")
        and row.get("reason")
        in {"header_footer_noise", "outside_bibliography_segments"}
    ]
    global_alerts = {
        "repeated_headers_detected": repeated_headers,
        "view_publication_stats_detected": any(
            "view publication stats" in _normalize_text(str(row.get("text") or ""))
            for row in bibliography_rows_phase.get("debug_rows") or []
        ),
        "body_text_mixed_in_bibliography": [
            {
                "page": row.get("page"),
                "text": str(row.get("text") or "")[:240],
                "reason": row.get("reason"),
            }
            for row in bibliography_noise_candidates[:12]
        ],
        "anchors_out_of_sequence": anchors_out_of_sequence,
        "references_truncated": truncated_references,
        "references_mixed": references_mixed,
        "columns_crossed": crossed_columns,
    }

    debug_payload = None
    if debug_reference_detection:
        raw_rows_layer = (
            layers.get("rows") if isinstance(layers.get("rows"), list) else []
        )
        raw_row_metadata_map = _build_raw_row_metadata_map(raw_rows_layer)
        document_diagnostics = _build_document_diagnostics(
            bibliography_rows_debug=bibliography_rows_phase.get("debug_rows") or [],
            bibliography_lines=bibliography_lines,
            bibliography_segments=bibliography_segments,
            selected_heading=(
                bibliography_phase.get("selected_heading")
                if isinstance(bibliography_phase.get("selected_heading"), dict)
                else None
            ),
            start_page=_to_int(bibliography_phase.get("start_page")),
        )
        phase_diagnostics = _build_phase_diagnostics(
            bibliography_phase=bibliography_phase,
            bibliography_rows_phase=bibliography_rows_phase,
            bibliography_lines=bibliography_lines,
            row_phase_details=row_phase_details,
            reference_entries=reference_entries,
            document_diagnostics=document_diagnostics,
        )
        row_rejection_audit = _build_row_rejection_audit(
            bibliography_rows_debug=bibliography_rows_phase.get("debug_rows") or [],
            row_phase_details=row_phase_details,
            rows_with_columns=bibliography_phase.get("rows_with_columns") or [],
            raw_row_metadata_map=raw_row_metadata_map,
            start_page=_to_int(bibliography_phase.get("start_page")),
        )
        reference_failure_audit = _build_reference_failure_audit(
            reference_entries=reference_entries,
            row_phase_details=row_phase_details,
        )
        numeric_coverage_summary = None
        if document_diagnostics.get("reference_style_detected") == "numeric":
            numeric_coverage_summary = _build_numeric_coverage_summary(
                metadata_by_index=metadata_by_index,
                bibliography_lines=bibliography_lines,
                reference_entries=reference_entries,
            )
        current_numeric_metrics = None
        current_numeric_metrics_v3 = None
        experimental_numeric_pipeline_v2 = None
        experimental_numeric_pipeline_v3 = None
        if references_numbered and metadata_by_index:
            detected_anchor_indices_for_current = [
                int(anchor.get("index"))
                for anchor in detect_reference_anchors_from_rows(bibliography_lines)
                if _to_int(anchor.get("index")) not in (None, 0)
            ]
            duplicate_indices_for_current = (
                numeric_coverage_summary.get("duplicate_indices") or []
                if isinstance(numeric_coverage_summary, dict)
                else [
                    index
                    for index, count in Counter(
                        detected_anchor_indices_for_current
                    ).items()
                    if int(count) > 1
                ]
            )
            current_numeric_metrics = _build_numeric_pipeline_metrics(
                expected_indices=sorted(metadata_by_index.keys()),
                reference_entries=reference_entries,
                detected_anchor_indices=detected_anchor_indices_for_current,
                duplicate_indices=duplicate_indices_for_current,
            )
            current_numeric_metrics_v3 = _build_numeric_pipeline_metrics_v3(
                expected_indices=sorted(metadata_by_index.keys()),
                reference_entries=reference_entries,
                detected_anchor_indices=detected_anchor_indices_for_current,
                duplicate_indices=duplicate_indices_for_current,
            )
            experimental_numeric_pipeline_v2 = _run_numeric_reference_pipeline_v2(
                references=references,
                metadata_by_index=metadata_by_index,
                rows=row_items,
                sections=section_items,
                bibliography_items=bibliography_items,
                token_items=token_items,
                current_reference_entries=reference_entries,
                current_numeric_metrics=current_numeric_metrics,
                crossref_context=crossref_context,
            )
            experimental_numeric_pipeline_v3 = _run_numeric_reference_pipeline_v3(
                references=references,
                metadata_by_index=metadata_by_index,
                rows=row_items,
                sections=section_items,
                bibliography_items=bibliography_items,
                token_items=token_items,
                current_reference_entries=reference_entries,
                current_numeric_metrics=(current_numeric_metrics_v3 or {}),
                crossref_context=crossref_context,
            )
        contamination_diagnostics = _build_contamination_diagnostics(
            bibliography_phase=bibliography_phase,
            global_alerts=global_alerts,
            reference_entries=reference_entries,
        )
        start_page_column_decision = _build_start_page_column_decision(
            bibliography_phase=bibliography_phase,
            bibliography_segments=bibliography_segments,
        )
        debug_payload = {
            "metadata": {
                "file_name": str(source_filename or ""),
                "article_doi": crossref_context.get("article_doi"),
                "engine_used": str(engine_used or ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "debug_mode": True,
                "pipeline_version": REFERENCE_PIPELINE_VERSION,
                "bibliography_start_page": bibliography_start_page,
                "references_total_detected": len(reference_entries),
                "total_rows_in_bibliography": len(bibliography_lines),
                "total_tokens_in_bibliography": len(tokens_in_bibliography),
                "crossref_available": bool(crossref_context.get("crossref_available")),
                "crossref_reference_count": int(
                    crossref_context.get("crossref_reference_count") or 0
                ),
            },
            "phases": {
                "crossref": {
                    "doi_detected": crossref_context.get("article_doi"),
                    "queried": bool(crossref_context.get("crossref_queried")),
                    "crossref_available": bool(
                        crossref_context.get("crossref_available")
                    ),
                    "article_metadata": crossref_context.get(
                        "crossref_article_metadata"
                    ),
                    "reference_candidates": crossref_context.get(
                        "crossref_reference_candidates"
                    )
                    or [],
                    "reference_count": int(
                        crossref_context.get("crossref_reference_count") or 0
                    ),
                    "matching_auxiliary": [
                        {
                            "ref_id": entry.get("ref_id"),
                            "index": entry.get("index"),
                            "crossref_match_score": (entry.get("scores") or {}).get(
                                "crossref_match_score"
                            ),
                            "doi_match_score": (entry.get("scores") or {}).get(
                                "doi_match_score"
                            ),
                            "match": (entry.get("crossref_match") or {}).get("match"),
                        }
                        for entry in reference_entries
                    ],
                },
                "bibliography_zone": {
                    "segments": [
                        {
                            "page": segment.get("page"),
                            "column_id": segment.get("column_id"),
                            "box": _serialize_box(segment.get("box")),
                            "source": segment.get("source"),
                            "confidence": segment.get("confidence"),
                            "raw_text": segment.get("raw_text"),
                            "accepted_because": segment.get("source"),
                        }
                        for segment in bibliography_segments
                    ],
                    "layer_boxes": [
                        _serialize_layer_item(item) for item in bibliography_items
                    ],
                },
                "sections": {
                    "relevant_sections": bibliography_phase.get("section_records")
                    or [],
                    "selected_start": (
                        {
                            "page": bibliography_phase["selected_heading"].get("page"),
                            "column_id": bibliography_phase["selected_heading"].get(
                                "column_id"
                            ),
                            "text": bibliography_phase["selected_heading"].get("text"),
                            "box": _serialize_box(
                                bibliography_phase["selected_heading"].get("box")
                            ),
                            "source": bibliography_phase["selected_heading"].get(
                                "source"
                            ),
                        }
                        if isinstance(bibliography_phase.get("selected_heading"), dict)
                        else None
                    ),
                    "candidate_noise": bibliography_phase.get(
                        "candidate_noise_sections"
                    )
                    or [],
                },
                "paragraphs": paragraph_phase,
                "rows": {
                    "rows_considered": bibliography_rows_phase.get("debug_rows") or [],
                    "reference_blocks": row_phase_details,
                },
                "tokens": {
                    "tokens_total_in_bibliography": len(tokens_in_bibliography),
                    "references": token_phase_details,
                },
            },
            "references": [dict(entry) for entry in reference_entries],
            "alerts": global_alerts,
            "document_diagnostics": document_diagnostics,
            "phase_diagnostics": phase_diagnostics,
            "row_rejection_audit": row_rejection_audit,
            "reference_failure_audit": reference_failure_audit,
            "contamination_diagnostics": contamination_diagnostics,
            "start_page_column_decision": start_page_column_decision,
        }
        if numeric_coverage_summary is not None:
            debug_payload["numeric_coverage_summary"] = numeric_coverage_summary
        if current_numeric_metrics is not None:
            debug_payload["numeric_pipeline_current_metrics"] = current_numeric_metrics
        if current_numeric_metrics_v3 is not None:
            debug_payload["numeric_pipeline_current_metrics_v3"] = (
                current_numeric_metrics_v3
            )
        if experimental_numeric_pipeline_v2 is not None:
            debug_payload[NUMERIC_REFERENCE_PIPELINE_V2_NAME] = (
                experimental_numeric_pipeline_v2
            )
        if experimental_numeric_pipeline_v3 is not None:
            debug_payload[NUMERIC_REFERENCE_PIPELINE_V3_NAME] = (
                experimental_numeric_pipeline_v3
            )

    logger.info(
        f"Completado build_references_data: {len(reference_entries)} reference_entries, {len(citations)} citations, {len(contexts)} contexts construidos."
    )

    return {
        "references": reference_entries,
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric" if references_numbered else "non_numeric",
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page,
        "bibliography_segments": bibliography_segments,
        "crossref_available": bool(crossref_context.get("crossref_available")),
        "article_doi": crossref_context.get("article_doi"),
        "crossref_article_metadata": crossref_context.get("crossref_article_metadata"),
        "crossref_reference_candidates": crossref_context.get(
            "crossref_reference_candidates"
        )
        or [],
        "crossref_reference_count": int(
            crossref_context.get("crossref_reference_count") or 0
        ),
        "global_alerts": global_alerts,
        "debug_payload": debug_payload,
        "reference_debug_steps": reference_debug_steps,
    }


def finalize_reference_detection_debug_payload(
    debug_payload: Optional[Dict[str, Any]],
    *,
    references: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(debug_payload, dict):
        return None
    finalized_references: List[Dict[str, Any]] = []
    for entry in references:
        if not isinstance(entry, dict):
            continue
        final_decision = (
            entry.get("final_decision")
            if isinstance(entry.get("final_decision"), dict)
            else (entry.get("scores") if isinstance(entry.get("scores"), dict) else {})
        )
        scores = dict(final_decision)
        validation = (
            entry.get("reference_validation")
            if isinstance(entry.get("reference_validation"), dict)
            else {}
        )
        validation_intermediate = (
            entry.get("validation_intermediate")
            if isinstance(entry.get("validation_intermediate"), dict)
            else {
                "match_score": validation.get("match_score"),
                "mixed_reference_score": validation.get("mixed_reference_score"),
                "has_nested_anchor": validation.get("has_nested_anchor"),
                "accepted": validation.get("intermediate_accepted"),
                "reason": validation.get("intermediate_reason"),
            }
        )
        crossref_match = (
            entry.get("crossref_match")
            if isinstance(entry.get("crossref_match"), dict)
            else {}
        )
        token_info = (
            entry.get("token_reconstruction")
            if isinstance(entry.get("token_reconstruction"), dict)
            else {}
        )
        enrichment_validation = (
            entry.get("enrichment_validation")
            if isinstance(entry.get("enrichment_validation"), dict)
            else None
        )
        enrichment_candidate = (
            entry.get("enrichment_candidate")
            if isinstance(entry.get("enrichment_candidate"), dict)
            else None
        )
        finalized_references.append(
            {
                "ref_id": entry.get("ref_id"),
                "index": entry.get("index"),
                "source": entry.get("structure_source"),
                "structure_source": entry.get("structure_source"),
                "anchor_row_id": entry.get("anchor_row_id"),
                "body_start_row_id": entry.get("body_start_row_id"),
                "layout_type": entry.get("layout_type"),
                "anchor_type": entry.get("anchor_type"),
                "used_marker_only_anchor": bool(entry.get("used_marker_only_anchor")),
                "anchor_to_body_link_reason": entry.get("anchor_to_body_link_reason"),
                "candidate_text_raw": entry.get("text_candidate_raw")
                or entry.get("text"),
                "token_candidate_text": token_info.get("token_text"),
                "hybrid_candidate_text": token_info.get("hybrid_text"),
                "backbone_text": token_info.get("backbone_text"),
                "final_text": entry.get("text"),
                "doi_detected": entry.get("doi"),
                "doi_enriched": entry.get("doi"),
                "match_with_crossref": crossref_match.get("match"),
                "accepted": bool(scores.get("accepted")),
                "rejected": not bool(scores.get("accepted")),
                "reason": scores.get("reason"),
                "final_decision": scores,
                "validation_intermediate": validation_intermediate,
                "scores": scores,
                "cleanups_applied": token_info.get("cleanups_applied") or [],
                "selected_candidate_source": token_info.get(
                    "selected_candidate_source"
                ),
                "order_similarity_to_rows": token_info.get("order_similarity_to_rows"),
                "order_guard_reasons": token_info.get("order_guard_reasons") or [],
                "backbone_source": token_info.get("backbone_source"),
                "candidate_scores": token_info.get("candidate_scores") or [],
                "backbone_local_edits": token_info.get("backbone_local_edits") or [],
                "local_token_edits": token_info.get("local_token_edits") or [],
                "new_word_split_detected": bool(
                    token_info.get("new_word_split_detected")
                ),
                "lexical_degradation_detected": bool(
                    token_info.get("lexical_degradation_detected")
                ),
                "accepted_local_edit_count": int(
                    token_info.get("accepted_local_edit_count") or 0
                ),
                "rejected_local_edit_count": int(
                    token_info.get("rejected_local_edit_count") or 0
                ),
                "enrichment_validation": enrichment_validation,
                "enrichment_candidate": enrichment_candidate,
                "enrichment_accepted": entry.get("enrichment_accepted"),
                "anomalies": (
                    entry.get("anomalies")
                    if isinstance(entry.get("anomalies"), dict)
                    else {}
                ),
                "fallback_used": "fallback" in str(entry.get("structure_source") or ""),
            }
        )
    debug_payload["references"] = finalized_references
    debug_payload.setdefault("metadata", {})
    debug_payload["metadata"]["references_total_detected"] = len(finalized_references)
    return debug_payload


def write_reference_detection_debug_json(
    debug_payload: Optional[Dict[str, Any]],
    *,
    source_filename: str,
) -> Optional[str]:
    if not isinstance(debug_payload, dict):
        return None
    safe_base_name = _sanitize_filename_component(
        Path(str(source_filename or "reference_debug.pdf")).stem
    )
    debug_timestamp = int(datetime.now(timezone.utc).timestamp())
    output_dir = REFERENCE_DEBUG_DIR / safe_base_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        output_dir
        / f"{REFERENCE_DEBUG_FILE_PREFIX}{debug_timestamp}{REFERENCE_DEBUG_FILE_EXTENSION}"
    )
    output_path.write_text(
        json.dumps(debug_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)

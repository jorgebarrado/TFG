from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from citations.logging_utils import get_logger

logger = get_logger("citations.references")
TRACE_REFERENCES = os.getenv("TRACE_REFERENCES", "0") == "1"
from .crossref_client import fetch_work_by_doi as crossref_fetch_work_by_doi
from .reference_reconciliation import validate_reference_against_metadata

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
INLINE_CITATION_REGEX = re.compile(
    r"\[\s*(\d+(?:\s*[,;]\s*\d+|\s*[-\u2013\u2014]\s*\d+)*)\s*\]"
)
NUMBERED_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:\[\s*(?P<bracket>\d{1,3})\s*\]|(?P<plain>\d{1,3})\s*[\.\)])"
    r"(?=\s|[A-ZÀ-ß]|$)"
)
NUMBERED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")
REFERENCE_BLOCK_ANCHOR_RE = re.compile(
    r"(?<!\w)(?:\[\s*(?P<bracket>\d{1,3})\s*\]|(?P<plain>\d{1,3})\s*[\.\)])"
    r"(?=\s|[A-ZÀ-ß]|$)"
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
REFERENCE_GLUE_RE = re.compile(
    r"\b[A-Za-zÀ-ÿ]{4,}[a-zà-ÿ][A-ZÀ-ß][A-Za-zÀ-ÿ]{2,}\b"
)
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
REFERENCE_AUTHOR_LEAD_RE = re.compile(
    r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,2}\s+"
    r"(?:[A-ZÀ-Ý](?:[A-Za-zÀ-ÿ'’.-]+)?[,\.]|et al\b)"
)
REFERENCE_AUTHOR_PREFIX_LEAD_RE = re.compile(
    r"^(?:da|de|del|della|der|des|di|dos|das|du|la|le|van|von)\s+"
    r"[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,2}\s+"
    r"(?:[A-ZÀ-Ý](?:[A-Za-zÀ-ÿ'’.-]+)?[,\.]|et al\b)",
    re.IGNORECASE,
)
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
REFERENCE_PIPELINE_VERSION = "references-phased-v3"
REFERENCE_DEBUG_DIR = (
    Path(__file__).resolve().parents[3] / "tmp" / "reference_debug"
)


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
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


def _page_index_value(raw_page: Any) -> Optional[int]:
    try:
        page_index = int(raw_page)
    except (TypeError, ValueError):
        return None
    if page_index < 0:
        return None
    return page_index


def _page_number_from_index(raw_page: Any) -> Optional[int]:
    page_index = _page_index_value(raw_page)
    if page_index is None:
        return None
    return page_index + 1


def _page_debug_fields(raw_page: Any) -> Dict[str, Optional[int]]:
    page_index = _page_index_value(raw_page)
    return {
        "page_index": page_index,
        "page_number": _page_number_from_index(page_index),
    }


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


def _pick_preferred_reference_input(
    candidates: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    valid_candidates = [candidate for candidate in candidates if isinstance(candidate, dict)]
    if not valid_candidates:
        return None
    return max(
        valid_candidates,
        key=lambda candidate: (
            len(str(candidate.get("raw") or candidate.get("text") or "")),
            1 if _extract_doi(str(candidate.get("raw") or candidate.get("text") or "")) else 0,
            1 if REFERENCE_YEAR_RE.search(str(candidate.get("raw") or candidate.get("text") or "")) else 0,
        ),
    )


def _reference_anchor_index_from_match(match: Optional[re.Match[str]]) -> Optional[int]:
    if match is None:
        return None
    raw_value = match.groupdict().get("bracket") or match.groupdict().get("plain")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _looks_like_reference_lead_text(text: str) -> bool:
    value = str(text or "").lstrip(" \t\n\r-–—;:,.")
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(
        (
            "doi",
            "http",
            "www",
            "pmid",
            "available from",
            "vol.",
            "volume",
            "p.",
            "pp.",
            "article",
        )
    ):
        return False
    if re.match(r"^\d", value):
        return False
    tokens = [
        token.strip("()[]{}.,;:'\"")
        for token in value.split()
        if token.strip("()[]{}.,;:'\"")
    ]
    if len(tokens) >= 2 and ("," in value[:60] or ". " in value[:30]):
        second_token = tokens[1]
        if second_token[:1].isupper():
            return True
        if (
            tokens[0].lower()
            in {"da", "de", "del", "della", "der", "des", "di", "dos", "das", "du", "la", "le", "van", "von"}
            and len(tokens) >= 3
            and tokens[2][:1].isupper()
        ):
            return True
    return bool(
        REFERENCE_AUTHOR_LEAD_RE.match(value)
        or REFERENCE_AUTHOR_PREFIX_LEAD_RE.match(value)
    )


def _extract_leading_reference_index(text: str) -> Optional[int]:
    value = str(text or "")
    match = NUMBERED_REFERENCE_LINE_RE.match(value)
    if match is None:
        return None
    if not _looks_like_reference_lead_text(value[match.end() :]):
        return None
    return _reference_anchor_index_from_match(match)


def _find_reference_block_anchor_matches(text: str) -> List[re.Match[str]]:
    matches: List[re.Match[str]] = []
    for match in REFERENCE_BLOCK_ANCHOR_RE.finditer(text or ""):
        if not _looks_like_reference_lead_text(str(text or "")[match.end() :]):
            continue
        matches.append(match)
    return matches


def _extract_reference_anchor_numbers(text: str) -> List[int]:
    numbers: List[int] = []
    leading_index = _extract_leading_reference_index(text)
    if leading_index is not None:
        numbers.append(leading_index)
    for match in NUMBERED_ANCHOR_RE.finditer(text or ""):
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in numbers:
            numbers.append(number)
    return numbers


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


def _boxes_overlap_vertically(box_a: Sequence[float], box_b: Sequence[float]) -> bool:
    ay0 = float(box_a[1])
    ay1 = ay0 + float(box_a[3])
    by0 = float(box_b[1])
    by1 = by0 + float(box_b[3])
    return max(ay0, by0) <= min(ay1, by1)


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
    if not text or _is_reference_noise_text(text):
        return []

    matches = _find_reference_block_anchor_matches(text)
    if not matches:
        return [dict(row)]

    spans: List[Tuple[int, int]] = []
    if matches[0].start() > 0:
        spans.append((0, matches[0].start()))
    for idx, match in enumerate(matches):
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        spans.append((match.start(), next_start))

    parts: List[Dict[str, Any]] = []
    for part_idx, (start_char, end_char) in enumerate(spans):
        segment_text = text[start_char:end_char].strip()
        if not segment_text or _is_reference_noise_text(segment_text):
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
    page_index = _page_index_value(item.get("page"))
    serialized = {
        "id": str(item.get("id") or ""),
        "text": str(item.get("text") or ""),
        "page": page_index,
        "page_index": page_index,
        "page_number": _page_number_from_index(page_index),
        "box": _serialize_box(item.get("box")),
    }
    if "column_id" in item:
        serialized["column_id"] = item.get("column_id")
    if "anchor_index" in item:
        serialized["anchor_index"] = item.get("anchor_index")
    return serialized


def _is_reference_heading_text(value: str) -> bool:
    return bool(REFERENCE_SECTION_HEADING_RE.match(str(value or "").strip()))


def _extract_inline_anchor_numbers(text: str) -> List[int]:
    return _extract_reference_anchor_numbers(text)


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
            or NUMBERED_REFERENCE_LINE_RE.match(str(text or ""))
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


def _normalize_crossref_reference_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
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
    max_page = bibliography_start_page if isinstance(bibliography_start_page, int) else 3
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
            token in normalized for token in ("doi:", "https://doi.org/", "acm isbn", "article")
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
    repeated_keys = {
        key
        for key, pages in pages_per_key.items()
        if len(pages) >= 2
    }
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
    if NUMBERED_REFERENCE_LINE_RE.match(text):
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


def _detect_page_column_split(rows: Sequence[Dict[str, Any]]) -> Optional[float]:
    if len(rows) < 4:
        return None
    content_rows = [
        row
        for row in rows
        if (
            (_to_float(row.get("y0")) or (_normalize_box(row.get("box")) or [0.0, 0.0, 0.0, 0.0])[1]) > 0.08
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
        if _to_float(row.get("x0")) is not None or _normalize_box(row.get("box")) is not None
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
            existing_column_id = str(next_row.get("column_id") or "").strip().lower()
            if existing_column_id in {"left", "right"}:
                column_id = existing_column_id
            else:
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


def _collect_page_split_map(rows: Sequence[Dict[str, Any]]) -> Dict[int, Optional[float]]:
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
            if not isinstance(page, int) or box is None or not _is_reference_heading_text(text):
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
    return sorted(candidates, key=lambda item: (item["page"], item["box"][1], item["box"][0]))


def _resolve_box_column_id(
    page: int,
    box: Sequence[float],
    page_splits: Dict[int, Optional[float]],
) -> str:
    split = page_splits.get(page)
    x_center = float(box[0]) + float(box[2]) / 2.0
    if split is None:
        return "left"
    return "left" if x_center < split else "right"


def _score_reference_like_text(text: str) -> float:
    value = str(text or "").strip()
    if not value:
        return 0.0
    normalized = _normalize_text(value)
    if not normalized:
        return 0.0

    score = 0.0
    if _extract_leading_reference_index(value) is not None:
        score += 0.34
    if _extract_doi(value):
        score += 0.24
    if REFERENCE_YEAR_RE.search(value):
        score += 0.14
    if re.search(
        r"\b(?:journal|proceedings|conference|review|educ|trans|press|springer|ieee|acm|scand|technol|comput|curric)\b",
        normalized,
    ):
        score += 0.14
    if re.search(
        r"\b[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,2},\s*(?:[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+|et al)\b",
        value,
    ):
        score += 0.16
    elif re.search(r"\b[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:,\s*[A-ZÀ-Ý])", value):
        score += 0.12
    if re.search(r"\b\d{1,4}\s*(?:[–-]\s*\d{1,4}|:\s*\d{1,4})\b", value):
        score += 0.08
    if len(value) >= 80:
        score += 0.06
    if PAGE_NUMBER_ONLY_RE.match(value):
        score -= 0.24
    if re.fullmatch(r"(?:\d+(?:\.\d+)?\s*){2,}", value):
        score -= 0.26
    return round(max(0.0, min(score, 1.0)), 3)


def _compute_reference_density(texts: Sequence[str]) -> Dict[str, Any]:
    normalized_texts = [str(text or "").strip() for text in texts if str(text or "").strip()]
    if not normalized_texts:
        return {
            "score": 0.0,
            "mean_score": 0.0,
            "strong_ratio": 0.0,
            "row_count": 0,
        }
    scores = [_score_reference_like_text(text) for text in normalized_texts]
    mean_score = sum(scores) / max(len(scores), 1)
    strong_ratio = sum(1 for score in scores if score >= 0.45) / max(len(scores), 1)
    density_score = min(1.0, mean_score * 0.7 + strong_ratio * 0.3)
    return {
        "score": round(density_score, 3),
        "mean_score": round(mean_score, 3),
        "strong_ratio": round(strong_ratio, 3),
        "row_count": len(normalized_texts),
    }


def _segment_reading_order_key(segment: Dict[str, Any]) -> Tuple[int, int, float, float]:
    page_index = _page_index_value(segment.get("page"))
    box = _normalize_box(segment.get("box")) or [0.0, 0.0, 0.0, 0.0]
    column_id = str(segment.get("column_id") or "left")
    column_order = 0 if column_id == "left" else 1 if column_id == "right" else 2
    return (
        int(page_index if page_index is not None else 10**6),
        column_order,
        float(box[1]),
        float(box[0]),
    )


def _sections_for_segment(
    segment: Dict[str, Any],
    sections: Sequence[Dict[str, Any]],
    *,
    start_page: Optional[int],
    heading_y: Optional[float],
) -> List[Dict[str, Any]]:
    page_index = _page_index_value(segment.get("page"))
    segment_box = _normalize_box(segment.get("box"))
    if page_index is None or segment_box is None:
        return []

    related: List[Dict[str, Any]] = []
    segment_y0 = float(segment_box[1])
    for section in sections:
        section_page = _page_index_value(section.get("page"))
        section_box = _normalize_box(section.get("box"))
        text = str(section.get("text") or "").strip()
        if (
            section_page != page_index
            or section_box is None
            or not text
            or _is_reference_heading_text(text)
        ):
            continue
        if (
            start_page is not None
            and page_index == start_page
            and heading_y is not None
            and float(section_box[1]) + float(section_box[3]) < float(heading_y)
        ):
            continue
        overlaps = _boxes_overlap_vertically(segment_box, section_box)
        near_segment_start = abs(float(section_box[1]) - segment_y0) <= 0.08
        if overlaps or near_segment_start:
            related.append(_serialize_layer_item(section))
    return related


def _paragraphs_for_segment(
    segment: Dict[str, Any],
    paragraphs: Sequence[Dict[str, Any]],
    page_splits: Dict[int, Optional[float]],
) -> List[Dict[str, Any]]:
    page_index = _page_index_value(segment.get("page"))
    segment_box = _normalize_box(segment.get("box"))
    segment_column = str(segment.get("column_id") or "left")
    if page_index is None or segment_box is None:
        return []

    related: List[Dict[str, Any]] = []
    for paragraph in paragraphs:
        paragraph_page = _page_index_value(paragraph.get("page"))
        paragraph_box = _normalize_box(paragraph.get("box"))
        text = str(paragraph.get("text") or "").strip()
        if paragraph_page != page_index or paragraph_box is None or not text:
            continue
        if _resolve_box_column_id(page_index, paragraph_box, page_splits) != segment_column:
            continue
        if not _boxes_overlap_vertically(segment_box, paragraph_box):
            continue
        related.append(
            {
                "page": page_index,
                "page_index": page_index,
                "page_number": _page_number_from_index(page_index),
                "column_id": segment_column,
                "box": _serialize_box(paragraph_box),
                "text": text,
            }
        )
    return related


def _reference_row_has_terminal_signal(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _extract_doi(value) or re.search(r"https?://\S+", value, flags=re.IGNORECASE):
        return True
    if re.search(r"\b\d{1,4}(?:[–-]\d{1,4}|:\d{1,6})\b", value) and value.rstrip().endswith("."):
        return True
    normalized = _normalize_text(value)
    return bool(
        REFERENCE_YEAR_RE.search(value)
        and re.search(
            r"\b(?:journal|review|educ|trans|proceedings|conference|press|springer|ieee|acm|technol|comput)\b",
            normalized,
        )
    )


def _trim_bibliography_segment_tail_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    artifact_info: Dict[str, Any],
) -> Dict[str, Any]:
    local_rows: List[Dict[str, Any]] = []
    for position, row in enumerate(rows):
        next_row = dict(row)
        next_row["flow_position"] = position
        local_rows.append(next_row)

    anchors = detect_reference_anchors_from_rows(local_rows)
    if not anchors:
        return {
            "rows": list(rows),
            "tail_trim_applied": False,
            "tail_trim_reason": None,
            "tail_trim_removed_text": "",
            "tail_trim_removed_rows_count": 0,
            "tail_trim_scope": "segment_tail_after_last_anchor",
        }

    last_anchor = anchors[-1]
    last_anchor_position = int(last_anchor.get("position", -1))
    if last_anchor_position < 0 or last_anchor_position >= len(local_rows) - 1:
        return {
            "rows": list(rows),
            "tail_trim_applied": False,
            "tail_trim_reason": None,
            "tail_trim_removed_text": "",
            "tail_trim_removed_rows_count": 0,
            "tail_trim_scope": "segment_tail_after_last_anchor",
        }

    diagnostics = build_reference_rows_between_anchors(
        ordered_rows=local_rows,
        current_anchor=last_anchor,
        next_anchor=None,
        artifact_info=artifact_info,
        include_diagnostics=True,
    )
    selected_tail_rows = diagnostics.get("rows") or []
    if not selected_tail_rows:
        return {
            "rows": list(rows),
            "tail_trim_applied": False,
            "tail_trim_reason": None,
            "tail_trim_removed_text": "",
            "tail_trim_removed_rows_count": 0,
            "tail_trim_scope": "segment_tail_after_last_anchor",
        }

    last_selected_row_id = str(selected_tail_rows[-1].get("id") or "")
    keep_until = len(local_rows)
    for position, row in enumerate(local_rows):
        if str(row.get("id") or "") == last_selected_row_id:
            keep_until = position + 1
            break

    kept_rows = list(rows[:keep_until])
    removed_rows = list(rows[keep_until:])
    rejected_tail_decision = next(
        (
            decision
            for decision in (diagnostics.get("row_decisions") or [])
            if not decision.get("included")
            and int(decision.get("position", -1)) >= last_anchor_position
        ),
        None,
    )
    tail_trim_reason = (
        rejected_tail_decision.get("reason")
        if isinstance(rejected_tail_decision, dict)
        else None
    ) or (
        (diagnostics.get("cut_reasons") or [None])[0]
        if removed_rows
        else None
    )
    return {
        "rows": kept_rows,
        "tail_trim_applied": bool(removed_rows),
        "tail_trim_reason": tail_trim_reason,
        "tail_trim_removed_text": _clean_reference_text(removed_rows),
        "tail_trim_removed_rows_count": len(removed_rows),
        "tail_trim_scope": "segment_tail_after_last_anchor",
    }


def _trim_bibliography_segments_with_structure(
    *,
    bibliography_segments: Sequence[Dict[str, Any]],
    rows_with_columns: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    paragraphs: Sequence[Dict[str, Any]],
    page_splits: Dict[int, Optional[float]],
    start_page: Optional[int],
    selected_heading: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    row_by_id = {
        str(row.get("id") or ""): row for row in rows_with_columns if str(row.get("id") or "")
    }
    ordered_segments = sorted(
        [dict(segment) for segment in bibliography_segments],
        key=_segment_reading_order_key,
    )
    heading_y = None
    if isinstance(selected_heading, dict) and _normalize_box(selected_heading.get("box")) is not None:
        heading_y = float(_normalize_box(selected_heading.get("box"))[1])

    accepted_segments: List[Dict[str, Any]] = []
    reading_order_blocks: List[Dict[str, Any]] = []
    bibliography_end_candidates: List[Dict[str, Any]] = []
    end_of_bibliography_signals: Optional[Dict[str, Any]] = None
    bibliography_end_reason = "kept_all_candidate_segments"
    previous_last_anchor: Optional[int] = None
    anchorless_run = 0

    for flow_position, segment in enumerate(ordered_segments):
        row_ids = [str(value) for value in segment.get("row_ids") or [] if str(value)]
        row_texts = [
            str(row_by_id[row_id].get("text") or "")
            for row_id in row_ids
            if row_id in row_by_id
        ]
        density = _compute_reference_density(row_texts)
        paragraph_records = _paragraphs_for_segment(segment, paragraphs, page_splits)
        paragraph_density = _compute_reference_density(
            [record.get("text") or "" for record in paragraph_records]
        )
        related_sections = _sections_for_segment(
            segment,
            sections,
            start_page=start_page,
            heading_y=heading_y,
        )
        leading_anchor_indices = sorted(
            {
                int(value)
                for value in (segment.get("leading_anchor_indices") or [])
                if isinstance(value, int) and value > 0
            }
        )

        anchor_continuity_status = "no_anchors"
        if leading_anchor_indices:
            first_anchor = leading_anchor_indices[0]
            if previous_last_anchor is None:
                anchor_continuity_status = (
                    "start_anchor_sequence" if first_anchor <= 10 else "late_anchor_start"
                )
            elif first_anchor <= previous_last_anchor + 1:
                anchor_continuity_status = "continuous"
            elif first_anchor <= previous_last_anchor + 3 and density["score"] >= 0.62:
                anchor_continuity_status = "near_continuous_high_density"
            else:
                anchor_continuity_status = "anchor_gap"

        section_transition_detected = bool(related_sections)
        continuity_from_previous = bool(
            accepted_segments
            and (
                _page_index_value(segment.get("page"))
                == _page_index_value(accepted_segments[-1].get("page"))
                or (
                    _page_index_value(segment.get("page")) is not None
                    and _page_index_value(accepted_segments[-1].get("page")) is not None
                    and _page_index_value(segment.get("page"))
                    == _page_index_value(accepted_segments[-1].get("page")) + 1
                )
            )
        )

        keep_segment = True
        keep_reason = "bibliography_continuity_preserved"
        if leading_anchor_indices:
            anchorless_run = 0
            if anchor_continuity_status == "anchor_gap" and density["score"] < 0.58:
                keep_segment = False
                keep_reason = "anchor_continuity_lost"
        else:
            anchorless_run += 1
            if (
                previous_last_anchor is not None
                and section_transition_detected
                and density["score"] < 0.4
                and paragraph_density["score"] < 0.4
            ):
                keep_segment = False
                keep_reason = "section_transition_without_bibliography_density"
            elif (
                previous_last_anchor is not None
                and anchorless_run >= 1
                and density["score"] < 0.3
                and paragraph_density["score"] < 0.34
            ):
                keep_segment = False
                keep_reason = "anchor_continuity_lost"

        if (
            keep_segment
            and section_transition_detected
            and not leading_anchor_indices
            and density["score"] < 0.32
            and paragraph_density["score"] < 0.36
        ):
            keep_segment = False
            keep_reason = "section_transition_low_density"

        block_record = {
            "flow_position": flow_position,
            "page": _page_index_value(segment.get("page")),
            "page_index": _page_index_value(segment.get("page")),
            "page_number": _page_number_from_index(segment.get("page")),
            "column_id": segment.get("column_id"),
            "box": _serialize_box(segment.get("box")),
            "row_count": int(segment.get("row_count") or len(row_ids)),
            "first_anchor_index": leading_anchor_indices[0] if leading_anchor_indices else None,
            "last_anchor_index": leading_anchor_indices[-1] if leading_anchor_indices else None,
            "anchor_count": len(leading_anchor_indices),
            "anchor_continuity_status": anchor_continuity_status,
            "bibliography_density": density["score"],
            "paragraph_bibliography_density": paragraph_density["score"],
            "section_transition_detected": section_transition_detected,
            "continuity_from_previous": continuity_from_previous,
            "accepted": keep_segment,
            "reason": keep_reason,
            "related_sections": related_sections,
            "related_paragraph_count": len(paragraph_records),
            "raw_text": segment.get("raw_text"),
        }
        reading_order_blocks.append(block_record)
        bibliography_end_candidates.append(dict(block_record))
        if not keep_segment:
            end_of_bibliography_signals = dict(block_record)
            bibliography_end_reason = keep_reason
            break

        accepted_segments.append(segment)
        if leading_anchor_indices:
            previous_last_anchor = leading_anchor_indices[-1]

    column_reading_order: List[Dict[str, Any]] = []
    for page_index in sorted(
        {
            _page_index_value(segment.get("page"))
            for segment in accepted_segments
            if _page_index_value(segment.get("page")) is not None
        }
    ):
        page_segments = [
            segment
            for segment in accepted_segments
            if _page_index_value(segment.get("page")) == page_index
        ]
        column_reading_order.append(
            {
                "page": page_index,
                "page_index": page_index,
                "page_number": _page_number_from_index(page_index),
                "columns": [str(segment.get("column_id") or "left") for segment in page_segments],
            }
        )

    return {
        "accepted_segments": accepted_segments,
        "reading_order_blocks": reading_order_blocks,
        "column_reading_order": column_reading_order,
        "bibliography_end_candidates": bibliography_end_candidates,
        "end_of_bibliography_signals": end_of_bibliography_signals,
        "bibliography_end_reason": bibliography_end_reason,
    }


def _build_bibliography_segments(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
    paragraphs: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rows_with_columns = _assign_column_ids(rows)
    page_splits = _collect_page_split_map(rows_with_columns)
    max_page = max(
        (int(row.get("page")) for row in rows_with_columns if isinstance(row.get("page"), int)),
        default=-1,
    )
    tail_page_span = max(3, int((max_page + 1) * 0.35))
    tail_start_page = max(0, max_page - tail_page_span + 1)
    heading_candidates = _detect_reference_heading_candidates(
        rows_with_columns,
        sections,
        page_splits,
    )
    anchors = detect_reference_anchors_from_rows(build_bibliography_reading_flow(rows_with_columns))
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
            if isinstance(item.get("page"), int) and int(item.get("page")) >= tail_start_page
        }
    )
    start_page_candidates = [candidate["page"] for candidate in tail_heading_candidates]
    start_page_candidates.extend(anchor.get("page") for anchor in tail_anchor_rows[:4])
    if not start_page_candidates and tail_bibliography_pages:
        start_page_candidates.append(tail_bibliography_pages[0])
    if not start_page_candidates:
        start_page_candidates.extend(candidate["page"] for candidate in heading_candidates)
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
        record["kind"] = "heading" if _is_reference_heading_text(section.get("text") or "") else "section"
        if score >= 0.5 and page >= int(start_page or page):
            record["candidate_noise"] = True
            candidate_noise_sections.append(record)
        else:
            record["candidate_noise"] = False
        section_records.append(record)

    for (page, column_id), page_rows in sorted(grouped_rows.items()):
        ordered_rows = sorted(page_rows, key=_line_sort_key)
        filtered_rows: List[Dict[str, Any]] = []
        for row in ordered_rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            if _is_header_footer_row(row, artifact_info) and not NUMBERED_REFERENCE_LINE_RE.match(text):
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
                    apply_heading_cutoff = (
                        not anchor_columns_by_page.get(page) or column_id == heading_column
                    )
                    if apply_heading_cutoff and float(row.get("y1") or 0.0) < heading_y:
                        continue
            filtered_rows.append(row)
        if not filtered_rows:
            continue
        tail_trim = _trim_bibliography_segment_tail_rows(
            filtered_rows,
            artifact_info=artifact_info,
        )
        filtered_rows = tail_trim.get("rows") or []
        if not filtered_rows:
            continue
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
        if anchor_columns_by_page.get(page) and column_id in anchor_columns_by_page[page]:
            confidence += 0.22
        if page == start_page and selected_heading is not None:
            confidence += 0.12
        if overlap_with_layer >= 0.2:
            confidence += min(overlap_with_layer, 0.12)
        leading_anchor_indices = [
            value
            for value in (
                _extract_leading_reference_index(str(row.get("text") or ""))
                for row in filtered_rows
            )
            if isinstance(value, int) and value > 0
        ]
        density = _compute_reference_density(
            [str(row.get("text") or "") for row in filtered_rows]
        )
        bibliography_segments.append(
            {
                "page": page,
                "column_id": column_id,
                "box": segment_box,
                "source": "+".join(
                    part
                    for part, enabled in (
                        ("rows", True),
                        ("sections", page == start_page and selected_heading is not None),
                        ("bibliography_layer", overlap_with_layer >= 0.2),
                    )
                    if enabled
                ),
                "confidence": round(min(confidence, 0.98), 3),
                "row_count": len(filtered_rows),
                "reference_density": density["score"],
                "reference_density_mean": density["mean_score"],
                "reference_density_strong_ratio": density["strong_ratio"],
                "leading_anchor_indices": leading_anchor_indices,
                "raw_text": _clean_reference_text(filtered_rows),
                "row_ids": [str(row.get("id") or "") for row in filtered_rows],
                "tail_trim_applied": bool(tail_trim.get("tail_trim_applied")),
                "tail_trim_reason": tail_trim.get("tail_trim_reason"),
                "tail_trim_removed_text": tail_trim.get("tail_trim_removed_text") or "",
                "tail_trim_removed_rows_count": int(
                    tail_trim.get("tail_trim_removed_rows_count") or 0
                ),
                "tail_trim_scope": tail_trim.get("tail_trim_scope"),
            }
        )

    structure_trim = _trim_bibliography_segments_with_structure(
        bibliography_segments=bibliography_segments,
        rows_with_columns=rows_with_columns,
        sections=sections,
        paragraphs=paragraphs,
        page_splits=page_splits,
        start_page=start_page,
        selected_heading=selected_heading,
    )
    bibliography_segments = structure_trim.get("accepted_segments") or []

    bibliography_anchor = None
    if bibliography_segments:
        first_segment = min(
            bibliography_segments,
            key=lambda item: (int(item["page"]), float(item["box"][1]), float(item["box"][0])),
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
        "reading_order_blocks": structure_trim.get("reading_order_blocks") or [],
        "column_reading_order": structure_trim.get("column_reading_order") or [],
        "bibliography_end_candidates": structure_trim.get("bibliography_end_candidates")
        or [],
        "end_of_bibliography_signals": structure_trim.get("end_of_bibliography_signals"),
        "bibliography_end_reason": structure_trim.get("bibliography_end_reason"),
    }


def _match_row_to_bibliography_segment(
    row: Dict[str, Any],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    page_index = _page_index_value(row.get("page"))
    box = _normalize_box(row.get("box"))
    row_column_id = str(row.get("column_id") or "").strip().lower() or None
    detail: Dict[str, Any] = {
        "reference_page_index": page_index,
        "reference_page_number": _page_number_from_index(page_index),
        "reference_box": _serialize_box(box),
        "reference_column_id": row_column_id,
        "matched_segment_index": None,
        "matched_segment_page_index": None,
        "matched_segment_page_number": None,
        "matched_segment_box": None,
        "matched_segment_column_id": None,
        "page_index_match": False,
        "column_id_match": None,
        "contains_match": False,
        "box_overlap_ratio": 0.0,
        "box_overlap_match": False,
        "inside_bibliography_zone": False,
        "inside_bibliography_zone_reason": "invalid_reference_geometry",
    }
    if page_index is None:
        detail["inside_bibliography_zone_reason"] = "invalid_reference_page_index"
        return detail
    if box is None:
        detail["inside_bibliography_zone_reason"] = "invalid_reference_box"
        return detail

    best_candidate: Optional[Dict[str, Any]] = None
    best_rank: Optional[Tuple[int, int, int, float]] = None
    for segment_index, segment in enumerate(bibliography_segments):
        segment_page_index = _page_index_value(segment.get("page"))
        segment_box = _normalize_box(segment.get("box"))
        segment_column_id = str(segment.get("column_id") or "").strip().lower() or None
        page_index_match = bool(
            segment_page_index is not None and segment_page_index == page_index
        )
        column_id_match = (
            None
            if not page_index_match
            else not (segment_column_id and row_column_id) or segment_column_id == row_column_id
        )
        contains_match = False
        box_overlap_ratio = 0.0
        box_overlap_match = False
        if page_index_match and segment_box is not None:
            contains_match = _contains_box(segment_box, box)
            box_overlap_ratio = round(_overlap_ratio(segment_box, box), 3)
            box_overlap_match = bool(contains_match or box_overlap_ratio >= 0.6)
        inside_bibliography_zone = bool(
            page_index_match
            and box_overlap_match
            and (column_id_match is None or column_id_match)
        )
        if inside_bibliography_zone:
            reason = "matched_bibliography_segment"
        elif not page_index_match:
            reason = "page_index_mismatch"
        elif column_id_match is False:
            reason = "column_id_mismatch"
        elif not box_overlap_match:
            reason = "box_not_inside_segment"
        else:
            reason = "segment_not_matched"
        candidate = {
            "reference_page_index": page_index,
            "reference_page_number": _page_number_from_index(page_index),
            "reference_box": _serialize_box(box),
            "reference_column_id": row_column_id,
            "matched_segment_index": segment_index,
            "matched_segment_page_index": segment_page_index,
            "matched_segment_page_number": _page_number_from_index(segment_page_index),
            "matched_segment_box": _serialize_box(segment_box),
            "matched_segment_column_id": segment_column_id,
            "page_index_match": page_index_match,
            "column_id_match": column_id_match,
            "contains_match": contains_match,
            "box_overlap_ratio": box_overlap_ratio,
            "box_overlap_match": box_overlap_match,
            "inside_bibliography_zone": inside_bibliography_zone,
            "inside_bibliography_zone_reason": reason,
        }
        rank = (
            1 if page_index_match else 0,
            1 if box_overlap_match else 0,
            1 if (column_id_match is True or column_id_match is None) else 0,
            float(box_overlap_ratio),
        )
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_candidate = candidate

    if best_candidate is not None:
        return best_candidate
    detail["inside_bibliography_zone_reason"] = "no_bibliography_segments_available"
    return detail


def _row_in_any_segment(
    row: Dict[str, Any],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> bool:
    return bool(
        _match_row_to_bibliography_segment(row, bibliography_segments).get(
            "inside_bibliography_zone"
        )
    )


def _build_bibliography_zone_match_detail(
    rows: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    row_matches = [
        _match_row_to_bibliography_segment(row, bibliography_segments)
        for row in rows
        if isinstance(row, dict)
    ]
    inside_bibliography_zone = bool(
        row_matches and all(match.get("inside_bibliography_zone") for match in row_matches)
    )
    failing_match = next(
        (match for match in row_matches if not match.get("inside_bibliography_zone")),
        None,
    )
    primary_match = row_matches[0] if row_matches else {}
    if inside_bibliography_zone:
        reason = "all_rows_inside_bibliography_segments"
    elif isinstance(failing_match, dict):
        reason = str(
            failing_match.get("inside_bibliography_zone_reason")
            or "bibliography_segment_mismatch"
        )
    else:
        reason = "no_rows_to_evaluate"
    return {
        "reference_page_index": primary_match.get("reference_page_index"),
        "reference_page_number": primary_match.get("reference_page_number"),
        "reference_box": primary_match.get("reference_box"),
        "matched_segment_index": primary_match.get("matched_segment_index"),
        "matched_segment_page_index": primary_match.get("matched_segment_page_index"),
        "matched_segment_page_number": primary_match.get("matched_segment_page_number"),
        "matched_segment_box": primary_match.get("matched_segment_box"),
        "matched_segment_column_id": primary_match.get("matched_segment_column_id"),
        "page_index_match": bool(
            row_matches and all(match.get("page_index_match") for match in row_matches)
        ),
        "box_overlap_match": bool(
            row_matches and all(match.get("box_overlap_match") for match in row_matches)
        ),
        "inside_bibliography_zone": inside_bibliography_zone,
        "inside_bibliography_zone_reason": reason,
        "row_matches": row_matches,
    }


def _collect_bibliography_rows_from_segments(
    rows_with_columns: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    selected_rows: List[Dict[str, Any]] = []
    debug_rows: List[Dict[str, Any]] = []
    seen: set[Tuple[int, int, str]] = set()
    for row in rows_with_columns:
        text = str(row.get("text") or "").strip()
        page = row.get("page")
        box = _normalize_box(row.get("box"))
        anchor_numbers = _extract_inline_anchor_numbers(text)
        bibliography_zone_match_detail = _match_row_to_bibliography_segment(
            row,
            bibliography_segments,
        )
        in_zone = bool(bibliography_zone_match_detail.get("inside_bibliography_zone"))
        header_footer = _is_header_footer_row(row, artifact_info)
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
                "page": _page_index_value(page),
                **_page_debug_fields(page),
                "box": _serialize_box(box),
                "text": text,
                "column_id": row.get("column_id"),
                "anchor_index": anchor_numbers[0] if anchor_numbers else None,
                "in_bibliography_zone": in_zone,
                "bibliography_zone_match_detail": bibliography_zone_match_detail,
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
            }
        )

    ordered_rows = build_bibliography_reading_flow(selected_rows)
    exploded: List[Dict[str, Any]] = []
    rows_sorted_for_bibliography: List[Dict[str, Any]] = []
    for row in ordered_rows:
        rows_sorted_for_bibliography.append(
            {
                "id": str(row.get("id") or ""),
                "page": _page_index_value(row.get("page")),
                **_page_debug_fields(row.get("page")),
                "column_id": row.get("column_id"),
                "flow_position": row.get("flow_position"),
                "box": _serialize_box(row.get("box")),
                "text": str(row.get("text") or ""),
            }
        )
        exploded.extend(_split_reference_row_on_anchors(row))
    return {
        "rows": exploded,
        "debug_rows": debug_rows,
        "rows_sorted_for_bibliography": rows_sorted_for_bibliography,
    }


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
        column_id = _resolve_box_column_id(page, box, page_splits)
        paragraph_records.append(
            {
                "id": str(paragraph.get("id") or ""),
                "page": page,
                "page_index": page,
                "page_number": _page_number_from_index(page),
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
        overlap = len(row_tokens.intersection(paragraph_tokens)) / max(len(row_tokens), 1)
        if overlap < 0.45:
            inconsistencies.append("paragraph_text_diverges_from_rows")
    return {
        "paragraphs": paragraph_records,
        "ordered_text": paragraph_text[:4000],
        "inconsistencies": inconsistencies,
    }


def _index_tokens_by_page(tokens: Sequence[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    indexed: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for token in tokens:
        page = token.get("page")
        box = _normalize_box(token.get("box"))
        text = str(token.get("text") or "")
        if not isinstance(page, int) or box is None or not text:
            continue
        indexed[page].append({"text": text, "box": box, "page": page})
    for page in list(indexed.keys()):
        indexed[page].sort(key=lambda item: (float(item["box"][1]), float(item["box"][0])))
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
        if row_y0 - 0.004 <= token_center_y <= row_y1 + 0.004 and float(box[0]) - 0.003 <= token_center_x <= float(box[0]) + float(box[2]) + 0.003:
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
        if re.search(r"(https?://|doi\.org/|10\.\d{4,9}/)\Z", merged, flags=re.IGNORECASE):
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
            current[:year_match.start()].strip(),
            cleanups=cleanups,
        )
        year_value = year_match.group(0)
        body_suffix = _normalize_reference_body_section(
            current[year_match.end():].lstrip(" ."),
            cleanups=cleanups,
        )
        current = (
            f"{author_prefix} {year_value}".strip()
            if author_prefix
            else year_value
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
            or re.search(r"10\.\d{4,9}/\S+\s+[A-Za-z0-9]", normalized, flags=re.IGNORECASE)
        ),
        "trailing_after_doi": bool(REFERENCE_TRAILING_AFTER_DOI_RE.search(normalized)),
        "fragment_after_pages": bool(REFERENCE_FRAGMENT_AFTER_PAGES_RE.search(normalized)),
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
        if suffix_key and lowered.endswith(suffix_key) and len(lowered) > len(suffix_key) + 4:
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
        if any(symbol in context for symbol in ("(", ")", "[", "]", '"', "”", "’", "'", ".", ",", ";", ":")):
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
        if suffix_key and lowered.endswith(suffix_key) and len(lowered) > len(suffix_key) + 4:
            return True
    for connector in REFERENCE_GLUE_SUFFIX_CONNECTORS:
        connector_key = _reference_edit_word_key(connector)
        if connector_key and lowered.endswith(connector_key) and len(lowered) > len(connector_key) + 4:
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
    row_evidence = _build_reference_edit_evidence(list(row_evidence_texts) + [base_value])
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

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base_value, candidate_value).get_opcodes():
        if tag == "equal":
            output_parts.append(base_value[i1:i2])
            continue
        before_segment = base_value[i1:i2]
        after_segment = candidate_value[j1:j2]
        prefix = base_value[max(0, i1 - 48):i1]
        suffix = base_value[i2:min(len(base_value), i2 + 48)]
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
            hit for hit in new_split_hits if hit.get("bigram_key") not in previous_split_hits
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
        elif edit_type in {"author_spacing", "publisher_spacing", "word_spacing"} and strong_pattern:
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


def _detect_reference_punctuation_anomalies(text: str) -> List[str]:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    anomalies: List[str] = []
    if re.search(r"\b(?:19|20)\d{2}\.\s+(?:and|to|through)\b", value, flags=re.IGNORECASE):
        anomalies.append("year_connector_dot")
    if re.search(r"\b(?:19|20)\d{2}\.\s*-\s*(?:19|20)\d{2}\b", value):
        anomalies.append("year_range_dot")
    if re.search(r"\b(?:19|20)\d{2}\.\s*;\s*", value):
        anomalies.append("year_semicolon_dot")
    if re.search(r"\b(?:19|20)\d{2}\.\s*/\s*\d{2}(?=\))", value):
        anomalies.append("year_month_slash_dot")
    return anomalies


def _build_reference_fine_cleanup_candidate(text: str) -> Dict[str, Any]:
    cleanups: set[str] = set()
    current = re.sub(r"\s+", " ", str(text or "")).strip()
    anomalies = _detect_reference_punctuation_anomalies(current)
    current = _apply_regex_substitution(
        current,
        r"\b((?:19|20)\d{2})\.\s+(and|to|through)\b",
        r"\1 \2",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
        flags=re.IGNORECASE,
    )
    current = _apply_regex_substitution(
        current,
        r"\b((?:19|20)\d{2})\.\s*-\s*((?:19|20)\d{2})\b",
        r"\1-\2",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\b((?:19|20)\d{2})\.\s*;\s*",
        r"\1; ",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    current = _apply_regex_substitution(
        current,
        r"\b((?:19|20)\d{2})\.\s*/\s*(\d{2})(?=\))",
        r"\1/\2",
        cleanups=cleanups,
        cleanup_name="punctuation_spacing",
    )
    return {
        "text": re.sub(r"\s+", " ", current).strip(),
        "cleanups_applied": sorted(cleanups),
        "anomalies_detected": anomalies,
    }


def _apply_reference_fine_cleanup(
    *,
    base_text: str,
    row_evidence_texts: Sequence[str],
    token_evidence_texts: Sequence[str],
) -> Dict[str, Any]:
    base_value = re.sub(r"\s+", " ", str(base_text or "")).strip()
    if not base_value:
        return {
            "text": "",
            "accepted_edits": [],
            "rejected_edits": [],
            "cleanups_applied": [],
            "punctuation_normalization_applied": False,
            "punctuation_anomalies_detected": [],
        }
    candidate = _build_reference_fine_cleanup_candidate(base_value)
    validated = _apply_validated_reference_local_edits(
        base_text=base_value,
        candidate_text=str(candidate.get("text") or base_value),
        row_evidence_texts=row_evidence_texts,
        token_evidence_texts=token_evidence_texts,
        edit_scope="fine_cleanup",
    )
    edits = validated.get("edits") or []
    accepted_edits = [edit for edit in edits if edit.get("status") == "accepted"]
    rejected_edits = [edit for edit in edits if edit.get("status") == "rejected"]
    return {
        "text": str(validated.get("text") or base_value).strip(),
        "accepted_edits": accepted_edits,
        "rejected_edits": rejected_edits,
        "cleanups_applied": validated.get("cleanups_applied") or [],
        "punctuation_normalization_applied": bool(accepted_edits),
        "punctuation_anomalies_detected": candidate.get("anomalies_detected") or [],
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
    if (
        candidate_metrics.get("fragment_after_pages")
        and not backbone_metrics.get("fragment_after_pages")
    ):
        order_penalty += 0.22
        reasons.append("pages_fragment_reordered")
    if (
        candidate_metrics.get("trailing_venue_fragment")
        and not backbone_metrics.get("trailing_venue_fragment")
    ):
        order_penalty += 0.24
        reasons.append("venue_fragment_reordered")
    if (
        candidate_metrics.get("trailing_after_doi")
        and not backbone_metrics.get("trailing_after_doi")
    ):
        order_penalty += 0.24
        reasons.append("doi_tail_reordered")
    cleanup_only = bool(signature_match and order_similarity >= 0.995)
    eligible = bool(signature_match and order_similarity >= 0.985 and order_penalty <= 0.18)
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
            if token_available and token_text and token_text != raw_text and not guard["eligible"]:
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
        if best_evaluation is None or combined_score > best_evaluation["combined_score"]:
            best_evaluation = evaluation

    if best_evaluation is None:
        return {
            "source": "rows_raw",
            "text": "",
            "candidate_scores": evaluations,
            "cleanups_applied": [],
        }

    raw_evaluation = evaluation_by_source.get("rows_raw") or best_evaluation
    backbone_evaluation = raw_evaluation
    hybrid_evaluation = evaluation_by_source.get("rows_hybrid")

    selected_evaluation = raw_evaluation
    if (
        hybrid_evaluation is not None
        and hybrid_evaluation.get("backbone_eligible")
        and str(hybrid_evaluation.get("text") or "") != str(raw_evaluation.get("text") or "")
        and hybrid_evaluation["combined_score"] >= raw_evaluation["combined_score"] - 0.01
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
            token_fragment = _merge_text_fragments([token["text"] for token in row_tokens])
            reconstructed_payload = _normalize_reference_fragment_text(token_fragment)
            reconstructed = str(
                reconstructed_payload.get("text") or normalized_row_text
            )
        else:
            reconstructed_payload = {"text": normalized_row_text, "cleanups_applied": []}
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
            for text in list(per_row_after)
            + [token_seed_text]
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
                        for name in list(hybrid_text_candidate.get("cleanups_applied") or [])
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
        overlap = len(local_tokens.intersection(candidate_tokens)) / max(len(candidate_tokens), 1)
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
    starts_with_anchor = bool(
        NUMBERED_REFERENCE_LINE_RE.match(first_text) and int(expected_index or 0) > 0
    )
    bibliography_zone_match_detail = _build_bibliography_zone_match_detail(
        rows,
        bibliography_segments,
    )
    inside_bibliography_zone = bool(
        bibliography_zone_match_detail.get("inside_bibliography_zone")
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
    selected_candidate_source = str(
        token_reconstruction.get("selected_candidate_source") or "rows_raw"
    ).strip() or "rows_raw"
    selected_candidate_quality = 0.0
    for candidate_score in token_reconstruction.get("candidate_scores") or []:
        if not isinstance(candidate_score, dict):
            continue
        if str(candidate_score.get("source") or "").strip() == selected_candidate_source:
            selected_candidate_quality = float(candidate_score.get("quality_score") or 0.0)
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
            "accepted_with_cleanup"
            if cleanup_applied
            else "accepted_structured"
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
        "bibliography_zone_match_detail": bibliography_zone_match_detail,
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
        number = _extract_leading_reference_index(str(line.get("text") or ""))
        if isinstance(number, int) and number > 0:
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
    x_values = sorted(float(line["box"][0]) for line in lines if _normalize_box(line.get("box")))
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
        index = _extract_leading_reference_index(text)
        if index is None:
            continue
        if index <= 0:
            continue
        anchors.append(
            {
                "index": index,
                "page": row.get("page"),
                "column_id": row.get("column_id"),
                "position": int(row.get("flow_position", position)),
                "row": row,
                "line": row,  # Compatibilidad con llamadas legacy.
            }
        )
    return anchors


def extract_numbered_anchors(lines: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Alias de compatibilidad para el flujo legacy.
    return detect_reference_anchors_from_rows(lines)


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
    first_index = _extract_leading_reference_index(first_line)
    if first_index is None:
        return False
    if first_index != expected_index:
        return False

    extra_line_anchors = sum(
        1
        for line in lines[1:]
        if NUMBERED_REFERENCE_LINE_RE.match(str(line.get("text") or ""))
    )
    if extra_line_anchors > 0:
        return False

    if len(text) < 24:
        return False
    if _is_reference_noise_text(text):
        return False
    if _is_reference_header_like(text):
        return False

    anchor_mentions = _extract_reference_anchor_numbers(text)
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
    anchor_mentions = _extract_reference_anchor_numbers(text)
    foreign_anchors = [value for value in anchor_mentions if value != expected_index]
    has_nested = len(foreign_anchors) > 0
    mixed_score = 0.72 if has_nested else 0.12
    accepted = bool(len(text) >= 24 and not has_nested)
    reason = None if accepted else ("mixed_rows_multiple_references" if has_nested else "short_or_empty_reference")
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
            "tail_trim_applied": False,
            "tail_trim_reason": None,
            "tail_trim_removed_text": "",
            "tail_trim_removed_rows_count": 0,
            "tail_trim_scope": "reference_tail_rows",
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
    trimmed_tail_rows: List[Dict[str, Any]] = []
    tail_trim_reason: Optional[str] = None
    for position in range(start, min(end, len(ordered_rows))):
        row = ordered_rows[position]
        text = str(row.get("text") or "").strip()
        if not text:
            row_decisions.append(
                {
                    "position": position,
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "empty_text",
                }
            )
            continue
        is_anchor_row = position == start
        inline_anchor_numbers = _extract_inline_anchor_numbers(text)
        foreign_inline_anchors = [
            value for value in inline_anchor_numbers if value != expected_index
        ]
        if foreign_inline_anchors and not is_anchor_row:
            nested_anchor_indices.extend(foreign_inline_anchors)
            cut_reasons.append(f"nested_anchor:{foreign_inline_anchors[0]}")
            row_decisions.append(
                {
                    "position": position,
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "nested_anchor_detected",
                    "inline_anchor_numbers": inline_anchor_numbers,
                }
            )
            break
        if not is_anchor_row and NUMBERED_REFERENCE_LINE_RE.match(text):
            cut_reasons.append("next_anchor_row")
            row_decisions.append(
                {
                    "position": position,
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
                    "column_id": row.get("column_id"),
                    "text": text,
                    "included": False,
                    "reason": "next_anchor_row",
                    "inline_anchor_numbers": inline_anchor_numbers,
                }
            )
            break
        if not is_anchor_row and _is_header_footer_row(row, artifact_info):
            row_decisions.append(
                {
                    "position": position,
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
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
                    "position": position,
                    "row_id": str(row.get("id") or ""),
                    "page": row.get("page"),
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
                previous_text = (
                    str(selected_rows[-1].get("text") or "") if selected_rows else ""
                )
                if _reference_row_has_terminal_signal(previous_text):
                    trimmed_tail_rows = [
                        candidate
                        for candidate in ordered_rows[position:min(end, len(ordered_rows))]
                        if str(candidate.get("text") or "").strip()
                    ]
                    tail_trim_reason = (
                        "tail_row_horizontal_reset_after_terminal_reference_line"
                    )
                    cut_reasons.append("tail_row_horizontal_reset")
                    row_decisions.append(
                        {
                            "position": position,
                            "row_id": str(row.get("id") or ""),
                            "page": row.get("page"),
                            "column_id": row_column,
                            "text": text,
                            "included": False,
                            "reason": "tail_row_horizontal_reset",
                            "inline_anchor_numbers": inline_anchor_numbers,
                        }
                    )
                    break
                row_decisions.append(
                    {
                        "position": position,
                        "row_id": str(row.get("id") or ""),
                        "page": row.get("page"),
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
                            trimmed_tail_rows = [
                                candidate
                                for candidate in ordered_rows[position:min(end, len(ordered_rows))]
                                if str(candidate.get("text") or "").strip()
                            ]
                            tail_trim_reason = "tail_row_vertical_gap"
                            row_decisions.append(
                                {
                                    "position": position,
                                    "row_id": str(row.get("id") or ""),
                                    "page": current_page,
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
                    trimmed_tail_rows = [
                        candidate
                        for candidate in ordered_rows[position:min(end, len(ordered_rows))]
                        if str(candidate.get("text") or "").strip()
                    ]
                    tail_trim_reason = "tail_row_page_jump"
                    break
                elif (_to_float(row.get("y0")) or 1.0) > 0.36:
                    cut_reasons.append("late_page_continuation")
                    trimmed_tail_rows = [
                        candidate
                        for candidate in ordered_rows[position:min(end, len(ordered_rows))]
                        if str(candidate.get("text") or "").strip()
                    ]
                    tail_trim_reason = "tail_row_late_page_continuation"
                    break

        selected_rows.append(row)
        row_decisions.append(
            {
                "position": position,
                "row_id": str(row.get("id") or ""),
                "page": row.get("page"),
                "column_id": row_column,
                "text": text,
                "included": True,
                "reason": "selected",
                "inline_anchor_numbers": inline_anchor_numbers,
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
        "tail_trim_applied": bool(trimmed_tail_rows),
        "tail_trim_reason": tail_trim_reason,
        "tail_trim_removed_text": _clean_reference_text(trimmed_tail_rows),
        "tail_trim_removed_rows_count": len(trimmed_tail_rows),
        "tail_trim_scope": "reference_tail_rows",
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
        selected_candidate_source = str(
            selected_candidate.get("source")
            or token_reconstruction.get("selected_candidate_source")
            or "rows_raw"
        ).strip() or "rows_raw"
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
        fine_cleanup = _apply_reference_fine_cleanup(
            base_text=str(token_reconstruction.get("final_text") or ""),
            row_evidence_texts=[
                str(token_reconstruction.get("raw_text") or ""),
                str(token_reconstruction.get("backbone_text") or ""),
            ]
            + [str(row.get("text") or "") for row in block_rows],
            token_evidence_texts=[
                str(token_reconstruction.get("token_text") or ""),
                str(token_reconstruction.get("hybrid_text") or ""),
            ],
        )
        token_reconstruction["final_text"] = str(
            fine_cleanup.get("text") or token_reconstruction.get("final_text") or ""
        ).strip()
        token_reconstruction["fine_cleanup_edits"] = (
            fine_cleanup.get("accepted_edits") or []
        )
        token_reconstruction["fine_cleanup_rejected_edits"] = (
            fine_cleanup.get("rejected_edits") or []
        )
        token_reconstruction["punctuation_normalization_applied"] = bool(
            fine_cleanup.get("punctuation_normalization_applied")
        )
        token_reconstruction["punctuation_anomalies_detected"] = (
            fine_cleanup.get("punctuation_anomalies_detected") or []
        )
        token_reconstruction["cleanups_applied"] = sorted(
            {
                str(name).strip()
                for name in list(token_reconstruction.get("cleanups_applied") or [])
                + list(fine_cleanup.get("cleanups_applied") or [])
                if str(name).strip()
            }
        )
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
                "fine_cleanup_edits": token_reconstruction.get("fine_cleanup_edits")
                or [],
                "fine_cleanup_rejected_edits": token_reconstruction.get(
                    "fine_cleanup_rejected_edits"
                )
                or [],
                "punctuation_normalization_applied": bool(
                    token_reconstruction.get("punctuation_normalization_applied")
                ),
                "punctuation_anomalies_detected": token_reconstruction.get(
                    "punctuation_anomalies_detected"
                )
                or [],
            },
            "anomalies": {
                "cut_reasons": block_result.get("cut_reasons") or [],
                "nested_anchor_indices": block_result.get("nested_anchor_indices")
                or [],
                "tail_trim_applied": bool(block_result.get("tail_trim_applied")),
                "tail_trim_reason": block_result.get("tail_trim_reason"),
                "tail_trim_removed_text": block_result.get("tail_trim_removed_text")
                or "",
                "tail_trim_removed_rows_count": int(
                    block_result.get("tail_trim_removed_rows_count") or 0
                ),
                "tail_trim_scope": block_result.get("tail_trim_scope"),
            },
        }
        if isinstance(row_debug_collector, list):
            row_debug_collector.append(
                {
                    "reference_index": index,
                    "row_decisions": block_result.get("row_decisions") or [],
                    "cut_reasons": block_result.get("cut_reasons") or [],
                    "nested_anchor_indices": block_result.get("nested_anchor_indices")
                    or [],
                    "tail_trim_applied": bool(block_result.get("tail_trim_applied")),
                    "tail_trim_reason": block_result.get("tail_trim_reason"),
                    "tail_trim_removed_text": block_result.get("tail_trim_removed_text")
                    or "",
                    "tail_trim_removed_rows_count": int(
                        block_result.get("tail_trim_removed_rows_count") or 0
                    ),
                    "tail_trim_scope": block_result.get("tail_trim_scope"),
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
                    "fine_cleanup_edits": token_reconstruction.get(
                        "fine_cleanup_edits"
                    )
                    or [],
                    "fine_cleanup_rejected_edits": token_reconstruction.get(
                        "fine_cleanup_rejected_edits"
                    )
                    or [],
                    "punctuation_normalization_applied": bool(
                        token_reconstruction.get("punctuation_normalization_applied")
                    ),
                    "punctuation_anomalies_detected": token_reconstruction.get(
                        "punctuation_anomalies_detected"
                    )
                    or [],
                    "token_cleanup_confidence": token_reconstruction.get(
                        "token_cleanup_confidence"
                    ),
                    "doi_after_cleanup": _extract_doi(block_text) or None,
                }
            )
    return parsed


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

    anchor_positions = sorted(int(anchor["position"]) for anchor in first_anchor_by_index.values())
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
    logger.info(f"build_references_data: {len(references)} referencias, {len(snippets)} snippets. references_numbered={references_numbered}")

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
        paragraphs=paragraph_items,
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
    bibliography_start_page_number = _page_number_from_index(
        bibliography_start_page_zero_based
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
    input_references_by_index: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    row_phase_details: List[Dict[str, Any]] = []
    token_phase_details: List[Dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        idx = _entry_index(ref)
        if idx is None or idx <= 0:
            continue
        input_references_by_index[idx].append(ref)
    for idx, candidates in input_references_by_index.items():
        preferred_input = _pick_preferred_reference_input(candidates)
        if preferred_input is not None:
            metadata_by_index[idx] = preferred_input
    indexed_input_references = sum(
        1 for ref in references if isinstance(ref, dict) and _entry_index(ref) is not None
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
    reference_input_sequence: List[Tuple[Optional[int], Dict[str, Any]]] = []
    canonical_row_indices = sorted(
        idx for idx in line_based_references.keys() if isinstance(idx, int) and idx > 0
    )
    if canonical_row_indices:
        for idx in canonical_row_indices:
            preferred_input = _pick_preferred_reference_input(
                input_references_by_index.get(idx) or []
            )
            if preferred_input is None:
                line_reference = line_based_references.get(idx) or {}
                preferred_input = {
                    "index": idx,
                    "raw": str(
                        line_reference.get("text_raw")
                        or line_reference.get("text")
                        or ""
                    ),
                }
            reference_input_sequence.append((idx, preferred_input))
    else:
        for ref in references:
            if not isinstance(ref, dict):
                continue
            reference_input_sequence.append((_entry_index(ref), ref))

    for fallback_idx, (canonical_idx, ref) in enumerate(reference_input_sequence, start=1):
        if not isinstance(ref, dict):
            continue
        idx = canonical_idx if isinstance(canonical_idx, int) and canonical_idx > 0 else _entry_index(ref)
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
            "bibliography_zone_match_detail": {
                "inside_bibliography_zone": False,
                "inside_bibliography_zone_reason": "not_evaluated_fallback",
                "row_matches": [],
            },
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
        crossref_match_payload: Dict[str, Any] = {"score": 0.0, "doi_match_score": 0.0, "match": None}
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
            "fine_cleanup_edits": [],
            "fine_cleanup_rejected_edits": [],
            "punctuation_normalization_applied": False,
            "punctuation_anomalies_detected": [],
        }
        anomalies: Dict[str, Any] = {
            "cut_reasons": [],
            "nested_anchor_indices": [],
            "tail_trim_applied": False,
            "tail_trim_reason": None,
            "tail_trim_removed_text": "",
            "tail_trim_removed_rows_count": 0,
            "tail_trim_scope": None,
        }
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
                    "match_score": float(candidate_validation.get("match_score") or 0.0),
                    "mixed_reference_score": float(candidate_validation.get("mixed_reference_score") or 0.0),
                    "has_nested_anchor": bool(candidate_validation.get("has_nested_anchor")),
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
                crossref_match_payload = dict(line_reference.get("crossref_match") or {})
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
                candidate_id = str(best_candidate.get("id") or best_candidate.get("page") or "")
                if candidate_id:
                    used_bibliography_ids.add(candidate_id)
                page = best_candidate["page"]
                box = _normalize_box(best_candidate.get("box"))
                text = str(best_candidate.get("text") or raw_text)
                doi_from_text = _extract_doi(text)
                if doi_from_text and (not doi_value or len(doi_from_text) > len(doi_value)):
                    doi_value = doi_from_text
                structure_source = "bibliography_box_fallback"
                decision_scores.update(
                    {
                        "inside_bibliography_zone": True,
                        "bibliography_zone_match_detail": {
                            "reference_page_index": _page_index_value(page),
                            "reference_page_number": _page_number_from_index(page),
                            "reference_box": _serialize_box(box),
                            "matched_segment_page_index": _page_index_value(page),
                            "matched_segment_page_number": _page_number_from_index(page),
                            "matched_segment_box": _serialize_box(box),
                            "page_index_match": True,
                            "box_overlap_match": True,
                            "inside_bibliography_zone": True,
                            "inside_bibliography_zone_reason": "bibliography_box_fallback",
                            "row_matches": [],
                        },
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
                if doi_from_text and (not doi_value or len(doi_from_text) > len(doi_value)):
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

        if text and line_reference is None:
            fine_cleanup = _apply_reference_fine_cleanup(
                base_text=text,
                row_evidence_texts=[raw_text, text_candidate_raw],
                token_evidence_texts=[
                    str(token_payload.get("raw_text") or ""),
                    str(token_payload.get("token_text") or ""),
                    str(token_payload.get("hybrid_text") or ""),
                ],
            )
            text = str(fine_cleanup.get("text") or text).strip()
            token_payload["final_text"] = text
            token_payload["fine_cleanup_edits"] = (
                fine_cleanup.get("accepted_edits") or []
            )
            token_payload["fine_cleanup_rejected_edits"] = (
                fine_cleanup.get("rejected_edits") or []
            )
            token_payload["punctuation_normalization_applied"] = bool(
                fine_cleanup.get("punctuation_normalization_applied")
            )
            token_payload["punctuation_anomalies_detected"] = (
                fine_cleanup.get("punctuation_anomalies_detected") or []
            )
            token_payload["cleanups_applied"] = sorted(
                {
                    str(name).strip()
                    for name in list(token_payload.get("cleanups_applied") or [])
                    + list(fine_cleanup.get("cleanups_applied") or [])
                    if str(name).strip()
                }
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
            final_decision["crossref_match_score"] = decision_scores["crossref_match_score"]
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
                "page": _page_index_value(page),
                **_page_debug_fields(page),
                "box": box,
                "doi": doi_value or None,
                "structure_source": structure_source,
                "local_row_count": max(0, local_row_count),
                "local_anchor_detected": bool(local_anchor_detected),
                "reference_validation": reference_validation,
                "validation_intermediate": validation_intermediate,
                "scores": decision_scores,
                "final_decision": final_decision,
                "bibliography_zone_match_detail": (
                    final_decision.get("bibliography_zone_match_detail")
                    if isinstance(final_decision, dict)
                    else None
                ),
                "crossref_match": crossref_match_payload,
                "token_reconstruction": token_payload,
                "anomalies": anomalies,
            }
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
                logger.debug(f"Descartando snippet {snippet_idx}: sin ref_ids resueltas. '{snippet_text[:50]}'")
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
                logger.debug(f"Descartando snippet {snippet_idx}: está dentro de la bibliografía.")
            continue
        if is_after_bibliography(mention_page, mention_y, bibliography_anchor):
            if TRACE_REFERENCES:
                logger.debug(f"Descartando snippet {snippet_idx}: es posterior al inicio de bibliografía.")
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
            page = _page_index_value(item.get("page"))
            box = _normalize_box(item.get("box"))
            next_item = dict(item)
            next_item["page"] = page
            next_item["page_index"] = page
            next_item["page_number"] = _page_number_from_index(page)
            next_item["box"] = box
            cleaned.append(next_item)
        return cleaned

    reference_entries = _clean_items(reference_entries)
    citations = _clean_items(citations)
    contexts = _clean_items(contexts)
    final_reference_ids_serialized = [
        str(entry.get("ref_id") or "")
        for entry in reference_entries
        if str(entry.get("ref_id") or "").strip()
    ]
    max_reference_index = max(references_by_index.keys(), default=0)
    if max_reference_index <= 0:
        max_reference_index = len(reference_entries)
    bibliography_start_page = bibliography_start_page_number
    anchors_out_of_sequence: List[Dict[str, int]] = []
    sorted_reference_indices = [
        int(entry.get("index"))
        for entry in reference_entries
        if isinstance(entry.get("index"), int)
    ]
    for previous, current in zip(sorted_reference_indices, sorted_reference_indices[1:]):
        if current != previous + 1:
            anchors_out_of_sequence.append({"expected": previous + 1, "actual": current})

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
        _build_repeating_page_artifacts(bibliography_phase.get("rows_with_columns") or [])
        .get("repeated_text_keys", set())
    )
    bibliography_noise_candidates = [
        row
        for row in (bibliography_rows_phase.get("debug_rows") or [])
        if not row.get("included")
        and row.get("reason") in {"header_footer_noise", "outside_bibliography_segments"}
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
        debug_payload = {
            "metadata": {
                "file_name": str(source_filename or ""),
                "article_doi": crossref_context.get("article_doi"),
                "engine_used": str(engine_used or ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "debug_mode": True,
                "pipeline_version": REFERENCE_PIPELINE_VERSION,
                "page_convention_internal": "page_index_zero_based",
                "page_convention_human": "page_number_one_based",
                "bibliography_start_page": bibliography_start_page,
                "bibliography_start_page_index": bibliography_start_page_zero_based,
                "bibliography_start_page_number": bibliography_start_page_number,
                "references_total_detected": len(reference_entries),
                "references_total_debug": len(reference_entries),
                "references_total_serialized": len(reference_entries),
                "references_total_source": "reference_entries_final",
                "final_reference_ids_serialized": final_reference_ids_serialized,
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
                    "crossref_available": bool(crossref_context.get("crossref_available")),
                    "article_metadata": crossref_context.get("crossref_article_metadata"),
                    "reference_candidates": crossref_context.get("crossref_reference_candidates")
                    or [],
                    "reference_count": int(
                        crossref_context.get("crossref_reference_count") or 0
                    ),
                    "matching_auxiliary": [
                        {
                            "ref_id": entry.get("ref_id"),
                            "index": entry.get("index"),
                            "crossref_match_score": (
                                entry.get("scores") or {}
                            ).get("crossref_match_score"),
                            "doi_match_score": (
                                entry.get("scores") or {}
                            ).get("doi_match_score"),
                            "match": (
                                entry.get("crossref_match") or {}
                            ).get("match"),
                        }
                        for entry in reference_entries
                    ],
                },
                "bibliography_zone": {
                    "segments": [
                        {
                            "page": _page_index_value(segment.get("page")),
                            **_page_debug_fields(segment.get("page")),
                            "column_id": segment.get("column_id"),
                            "box": _serialize_box(segment.get("box")),
                            "source": segment.get("source"),
                            "confidence": segment.get("confidence"),
                            "row_count": segment.get("row_count"),
                            "leading_anchor_indices": segment.get("leading_anchor_indices")
                            or [],
                            "reference_density": segment.get("reference_density"),
                            "reference_density_mean": segment.get(
                                "reference_density_mean"
                            ),
                            "reference_density_strong_ratio": segment.get(
                                "reference_density_strong_ratio"
                            ),
                            "raw_text": segment.get("raw_text"),
                            "tail_trim_applied": bool(segment.get("tail_trim_applied")),
                            "tail_trim_reason": segment.get("tail_trim_reason"),
                            "tail_trim_removed_text": segment.get(
                                "tail_trim_removed_text"
                            )
                            or "",
                            "tail_trim_removed_rows_count": int(
                                segment.get("tail_trim_removed_rows_count") or 0
                            ),
                            "tail_trim_scope": segment.get("tail_trim_scope"),
                            "accepted_because": segment.get("source"),
                        }
                        for segment in bibliography_segments
                    ],
                    "reading_order_blocks": bibliography_phase.get("reading_order_blocks")
                    or [],
                    "column_reading_order": bibliography_phase.get("column_reading_order")
                    or [],
                    "reading_order_reason": (
                        "ordered_by_page_then_column_left_to_right_then_top_to_bottom_within_bibliography_segments"
                    ),
                    "bibliography_end_candidates": bibliography_phase.get(
                        "bibliography_end_candidates"
                    )
                    or [],
                    "end_of_bibliography_signals": bibliography_phase.get(
                        "end_of_bibliography_signals"
                    ),
                    "bibliography_end_reason": bibliography_phase.get(
                        "bibliography_end_reason"
                    ),
                    "layer_boxes": [
                        _serialize_layer_item(item) for item in bibliography_items
                    ],
                },
                "sections": {
                    "relevant_sections": bibliography_phase.get("section_records") or [],
                    "selected_start": (
                        {
                            "page": _page_index_value(
                                bibliography_phase["selected_heading"].get("page")
                            ),
                            **_page_debug_fields(
                                bibliography_phase["selected_heading"].get("page")
                            ),
                            "column_id": bibliography_phase["selected_heading"].get(
                                "column_id"
                            ),
                            "text": bibliography_phase["selected_heading"].get("text"),
                            "box": _serialize_box(
                                bibliography_phase["selected_heading"].get("box")
                            ),
                            "source": bibliography_phase["selected_heading"].get("source"),
                        }
                        if isinstance(bibliography_phase.get("selected_heading"), dict)
                        else None
                    ),
                    "candidate_noise": bibliography_phase.get("candidate_noise_sections")
                    or [],
                },
                "paragraphs": paragraph_phase,
                "rows": {
                    "rows_considered": bibliography_rows_phase.get("debug_rows") or [],
                    "rows_sorted_for_bibliography": bibliography_rows_phase.get(
                        "rows_sorted_for_bibliography"
                    )
                    or [],
                    "reference_blocks": row_phase_details,
                },
                "tokens": {
                    "tokens_total_in_bibliography": len(tokens_in_bibliography),
                    "references": token_phase_details,
                },
            },
            "references": [dict(entry) for entry in reference_entries],
            "alerts": global_alerts,
        }

    logger.info(f"Completado build_references_data: {len(reference_entries)} reference_entries, {len(citations)} citations, {len(contexts)} contexts construidos.")

    return {
        "references": reference_entries,
        "references_total": len(reference_entries),
        "references_total_source": "reference_entries_final",
        "final_reference_ids_serialized": final_reference_ids_serialized,
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric" if references_numbered else "non_numeric",
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page,
        "bibliography_start_page_index": bibliography_start_page_zero_based,
        "bibliography_start_page_number": bibliography_start_page_number,
        "bibliography_segments": bibliography_segments,
        "crossref_available": bool(crossref_context.get("crossref_available")),
        "article_doi": crossref_context.get("article_doi"),
        "crossref_article_metadata": crossref_context.get("crossref_article_metadata"),
        "crossref_reference_candidates": crossref_context.get("crossref_reference_candidates")
        or [],
        "crossref_reference_count": int(crossref_context.get("crossref_reference_count") or 0),
        "global_alerts": global_alerts,
        "debug_payload": debug_payload,
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
            else (
                entry.get("scores")
                if isinstance(entry.get("scores"), dict)
                else {}
            )
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
        anomalies = (
            entry.get("anomalies") if isinstance(entry.get("anomalies"), dict) else {}
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
                "page": _page_index_value(entry.get("page")),
                "page_index": _page_index_value(entry.get("page")),
                "page_number": _page_number_from_index(entry.get("page")),
                "source": entry.get("structure_source"),
                "structure_source": entry.get("structure_source"),
                "candidate_text_raw": entry.get("text_candidate_raw") or entry.get("text"),
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
                "bibliography_zone_match_detail": scores.get(
                    "bibliography_zone_match_detail"
                ),
                "cleanups_applied": token_info.get("cleanups_applied") or [],
                "selected_candidate_source": token_info.get(
                    "selected_candidate_source"
                ),
                "order_similarity_to_rows": token_info.get(
                    "order_similarity_to_rows"
                ),
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
                "fine_cleanup_edits": token_info.get("fine_cleanup_edits") or [],
                "fine_cleanup_rejected_edits": token_info.get(
                    "fine_cleanup_rejected_edits"
                )
                or [],
                "punctuation_normalization_applied": bool(
                    token_info.get("punctuation_normalization_applied")
                ),
                "punctuation_anomalies_detected": token_info.get(
                    "punctuation_anomalies_detected"
                )
                or [],
                "enrichment_validation": enrichment_validation,
                "enrichment_candidate": enrichment_candidate,
                "enrichment_accepted": entry.get("enrichment_accepted"),
                "tail_trim_applied": bool(anomalies.get("tail_trim_applied")),
                "tail_trim_reason": anomalies.get("tail_trim_reason"),
                "tail_trim_removed_text": anomalies.get("tail_trim_removed_text")
                or "",
                "tail_trim_removed_rows_count": int(
                    anomalies.get("tail_trim_removed_rows_count") or 0
                ),
                "tail_trim_scope": anomalies.get("tail_trim_scope"),
                "anomalies": anomalies,
                "fallback_used": "fallback" in str(entry.get("structure_source") or ""),
            }
        )
    debug_payload["references"] = finalized_references
    debug_payload.setdefault("metadata", {})
    debug_payload["metadata"]["references_total_detected"] = len(finalized_references)
    debug_payload["metadata"]["references_total_debug"] = len(finalized_references)
    debug_payload["metadata"]["references_total_serialized"] = len(
        finalized_references
    )
    debug_payload["metadata"]["references_total_source"] = "reference_entries_final"
    debug_payload["metadata"]["final_reference_ids_serialized"] = [
        str(entry.get("ref_id") or "")
        for entry in finalized_references
        if str(entry.get("ref_id") or "").strip()
    ]
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

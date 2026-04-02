from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
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
NUMBERED_REFERENCE_LINE_RE = re.compile(r"^\s*\[\s*(\d+)\s*\]")
NUMBERED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")
HEADER_LIKE_REFERENCE_RE = re.compile(
    r"\b(?:wipsce|copyright|all rights reserved|acm isbn|proceedings)\b",
    re.IGNORECASE,
)
FIXED_ARTIFACT_RE = re.compile(
    r"\b(?:proceedings|copyright|all rights reserved|acm isbn|issn|vol\.|volume|number|no\.)\b",
    re.IGNORECASE,
)
PAGE_NUMBER_ONLY_RE = re.compile(r"^\s*\(?\d{1,4}\)?\s*$")
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
REFERENCE_DEBUG_FILE_SUFFIX = "__reference_debug.json"
REFERENCE_PIPELINE_VERSION = "references-phased-v1"
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
    if not text or _is_reference_noise_text(text):
        return []

    matches = list(NUMBERED_ANCHOR_RE.finditer(text))
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


def _extract_inline_anchor_numbers(text: str) -> List[int]:
    numbers: List[int] = []
    for match in NUMBERED_ANCHOR_RE.finditer(text or ""):
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if number > 0:
            numbers.append(number)
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
        return 0.74
    if FIXED_ARTIFACT_RE.search(normalized):
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


def _build_bibliography_segments(
    *,
    rows: Sequence[Dict[str, Any]],
    sections: Sequence[Dict[str, Any]],
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
                    if float(row.get("y1") or 0.0) < heading_y:
                        continue
            filtered_rows.append(row)
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
                "raw_text": _clean_reference_text(filtered_rows),
                "row_ids": [str(row.get("id") or "") for row in filtered_rows],
            }
        )

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
        if segment.get("column_id") and row.get("column_id") and segment.get("column_id") != row.get("column_id"):
            continue
        if _contains_box(segment_box, box) or _overlap_ratio(segment_box, box) >= 0.6:
            return True
    return False


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
        in_zone = _row_in_any_segment(row, bibliography_segments)
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
                "page": page,
                "box": _serialize_box(box),
                "text": text,
                "column_id": row.get("column_id"),
                "anchor_index": anchor_numbers[0] if anchor_numbers else None,
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


def _reconstruct_reference_text_from_rows_and_tokens(
    rows: Sequence[Dict[str, Any]],
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    raw_text = _clean_reference_text(rows)
    per_row_before: List[str] = []
    per_row_after: List[str] = []
    token_rows_used = 0
    for row in rows:
        row_text = str(row.get("text") or "").strip()
        per_row_before.append(row_text)
        row_tokens = _tokens_for_row(row, tokens_by_page)
        if row_tokens:
            token_rows_used += 1
            reconstructed = _merge_text_fragments([token["text"] for token in row_tokens])
            per_row_after.append(reconstructed or row_text)
        else:
            per_row_after.append(row_text)
    token_text = _merge_text_fragments(per_row_after)
    final_text = token_text or raw_text
    confidence = round(token_rows_used / max(len(rows), 1), 3)
    return {
        "raw_text": raw_text,
        "final_text": final_text,
        "token_cleanup_confidence": confidence,
        "token_rows_used": token_rows_used,
        "per_row_before": per_row_before,
        "per_row_after": per_row_after,
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
        elif bool(crossref_context.get("crossref_available")):
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
    inside_bibliography_zone = bool(
        rows
        and all(_row_in_any_segment(row, bibliography_segments) for row in rows)
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
    crossref_match_score = float(crossref_match.get("score") or 0.0)
    doi_match_score = float(crossref_match.get("doi_match_score") or 0.0)
    final_score = 0.0
    final_score += 0.18 if inside_bibliography_zone else -0.35
    final_score += 0.16 if inside_expected_column else -0.32
    final_score += 0.18 if starts_with_anchor else -0.25
    final_score += 0.14 * row_continuity_score
    final_score += 0.12 * crossref_match_score
    final_score += 0.08 * doi_match_score
    final_score += 0.08 * token_cleanup_confidence
    final_score -= 0.28 * header_noise_score
    if has_nested_anchor:
        final_score -= 0.34
    if not bool(validation.get("accepted")):
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
    elif final_score >= 0.72 and token_cleanup_confidence >= 0.25:
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

    if validation.get("reason") and accepted:
        reason = validation.get("reason")
    if not validation.get("accepted") and validation.get("reason"):
        accepted = False
        if classification == "accepted_structured":
            classification = "fallback_needed"
        reason = str(validation.get("reason"))
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
        "final_score": final_score,
        "accepted": accepted,
        "classification": classification,
        "reason": reason,
    }


def is_numbered_bibliography(lines: Sequence[Dict[str, Any]]) -> bool:
    if len(lines) < 6:
        return False
    numbers: List[int] = []
    for line in lines:
        match = NUMBERED_REFERENCE_LINE_RE.match(str(line.get("text") or ""))
        if not match:
            continue
        try:
            number = int(match.group(1))
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
        match = NUMBERED_REFERENCE_LINE_RE.match(text)
        if not match:
            continue
        try:
            index = int(match.group(1))
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
    first_match = NUMBERED_REFERENCE_LINE_RE.match(first_line)
    if not first_match:
        return False
    try:
        first_index = int(first_match.group(1))
    except (TypeError, ValueError):
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

    anchor_mentions = [
        int(match.group(1))
        for match in NUMBERED_ANCHOR_RE.finditer(text)
        if match.group(1).isdigit()
    ]
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
    anchor_mentions = [
        int(match.group(1))
        for match in NUMBERED_ANCHOR_RE.finditer(text)
        if match.group(1).isdigit()
    ]
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
        text = str(row.get("text") or "").strip()
        if not text:
            row_decisions.append(
                {
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
                row_decisions.append(
                    {
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
                            row_decisions.append(
                                {
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
                    break
                elif (_to_float(row.get("y0")) or 1.0) > 0.36:
                    cut_reasons.append("late_page_continuation")
                    break

        selected_rows.append(row)
        row_decisions.append(
            {
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
        local_validation = {
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
        structure_source = (
            "rows_tokens"
            if float(token_reconstruction.get("token_cleanup_confidence") or 0.0) >= 0.25
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
            "column_id": anchor.get("column_id"),
            "anchor_position": start_position,
            "scores": decision,
            "crossref_match": crossref_match,
            "token_reconstruction": {
                "token_cleanup_confidence": token_reconstruction.get(
                    "token_cleanup_confidence"
                ),
                "token_rows_used": token_reconstruction.get("token_rows_used"),
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
                    "row_decisions": block_result.get("row_decisions") or [],
                    "cut_reasons": block_result.get("cut_reasons") or [],
                    "nested_anchor_indices": block_result.get("nested_anchor_indices")
                    or [],
                    "scores": decision,
                }
            )
        if isinstance(token_debug_collector, list):
            token_debug_collector.append(
                {
                    "reference_index": index,
                    "before": token_reconstruction.get("raw_text"),
                    "after": token_reconstruction.get("final_text"),
                    "per_row_before": token_reconstruction.get("per_row_before") or [],
                    "per_row_after": token_reconstruction.get("per_row_after") or [],
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
            "final_score": 0.0,
            "accepted": False,
            "classification": "fallback_needed",
            "reason": "fallback_without_rows_structure",
        }
        crossref_match_payload: Dict[str, Any] = {"score": 0.0, "doi_match_score": 0.0, "match": None}
        token_payload: Dict[str, Any] = {
            "token_cleanup_confidence": 0.0,
            "token_rows_used": 0,
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
                    "match_score": float(candidate_validation.get("match_score") or 0.0),
                    "mixed_reference_score": float(candidate_validation.get("mixed_reference_score") or 0.0),
                    "has_nested_anchor": bool(candidate_validation.get("has_nested_anchor")),
                    "accepted": bool(candidate_validation.get("accepted")),
                    "reason": candidate_validation.get("reason"),
                }
            if isinstance(line_reference.get("scores"), dict):
                decision_scores = dict(line_reference.get("scores") or {})
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
                        "final_score": round(min(best_score / 5.0, 0.52), 3),
                        "reason": "bibliography_box_fallback",
                    }
                )
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
                decision_scores.update({"reason": "raw_reference_fallback"})
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
                "scores": decision_scores,
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
                    "relevant_sections": bibliography_phase.get("section_records") or [],
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
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric" if references_numbered else "non_numeric",
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page,
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
        scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
        validation = (
            entry.get("reference_validation")
            if isinstance(entry.get("reference_validation"), dict)
            else {}
        )
        crossref_match = (
            entry.get("crossref_match")
            if isinstance(entry.get("crossref_match"), dict)
            else {}
        )
        finalized_references.append(
            {
                "ref_id": entry.get("ref_id"),
                "index": entry.get("index"),
                "source": entry.get("structure_source"),
                "structure_source": entry.get("structure_source"),
                "candidate_text_raw": entry.get("text_candidate_raw") or entry.get("text"),
                "final_text": entry.get("text"),
                "doi_detected": entry.get("doi"),
                "doi_enriched": entry.get("doi"),
                "match_with_crossref": crossref_match.get("match"),
                "accepted": bool(validation.get("accepted")),
                "rejected": not bool(validation.get("accepted")),
                "reason": validation.get("reason") or scores.get("reason"),
                "scores": scores,
                "anomalies": entry.get("anomalies") if isinstance(entry.get("anomalies"), dict) else {},
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
    REFERENCE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REFERENCE_DEBUG_DIR / f"{safe_base_name}{REFERENCE_DEBUG_FILE_SUFFIX}"
    output_path.write_text(
        json.dumps(debug_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from citations.logging_utils import get_logger

logger = get_logger("citations.references")
TRACE_REFERENCES = os.getenv("TRACE_REFERENCES", "0") == "1"
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
    return out


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
    if len(rows) < 8:
        return None
    content_rows = [
        row
        for row in rows
        if (_to_float(row.get("y0")) or 0.0) > 0.08 and (_to_float(row.get("y1")) or 0.0) < 0.94
    ]
    sample = content_rows if len(content_rows) >= 8 else list(rows)
    x_values = sorted(
        float(row.get("x0"))
        for row in sample
        if _to_float(row.get("x0")) is not None
    )
    if len(x_values) < 8:
        return None
    max_gap = 0.0
    split_threshold: Optional[float] = None
    for left_x, right_x in zip(x_values, x_values[1:]):
        gap = float(right_x) - float(left_x)
        if gap > max_gap:
            max_gap = gap
            split_threshold = (float(left_x) + float(right_x)) / 2.0
    if split_threshold is None or max_gap < 0.12:
        return None
    left_count = sum(1 for row in sample if float(row.get("x0", 0.0)) < split_threshold)
    right_count = len(sample) - left_count
    if left_count < 3 or right_count < 3:
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
        by_page[page].append(dict(row))

    out: List[Dict[str, Any]] = []
    for page in sorted(by_page.keys()):
        page_rows = by_page[page]
        split = _detect_page_column_split(page_rows)
        for row in page_rows:
            next_row = dict(row)
            x_center = (float(next_row.get("x0", 0.0)) + float(next_row.get("x1", 0.0))) / 2.0
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
        if parts and parts[-1].endswith("-") and text and text[0].islower():
            parts[-1] = f"{parts[-1][:-1]}{text}"
        else:
            parts.append(text)

    merged = " ".join(parts)
    merged = re.sub(r"\s+([,.;:)\]])", r"\1", merged)
    merged = re.sub(r"([\[(])\s+", r"\1", merged)
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
    other_candidates = [
        (idx, candidate)
        for idx, candidate in metadata_by_index.items()
        if idx != expected_index and isinstance(candidate, dict)
    ]
    return validate_reference_against_metadata(
        text,
        metadata,
        expected_index=expected_index,
        other_metadata_candidates=other_candidates,
    )


def build_reference_rows_between_anchors(
    *,
    ordered_rows: Sequence[Dict[str, Any]],
    current_anchor: Dict[str, Any],
    next_anchor: Optional[Dict[str, Any]],
    artifact_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    start = int(current_anchor.get("position", 0))
    end = len(ordered_rows)
    if next_anchor is not None:
        candidate_end = int(next_anchor.get("position", end))
        if candidate_end > start:
            end = candidate_end
    if start < 0 or start >= len(ordered_rows):
        return []

    expected_column = current_anchor.get("column_id")
    selected_rows: List[Dict[str, Any]] = []
    for position in range(start, min(end, len(ordered_rows))):
        row = ordered_rows[position]
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        is_anchor_row = position == start
        if not is_anchor_row and NUMBERED_REFERENCE_LINE_RE.match(text):
            break
        if not is_anchor_row and _is_header_footer_row(row, artifact_info):
            continue

        row_column = row.get("column_id")
        if (
            not is_anchor_row
            and expected_column in {"left", "right"}
            and row_column in {"left", "right"}
            and row_column != expected_column
        ):
            break

        if selected_rows:
            previous = selected_rows[-1]
            previous_page = previous.get("page")
            current_page = row.get("page")
            if isinstance(previous_page, int) and isinstance(current_page, int):
                if current_page < previous_page:
                    break
                if current_page == previous_page:
                    previous_y1 = _to_float(previous.get("y1"))
                    current_y0 = _to_float(row.get("y0"))
                    if previous_y1 is not None and current_y0 is not None:
                        gap = float(current_y0) - float(previous_y1)
                        if gap > 0.085:
                            break
                elif current_page - previous_page > 1:
                    break
                elif (_to_float(row.get("y0")) or 1.0) > 0.36:
                    break

        selected_rows.append(row)
        if len(selected_rows) >= 14:
            break

    return selected_rows


def build_references_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    metadata_by_index: Optional[Dict[int, Dict[str, Any]]] = None,
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

        block_rows = build_reference_rows_between_anchors(
            ordered_rows=ordered_rows,
            current_anchor=anchor,
            next_anchor=next_anchor,
            artifact_info=artifact_info,
        )
        if not block_rows:
            continue
        block_text = _clean_reference_text(block_rows)
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
        parsed[index] = {
            "text": block_text,
            "page": block_rows[0].get("page"),
            "box": union_box,
            "rows": block_rows,
            "local_row_count": len(block_rows),
            "local_anchor_detected": True,
            "structure_source": "rows",
            "reference_validation": local_validation,
            "column_id": anchor.get("column_id"),
            "anchor_position": start_position,
        }
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
) -> Dict[str, Any]:
    logger.info(f"build_references_data: {len(references)} referencias, {len(snippets)} snippets. references_numbered={references_numbered}")

    bibliography_items = _layer_items(layers, "bibliographies")
    token_items = _layer_items(layers, "tokens")
    row_items = _layer_items(layers, "rows")
    paragraph_items = _layer_items(layers, "paragraphs")

    logger.debug(f"Capas cargadas: {len(bibliography_items)} bibliographies, {len(token_items)} tokens, {len(row_items)} rows, {len(paragraph_items)} paragraphs")

    bibliography_anchor: Optional[Tuple[int, float]] = None
    if bibliography_items:
        first_bibliography_item = min(
            bibliography_items,
            key=lambda item: (int(item.get("page", 10**6)), float(item["box"][1])),
        )
        bibliography_anchor = (
            int(first_bibliography_item.get("page", 0)),
            float(first_bibliography_item["box"][1]),
        )
        logger.info(f"Detección de bibliografía: página inicio {bibliography_anchor[0] + 1}")
    else:
        logger.warning("No se encontró capa 'bibliographies' (sin anchor de inicio).")
    bibliography_lines = _collect_bibliography_lines(
        row_items,
        bibliography_items,
        bibliography_anchor,
    )
    line_based_references: Dict[int, Dict[str, Any]] = {}
    metadata_by_index: Dict[int, Dict[str, Any]] = {}
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
        if line_reference is not None:
            line_page = line_reference.get("page")
            page = line_page if isinstance(line_page, int) and line_page >= 0 else None
            box = _normalize_box(line_reference.get("box"))
            text = str(line_reference.get("text") or raw_text)
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
            if TRACE_REFERENCES:
                logger.debug(
                    f"Referencia {ref_id} reconstruida desde rows "
                    f"(source={structure_source}, rows={local_row_count})"
                )
        else:
            best_candidate: Optional[Dict[str, Any]] = None
            best_score = 0.0
            for candidate in bibliography_items:
                if candidate["id"] in used_bibliography_ids:
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
                used_bibliography_ids.add(best_candidate["id"])
                page = best_candidate["page"]
                box = best_candidate["box"]
                text = str(best_candidate.get("text") or raw_text)
                structure_source = "bibliography_box_fallback"
                if TRACE_REFERENCES:
                    logger.debug(
                        f"Referencia {ref_id} emparejada con caja de bibliografía "
                        f"(score: {best_score:.2f})"
                    )
            else:
                page = None
                box = None
                text = raw_text
                structure_source = "raw_reference_fallback"
                if TRACE_REFERENCES:
                    logger.debug(
                        f"Referencia {ref_id} sin caja de bibliografía emparejada."
                    )

        reference_entries.append(
            {
                "id": f"reference-entry-{ref_id}",
                "ref_id": ref_id,
                "index": idx,
                "text": text,
                "page": page,
                "box": box,
                "doi": doi_value or None,
                "structure_source": structure_source,
                "local_row_count": max(0, local_row_count),
                "local_anchor_detected": bool(local_anchor_detected),
                "reference_validation": reference_validation,
            }
        )

    contexts_seen: set[Tuple[str, int, str]] = set()
    seen_mentions: set[Tuple[Any, ...]] = set()
    mention_text_key_max_len = 220

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
            bibliography_items,
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

    logger.info(f"Completado build_references_data: {len(reference_entries)} reference_entries, {len(citations)} citations, {len(contexts)} contexts construidos.")

    return {
        "references": reference_entries,
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric" if references_numbered else "non_numeric",
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page,
    }

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

from citations.logging_utils import get_logger

from ..references_legacy import (
    NUMBERED_REFERENCE_LINE_RE,
    REFERENCE_AUTHOR_LEAD_RE,
    REFERENCE_AUTHOR_PREFIX_LEAD_RE,
    _apply_reference_fine_cleanup,
    _build_bibliography_segments,
    _build_bibliography_zone_match_detail,
    _build_repeating_page_artifacts,
    _compute_reference_density,
    _compute_row_continuity_score,
    _contains_box,
    _entry_index,
    _extract_doi,
    _extract_inline_anchor_numbers,
    _extract_leading_reference_index,
    _index_tokens_by_page,
    _layer_items,
    _line_sort_key,
    _match_reference_against_crossref,
    _match_row_to_bibliography_segment,
    _merge_text_fragments,
    _normalize_box,
    _normalize_doi,
    _normalize_mention_text,
    _normalize_text,
    _overlap_ratio,
    _page_debug_fields,
    _page_index_value,
    _page_number_from_index,
    _parse_citation_numbers,
    _pick_best_text_box,
    _pick_context_paragraph,
    _pick_preferred_reference_input,
    _prepare_crossref_context,
    _quantize_box,
    _reference_text_quality_score,
    _reconstruct_reference_text_from_rows_and_tokens,
    _sanitize_filename_component,
    _score_reference_like_text,
    _select_reference_text_candidate,
    _serialize_box,
    _tokens_for_row,
    _union_boxes,
    build_bibliography_reading_flow,
    is_after_bibliography,
    is_inside_bibliography,
)

logger = get_logger("citations.references.pipeline")

AUTHOR_YEAR_YEAR_RE = re.compile(r"\((?:19|20)\d{2}[a-z]?\)|\b(?:19|20)\d{2}[a-z]?\b")
AUTHOR_YEAR_VENUE_RE = re.compile(
    r"\b(?:journal|conference|proceedings|press|report|review|studies|analysis|"
    r"software|engineering|education|economics|political|transactions?|"
    r"springer|cambridge|oxford|ieee|acm|notes|workshop)\b",
    re.IGNORECASE,
)
AUTHOR_YEAR_WORD_RE = re.compile(r"\b(?:AI|[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]{2,})\b")
PAGE_RANGE_RE = re.compile(r"\b\d{1,4}(?:\s*[–-]\s*\d{1,4}|:\s*\d{1,4})\b")


def _clamp(value: float, floor: float = 0.0, ceil: float = 1.0) -> float:
    return max(floor, min(ceil, value))


def _normalized_box_or_none(value: Any) -> Optional[List[float]]:
    return _normalize_box(value)


def _rows_debug(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for row in rows:
        serialized.append(
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
    return serialized


def _normalized_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return round(_clamp((ratio * 0.65) + (overlap * 0.35)), 3)


def extract_relaxed_numeric_anchor(text: str) -> Optional[int]:
    match = NUMBERED_REFERENCE_LINE_RE.match(str(text or ""))
    if match is None:
        return None
    value = match.group("bracket") or match.group("plain")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or parsed > 400:
        return None
    if 1900 <= parsed <= 2099:
        return None
    return parsed


def score_author_year_lead(text: str) -> Dict[str, Any]:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return {"score": 0.0, "reasons": ["empty_text"]}

    score = 0.0
    reasons: List[str] = []
    lead_window = value[:120]
    early_window = value[:80]

    if REFERENCE_AUTHOR_LEAD_RE.match(value) or REFERENCE_AUTHOR_PREFIX_LEAD_RE.match(value):
        score += 0.52
        reasons.append("author_regex")
    elif re.match(r"^(?:AI|[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+),?\s*(?:[A-Z](?:\.\s*)?){1,4}", value):
        score += 0.42
        reasons.append("surname_initials")
    elif re.match(r"^(?:AI|[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’.-]+){0,2})\s+\((?:19|20)\d{2}", value):
        score += 0.38
        reasons.append("author_then_year")

    if AUTHOR_YEAR_YEAR_RE.search(early_window):
        score += 0.24
        reasons.append("early_year")
    elif AUTHOR_YEAR_YEAR_RE.search(lead_window):
        score += 0.12
        reasons.append("late_year")

    if AUTHOR_YEAR_VENUE_RE.search(value):
        score += 0.12
        reasons.append("venue_signal")
    if _extract_doi(value):
        score += 0.08
        reasons.append("doi_signal")
    if PAGE_RANGE_RE.search(value):
        score += 0.05
        reasons.append("page_range")
    if len(value) >= 48:
        score += 0.05
        reasons.append("length")

    lowered = value.lower()
    if lowered.startswith(("and ", "in ", "pp ", "pages ", "technical report ")):
        score -= 0.25
        reasons.append("continuation_prefix")
    if re.match(r"^\d", value):
        score -= 0.15
        reasons.append("digit_prefix")

    return {
        "score": round(_clamp(score), 3),
        "reasons": reasons,
        "has_year": bool(AUTHOR_YEAR_YEAR_RE.search(value)),
        "has_venue": bool(AUTHOR_YEAR_VENUE_RE.search(value)),
    }


def _prefix_looks_like_entry_end(prefix: str) -> bool:
    value = str(prefix or "").strip()
    if len(value) < 12:
        return False

    score = 0.0
    if AUTHOR_YEAR_YEAR_RE.search(value):
        score += 0.28
    if PAGE_RANGE_RE.search(value):
        score += 0.22
    if _extract_doi(value):
        score += 0.18
    if AUTHOR_YEAR_VENUE_RE.search(value):
        score += 0.16
    if value.rstrip().endswith((".", ";")):
        score += 0.12
    return score >= 0.32


def find_inline_author_year_boundaries(text: str) -> List[Dict[str, Any]]:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value or len(value) < 36:
        return []

    boundaries: List[Dict[str, Any]] = []
    for match in AUTHOR_YEAR_WORD_RE.finditer(value):
        start = match.start()
        if start < 18:
            continue
        prefix = value[:start].rstrip()
        suffix = value[start:].lstrip()
        if not _prefix_looks_like_entry_end(prefix):
            continue
        lead_score = score_author_year_lead(suffix)
        if lead_score["score"] < 0.65:
            continue
        if boundaries and start - boundaries[-1]["start"] < 18:
            continue
        boundaries.append(
            {
                "start": start,
                "score": lead_score["score"],
                "reasons": lead_score["reasons"],
                "prefix_preview": prefix[-80:],
                "suffix_preview": suffix[:140],
            }
        )
    return boundaries


def _looks_truncated(text: str, *, mode: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return True
    if value.endswith("-"):
        return True
    if len(value) < 28:
        return True
    if mode == "numeric_rich" and not re.search(r"\b(?:19|20)\d{2}\b", value):
        return len(value) < 56 and not _extract_doi(value)
    if mode == "author_year_rich":
        lead = score_author_year_lead(value)
        if lead["score"] < 0.45 and len(value) < 48:
            return True
    return False


def _looks_merged_numeric(text: str, expected_index: Optional[int]) -> bool:
    anchors = _extract_inline_anchor_numbers(text)
    foreign = [anchor for anchor in anchors if expected_index is None or anchor != expected_index]
    return len(foreign) > 0


def _looks_merged_author_year(text: str) -> bool:
    boundaries = find_inline_author_year_boundaries(text)
    return bool(boundaries)


def _best_reference_hint(
    *,
    candidate_text: str,
    index: Optional[int],
    references: Sequence[Dict[str, Any]],
    references_by_index: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if isinstance(index, int) and index in references_by_index:
        return references_by_index[index]

    best_hint: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for reference in references:
        if not isinstance(reference, dict):
            continue
        hint_text = str(reference.get("raw") or reference.get("text") or "")
        score = _normalized_similarity(candidate_text, hint_text)
        if score > best_score:
            best_score = score
            best_hint = reference
    if best_score < 0.28:
        return None
    return best_hint


def collect_inputs(
    *,
    references: Sequence[Dict[str, Any]],
    layers: Dict[str, Any],
    article_doi: str,
) -> Dict[str, Any]:
    bibliography_items = _layer_items(layers, "bibliographies")
    token_items = _layer_items(layers, "tokens")
    row_items = _layer_items(layers, "rows")
    paragraph_items = _layer_items(layers, "paragraphs")
    section_items = _layer_items(layers, "sections")

    input_references_by_index: Dict[int, List[Dict[str, Any]]] = {}
    for reference in references:
        if not isinstance(reference, dict):
            continue
        index = _entry_index(reference)
        if index is None or index <= 0:
            continue
        input_references_by_index.setdefault(index, []).append(reference)

    preferred_by_index: Dict[int, Dict[str, Any]] = {}
    for index, candidates in input_references_by_index.items():
        preferred = _pick_preferred_reference_input(candidates)
        if preferred is not None:
            preferred_by_index[index] = preferred

    crossref_context = _prepare_crossref_context(
        article_doi=article_doi,
        row_items=row_items,
        bibliography_start_page=None,
    )
    return {
        "bibliography_items": bibliography_items,
        "token_items": token_items,
        "row_items": row_items,
        "paragraph_items": paragraph_items,
        "section_items": section_items,
        "references_by_index": preferred_by_index,
        "references": [reference for reference in references if isinstance(reference, dict)],
        "crossref_context": crossref_context,
    }


def _row_overlaps_bibliography_item(
    row: Dict[str, Any],
    *,
    page: int,
    item_box: Sequence[float],
) -> bool:
    row_page = _page_index_value(row.get("page"))
    row_box = _normalize_box(row.get("box"))
    if row_page is None or row_page != page or row_box is None:
        return False
    return bool(_contains_box(item_box, row_box) or _overlap_ratio(item_box, row_box) >= 0.6)


def _build_fallback_bibliography_segments(
    *,
    rows_with_columns: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
    selected_heading: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidate_segments: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    heading_page = (
        _page_index_value(selected_heading.get("page"))
        if isinstance(selected_heading, dict)
        else None
    )

    for item in bibliography_items:
        page = _page_index_value(item.get("page"))
        item_box = _normalize_box(item.get("box"))
        if page is None or item_box is None:
            continue

        overlapping_rows = [
            row
            for row in rows_with_columns
            if _row_overlaps_bibliography_item(row, page=page, item_box=item_box)
        ]
        if not overlapping_rows:
            continue

        rows_by_column: Dict[str, List[Dict[str, Any]]] = {}
        for row in overlapping_rows:
            column_id = str(row.get("column_id") or "left")
            rows_by_column.setdefault(column_id, []).append(row)

        for column_id, column_rows in rows_by_column.items():
            ordered_rows = build_bibliography_reading_flow(column_rows)
            row_texts = [
                str(row.get("text") or "").strip()
                for row in ordered_rows
                if str(row.get("text") or "").strip()
            ]
            if len(row_texts) < 2:
                continue

            density = _compute_reference_density(row_texts)
            anchor_indices = [
                int(index)
                for index in (
                    extract_relaxed_numeric_anchor(text)
                    for text in row_texts
                )
                if isinstance(index, int) and int(index) > 0
            ]
            author_year_scores = [
                score_author_year_lead(text)["score"]
                for text in row_texts
                if text.lower() not in {"references", "bibliography", "works cited", "referencias", "bibliografia"}
            ]
            strong_author_year_ratio = (
                len([score for score in author_year_scores if score >= 0.55])
                / max(len(author_year_scores), 1)
            )

            if (
                density["score"] < 0.18
                and strong_author_year_ratio < 0.28
                and len(anchor_indices) < 2
            ):
                continue

            segment_box = _union_boxes(
                [
                    _normalize_box(row.get("box"))
                    for row in ordered_rows
                    if _normalize_box(row.get("box")) is not None
                ]
            ) or list(item_box)
            confidence = 0.24
            confidence += min(0.3, float(density["score"] or 0.0) * 0.45)
            confidence += min(0.22, strong_author_year_ratio * 0.32)
            if anchor_indices:
                confidence += min(0.12, len(anchor_indices) * 0.03)
            if len(ordered_rows) >= 4:
                confidence += 0.06
            if heading_page is not None and page >= heading_page:
                confidence += 0.08
            confidence = round(_clamp(confidence), 3)

            row_ids = tuple(str(row.get("id") or "") for row in ordered_rows if str(row.get("id") or ""))
            key = (page, column_id, row_ids)
            current = candidate_segments.get(key)
            candidate = {
                "page": page,
                "column_id": column_id,
                "box": segment_box,
                "source": "bibliography_layer_rows_fallback",
                "confidence": confidence,
                "row_count": len(ordered_rows),
                "reference_density": round(float(density.get("score") or 0.0), 3),
                "reference_density_mean": round(float(density.get("mean_score") or 0.0), 3),
                "reference_density_strong_ratio": round(
                    float(density.get("strong_ratio") or 0.0),
                    3,
                ),
                "leading_anchor_indices": anchor_indices,
                "raw_text": _merge_text_fragments(row_texts[:40]),
                "row_ids": list(row_ids),
                "tail_trim_applied": False,
                "tail_trim_reason": None,
                "tail_trim_removed_text": "",
                "tail_trim_removed_rows_count": 0,
                "tail_trim_scope": None,
            }
            if current is None or float(candidate["confidence"]) > float(current["confidence"]):
                candidate_segments[key] = candidate

    segments = sorted(
        candidate_segments.values(),
        key=lambda item: (
            int(item["page"]),
            str(item.get("column_id") or ""),
            float(item["box"][1]),
        ),
    )
    if not segments:
        return []

    kept_pages = {int(segments[-1]["page"])}
    previous_page = int(segments[-1]["page"])
    for page in sorted({int(segment["page"]) for segment in segments}, reverse=True)[1:]:
        if previous_page - page > 1:
            break
        kept_pages.add(page)
        previous_page = page
    return [segment for segment in segments if int(segment["page"]) in kept_pages]


def build_bibliography_zone(
    *,
    row_items: Sequence[Dict[str, Any]],
    section_items: Sequence[Dict[str, Any]],
    paragraph_items: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    phase = _build_bibliography_segments(
        rows=row_items,
        sections=section_items,
        paragraphs=paragraph_items,
        bibliography_items=bibliography_items,
    )
    bibliography_segments = list(phase.get("bibliography_segments") or [])
    fallback_strategy = None
    fallback_segments = (
        _build_fallback_bibliography_segments(
            rows_with_columns=phase.get("rows_with_columns") or row_items,
            bibliography_items=bibliography_items,
            selected_heading=phase.get("selected_heading"),
        )
        if bibliography_items
        else []
    )

    if fallback_segments:
        existing_pages = {int(segment["page"]) for segment in bibliography_segments}
        fallback_pages = {int(segment["page"]) for segment in fallback_segments}
        existing_anchor_total = len(
            {
                int(index)
                for segment in bibliography_segments
                for index in (segment.get("leading_anchor_indices") or [])
                if isinstance(index, int) and int(index) > 0
            }
        )
        fallback_anchor_total = len(
            {
                int(index)
                for segment in fallback_segments
                for index in (segment.get("leading_anchor_indices") or [])
                if isinstance(index, int) and int(index) > 0
            }
        )
        existing_max_density = max(
            (
                float(segment.get("reference_density") or 0.0)
                for segment in bibliography_segments
            ),
            default=0.0,
        )
        fallback_max_density = max(
            (
                float(segment.get("reference_density") or 0.0)
                for segment in fallback_segments
            ),
            default=0.0,
        )
        existing_has_numeric_signal = any(
            bool(segment.get("leading_anchor_indices")) for segment in bibliography_segments
        )
        if existing_has_numeric_signal and bibliography_segments:
            should_prefer_fallback = bool(
                fallback_anchor_total > existing_anchor_total + 2
                or (
                    existing_max_density < 0.16
                    and fallback_max_density >= existing_max_density + 0.08
                )
            )
        else:
            should_prefer_fallback = (
                not bibliography_segments
                or len(fallback_pages) > len(existing_pages)
                or fallback_max_density >= existing_max_density + 0.08
                or (
                    existing_max_density < 0.16
                    and fallback_max_density >= 0.18
                )
            )
        if should_prefer_fallback:
            bibliography_segments = fallback_segments
            fallback_strategy = "bibliography_layer_rows_fallback"

    if not bibliography_segments and bibliography_items:
        if not fallback_strategy:
            fallback_segments = []
            for item in bibliography_items:
                page = _page_index_value(item.get("page"))
                box = _normalize_box(item.get("box"))
                if page is None or box is None:
                    continue
                fallback_segments.append(
                    {
                        "page": page,
                        "column_id": "left",
                        "box": box,
                        "source": "bibliography_layer_fallback",
                        "confidence": 0.42,
                        "row_count": 0,
                        "reference_density": 0.0,
                        "reference_density_mean": 0.0,
                        "reference_density_strong_ratio": 0.0,
                        "leading_anchor_indices": [],
                        "raw_text": str(item.get("text") or ""),
                        "row_ids": [],
                        "tail_trim_applied": False,
                        "tail_trim_reason": None,
                        "tail_trim_removed_text": "",
                        "tail_trim_removed_rows_count": 0,
                        "tail_trim_scope": None,
                    }
                )
            bibliography_segments = sorted(
                fallback_segments,
                key=lambda item: (
                    int(item["page"]),
                    float(item["box"][1]),
                    float(item["box"][0]),
                ),
            )
            fallback_strategy = "bibliography_layer_box_fallback"

    bibliography_anchor = phase.get("bibliography_anchor")
    if bibliography_anchor is None and bibliography_segments:
        first_segment = bibliography_segments[0]
        bibliography_anchor = (
            int(first_segment["page"]),
            float(first_segment["box"][1]),
        )

    zone_confidence = round(
        _clamp(
            max(
                (
                    float(segment.get("confidence") or 0.0)
                    for segment in bibliography_segments
                ),
                default=0.0,
            )
        ),
        3,
    )
    return {
        "bibliography_zone": {
            "confidence": zone_confidence,
            "anchor": bibliography_anchor,
            "segments": bibliography_segments,
        },
        "bibliography_segments": bibliography_segments,
        "bibliography_anchor": bibliography_anchor,
        "rows_with_columns": phase.get("rows_with_columns") or [],
        "page_splits": phase.get("page_splits") or {},
        "bibliography_zone_debug": {
            "zone_confidence": zone_confidence,
            "selected_heading": phase.get("selected_heading"),
            "segment_count": len(bibliography_segments),
            "segments": bibliography_segments,
            "reading_order_blocks": phase.get("reading_order_blocks") or [],
            "column_reading_order": phase.get("column_reading_order") or [],
            "bibliography_end_candidates": phase.get("bibliography_end_candidates") or [],
            "bibliography_end_reason": phase.get("bibliography_end_reason"),
            "fallback_strategy": fallback_strategy,
        },
    }


def build_bibliography_stream(
    *,
    rows_with_columns: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    artifact_info = _build_repeating_page_artifacts(rows_with_columns)
    tokens_by_page = _index_tokens_by_page(token_items)
    selected_rows: List[Dict[str, Any]] = []
    excluded_rows: List[Dict[str, Any]] = []

    for row in rows_with_columns:
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        page = _page_index_value(row.get("page"))
        box = _normalize_box(row.get("box"))
        zone_match = _match_row_to_bibliography_segment(row, bibliography_segments)
        in_zone = bool(zone_match.get("inside_bibliography_zone"))
        include = True
        reason = "accepted"
        if page is None or box is None:
            include = False
            reason = "invalid_geometry"
        elif not in_zone:
            include = False
            reason = "outside_bibliography_zone"
        elif not text:
            include = False
            reason = "empty_text"
        elif row.get("text") and row.get("page") is not None:
            header_footer = row.get("id") and False
            header_footer = bool(
                not _extract_inline_anchor_numbers(text)
                and artifact_info
                and artifact_info.get("repeated_text_keys")
                and _normalize_text(text)
                in artifact_info.get("repeated_text_keys", set())
            )
            if header_footer and score_author_year_lead(text)["score"] < 0.6:
                include = False
                reason = "header_footer_noise"

        debug_item = {
            "id": str(row.get("id") or ""),
            "page": page,
            **_page_debug_fields(page),
            "column_id": row.get("column_id"),
            "box": _serialize_box(box),
            "text": text,
            "in_bibliography_zone": in_zone,
            "reason": reason,
            "included": include,
        }
        if not include:
            excluded_rows.append(debug_item)
            continue

        selected_rows.append(
            {
                "id": str(row.get("id") or f"row-{page}-{len(selected_rows) + 1}"),
                "text": text,
                "page": page,
                "box": box,
                "column_id": row.get("column_id") or "left",
                "x0": float(box[0]),
                "y0": float(box[1]),
                "x1": float(box[0]) + float(box[2]),
                "y1": float(box[1]) + float(box[3]),
                "width": float(box[2]),
                "height": float(box[3]),
            }
        )

    ordered_rows = build_bibliography_reading_flow(selected_rows)
    stream_units: List[Dict[str, Any]] = []
    anomaly_units: List[Dict[str, Any]] = []
    for flow_position, row in enumerate(ordered_rows):
        row["flow_position"] = flow_position
        row_tokens = _tokens_for_row(row, tokens_by_page)
        numeric_anchors = _extract_inline_anchor_numbers(str(row.get("text") or ""))
        author_year_boundaries = find_inline_author_year_boundaries(str(row.get("text") or ""))
        author_year_lead = score_author_year_lead(str(row.get("text") or ""))
        unit = {
            **row,
            "tokens": row_tokens,
            "tokens_total": len(row_tokens),
            "numeric_anchor_numbers": numeric_anchors,
            "author_year_lead_score": author_year_lead["score"],
            "author_year_lead_reasons": author_year_lead["reasons"],
            "author_year_inline_boundaries": author_year_boundaries,
        }
        if len(numeric_anchors) > 1 or author_year_boundaries:
            anomaly_units.append(
                {
                    "id": unit["id"],
                    "page": unit["page"],
                    "flow_position": flow_position,
                    "numeric_anchor_numbers": numeric_anchors,
                    "author_year_inline_boundaries": author_year_boundaries,
                    "text": unit["text"],
                }
            )
        stream_units.append(unit)

    return {
        "bibliography_stream": {"stream_units": stream_units},
        "stream_units": stream_units,
        "stream_debug": {
            "stream_units_total": len(stream_units),
            "excluded_rows_total": len(excluded_rows),
            "excluded_rows": excluded_rows[:80],
            "anomaly_units": anomaly_units[:80],
            "reading_order_preview": _rows_debug(stream_units[:60]),
        },
        "tokens_by_page": tokens_by_page,
    }


def repair_reference_candidate(
    *,
    candidate: Dict[str, Any],
    mode: str,
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    raw_rows = list(candidate.get("raw_rows") or [])
    source_rows = list(candidate.get("source_rows") or raw_rows)
    continuation_rows = list(candidate.get("continuation_rows") or [])
    raw_text = str(candidate.get("raw_text") or "").strip()
    repaired_rows = list(raw_rows)
    repaired_text = raw_text
    repair_actions: List[str] = []
    repair_notes: List[str] = []

    if (
        mode == "numeric_rich"
        and candidate.get("next_anchor_index") is not None
        and isinstance(candidate.get("next_anchor_index"), int)
    ):
        next_index = int(candidate["next_anchor_index"])
        next_anchor_token = f"[{next_index}]"
        split_pos = repaired_text.find(next_anchor_token)
        if split_pos > 0:
            repaired_text = repaired_text[:split_pos].strip()
            repair_actions.append("split_local_on_next_anchor")
            repair_notes.append(f"split_before_{next_anchor_token}")

    if mode == "author_year_rich":
        boundaries = find_inline_author_year_boundaries(repaired_text)
        if boundaries:
            repaired_text = repaired_text[: boundaries[0]["start"]].strip()
            repair_actions.append("trim_tail_on_inline_author_year_boundary")
            repair_notes.append("trimmed_merged_author_year_tail")

    if continuation_rows and _looks_truncated(repaired_text, mode=mode):
        extension_parts: List[str] = []
        extension_rows: List[Dict[str, Any]] = []
        for row in continuation_rows[:2]:
            row_text = str(row.get("text") or "").strip()
            if not row_text:
                continue
            if mode == "numeric_rich" and _extract_leading_reference_index(row_text) is not None:
                break
            if mode == "author_year_rich" and score_author_year_lead(row_text)["score"] >= 0.72:
                break
            extension_parts.append(row_text)
            extension_rows.append(row)
        if extension_parts:
            repaired_rows.extend(extension_rows)
            repaired_text = _merge_text_fragments([repaired_text, *extension_parts])
            repair_actions.append("extend_with_continuation_rows")
            repair_notes.append(f"extended_by_{len(extension_rows)}_rows")

    token_payload: Dict[str, Any] = {
        "raw_text": raw_text,
        "token_text": raw_text,
        "hybrid_text": raw_text,
        "final_text": repaired_text,
        "selected_candidate_source": "rows_raw",
        "cleanups_applied": [],
        "candidate_scores": [],
        "token_cleanup_confidence": 0.0,
        "token_rows_used": len(source_rows),
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
    if source_rows and bool(candidate.get("token_reconstruction_safe", False)):
        reconstructed = _reconstruct_reference_text_from_rows_and_tokens(
            source_rows,
            tokens_by_page,
        )
        reference_doi = _extract_doi(raw_text) or _extract_doi(repaired_text)
        selected = _select_reference_text_candidate(
            candidates=reconstructed.get("candidates") or [],
            reference_doi=reference_doi,
            crossref_context=crossref_context,
        )
        selected_text = str(selected.get("text") or "").strip()
        if selected_text:
            repaired_text = selected_text
            repair_actions.append("reconstruct_with_rows_and_tokens")
        token_payload.update(
            {
                "raw_text": str(reconstructed.get("raw_text") or raw_text),
                "token_text": str(reconstructed.get("token_text") or raw_text),
                "hybrid_text": str(reconstructed.get("hybrid_text") or raw_text),
                "final_text": repaired_text,
                "selected_candidate_source": str(selected.get("source") or "rows_raw"),
                "cleanups_applied": list(selected.get("cleanups_applied") or []),
                "candidate_scores": list(selected.get("candidate_scores") or []),
                "token_cleanup_confidence": round(
                    max(
                        (
                            float(item.get("quality_score") or 0.0)
                            for item in (selected.get("candidate_scores") or [])
                            if isinstance(item, dict)
                        ),
                        default=0.0,
                    ),
                    3,
                ),
                "order_guard_reasons": list(
                    next(
                        (
                            item.get("order_guard_reasons") or []
                            for item in (selected.get("candidate_scores") or [])
                            if isinstance(item, dict)
                            and str(item.get("source") or "")
                            == str(selected.get("source") or "rows_raw")
                        ),
                        [],
                    )
                ),
                "backbone_source": selected.get("backbone_source") or "rows_raw",
                "backbone_text": str(selected.get("backbone_text") or raw_text),
            }
        )

    fine_cleanup = _apply_reference_fine_cleanup(
        base_text=repaired_text,
        row_evidence_texts=[raw_text] + [str(row.get("text") or "") for row in repaired_rows],
        token_evidence_texts=[
            str(token_payload.get("raw_text") or ""),
            str(token_payload.get("token_text") or ""),
            str(token_payload.get("hybrid_text") or ""),
        ],
    )
    cleaned_text = str(fine_cleanup.get("text") or repaired_text).strip()
    if cleaned_text and cleaned_text != repaired_text:
        repair_actions.append("normalize_text_minimally")
    repaired_text = cleaned_text or repaired_text
    token_payload.update(
        {
            "final_text": repaired_text,
            "fine_cleanup_edits": list(fine_cleanup.get("accepted_edits") or []),
            "fine_cleanup_rejected_edits": list(
                fine_cleanup.get("rejected_edits") or []
            ),
            "punctuation_normalization_applied": bool(
                fine_cleanup.get("punctuation_normalization_applied")
            ),
            "punctuation_anomalies_detected": list(
                fine_cleanup.get("punctuation_anomalies_detected") or []
            ),
        }
    )
    token_payload["cleanups_applied"] = sorted(
        {
            str(value).strip()
            for value in list(token_payload.get("cleanups_applied") or [])
            + list(fine_cleanup.get("cleanups_applied") or [])
            if str(value).strip()
        }
    )
    token_payload["accepted_local_edit_count"] = len(token_payload["fine_cleanup_edits"])
    token_payload["rejected_local_edit_count"] = len(
        token_payload["fine_cleanup_rejected_edits"]
    )

    candidate.update(
        {
            "repaired_rows": repaired_rows,
            "repaired_text": repaired_text,
            "repair_actions_applied": repair_actions,
            "repair_debug": {
                "repair_notes": repair_notes,
                "token_reconstruction_safe": bool(
                    candidate.get("token_reconstruction_safe", False)
                ),
            },
            "token_reconstruction": token_payload,
        }
    )
    return candidate


def validate_reference_candidate(
    *,
    candidate: Dict[str, Any],
    mode: str,
    bibliography_segments: Sequence[Dict[str, Any]],
    references: Sequence[Dict[str, Any]],
    references_by_index: Dict[int, Dict[str, Any]],
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    text = str(candidate.get("repaired_text") or candidate.get("raw_text") or "").strip()
    rows = list(candidate.get("repaired_rows") or candidate.get("raw_rows") or [])
    index = candidate.get("index")
    doi = _extract_doi(text)
    hint = _best_reference_hint(
        candidate_text=text,
        index=index if isinstance(index, int) else None,
        references=references,
        references_by_index=references_by_index,
    )

    if rows:
        bibliography_zone_match_detail = _build_bibliography_zone_match_detail(
            rows,
            bibliography_segments,
        )
    else:
        bibliography_zone_match_detail = {
            "inside_bibliography_zone": False,
            "inside_bibliography_zone_reason": "no_rows_available",
            "row_matches": [],
        }

    inside_bibliography_zone = bool(
        bibliography_zone_match_detail.get("inside_bibliography_zone")
    )
    starts_with_expected_anchor = bool(
        mode == "numeric_rich"
        and isinstance(index, int)
        and _extract_leading_reference_index(text) == index
    )
    expected_column_consistency = bool(
        rows and len({str(row.get("column_id") or "") for row in rows}) == 1
    )
    row_continuity_score = round(
        float(_compute_row_continuity_score(rows) if rows else 0.0),
        3,
    )
    unresolved_overlap = bool(
        (mode == "numeric_rich" and _looks_merged_numeric(text, index if isinstance(index, int) else None))
        or (mode == "author_year_rich" and _looks_merged_author_year(text))
    )

    structural_components = [
        1.0 if inside_bibliography_zone else 0.0,
        1.0 if expected_column_consistency or not rows else 0.0,
        row_continuity_score,
    ]
    if mode == "numeric_rich":
        structural_components.append(1.0 if starts_with_expected_anchor else 0.0)
    structural_score = round(
        _clamp(sum(structural_components) / max(len(structural_components), 1) - (0.18 if unresolved_overlap else 0.0)),
        3,
    )

    lead_score = score_author_year_lead(text)["score"]
    length_score = _clamp(len(text) / 180.0)
    reference_like_score = float(_score_reference_like_text(text))
    text_quality_score = float(_reference_text_quality_score(text))
    has_year = bool(AUTHOR_YEAR_YEAR_RE.search(text))
    has_venue = bool(AUTHOR_YEAR_VENUE_RE.search(text))
    truncated = _looks_truncated(text, mode=mode)

    textual_score = (
        (0.34 * text_quality_score)
        + (0.22 * reference_like_score)
        + (0.18 * length_score)
        + (0.12 * (lead_score if mode == "author_year_rich" else (1.0 if starts_with_expected_anchor else 0.0)))
        + (0.08 * (1.0 if has_year else 0.0))
        + (0.06 * (1.0 if has_venue or doi else 0.0))
    )
    if truncated:
        textual_score -= 0.22
    if unresolved_overlap:
        textual_score -= 0.28
    textual_score = round(_clamp(textual_score), 3)
    if mode == "author_year_rich" and lead_score < 0.45:
        textual_score = round(_clamp(textual_score - 0.22), 3)

    metadata_similarity = 0.0
    hint_doi = _normalize_doi(str(hint.get("doi") or "")) if isinstance(hint, dict) else ""
    if isinstance(hint, dict):
        hint_text = str(hint.get("raw") or hint.get("text") or hint.get("title") or "")
        metadata_similarity = _normalized_similarity(text, hint_text)
    doi_match = 1.0 if doi and hint_doi and doi == hint_doi else 0.0
    crossref_match = _match_reference_against_crossref(
        reference_text=text,
        reference_doi=doi,
        crossref_context=crossref_context,
    )
    metadata_score = round(
        _clamp(
            (0.5 * metadata_similarity)
            + (0.25 * doi_match)
            + (0.2 * float(crossref_match.get("score") or 0.0))
            + (0.05 * float(crossref_match.get("doi_match_score") or 0.0))
        ),
        3,
    )

    combined_confidence = round(
        _clamp((0.46 * structural_score) + (0.39 * textual_score) + (0.15 * metadata_score)),
        3,
    )

    if not text:
        status = "failed"
        final_reason = "raw_candidate_missing"
    elif combined_confidence >= 0.8 and structural_score >= 0.62 and textual_score >= 0.62:
        status = "high_confidence"
        final_reason = "validated_high_confidence"
    elif combined_confidence >= 0.62 and structural_score >= 0.48 and textual_score >= 0.48:
        status = "medium_confidence"
        final_reason = "validated_medium_confidence"
    elif candidate.get("repair_actions_applied") and combined_confidence >= 0.42 and textual_score >= 0.34:
        status = "partial_repaired"
        final_reason = "validated_after_repair"
    else:
        status = "failed"
        if unresolved_overlap:
            final_reason = "validation_failed_unresolved_merge"
        elif truncated:
            final_reason = "validation_failed_truncated"
        else:
            final_reason = "validation_failed"
    if mode == "author_year_rich" and lead_score < 0.45 and not has_year:
        status = "failed"
        final_reason = "validation_failed_author_year_pattern"

    candidate.update(
        {
            "doi": doi or None,
            "status": status,
            "structural_score": structural_score,
            "textual_score": textual_score,
            "metadata_score": metadata_score,
            "combined_confidence": combined_confidence,
            "metadata_hint": hint,
            "crossref_match": crossref_match,
            "validation_debug": {
                "structural": {
                    "inside_bibliography_zone": inside_bibliography_zone,
                    "starts_with_expected_anchor": starts_with_expected_anchor,
                    "expected_column_consistency": expected_column_consistency,
                    "row_continuity_score": row_continuity_score,
                    "no_severe_unresolved_overlap": not unresolved_overlap,
                    "bibliography_zone_match_detail": bibliography_zone_match_detail,
                },
                "textual": {
                    "length_score": round(length_score, 3),
                    "reference_like_score": round(reference_like_score, 3),
                    "text_quality_score": round(text_quality_score, 3),
                    "author_year_lead_score": round(lead_score, 3),
                    "has_year": has_year,
                    "has_venue": has_venue,
                    "has_doi": bool(doi),
                    "truncated": truncated,
                    "unresolved_overlap": unresolved_overlap,
                },
                "metadata": {
                    "metadata_similarity": metadata_similarity,
                    "doi_match": doi_match,
                    "crossref_match_score": round(
                        float(crossref_match.get("score") or 0.0),
                        3,
                    ),
                    "crossref_doi_match_score": round(
                        float(crossref_match.get("doi_match_score") or 0.0),
                        3,
                    ),
                    "hint_index": hint.get("index") if isinstance(hint, dict) else None,
                },
            },
            "final_status": status,
            "final_reason": final_reason,
        }
    )
    return candidate


def build_fallback_candidates(
    *,
    references: Sequence[Dict[str, Any]],
    references_by_index: Dict[int, Dict[str, Any]],
    document_mode: str,
    reason: str,
) -> List[Dict[str, Any]]:
    ordered: List[Tuple[Optional[int], Dict[str, Any]]] = []
    if references_by_index:
        for index in sorted(references_by_index):
            ordered.append((index, references_by_index[index]))
    else:
        for reference in references:
            ordered.append((_entry_index(reference), reference))

    candidates: List[Dict[str, Any]] = []
    for position, (index, reference) in enumerate(ordered, start=1):
        raw_text = str(reference.get("raw") or reference.get("text") or "")
        candidates.append(
            {
                "candidate_id": f"fallback-{position}",
                "index": index,
                "raw_rows": [],
                "source_rows": [],
                "repaired_rows": [],
                "raw_text": raw_text,
                "repaired_text": raw_text,
                "repair_actions_applied": ["fallback_to_input_reference_text"] if raw_text else [],
                "repair_debug": {"fallback": True},
                "token_reconstruction": {
                    "raw_text": raw_text,
                    "token_text": raw_text,
                    "hybrid_text": raw_text,
                    "final_text": raw_text,
                    "selected_candidate_source": "fallback_input_reference",
                    "cleanups_applied": [],
                    "candidate_scores": [],
                    "token_cleanup_confidence": 0.0,
                    "token_rows_used": 0,
                    "order_guard_reasons": [],
                    "backbone_source": "fallback_input_reference",
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
                },
                "status": "failed",
                "final_status": "failed",
                "final_reason": reason,
                "structural_score": 0.0,
                "textual_score": round(_clamp(_reference_text_quality_score(raw_text) * 0.35), 3),
                "metadata_score": 0.0,
                "combined_confidence": 0.0,
                "crossref_match": {"score": 0.0, "doi_match_score": 0.0, "match": None},
                "anomalies_raw": [reason],
                "validation_debug": {},
                "mode": document_mode,
                "page": None,
                "box": None,
            }
        )
    return candidates


def audit_reference_coverage(
    *,
    mode: str,
    candidates: Sequence[Dict[str, Any]],
    expected_indices: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    if mode == "numeric_rich":
        expected = sorted({int(index) for index in expected_indices or [] if int(index) > 0})
        serialized_indices = sorted(
            int(candidate["index"])
            for candidate in candidates
            if isinstance(candidate.get("index"), int)
            and candidate.get("status") != "failed"
        )
        failed_indices = sorted(
            int(candidate["index"])
            for candidate in candidates
            if isinstance(candidate.get("index"), int)
            and candidate.get("status") == "failed"
        )
        missing_indices = sorted(
            int(candidate["index"])
            for candidate in candidates
            if isinstance(candidate.get("index"), int)
            and candidate.get("final_reason") == "raw_candidate_missing"
        )
        coverage_ratio = round(
            len(serialized_indices) / max(len(expected), 1),
            3,
        )
        if expected and coverage_ratio >= 0.9 and not failed_indices:
            extraction_status = "complete"
        elif expected and coverage_ratio >= 0.55:
            extraction_status = "partial"
        else:
            extraction_status = "inconsistent"
        return {
            "detected_anchor_indices": sorted(
                {
                    int(candidate["index"])
                    for candidate in candidates
                    if isinstance(candidate.get("index"), int)
                }
            ),
            "expected_indices": expected,
            "serialized_indices": serialized_indices,
            "failed_indices": failed_indices,
            "missing_indices": missing_indices,
            "coverage_ratio": coverage_ratio,
            "extraction_status": extraction_status,
        }

    candidate_ids = [str(candidate.get("candidate_id") or "") for candidate in candidates]
    serialized_candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if candidate.get("status") != "failed"
    ]
    failed_candidate_ids = [
        str(candidate.get("candidate_id") or "")
        for candidate in candidates
        if candidate.get("status") == "failed"
    ]
    coverage_ratio = round(
        len(serialized_candidate_ids) / max(len(candidate_ids), 1),
        3,
    )
    if candidate_ids and coverage_ratio >= 0.85 and len(failed_candidate_ids) <= 1:
        extraction_status = "complete"
    elif candidate_ids and coverage_ratio >= 0.55:
        extraction_status = "partial"
    else:
        extraction_status = "inconsistent"
    return {
        "candidate_indices_or_ids": candidate_ids,
        "serialized_candidate_ids": serialized_candidate_ids,
        "failed_candidate_ids": failed_candidate_ids,
        "coverage_ratio": coverage_ratio,
        "extraction_status": extraction_status,
    }


__all__ = [
    "_extract_doi",
    "_layer_items",
    "_normalize_box",
    "_normalize_doi",
    "_normalize_mention_text",
    "_page_debug_fields",
    "_page_index_value",
    "_page_number_from_index",
    "_parse_citation_numbers",
    "_pick_best_text_box",
    "_pick_context_paragraph",
    "_quantize_box",
    "_sanitize_filename_component",
    "_serialize_box",
    "_union_boxes",
    "AUTHOR_YEAR_VENUE_RE",
    "audit_reference_coverage",
    "build_bibliography_stream",
    "build_bibliography_zone",
    "build_fallback_candidates",
    "build_bibliography_reading_flow",
    "collect_inputs",
    "extract_relaxed_numeric_anchor",
    "find_inline_author_year_boundaries",
    "is_after_bibliography",
    "is_inside_bibliography",
    "repair_reference_candidate",
    "score_author_year_lead",
    "validate_reference_candidate",
]

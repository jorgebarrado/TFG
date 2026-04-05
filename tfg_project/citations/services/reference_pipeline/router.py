from __future__ import annotations

from typing import Any, Dict, Sequence

from ..references_legacy import (
    _assign_column_ids,
    _collect_page_split_map,
    _compute_reference_density,
    _detect_reference_heading_candidates,
)
from .common import (
    build_bibliography_reading_flow,
    extract_relaxed_numeric_anchor,
    score_author_year_lead,
)

REFERENCE_HEADINGS = {
    "references",
    "bibliography",
    "works cited",
    "referencias",
    "bibliografia",
}


def _anchor_continuity(anchor_indices: Sequence[int]) -> float:
    unique = sorted({int(index) for index in anchor_indices if int(index) > 0})
    if len(unique) <= 1:
        return 0.0
    contiguous_pairs = sum(
        1
        for previous, current in zip(unique, unique[1:])
        if current == previous + 1
    )
    return round(contiguous_pairs / max(len(unique) - 1, 1), 3)


def _clamp(value: float, floor: float = 0.0, ceil: float = 1.0) -> float:
    return max(floor, min(ceil, value))


def _mean_top_scores(scores: Sequence[float], *, limit: int = 12) -> float:
    if not scores:
        return 0.0
    window = sorted((float(score) for score in scores), reverse=True)[:limit]
    return sum(window) / max(len(window), 1)


def _summarize_author_year_signal(scores: Sequence[float]) -> Dict[str, float]:
    clean_scores = [float(score) for score in scores if float(score) > 0.0]
    if not clean_scores:
        return {
            "pattern_score": 0.0,
            "strong_ratio": 0.0,
            "top_mean": 0.0,
        }
    strong_ratio = len([score for score in clean_scores if score >= 0.55]) / max(
        len(clean_scores), 1
    )
    top_mean = _mean_top_scores(clean_scores)
    pattern_score = _clamp((top_mean * 0.62) + (strong_ratio * 0.38))
    return {
        "pattern_score": round(pattern_score, 3),
        "strong_ratio": round(strong_ratio, 3),
        "top_mean": round(top_mean, 3),
    }


def _resolve_profile_rows(
    *,
    ordered_rows: Sequence[Dict[str, Any]],
    heading_candidates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    if heading_candidates:
        selected_heading = sorted(
            heading_candidates,
            key=lambda item: (
                int(item.get("page") or 0),
                float((item.get("box") or [0.0, 0.0, 0.0, 0.0])[1]),
                -float(item.get("confidence") or 0.0),
            ),
        )[0]
        heading_page = int(selected_heading.get("page") or 0)
        heading_box = selected_heading.get("box") or [0.0, 0.0, 0.0, 0.0]
        heading_y = (
            float(heading_box[1])
            if isinstance(heading_box, (list, tuple)) and len(heading_box) >= 2
            else None
        )
        heading_rows = []
        for row in ordered_rows:
            row_page = row.get("page")
            if not isinstance(row_page, int):
                continue
            if row_page < heading_page:
                continue
            if row_page == heading_page and heading_y is not None:
                row_box = row.get("box") or [0.0, 0.0, 0.0, 0.0]
                row_y = (
                    float(row_box[1])
                    if isinstance(row_box, (list, tuple)) and len(row_box) >= 2
                    else None
                )
                if row_y is not None and row_y + 0.002 < heading_y:
                    continue
            heading_rows.append(row)
        minimum_rows = 3 if len(ordered_rows) < 18 else 6
        if len(heading_rows) >= minimum_rows:
            return {
                "rows": heading_rows,
                "row_source": "heading_window",
                "selected_heading": selected_heading,
            }

    tail_span = max(20, int(len(ordered_rows) * 0.28))
    tail_rows = ordered_rows[-tail_span:] if ordered_rows else []
    return {
        "rows": tail_rows,
        "row_source": "tail_window",
        "selected_heading": None,
    }


def _summarize_stream_inputs(stream_units: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    unit_texts = [
        str(unit.get("text") or "").strip()
        for unit in stream_units
        if str(unit.get("text") or "").strip()
    ]
    anchor_indices = [
        int(index)
        for index in (extract_relaxed_numeric_anchor(text) for text in unit_texts)
        if isinstance(index, int) and int(index) > 0
    ]
    author_year_scores = [
        score_author_year_lead(text)["score"]
        for text in unit_texts
        if text.lower() not in REFERENCE_HEADINGS
    ]
    author_year_summary = _summarize_author_year_signal(author_year_scores)
    density = _compute_reference_density(unit_texts)
    return {
        "anchor_indices": anchor_indices,
        "anchor_continuity": _anchor_continuity(anchor_indices),
        "author_year_pattern_score": author_year_summary["pattern_score"],
        "author_year_strong_ratio": author_year_summary["strong_ratio"],
        "author_year_top_mean": author_year_summary["top_mean"],
        "reference_density": density,
        "stream_units_total": len(stream_units),
    }


def build_document_profile(
    *,
    row_items: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
    section_items: Sequence[Dict[str, Any]],
    bibliography_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rows_with_columns = _assign_column_ids(row_items)
    page_splits = _collect_page_split_map(rows_with_columns)
    ordered_rows = build_bibliography_reading_flow(rows_with_columns)
    heading_candidates = _detect_reference_heading_candidates(
        rows_with_columns,
        section_items,
        page_splits,
    )
    profile_rows_payload = _resolve_profile_rows(
        ordered_rows=ordered_rows,
        heading_candidates=heading_candidates,
    )
    profile_rows = list(profile_rows_payload["rows"])

    anchor_indices = [
        int(index)
        for index in (
            extract_relaxed_numeric_anchor(str(row.get("text") or ""))
            for row in profile_rows
        )
        if isinstance(index, int) and int(index) > 0
    ]
    author_year_signal = _summarize_author_year_signal(
        [
            score_author_year_lead(str(row.get("text") or ""))["score"]
            for row in profile_rows
            if str(row.get("text") or "").strip()
            and str(row.get("text") or "").strip().lower() not in REFERENCE_HEADINGS
        ]
    )
    density = _compute_reference_density(
        [
            str(row.get("text") or "")
            for row in profile_rows
            if str(row.get("text") or "").strip()
        ]
    )
    strong_author_year_rows = int(
        round(author_year_signal["strong_ratio"] * max(len(profile_rows), 1))
    )

    rows_available = len(row_items)
    tokens_available = len(token_items)
    layout_confidence = 0.0
    if rows_available >= 40:
        layout_confidence += 0.4
    elif rows_available >= 20:
        layout_confidence += 0.24
    if tokens_available >= 150:
        layout_confidence += 0.35
    elif tokens_available >= 60:
        layout_confidence += 0.2
    if bibliography_items:
        layout_confidence += 0.15
    if heading_candidates:
        layout_confidence += 0.1
    layout_confidence = round(min(layout_confidence, 1.0), 3)

    bibliography_zone_confidence = 0.0
    if heading_candidates:
        bibliography_zone_confidence += 0.32
    if bibliography_items:
        bibliography_zone_confidence += 0.2
    if density["score"] >= 0.45:
        bibliography_zone_confidence += 0.24
    if anchor_indices:
        bibliography_zone_confidence += 0.14
    if strong_author_year_rows > 0:
        bibliography_zone_confidence += 0.1
    bibliography_zone_confidence = round(min(bibliography_zone_confidence, 1.0), 3)

    profile = {
        "document_mode": "weak_or_unknown",
        "bibliography_heading_detected": bool(heading_candidates),
        "numbered_anchor_count": len(anchor_indices),
        "author_year_pattern_score": author_year_signal["pattern_score"],
        "rows_available": rows_available,
        "tokens_available": tokens_available,
        "layout_confidence": layout_confidence,
        "bibliography_zone_confidence": bibliography_zone_confidence,
        "anchor_continuity": _anchor_continuity(anchor_indices),
    }
    return {
        "document_profile": profile,
        "routing_inputs": {
            "heading_candidates": heading_candidates,
            "anchor_indices": anchor_indices,
            "profile_rows_evaluated": len(profile_rows),
            "profile_row_source": profile_rows_payload["row_source"],
            "profile_reference_density": density,
            "strong_author_year_rows": strong_author_year_rows,
            "selected_heading_for_profile": profile_rows_payload["selected_heading"],
            "author_year_top_mean": author_year_signal["top_mean"],
            "author_year_strong_ratio": author_year_signal["strong_ratio"],
        },
        "rows_with_columns": rows_with_columns,
        "page_splits": page_splits,
    }


def route_reference_pipeline(
    document_profile: Dict[str, Any],
    *,
    routing_inputs: Dict[str, Any],
) -> Dict[str, Any]:
    raw_anchor_count = int(document_profile.get("numbered_anchor_count") or 0)
    raw_anchor_continuity = float(document_profile.get("anchor_continuity") or 0.0)
    raw_author_year_pattern_score = float(
        document_profile.get("author_year_pattern_score") or 0.0
    )
    layout_confidence = float(document_profile.get("layout_confidence") or 0.0)
    bibliography_zone_confidence = float(
        document_profile.get("bibliography_zone_confidence") or 0.0
    )
    heading_detected = bool(document_profile.get("bibliography_heading_detected"))
    profile_reference_density = float(
        ((routing_inputs or {}).get("profile_reference_density") or {}).get("score") or 0.0
    )

    stream_summary = _summarize_stream_inputs((routing_inputs or {}).get("stream_units") or [])
    anchor_count = (
        len(stream_summary["anchor_indices"])
        if stream_summary["stream_units_total"] > 0
        else raw_anchor_count
    )
    anchor_continuity = (
        float(stream_summary["anchor_continuity"])
        if stream_summary["stream_units_total"] > 0
        else raw_anchor_continuity
    )
    author_year_pattern_score = max(
        raw_author_year_pattern_score,
        float(stream_summary["author_year_pattern_score"] or 0.0),
    )
    reference_density = max(
        profile_reference_density,
        float((stream_summary.get("reference_density") or {}).get("score") or 0.0),
    )

    numeric_score = 0.0
    if heading_detected:
        numeric_score += 0.18
    if anchor_count >= 8:
        numeric_score += 0.46
    elif anchor_count >= 4:
        numeric_score += 0.34
    elif anchor_count >= 2:
        numeric_score += 0.18
    numeric_score += 0.18 * anchor_continuity
    numeric_score += 0.12 * layout_confidence
    numeric_score += 0.06 * bibliography_zone_confidence
    numeric_score = round(min(numeric_score, 1.0), 3)

    author_year_score = 0.0
    if heading_detected:
        author_year_score += 0.12
    author_year_score += 0.52 * author_year_pattern_score
    author_year_score += 0.14 * layout_confidence
    author_year_score += 0.12 * bibliography_zone_confidence
    author_year_score += 0.1 * reference_density
    if anchor_count >= 3:
        author_year_score -= 0.18
    author_year_score = round(max(0.0, min(author_year_score, 1.0)), 3)

    if numeric_score >= 0.48 and numeric_score >= author_year_score + 0.05:
        document_mode = "numeric_rich"
        selected_reason = "numbered_anchor_signal_strong"
    elif (
        (author_year_score >= 0.44 and anchor_count < 4)
        or (
            heading_detected
            and anchor_count == 0
            and layout_confidence >= 0.6
            and bibliography_zone_confidence >= 0.5
            and author_year_pattern_score >= 0.15
        )
    ):
        document_mode = "author_year_rich"
        selected_reason = "author_year_pattern_signal_strong"
    else:
        document_mode = "weak_or_unknown"
        selected_reason = "insufficient_rich_signal"

    next_profile = dict(document_profile)
    next_profile.update(
        {
            "document_mode": document_mode,
            "numbered_anchor_count": anchor_count,
            "author_year_pattern_score": round(author_year_pattern_score, 3),
            "anchor_continuity": round(anchor_continuity, 3),
        }
    )
    return {
        "document_profile": next_profile,
        "routing_debug": {
            "numeric_score": numeric_score,
            "author_year_score": author_year_score,
            "selected_pipeline": document_mode,
            "selected_reason": selected_reason,
            "anchor_count": anchor_count,
            "anchor_continuity": anchor_continuity,
            "author_year_pattern_score": author_year_pattern_score,
            "layout_confidence": layout_confidence,
            "bibliography_zone_confidence": bibliography_zone_confidence,
            "reference_density": reference_density,
            "raw_anchor_count": raw_anchor_count,
            "raw_anchor_continuity": raw_anchor_continuity,
            "raw_author_year_pattern_score": raw_author_year_pattern_score,
            "profile_row_source": (routing_inputs or {}).get("profile_row_source"),
            "profile_rows_evaluated": (routing_inputs or {}).get("profile_rows_evaluated"),
            "stream_units_evaluated": stream_summary["stream_units_total"],
            "stream_anchor_count": len(stream_summary["anchor_indices"]),
            "stream_anchor_continuity": stream_summary["anchor_continuity"],
            "stream_author_year_pattern_score": stream_summary["author_year_pattern_score"],
            "stream_author_year_strong_ratio": stream_summary["author_year_strong_ratio"],
            "stream_reference_density": (stream_summary.get("reference_density") or {}).get(
                "score"
            ),
        },
    }


__all__ = ["build_document_profile", "route_reference_pipeline"]

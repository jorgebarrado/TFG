from __future__ import annotations

from typing import Any, Dict, List, Sequence

from ..references_legacy import _merge_text_fragments
from .common import (
    _extract_doi,
    _union_boxes,
    audit_reference_coverage,
    find_inline_author_year_boundaries,
    repair_reference_candidate,
    score_author_year_lead,
    validate_reference_candidate,
)

REFERENCE_HEADINGS = {"references", "bibliography", "works cited", "referencias", "bibliografia"}


def detect_author_year_boundaries(
    stream_units: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    boundary_candidates: List[Dict[str, Any]] = []
    fragments: List[Dict[str, Any]] = []

    for unit in stream_units:
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        if text.lower() in REFERENCE_HEADINGS:
            continue

        lead = score_author_year_lead(text)
        inline_boundaries = find_inline_author_year_boundaries(text)
        split_positions = [item["start"] for item in inline_boundaries]
        fragment_spans: List[tuple[int, int]] = []
        if split_positions:
            previous = 0
            for position in split_positions:
                fragment_spans.append((previous, position))
                previous = position
            fragment_spans.append((previous, len(text)))
        else:
            fragment_spans.append((0, len(text)))

        for fragment_index, (start, end) in enumerate(fragment_spans):
            fragment_text = text[start:end].strip()
            if not fragment_text:
                continue
            fragment_lead = score_author_year_lead(fragment_text)
            starts_new_entry = bool(
                (fragment_index == 0 and lead["score"] >= 0.62)
                or fragment_index > 0
            )
            fragment = {
                "id": f"{unit.get('id') or 'row'}::ay-{fragment_index}",
                "source_row_id": str(unit.get("id") or ""),
                "source_row": unit,
                "page": unit.get("page"),
                "box": unit.get("box"),
                "column_id": unit.get("column_id"),
                "flow_position": unit.get("flow_position"),
                "text": fragment_text,
                "starts_new_entry": starts_new_entry,
                "split_from_inline_boundary": fragment_index > 0 or len(fragment_spans) > 1,
                "boundary_score": fragment_lead["score"],
                "boundary_reasons": fragment_lead["reasons"],
            }
            if starts_new_entry:
                boundary_candidates.append(
                    {
                        "fragment_id": fragment["id"],
                        "page": fragment["page"],
                        "flow_position": fragment["flow_position"],
                        "column_id": fragment["column_id"],
                        "score": fragment_lead["score"],
                        "reasons": fragment_lead["reasons"],
                        "text": fragment_text[:220],
                    }
                )
            fragments.append(fragment)

    if fragments and not any(fragment.get("starts_new_entry") for fragment in fragments):
        fragments[0]["starts_new_entry"] = True
        boundary_candidates.append(
            {
                "fragment_id": fragments[0]["id"],
                "page": fragments[0]["page"],
                "flow_position": fragments[0]["flow_position"],
                "column_id": fragments[0]["column_id"],
                "score": fragments[0]["boundary_score"],
                "reasons": fragments[0]["boundary_reasons"],
                "text": str(fragments[0].get("text") or "")[:220],
            }
        )

    return {
        "fragments": fragments,
        "boundary_candidates": boundary_candidates,
        "boundary_debug": {
            "boundary_candidates_total": len(boundary_candidates),
            "boundary_candidates": boundary_candidates[:120],
        },
    }


def _continuation_rows(
    stream_units: Sequence[Dict[str, Any]],
    *,
    source_flow_position: int,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for unit in stream_units:
        flow_position = int(unit.get("flow_position") or -1)
        if flow_position <= source_flow_position:
            continue
        if score_author_year_lead(str(unit.get("text") or ""))["score"] >= 0.72:
            break
        candidates.append(unit)
        if len(candidates) >= 2:
            break
    return candidates


def build_author_year_raw_candidates(
    *,
    stream_units: Sequence[Dict[str, Any]],
    boundary_detection: Dict[str, Any],
) -> Dict[str, Any]:
    fragments = list(boundary_detection.get("fragments") or [])
    raw_candidates: List[Dict[str, Any]] = []
    current_fragments: List[Dict[str, Any]] = []

    def _flush() -> None:
        nonlocal current_fragments
        if not current_fragments:
            return
        source_rows: List[Dict[str, Any]] = []
        seen_rows = set()
        for fragment in current_fragments:
            source_row_id = str(fragment.get("source_row_id") or "")
            if source_row_id in seen_rows:
                continue
            seen_rows.add(source_row_id)
            source_rows.append(fragment["source_row"])
        raw_text = _merge_text_fragments(
            [str(fragment.get("text") or "") for fragment in current_fragments]
        )
        anomalies_raw: List[str] = []
        if any(bool(fragment.get("split_from_inline_boundary")) for fragment in current_fragments):
            anomalies_raw.append("possible_split_or_merge")
        if find_inline_author_year_boundaries(raw_text):
            anomalies_raw.append("possible_merge")
        if not raw_text or raw_text.endswith("-") or _extract_doi(raw_text) == "":
            anomalies_raw.append("possible_truncation")
        columns = {
            str(row.get("column_id") or "")
            for row in source_rows
            if str(row.get("column_id") or "")
        }
        if len(columns) > 1:
            anomalies_raw.append("column_shift")
        page = source_rows[0].get("page") if source_rows else None
        candidate_index = len(raw_candidates) + 1
        token_reconstruction_safe = bool(
            source_rows
            and len(current_fragments) == len(source_rows)
            and not any(bool(fragment.get("split_from_inline_boundary")) for fragment in current_fragments)
        )
        raw_candidates.append(
            {
                "candidate_id": f"ay-{candidate_index}",
                "index": candidate_index,
                "mode": "author_year_rich",
                "raw_rows": current_fragments[:],
                "source_rows": source_rows,
                "raw_text": raw_text,
                "page": page,
                "box": _union_boxes(
                    [row.get("box") for row in source_rows if row.get("box") is not None]
                ),
                "anomalies_raw": sorted(set(anomalies_raw)),
                "continuation_rows": _continuation_rows(
                    stream_units,
                    source_flow_position=int(
                        max(
                            (
                                fragment.get("flow_position")
                                for fragment in current_fragments
                                if fragment.get("flow_position") is not None
                            ),
                            default=-1,
                        )
                    ),
                ),
                "token_reconstruction_safe": token_reconstruction_safe,
            }
        )
        current_fragments = []

    for fragment in fragments:
        if fragment.get("starts_new_entry") and current_fragments:
            _flush()
        current_fragments.append(fragment)
    _flush()
    return {
        "raw_candidates": raw_candidates,
        "raw_candidate_debug": {
            "raw_candidates_total": len(raw_candidates),
            "raw_candidates": [
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "index": candidate.get("index"),
                    "raw_text": str(candidate.get("raw_text") or "")[:320],
                    "anomalies_raw": candidate.get("anomalies_raw") or [],
                }
                for candidate in raw_candidates[:120]
            ],
        },
    }


def run_author_year_rich_pipeline(
    *,
    stream_units: Sequence[Dict[str, Any]],
    references: Sequence[Dict[str, Any]],
    references_by_index: Dict[int, Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    boundary_detection = detect_author_year_boundaries(stream_units)
    raw_candidates_payload = build_author_year_raw_candidates(
        stream_units=stream_units,
        boundary_detection=boundary_detection,
    )
    final_candidates: List[Dict[str, Any]] = []
    for candidate in raw_candidates_payload.get("raw_candidates") or []:
        candidate = repair_reference_candidate(
            candidate=candidate,
            mode="author_year_rich",
            tokens_by_page=tokens_by_page,
            crossref_context=crossref_context,
        )
        candidate = validate_reference_candidate(
            candidate=candidate,
            mode="author_year_rich",
            bibliography_segments=bibliography_segments,
            references=references,
            references_by_index=references_by_index,
            crossref_context=crossref_context,
        )
        final_candidates.append(candidate)

    coverage_audit = audit_reference_coverage(
        mode="author_year_rich",
        candidates=final_candidates,
    )
    return {
        "pipeline_mode": "author_year_rich",
        "reference_candidates": final_candidates,
        "boundary_candidates": boundary_detection.get("boundary_candidates") or [],
        "boundary_debug": boundary_detection.get("boundary_debug") or {},
        "raw_candidate_debug": raw_candidates_payload.get("raw_candidate_debug") or {},
        "coverage_audit": coverage_audit,
    }


__all__ = [
    "build_author_year_raw_candidates",
    "detect_author_year_boundaries",
    "run_author_year_rich_pipeline",
]

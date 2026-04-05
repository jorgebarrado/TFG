from __future__ import annotations

from collections import Counter
import re
from typing import Any, Dict, List, Optional, Sequence

from ..references_legacy import (
    REFERENCE_BLOCK_ANCHOR_RE,
    _extract_inline_anchor_numbers,
    _merge_text_fragments,
)
from .common import (
    _extract_doi,
    _union_boxes,
    audit_reference_coverage,
    extract_relaxed_numeric_anchor,
    repair_reference_candidate,
    validate_reference_candidate,
)


def _anchor_index_from_match(match: re.Match[str]) -> Optional[int]:
    value = match.group("bracket") or match.group("plain")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0 or parsed > 400 or 1900 <= parsed <= 2099:
        return None
    return parsed


def _split_numeric_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = str(row.get("text") or "").strip()
    if not text:
        return []
    matches = [
        match
        for match in REFERENCE_BLOCK_ANCHOR_RE.finditer(text)
        if match.group("bracket") is not None and _anchor_index_from_match(match) is not None
    ]
    if not matches:
        return [dict(row)]

    spans: List[tuple[int, int]] = []
    if matches[0].start() > 0:
        spans.append((0, matches[0].start()))
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans.append((match.start(), next_start))

    parts: List[Dict[str, Any]] = []
    for part_index, (start, end) in enumerate(spans):
        part_text = text[start:end].strip()
        if not part_text:
            continue
        next_row = dict(row)
        next_row["id"] = f"{row.get('id') or 'row'}::seg-{part_index}"
        next_row["text"] = part_text
        next_row["split_segment"] = True
        next_row["split_segment_index"] = part_index
        next_row["split_segment_total"] = len(spans)
        parts.append(next_row)
    return parts


def build_numeric_anchor_sequence(
    stream_units: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    exploded_units: List[Dict[str, Any]] = []
    source_unit_by_id = {
        str(unit.get("id") or ""): unit for unit in stream_units if isinstance(unit, dict)
    }
    anchor_occurrences: List[Dict[str, Any]] = []
    for unit in stream_units:
        parts = _split_numeric_row(unit) or [dict(unit)]
        for part_index, part in enumerate(parts):
            leading_anchor_index = extract_relaxed_numeric_anchor(str(part.get("text") or ""))
            exploded = {
                **part,
                "leading_anchor_index": leading_anchor_index,
                "position": len(exploded_units),
                "source_row_id": str(unit.get("id") or ""),
                "source_flow_position": int(unit.get("flow_position") or len(exploded_units)),
                "split_from_multi_anchor": len(parts) > 1,
                "split_segment_index": part_index,
                "split_segment_total": len(parts),
            }
            exploded_units.append(exploded)
            if isinstance(leading_anchor_index, int) and leading_anchor_index > 0:
                anchor_occurrences.append(exploded)

    anchor_counts = Counter(
        int(item["leading_anchor_index"])
        for item in anchor_occurrences
        if isinstance(item.get("leading_anchor_index"), int)
    )
    detected_anchor_indices = sorted(anchor_counts)
    duplicated_anchor_indices = sorted(
        index for index, count in anchor_counts.items() if count > 1
    )
    max_index = max(detected_anchor_indices, default=0)
    start_index = 0
    if detected_anchor_indices:
        start_index = 1 if detected_anchor_indices[0] <= 3 else detected_anchor_indices[0]
    expected_indices = list(range(start_index, max_index + 1)) if max_index > 0 else []
    initial_missing_indices = sorted(
        index for index in expected_indices if index not in anchor_counts
    )
    continuity = 0.0
    if len(detected_anchor_indices) > 1:
        continuity = sum(
            1
            for previous, current in zip(
                detected_anchor_indices,
                detected_anchor_indices[1:],
            )
            if current == previous + 1
        ) / max(len(detected_anchor_indices) - 1, 1)
    anchor_sequence_confidence = round(
        min(
            1.0,
            (
                (0.55 if len(detected_anchor_indices) >= 6 else 0.35 if len(detected_anchor_indices) >= 3 else 0.0)
                + (0.3 * continuity)
                + (0.1 if start_index == 1 else 0.0)
                - (0.08 * len(duplicated_anchor_indices))
            ),
        ),
        3,
    )
    return {
        "exploded_units": exploded_units,
        "source_unit_by_id": source_unit_by_id,
        "detected_anchor_indices": detected_anchor_indices,
        "expected_indices": expected_indices,
        "max_index": max_index,
        "initial_missing_indices": initial_missing_indices,
        "duplicated_anchor_indices": duplicated_anchor_indices,
        "anchor_sequence_confidence": anchor_sequence_confidence,
        "anchor_occurrences": anchor_occurrences,
        "anchor_sequence_debug": {
            "detected_anchor_indices": detected_anchor_indices,
            "expected_indices": expected_indices,
            "max_index": max_index,
            "initial_missing_indices": initial_missing_indices,
            "duplicated_anchor_indices": duplicated_anchor_indices,
            "anchor_sequence_confidence": anchor_sequence_confidence,
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
        if extract_relaxed_numeric_anchor(str(unit.get("text") or "")) is not None:
            break
        candidates.append(unit)
        if len(candidates) >= 2:
            break
    return candidates


def build_numeric_raw_candidates(
    *,
    stream_units: Sequence[Dict[str, Any]],
    anchor_sequence: Dict[str, Any],
    references_by_index: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    exploded_units = list(anchor_sequence.get("exploded_units") or [])
    expected_indices = list(anchor_sequence.get("expected_indices") or [])
    first_anchor_by_index: Dict[int, Dict[str, Any]] = {}
    for unit in exploded_units:
        index = unit.get("leading_anchor_index")
        if not isinstance(index, int) or index <= 0 or index in first_anchor_by_index:
            continue
        first_anchor_by_index[index] = unit

    raw_candidates: List[Dict[str, Any]] = []
    for index in expected_indices:
        anchor_unit = first_anchor_by_index.get(index)
        anomalies_raw: List[str] = []
        raw_rows: List[Dict[str, Any]] = []
        source_rows: List[Dict[str, Any]] = []
        raw_text = ""
        page = None
        box = None
        next_anchor_index: Optional[int] = None
        continuation_rows: List[Dict[str, Any]] = []
        token_reconstruction_safe = False

        if anchor_unit is None:
            anomalies_raw.append("raw_candidate_missing")
            raw_text = str(
                (references_by_index.get(index) or {}).get("raw")
                or (references_by_index.get(index) or {}).get("text")
                or ""
            ).strip()
        else:
            start_position = int(anchor_unit.get("position") or 0)
            next_position = len(exploded_units)
            for candidate_unit in exploded_units:
                position = int(candidate_unit.get("position") or -1)
                if position <= start_position:
                    continue
                if not isinstance(candidate_unit.get("leading_anchor_index"), int):
                    continue
                next_position = position
                next_anchor_index = (
                    int(candidate_unit["leading_anchor_index"])
                    if isinstance(candidate_unit.get("leading_anchor_index"), int)
                    else None
                )
                break
            raw_rows = exploded_units[start_position:next_position]
            seen_source_row_ids = set()
            for row in raw_rows:
                source_row_id = str(row.get("source_row_id") or "")
                if source_row_id in seen_source_row_ids:
                    continue
                seen_source_row_ids.add(source_row_id)
                source_rows.append(
                    next(
                        unit
                        for unit in stream_units
                        if str(unit.get("id") or "") == source_row_id
                    )
                )
            raw_text = _merge_text_fragments(
                [str(row.get("text") or "") for row in raw_rows]
            )
            page = source_rows[0].get("page") if source_rows else anchor_unit.get("page")
            box = _union_boxes(
                [
                    row.get("box")
                    for row in source_rows
                    if row.get("box") is not None
                ]
            )
            if any(bool(row.get("split_from_multi_anchor")) for row in raw_rows):
                anomalies_raw.append("foreign_anchor_inside_span")
            columns = {
                str(row.get("column_id") or "")
                for row in source_rows
                if str(row.get("column_id") or "")
            }
            if len(columns) > 1:
                anomalies_raw.append("column_shift")
            if any(
                extract_relaxed_numeric_anchor(str(row.get("text") or "")) not in (None, index)
                for row in raw_rows[1:]
            ):
                anomalies_raw.append("possible_merge")
            if len(
                {
                    int(row.get("page"))
                    for row in source_rows
                    if isinstance(row.get("page"), int)
                }
            ) > 1:
                anomalies_raw.append("large_gap")
            if not raw_text or raw_text.endswith("-") or _extract_doi(raw_text) == "":
                anomalies_raw.append("possible_truncation")
            continuation_rows = _continuation_rows(
                stream_units,
                source_flow_position=int(anchor_unit.get("source_flow_position") or 0),
            )
            token_reconstruction_safe = bool(
                source_rows
                and len(raw_rows) == len(source_rows)
                and not any(bool(row.get("split_from_multi_anchor")) for row in raw_rows)
            )

        raw_candidates.append(
            {
                "candidate_id": f"numeric-{index}",
                "index": index,
                "mode": "numeric_rich",
                "raw_rows": raw_rows,
                "source_rows": source_rows,
                "raw_text": raw_text,
                "page": page,
                "box": box,
                "anomalies_raw": sorted(set(anomalies_raw)),
                "next_anchor_index": next_anchor_index,
                "continuation_rows": continuation_rows,
                "token_reconstruction_safe": token_reconstruction_safe,
            }
        )
    return raw_candidates


def run_numeric_rich_pipeline(
    *,
    stream_units: Sequence[Dict[str, Any]],
    references: Sequence[Dict[str, Any]],
    references_by_index: Dict[int, Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    tokens_by_page: Dict[int, List[Dict[str, Any]]],
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    anchor_sequence = build_numeric_anchor_sequence(stream_units)
    raw_candidates = build_numeric_raw_candidates(
        stream_units=stream_units,
        anchor_sequence=anchor_sequence,
        references_by_index=references_by_index,
    )

    final_candidates: List[Dict[str, Any]] = []
    for candidate in raw_candidates:
        candidate = repair_reference_candidate(
            candidate=candidate,
            mode="numeric_rich",
            tokens_by_page=tokens_by_page,
            crossref_context=crossref_context,
        )
        candidate = validate_reference_candidate(
            candidate=candidate,
            mode="numeric_rich",
            bibliography_segments=bibliography_segments,
            references=references,
            references_by_index=references_by_index,
            crossref_context=crossref_context,
        )
        final_candidates.append(candidate)

    coverage_audit = audit_reference_coverage(
        mode="numeric_rich",
        candidates=final_candidates,
        expected_indices=anchor_sequence.get("expected_indices") or [],
    )
    return {
        "pipeline_mode": "numeric_rich",
        "reference_candidates": final_candidates,
        "coverage_expectation": {
            "detected_anchor_indices": anchor_sequence.get("detected_anchor_indices") or [],
            "expected_indices": anchor_sequence.get("expected_indices") or [],
            "max_index": anchor_sequence.get("max_index") or 0,
            "initial_missing_indices": anchor_sequence.get("initial_missing_indices") or [],
            "duplicated_anchor_indices": anchor_sequence.get("duplicated_anchor_indices") or [],
            "anchor_sequence_confidence": anchor_sequence.get("anchor_sequence_confidence") or 0.0,
        },
        "coverage_audit": coverage_audit,
        "anchor_sequence_debug": anchor_sequence.get("anchor_sequence_debug") or {},
    }


__all__ = [
    "build_numeric_anchor_sequence",
    "build_numeric_raw_candidates",
    "run_numeric_rich_pipeline",
]

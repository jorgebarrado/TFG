from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from .common import (
    _extract_doi,
    _normalize_box,
    _normalize_doi,
    _normalize_mention_text,
    _page_debug_fields,
    _page_index_value,
    _page_number_from_index,
    _parse_citation_numbers,
    _pick_best_text_box,
    _pick_context_paragraph,
    _quantize_box,
    _serialize_box,
    is_after_bibliography,
    is_inside_bibliography,
)


def _make_ref_id(candidate: Dict[str, Any], document_mode: str, position: int) -> str:
    index = candidate.get("index")
    if document_mode == "numeric_rich" and isinstance(index, int) and index > 0:
        return f"ref-{index}"
    if document_mode == "author_year_rich":
        return f"ref-ay-{position}"
    return f"ref-unlabeled-{position}"


def serialize_reference_entries(
    *,
    candidates: Sequence[Dict[str, Any]],
    document_mode: str,
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for position, candidate in enumerate(candidates, start=1):
        ref_id = _make_ref_id(candidate, document_mode, position)
        text = str(candidate.get("repaired_text") or candidate.get("raw_text") or "").strip()
        page = _page_index_value(candidate.get("page"))
        box = _normalize_box(candidate.get("box"))
        source_rows = list(candidate.get("source_rows") or [])
        validation_debug = candidate.get("validation_debug") or {}
        structural_debug = validation_debug.get("structural") or {}
        metadata_debug = validation_debug.get("metadata") or {}
        anomalies = sorted(
            {
                str(item).strip()
                for item in list(candidate.get("anomalies_raw") or [])
                + ([candidate.get("final_reason")] if candidate.get("final_reason") else [])
                if str(item).strip()
            }
        )
        accepted = candidate.get("status") != "failed"
        final_decision = {
            "structural_score": round(float(candidate.get("structural_score") or 0.0), 3),
            "textual_score": round(float(candidate.get("textual_score") or 0.0), 3),
            "metadata_score": round(float(candidate.get("metadata_score") or 0.0), 3),
            "combined_confidence": round(
                float(candidate.get("combined_confidence") or 0.0),
                3,
            ),
            "inside_bibliography_zone": bool(
                structural_debug.get("inside_bibliography_zone")
            ),
            "inside_expected_column": bool(
                structural_debug.get("expected_column_consistency")
            ),
            "starts_with_anchor": bool(structural_debug.get("starts_with_expected_anchor")),
            "expected_anchor_index": candidate.get("index"),
            "has_nested_anchor": "possible_merge" in anomalies
            or "validation_failed_unresolved_merge" in anomalies,
            "crossref_match_score": round(
                float(metadata_debug.get("crossref_match_score") or 0.0),
                3,
            ),
            "doi_match_score": round(
                float(metadata_debug.get("crossref_doi_match_score") or 0.0),
                3,
            ),
            "row_continuity_score": round(
                float(structural_debug.get("row_continuity_score") or 0.0),
                3,
            ),
            "cleanup_applied": bool(candidate.get("repair_actions_applied")),
            "selected_candidate_source": (
                (candidate.get("token_reconstruction") or {}).get("selected_candidate_source")
                or document_mode
            ),
            "final_score": round(float(candidate.get("combined_confidence") or 0.0), 3),
            "accepted": accepted,
            "classification": candidate.get("status"),
            "reason": candidate.get("final_reason"),
            "bibliography_zone_match_detail": structural_debug.get(
                "bibliography_zone_match_detail"
            ),
            "accepted_local_edit_count": len(candidate.get("repair_actions_applied") or []),
            "rejected_local_edit_count": int(
                ((candidate.get("token_reconstruction") or {}).get("rejected_local_edit_count") or 0)
            ),
        }
        reference_validation = {
            "match_score": round(float(candidate.get("metadata_score") or 0.0), 3),
            "mixed_reference_score": 1.0 if "possible_merge" in anomalies else 0.0,
            "has_nested_anchor": bool(final_decision["has_nested_anchor"]),
            "accepted": accepted,
            "reason": None if accepted else candidate.get("final_reason"),
            "intermediate_accepted": bool(
                float(candidate.get("combined_confidence") or 0.0) >= 0.42
            ),
            "intermediate_reason": candidate.get("final_reason"),
            "final_classification": candidate.get("status"),
            "final_score": round(float(candidate.get("combined_confidence") or 0.0), 3),
        }
        entries.append(
            {
                "id": f"reference-entry-{ref_id}",
                "ref_id": ref_id,
                "index": candidate.get("index"),
                "text": text,
                "text_candidate_raw": str(candidate.get("raw_text") or ""),
                "page": page,
                **_page_debug_fields(page),
                "box": box,
                "doi": candidate.get("doi"),
                "status": candidate.get("status"),
                "combined_confidence": round(
                    float(candidate.get("combined_confidence") or 0.0),
                    3,
                ),
                "structural_score": round(
                    float(candidate.get("structural_score") or 0.0),
                    3,
                ),
                "textual_score": round(
                    float(candidate.get("textual_score") or 0.0),
                    3,
                ),
                "metadata_score": round(
                    float(candidate.get("metadata_score") or 0.0),
                    3,
                ),
                "final_decision_reason": candidate.get("final_reason"),
                "anomalies": {
                    "items": anomalies,
                    "tail_trim_applied": False,
                    "tail_trim_reason": None,
                    "tail_trim_removed_text": "",
                    "tail_trim_removed_rows_count": 0,
                    "tail_trim_scope": None,
                },
                "repair_actions_applied": list(candidate.get("repair_actions_applied") or []),
                "structure_source": document_mode,
                "local_row_count": len(source_rows),
                "local_anchor_detected": bool(
                    document_mode == "numeric_rich" and isinstance(candidate.get("index"), int)
                ),
                "reference_validation": reference_validation,
                "validation_intermediate": {
                    "match_score": reference_validation["match_score"],
                    "mixed_reference_score": reference_validation["mixed_reference_score"],
                    "has_nested_anchor": reference_validation["has_nested_anchor"],
                    "accepted": reference_validation["intermediate_accepted"],
                    "reason": reference_validation["intermediate_reason"],
                },
                "scores": final_decision,
                "final_decision": final_decision,
                "bibliography_zone_match_detail": final_decision.get(
                    "bibliography_zone_match_detail"
                ),
                "crossref_match": candidate.get("crossref_match") or {},
                "token_reconstruction": candidate.get("token_reconstruction") or {},
                "raw_rows": list(candidate.get("raw_rows") or []),
                "repaired_rows": list(candidate.get("repaired_rows") or []),
                "raw_text": str(candidate.get("raw_text") or ""),
                "repaired_text": text,
                "anomalies_raw": list(candidate.get("anomalies_raw") or []),
                "repair_debug": candidate.get("repair_debug") or {},
                "validation_scores": {
                    "structural_score": round(float(candidate.get("structural_score") or 0.0), 3),
                    "textual_score": round(float(candidate.get("textual_score") or 0.0), 3),
                    "metadata_score": round(float(candidate.get("metadata_score") or 0.0), 3),
                    "combined_confidence": round(float(candidate.get("combined_confidence") or 0.0), 3),
                },
                "final_status": candidate.get("status"),
                "final_reason": candidate.get("final_reason"),
            }
        )
    return entries


def build_citations_and_contexts(
    *,
    snippets: Sequence[Dict[str, Any]],
    references: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
    row_items: Sequence[Dict[str, Any]],
    paragraph_items: Sequence[Dict[str, Any]],
    bibliography_segments: Sequence[Dict[str, Any]],
    bibliography_anchor: Any,
    document_mode: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    references_by_index: Dict[int, str] = {}
    references_by_doi: Dict[str, str] = {}
    for reference in references:
        ref_id = str(reference.get("ref_id") or "")
        index = reference.get("index")
        if ref_id and isinstance(index, int):
            references_by_index[index] = ref_id
        doi = _normalize_doi(str(reference.get("doi") or ""))
        if ref_id and doi:
            references_by_doi[doi] = ref_id

    citations: List[Dict[str, Any]] = []
    contexts: List[Dict[str, Any]] = []
    seen_mentions = set()
    contexts_seen = set()
    mention_text_key_max_len = 220

    for snippet_idx, snippet in enumerate(snippets, start=1):
        if not isinstance(snippet, dict):
            continue
        snippet_text = str(snippet.get("snippet") or snippet.get("text") or "")
        if not snippet_text:
            continue

        ref_ids: List[str] = []
        extracted_doi = _normalize_doi(_extract_doi(snippet_text))
        if extracted_doi and extracted_doi in references_by_doi:
            ref_ids.append(references_by_doi[extracted_doi])

        if document_mode == "numeric_rich":
            for number in _parse_citation_numbers(snippet_text):
                ref_id = references_by_index.get(number)
                if ref_id:
                    ref_ids.append(ref_id)

        seen_ref_ids = set()
        dedup_ref_ids: List[str] = []
        for ref_id in ref_ids:
            if ref_id in seen_ref_ids:
                continue
            seen_ref_ids.add(ref_id)
            dedup_ref_ids.append(ref_id)
        if not dedup_ref_ids:
            continue

        page_hint = _page_index_value(snippet.get("page"))
        mention_anchor = _pick_best_text_box(
            snippet_text,
            page_hint,
            list(token_items),
            list(row_items),
            list(paragraph_items),
        )
        mention_page = mention_anchor["page"] if mention_anchor is not None else page_hint
        mention_box = mention_anchor["box"] if mention_anchor is not None else None
        mention_y = float(mention_box[1]) if isinstance(mention_box, list) else None

        if mention_y is not None and (mention_y < 0.05 or mention_y > 0.95):
            continue
        if is_inside_bibliography(
            {"page": mention_page, "box": mention_box},
            bibliography_segments,
        ):
            continue
        if is_after_bibliography(mention_page, mention_y, bibliography_anchor):
            continue

        for mention_pos, ref_id in enumerate(dedup_ref_ids, start=1):
            quantized_mention_box = _quantize_box(mention_box)
            if quantized_mention_box is not None:
                dedupe_key = ("box", ref_id, mention_page, quantized_mention_box)
            else:
                dedupe_key = (
                    "text",
                    ref_id,
                    mention_page,
                    _normalize_mention_text(snippet_text)[:mention_text_key_max_len],
                )
            if dedupe_key in seen_mentions:
                continue
            seen_mentions.add(dedupe_key)

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
                item for item in paragraph_items if item.get("page") == mention_page
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

    return citations, contexts


def build_debug_payload(
    *,
    source_filename: str,
    article_doi: str,
    engine_used: str,
    pipeline_version: str,
    bibliography_anchor: Any,
    bibliography_segments: Sequence[Dict[str, Any]],
    stream_debug: Dict[str, Any],
    bibliography_zone_debug: Dict[str, Any],
    document_profile: Dict[str, Any],
    routing_debug: Dict[str, Any],
    coverage_audit: Dict[str, Any],
    pipeline_debug: Dict[str, Any],
    reference_entries: Sequence[Dict[str, Any]],
    token_items: Sequence[Dict[str, Any]],
    crossref_context: Dict[str, Any],
) -> Dict[str, Any]:
    bibliography_start_page_index = (
        bibliography_anchor[0] if isinstance(bibliography_anchor, tuple) else None
    )
    bibliography_start_page_number = _page_number_from_index(
        bibliography_start_page_index
    )
    return {
        "metadata": {
            "file_name": str(source_filename or ""),
            "article_doi": _normalize_doi(str(article_doi or "")) or None,
            "engine_used": str(engine_used or ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "debug_mode": True,
            "pipeline_version": pipeline_version,
            "page_convention_internal": "page_index_zero_based",
            "page_convention_human": "page_number_one_based",
            "bibliography_start_page": bibliography_start_page_number,
            "bibliography_start_page_index": bibliography_start_page_index,
            "bibliography_start_page_number": bibliography_start_page_number,
            "references_total_detected": len(reference_entries),
            "references_total_debug": len(reference_entries),
            "references_total_serialized": len(reference_entries),
            "references_total_source": "reference_entries_final",
            "final_reference_ids_serialized": [
                str(entry.get("ref_id") or "")
                for entry in reference_entries
                if str(entry.get("ref_id") or "").strip()
            ],
            "total_rows_in_bibliography": int(
                stream_debug.get("stream_units_total") or 0
            ),
            "total_tokens_in_bibliography": len(token_items),
            "crossref_available": bool(crossref_context.get("crossref_available")),
            "crossref_reference_count": int(
                crossref_context.get("crossref_reference_count") or 0
            ),
        },
        "document_profile": document_profile,
        "routing_debug": routing_debug,
        "bibliography_zone_debug": bibliography_zone_debug,
        "stream_debug": stream_debug,
        "coverage_audit": coverage_audit,
        "phases": {
            "document_profile": document_profile,
            "routing": routing_debug,
            "bibliography_zone": bibliography_zone_debug,
            "stream": stream_debug,
            "pipeline": pipeline_debug,
        },
        "references": [dict(entry) for entry in reference_entries],
    }


__all__ = [
    "build_citations_and_contexts",
    "build_debug_payload",
    "serialize_reference_entries",
]

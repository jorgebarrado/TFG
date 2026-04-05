from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .reference_pipeline.facade import (
    REFERENCE_PIPELINE_VERSION,
    build_references_data_payload,
)
from .references_legacy import (
    REFERENCE_DEBUG_DIR,
    REFERENCE_DEBUG_FILE_EXTENSION,
    REFERENCE_DEBUG_FILE_PREFIX,
    REFERENCE_NOISE_RE,
    _page_debug_fields,
    _page_index_value,
    _page_number_from_index,
    _sanitize_filename_component,
)


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
    return build_references_data_payload(
        references=references,
        snippets=snippets,
        layers=layers,
        references_numbered=references_numbered,
        article_doi=article_doi,
        source_filename=source_filename,
        engine_used=engine_used,
        debug_reference_detection=debug_reference_detection,
    )


def finalize_reference_detection_debug_payload(
    debug_payload: Optional[Dict[str, Any]],
    *,
    references: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(debug_payload, dict):
        return None

    finalized_references = []
    for entry in references:
        if not isinstance(entry, dict):
            continue
        final_decision = (
            entry.get("final_decision")
            if isinstance(entry.get("final_decision"), dict)
            else (
                entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
            )
        )
        token_info = (
            entry.get("token_reconstruction")
            if isinstance(entry.get("token_reconstruction"), dict)
            else {}
        )
        finalized_references.append(
            {
                "ref_id": entry.get("ref_id"),
                "index": entry.get("index"),
                "page": _page_index_value(entry.get("page")),
                "page_index": _page_index_value(entry.get("page")),
                "page_number": _page_number_from_index(entry.get("page")),
                "status": entry.get("status"),
                "source": entry.get("structure_source"),
                "structure_source": entry.get("structure_source"),
                "candidate_text_raw": entry.get("text_candidate_raw") or entry.get("text"),
                "token_candidate_text": token_info.get("token_text"),
                "hybrid_candidate_text": token_info.get("hybrid_text"),
                "backbone_text": token_info.get("backbone_text"),
                "final_text": entry.get("text"),
                "doi_detected": entry.get("doi"),
                "accepted": bool(final_decision.get("accepted")),
                "rejected": not bool(final_decision.get("accepted")),
                "reason": final_decision.get("reason"),
                "final_decision": final_decision,
                "validation_intermediate": entry.get("validation_intermediate") or {},
                "scores": final_decision,
                "bibliography_zone_match_detail": entry.get(
                    "bibliography_zone_match_detail"
                ),
                "cleanups_applied": token_info.get("cleanups_applied") or [],
                "selected_candidate_source": token_info.get(
                    "selected_candidate_source"
                ),
                "order_guard_reasons": token_info.get("order_guard_reasons") or [],
                "backbone_source": token_info.get("backbone_source"),
                "candidate_scores": token_info.get("candidate_scores") or [],
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
                "anomalies": entry.get("anomalies") or {},
                "repair_actions_applied": entry.get("repair_actions_applied") or [],
                "final_status": entry.get("final_status"),
                "final_reason": entry.get("final_reason"),
            }
        )

    debug_payload["references"] = finalized_references
    debug_payload.setdefault("metadata", {})
    debug_payload["metadata"]["references_total_detected"] = len(finalized_references)
    debug_payload["metadata"]["references_total_debug"] = len(finalized_references)
    debug_payload["metadata"]["references_total_serialized"] = len(finalized_references)
    debug_payload["metadata"]["references_total_source"] = "reference_entries_final"
    debug_payload["metadata"]["final_reference_ids_serialized"] = [
        str(entry.get("ref_id") or "")
        for entry in finalized_references
        if str(entry.get("ref_id") or "").strip()
    ]
    debug_payload["metadata"]["pipeline_version"] = REFERENCE_PIPELINE_VERSION
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


__all__ = [
    "REFERENCE_NOISE_RE",
    "REFERENCE_PIPELINE_VERSION",
    "build_references_data",
    "finalize_reference_detection_debug_payload",
    "write_reference_detection_debug_json",
]

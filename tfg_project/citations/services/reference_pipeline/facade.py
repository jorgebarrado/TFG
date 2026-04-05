from __future__ import annotations

from typing import Any, Dict, Sequence

from citations.logging_utils import get_logger

from .author_year import run_author_year_rich_pipeline
from .common import (
    audit_reference_coverage,
    build_bibliography_stream,
    build_bibliography_zone,
    build_fallback_candidates,
    collect_inputs,
)
from .numeric import run_numeric_rich_pipeline
from .router import build_document_profile, route_reference_pipeline
from .serialization import (
    build_citations_and_contexts,
    build_debug_payload,
    serialize_reference_entries,
)

logger = get_logger("citations.references")
REFERENCE_PIPELINE_VERSION = "references-router-v1"


def build_references_data_payload(
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
        "build_references_data: %s referencias, %s snippets. references_numbered=%s",
        len(references),
        len(snippets),
        references_numbered,
    )

    inputs = collect_inputs(
        references=references,
        layers=layers,
        article_doi=article_doi,
    )
    profile_payload = build_document_profile(
        row_items=inputs["row_items"],
        token_items=inputs["token_items"],
        section_items=inputs["section_items"],
        bibliography_items=inputs["bibliography_items"],
    )
    document_profile = dict(profile_payload["document_profile"])

    zone_payload = build_bibliography_zone(
        row_items=inputs["row_items"],
        section_items=inputs["section_items"],
        paragraph_items=inputs["paragraph_items"],
        bibliography_items=inputs["bibliography_items"],
    )
    bibliography_segments = zone_payload["bibliography_segments"]
    bibliography_anchor = zone_payload["bibliography_anchor"]
    bibliography_zone_debug = zone_payload["bibliography_zone_debug"]
    if bibliography_segments:
        document_profile["bibliography_zone_confidence"] = max(
            float(document_profile.get("bibliography_zone_confidence") or 0.0),
            float(zone_payload["bibliography_zone"].get("confidence") or 0.0),
        )

    stream_payload = build_bibliography_stream(
        rows_with_columns=zone_payload["rows_with_columns"],
        bibliography_segments=bibliography_segments,
        token_items=inputs["token_items"],
    )
    stream_units = stream_payload["stream_units"]
    routed = route_reference_pipeline(
        document_profile,
        routing_inputs={
            **profile_payload["routing_inputs"],
            "stream_units": stream_units,
        },
    )
    document_profile = routed["document_profile"]
    routing_debug = routed["routing_debug"]

    if document_profile["document_mode"] == "numeric_rich":
        pipeline_result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=inputs["references"],
            references_by_index=inputs["references_by_index"],
            bibliography_segments=bibliography_segments,
            tokens_by_page=stream_payload["tokens_by_page"],
            crossref_context=inputs["crossref_context"],
        )
    elif document_profile["document_mode"] == "author_year_rich":
        pipeline_result = run_author_year_rich_pipeline(
            stream_units=stream_units,
            references=inputs["references"],
            references_by_index=inputs["references_by_index"],
            bibliography_segments=bibliography_segments,
            tokens_by_page=stream_payload["tokens_by_page"],
            crossref_context=inputs["crossref_context"],
        )
    else:
        fallback_candidates = build_fallback_candidates(
            references=inputs["references"],
            references_by_index=inputs["references_by_index"],
            document_mode=document_profile["document_mode"],
            reason="routing_not_supported",
        )
        pipeline_result = {
            "pipeline_mode": document_profile["document_mode"],
            "reference_candidates": fallback_candidates,
            "coverage_audit": audit_reference_coverage(
                mode="author_year_rich",
                candidates=fallback_candidates,
            ),
        }

    reference_entries = serialize_reference_entries(
        candidates=pipeline_result.get("reference_candidates") or [],
        document_mode=document_profile["document_mode"],
    )
    citations, contexts = build_citations_and_contexts(
        snippets=snippets,
        references=reference_entries,
        token_items=inputs["token_items"],
        row_items=inputs["row_items"],
        paragraph_items=inputs["paragraph_items"],
        bibliography_segments=bibliography_segments,
        bibliography_anchor=bibliography_anchor,
        document_mode=document_profile["document_mode"],
    )

    bibliography_start_page_index = (
        bibliography_anchor[0] if isinstance(bibliography_anchor, tuple) else None
    )
    bibliography_start_page_number = (
        bibliography_start_page_index + 1
        if isinstance(bibliography_start_page_index, int)
        else None
    )

    final_reference_ids_serialized = [
        str(entry.get("ref_id") or "")
        for entry in reference_entries
        if str(entry.get("ref_id") or "").strip()
    ]
    max_reference_index = max(
        (
            int(entry.get("index"))
            for entry in reference_entries
            if isinstance(entry.get("index"), int)
        ),
        default=len(reference_entries),
    )
    coverage_audit = pipeline_result.get("coverage_audit") or {}
    global_alerts = {
        "missing_indices": coverage_audit.get("missing_indices") or [],
        "failed_reference_ids": [
            str(entry.get("ref_id") or "")
            for entry in reference_entries
            if entry.get("status") == "failed"
        ],
        "coverage_ratio": coverage_audit.get("coverage_ratio"),
        "extraction_status": coverage_audit.get("extraction_status"),
    }

    debug_payload = None
    if debug_reference_detection:
        pipeline_debug = dict(pipeline_result)
        pipeline_debug.pop("reference_candidates", None)
        debug_payload = build_debug_payload(
            source_filename=source_filename,
            article_doi=article_doi,
            engine_used=engine_used,
            pipeline_version=REFERENCE_PIPELINE_VERSION,
            bibliography_anchor=bibliography_anchor,
            bibliography_segments=bibliography_segments,
            stream_debug=stream_payload["stream_debug"],
            bibliography_zone_debug=bibliography_zone_debug,
            document_profile=document_profile,
            routing_debug=routing_debug,
            coverage_audit=coverage_audit,
            pipeline_debug=pipeline_debug,
            reference_entries=reference_entries,
            token_items=inputs["token_items"],
            crossref_context=inputs["crossref_context"],
        )

    logger.info(
        "Completado build_references_data: %s reference_entries, %s citations, %s contexts construidos.",
        len(reference_entries),
        len(citations),
        len(contexts),
    )
    return {
        "references": reference_entries,
        "references_total": len(reference_entries),
        "references_total_source": "reference_entries_final",
        "final_reference_ids_serialized": final_reference_ids_serialized,
        "citations": citations,
        "contexts": contexts,
        "citation_style": "numeric"
        if document_profile["document_mode"] == "numeric_rich" or references_numbered
        else "non_numeric",
        "document_mode": document_profile["document_mode"],
        "max_reference_index": max_reference_index,
        "bibliography_start_page": bibliography_start_page_number,
        "bibliography_start_page_index": bibliography_start_page_index,
        "bibliography_start_page_number": bibliography_start_page_number,
        "bibliography_segments": bibliography_segments,
        "crossref_available": bool(inputs["crossref_context"].get("crossref_available")),
        "article_doi": inputs["crossref_context"].get("article_doi"),
        "crossref_article_metadata": inputs["crossref_context"].get(
            "crossref_article_metadata"
        ),
        "crossref_reference_candidates": inputs["crossref_context"].get(
            "crossref_reference_candidates"
        )
        or [],
        "crossref_reference_count": int(
            inputs["crossref_context"].get("crossref_reference_count") or 0
        ),
        "coverage_audit": coverage_audit,
        "document_profile": document_profile,
        "routing_debug": routing_debug,
        "stream_debug": stream_payload["stream_debug"],
        "bibliography_zone_debug": bibliography_zone_debug,
        "global_alerts": global_alerts,
        "debug_payload": debug_payload,
    }


__all__ = ["REFERENCE_PIPELINE_VERSION", "build_references_data_payload"]

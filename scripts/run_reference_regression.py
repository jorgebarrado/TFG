#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
DATASET_DIR = ROOT / "tfg_project/citations/static/citations/PDFs-Reales"
DEFAULT_OUTPUT_ROOT = ROOT / "tmp/reference_regression"
DATASET_TYPE_VALUES = ("exploratory",)
DATASET_SOURCE_LABEL = "directory_scan"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tfg_project.settings")
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / ".cache" / "transformers"))

import django  # noqa: E402

django.setup()

from citations.services.citation_extractor import process_manuscript  # noqa: E402
from citations.services.engines import ALLOWED_ENGINES  # noqa: E402
from citations.services.papermage_extractor import extract_pdf_data  # noqa: E402
from citations.services.reader_data import (  # noqa: E402
    build_snippets_from_results,
    extract_pdf_references,
)
from citations.services.references_data import build_references_data  # noqa: E402

try:
    from citations.services.references_data import (  # noqa: E402
        finalize_reference_detection_debug_payload,
    )
except Exception:  # pragma: no cover - compat defensiva entre ramas
    finalize_reference_detection_debug_payload = None


SUPPORTED_RUNNER_ENGINES = tuple(sorted(set(ALLOWED_ENGINES) | {"auto"}))
TAIL_NOISE_MARKERS = (
    "cite this article",
    "how to cite",
    "copyright",
    "received:",
    "accepted:",
    "published online",
    "correspondence:",
    "license",
    "funding:",
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _round_pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def _round_ratio(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(float(part) / float(total), 3)


def _safe_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_non_empty_text(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _contains_tail_noise(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in TAIL_NOISE_MARKERS)


def _derive_paper_id(pdf_name: str) -> str:
    stem = Path(str(pdf_name or "")).stem.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", stem)
    normalized = normalized.strip("_")
    return normalized or "paper"


def _coerce_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _discover_dataset_entries(dataset_dir: Path) -> List[Dict[str, Any]]:
    pdf_paths = sorted(dataset_dir.glob("*.pdf"), key=lambda path: path.name.lower())
    if not pdf_paths:
        raise SystemExit(f"No se encontraron PDFs en {dataset_dir}")

    seen_ids: Counter[str] = Counter()
    entries: List[Dict[str, Any]] = []
    for pdf_path in pdf_paths:
        base_id = _derive_paper_id(pdf_path.name)
        seen_ids[base_id] += 1
        paper_id = (
            base_id if seen_ids[base_id] == 1 else f"{base_id}_{seen_ids[base_id]}"
        )
        entries.append(
            {
                "id": paper_id,
                "dataset_type": "exploratory",
                "pdf": pdf_path.name,
                "expected_max_reference_index": None,
                "notes": "",
                "autodiscovered": True,
            }
        )
    return entries


def _filter_dataset(
    dataset: Sequence[Dict[str, Any]],
    *,
    paper_ids: Sequence[str],
    dataset_type: str,
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    selected = list(dataset)
    if dataset_type != "all":
        selected = [
            entry
            for entry in selected
            if str(entry.get("dataset_type") or "").strip().lower() == dataset_type
        ]
    if paper_ids:
        selected_ids = {paper_id.strip() for paper_id in paper_ids if paper_id.strip()}
        selected = [
            entry
            for entry in selected
            if str(entry.get("id") or "").strip() in selected_ids
        ]
    if limit is not None and limit >= 0:
        selected = selected[:limit]
    return selected


def _resolve_pdf_path(entry: Dict[str, Any]) -> Path:
    pdf_name = str(entry.get("pdf") or "").strip()
    pdf_path = DATASET_DIR / pdf_name
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"No se encontro el PDF '{pdf_name}' en {DATASET_DIR}"
        )
    return pdf_path


def _resolve_reference_context(
    references: Sequence[Dict[str, Any]],
    ref_stats: Dict[str, Any],
) -> Dict[str, Any]:
    citation_style = (
        str(
            ref_stats.get("citation_style")
            or (
                "numeric" if ref_stats.get("references_numbered") else "non_numeric"
            )
        )
        .strip()
        .lower()
    )
    try:
        max_reference_index = int(
            ref_stats.get("max_reference_index")
            or ref_stats.get("references_total")
            or len(references)
            or 0
        )
    except (TypeError, ValueError):
        max_reference_index = int(
            ref_stats.get("references_total") or len(references) or 0
        )
    total_references_for_validation = (
        max_reference_index if citation_style == "numeric" else len(references)
    )
    return {
        "citation_style": citation_style,
        "max_reference_index": max_reference_index,
        "total_references_for_validation": total_references_for_validation,
    }


def _extract_reader_layers(
    *,
    pdf_path: Path,
    engine_requested: str,
    engine_effective: Optional[str],
) -> Dict[str, Any]:
    try:
        reader_data = extract_pdf_data(str(pdf_path))
    except Exception as exc:
        if engine_requested == "papermage" or engine_effective == "papermage":
            raise RuntimeError(
                f"No se pudieron preparar las capas del reader con PaperMage: {exc}"
            ) from exc
        reader_data = {"pages": [], "layers": {}}
    return (
        reader_data
        if isinstance(reader_data, dict)
        else {"pages": [], "layers": {}}
    )


def _finalize_debug_payload(
    debug_payload: Any,
    *,
    references: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(debug_payload, dict):
        return None
    if callable(finalize_reference_detection_debug_payload):
        try:
            finalized = finalize_reference_detection_debug_payload(
                debug_payload,
                references=references,
            )
        except Exception:
            return debug_payload
        return finalized if isinstance(finalized, dict) else None
    return debug_payload


def _run_single_extraction(
    *,
    pdf_path: Path,
    paper_entry: Dict[str, Any],
    engine: str,
) -> Dict[str, Any]:
    article_doi = str(paper_entry.get("article_doi") or "").strip()
    started_at = time.perf_counter()

    base_references, base_stats = extract_pdf_references(str(pdf_path))
    reference_context = _resolve_reference_context(base_references, base_stats)

    manuscript_data = process_manuscript(
        str(pdf_path),
        engine=engine,
        debug=True,
        references=base_references,
        citation_style=reference_context["citation_style"],
        total_references=reference_context["total_references_for_validation"],
    )
    if not manuscript_data.get("ok"):
        raise RuntimeError(
            "process_manuscript fallo con engine='{engine}': {error}".format(
                engine=engine,
                error=str(manuscript_data.get("error") or "sin detalle"),
            )
        )

    snippets = build_snippets_from_results(manuscript_data.get("results"))
    reader_data = _extract_reader_layers(
        pdf_path=pdf_path,
        engine_requested=engine,
        engine_effective=str(manuscript_data.get("engine_used") or "").strip() or None,
    )
    pages = reader_data.get("pages", []) if isinstance(reader_data, dict) else []
    layers = reader_data.get("layers", {}) if isinstance(reader_data, dict) else {}

    references_data = build_references_data(
        references=base_references,
        snippets=snippets,
        layers=layers,
        references_numbered=bool(base_stats.get("references_numbered")),
        article_doi=article_doi,
        source_filename=pdf_path.name,
        engine_used=str(manuscript_data.get("engine_used") or ""),
        debug_reference_detection=True,
    )
    debug_payload = _finalize_debug_payload(
        references_data.pop("debug_payload", None),
        references=references_data.get("references") or [],
    )

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    layer_item_counts = {
        key: len(value)
        for key, value in (layers.items() if isinstance(layers, dict) else [])
        if isinstance(value, list)
    }
    extraction_payload = {
        "paper_id": str(paper_entry.get("id") or ""),
        "dataset_type": str(paper_entry.get("dataset_type") or ""),
        "pdf_file": pdf_path.name,
        "pdf_path": str(pdf_path),
        "dataset_entry": dict(paper_entry),
        "engine_requested": engine,
        "engine_effective": str(manuscript_data.get("engine_used") or "") or None,
        "time_ms": elapsed_ms,
        "base_reference_stats": base_stats,
        "base_reference_count": len(base_references),
        "citation_context": reference_context,
        "process_manuscript": {
            "summary": manuscript_data.get("summary") or {},
            "citation_style": manuscript_data.get("citation_style"),
            "total_references": manuscript_data.get("total_references"),
            "max_reference_index": manuscript_data.get("max_reference_index"),
            "results_total": len(manuscript_data.get("results") or []),
            "trace": manuscript_data.get("trace") or {},
        },
        "reader_data_summary": {
            "pages_total": len(pages) if isinstance(pages, list) else 0,
            "layer_keys": sorted(layer_item_counts.keys()),
            "layer_item_counts": layer_item_counts,
        },
        "snippets_total": len(snippets),
        "final_extraction": references_data,
    }
    return {
        "extraction": extraction_payload,
        "debug": debug_payload,
    }


def _reference_token_payload(reference: Dict[str, Any]) -> Dict[str, Any]:
    payload = reference.get("token_reconstruction")
    return payload if isinstance(payload, dict) else {}


def _reference_final_decision(reference: Dict[str, Any]) -> Dict[str, Any]:
    final_decision = reference.get("final_decision")
    if isinstance(final_decision, dict):
        return final_decision
    scores = reference.get("scores")
    return scores if isinstance(scores, dict) else {}


def _reference_has_crossref_match(reference: Dict[str, Any]) -> bool:
    match_payload = reference.get("crossref_match")
    if isinstance(match_payload, dict):
        if match_payload.get("match"):
            return True
        if _safe_float(match_payload.get("score")) >= 0.75:
            return True
    return (
        _safe_float(_reference_final_decision(reference).get("crossref_match_score"))
        >= 0.75
    )


def _reference_has_cleanup(reference: Dict[str, Any]) -> bool:
    if bool(_reference_final_decision(reference).get("cleanup_applied")):
        return True
    token_payload = _reference_token_payload(reference)
    if int(token_payload.get("accepted_local_edit_count") or 0) > 0:
        return True
    if token_payload.get("cleanups_applied") or token_payload.get("fine_cleanup_edits"):
        return True
    return False


def _reference_tail_trimmed(reference: Dict[str, Any]) -> bool:
    anomalies = reference.get("anomalies")
    if not isinstance(anomalies, dict):
        return False
    return bool(anomalies.get("tail_trim_applied")) or int(
        anomalies.get("tail_trim_removed_rows_count") or 0
    ) > 0


def _reference_has_tail_noise(reference: Dict[str, Any]) -> bool:
    anomalies = reference.get("anomalies")
    anomalies = anomalies if isinstance(anomalies, dict) else {}
    text = _first_non_empty_text(
        [
            reference.get("text"),
            _reference_token_payload(reference).get("final_text"),
            anomalies.get("tail_trim_removed_text"),
        ]
    )
    return bool(
        _contains_tail_noise(text)
        or _contains_tail_noise(str(anomalies.get("tail_trim_removed_text") or ""))
        or anomalies.get("tail_trim_reason")
        in {
            "tail_row_horizontal_reset",
            "tail_row_horizontal_reset_after_terminal_reference_line",
        }
    )


def _reference_has_page_location(reference: Dict[str, Any]) -> bool:
    return _safe_int(reference.get("page_index")) is not None or _safe_int(
        reference.get("page")
    ) is not None


def _current_git_revision() -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None
    value = str(completed.stdout or "").strip()
    return value or None


def _derive_expected_reference_total(
    *,
    paper_entry: Dict[str, Any],
    extraction_payload: Dict[str, Any],
    coverage_audit: Dict[str, Any],
    default_total: int,
) -> int:
    expected_indices = _coerce_list(coverage_audit.get("expected_indices"))
    if expected_indices:
        return len(expected_indices)

    candidate_ids = _coerce_list(coverage_audit.get("candidate_indices_or_ids"))
    if candidate_ids:
        return len(candidate_ids)

    expected_max = _safe_int(paper_entry.get("expected_max_reference_index"))
    if expected_max is not None and expected_max > 0:
        return expected_max

    citation_context = _coerce_dict(extraction_payload.get("citation_context"))
    citation_total = _safe_int(citation_context.get("total_references_for_validation"))
    if citation_total is not None and citation_total > 0:
        return citation_total

    base_stats = _coerce_dict(extraction_payload.get("base_reference_stats"))
    base_max = _safe_int(base_stats.get("max_reference_index"))
    if base_max is not None and base_max > 0:
        return base_max

    base_total = _safe_int(base_stats.get("references_total"))
    if base_total is not None and base_total > 0:
        return base_total

    payload_total = _safe_int(extraction_payload.get("base_reference_count"))
    if payload_total is not None and payload_total > 0:
        return payload_total

    return max(default_total, 0)


def _calculate_metrics(
    *,
    paper_entry: Dict[str, Any],
    extraction_payload: Dict[str, Any],
    debug_payload: Optional[Dict[str, Any]],
    dataset_root: Path,
    dataset_source: str,
    run_id: str,
    run_timestamp: str,
    git_revision: Optional[str],
) -> Dict[str, Any]:
    references_data = _coerce_dict(extraction_payload.get("final_extraction"))
    references = [
        item
        for item in _coerce_list(references_data.get("references"))
        if isinstance(item, dict)
    ]
    coverage_audit = _coerce_dict(references_data.get("coverage_audit"))
    total = len(references)
    successful_references = [
        item for item in references if str(item.get("status") or "") != "failed"
    ]
    failed_references = [
        item for item in references if str(item.get("status") or "") == "failed"
    ]
    debug_payload = debug_payload if isinstance(debug_payload, dict) else None
    debug_metadata = _coerce_dict((debug_payload or {}).get("metadata"))
    debug_document_profile = _coerce_dict((debug_payload or {}).get("document_profile"))
    document_mode = str(
        references_data.get("document_mode")
        or debug_document_profile.get("document_mode")
        or debug_metadata.get("document_mode")
        or ""
    ).strip() or None

    detected_anchor_indices = _coerce_list(
        coverage_audit.get("detected_anchor_indices")
    )
    candidate_ids = _coerce_list(coverage_audit.get("candidate_indices_or_ids"))
    serialized_indices = _coerce_list(coverage_audit.get("serialized_indices"))
    serialized_candidate_ids = _coerce_list(
        coverage_audit.get("serialized_candidate_ids")
    )
    failed_indices = _coerce_list(coverage_audit.get("failed_indices"))
    failed_candidate_ids = _coerce_list(coverage_audit.get("failed_candidate_ids"))
    missing_indices = _coerce_list(coverage_audit.get("missing_indices"))

    serialized_useful_total = (
        len(serialized_indices)
        if serialized_indices
        else (
            len(serialized_candidate_ids)
            if serialized_candidate_ids
            else len(successful_references)
        )
    )
    failed_total = (
        len(failed_indices)
        if failed_indices
        else (len(failed_candidate_ids) if failed_candidate_ids else len(failed_references))
    )
    expected_total = _derive_expected_reference_total(
        paper_entry=paper_entry,
        extraction_payload=extraction_payload,
        coverage_audit=coverage_audit,
        default_total=total,
    )
    anchors_or_candidates_detected = (
        len(detected_anchor_indices)
        if detected_anchor_indices
        else (len(candidate_ids) if candidate_ids else expected_total)
    )
    missing_total = (
        len(missing_indices)
        if missing_indices
        else max(expected_total - serialized_useful_total - failed_total, 0)
    )
    coverage_ratio = _safe_float(coverage_audit.get("coverage_ratio"))
    if not coverage_audit or coverage_audit.get("coverage_ratio") is None:
        coverage_ratio = _round_ratio(serialized_useful_total, expected_total)
    extraction_status = (
        str(coverage_audit.get("extraction_status") or "").strip()
        or (
            "derived_from_serialized_references"
            if expected_total > 0 and not coverage_audit
            else None
        )
    )

    expected_max = _safe_int(paper_entry.get("expected_max_reference_index"))
    max_detected = _safe_int(references_data.get("max_reference_index"))
    if max_detected is None:
        max_detected = _safe_int(
            _coerce_dict(extraction_payload.get("process_manuscript")).get(
                "max_reference_index"
            )
        )
    if max_detected is None:
        max_detected = _safe_int(
            _coerce_dict(extraction_payload.get("citation_context")).get(
                "max_reference_index"
            )
        )
    if max_detected is None:
        max_detected = max(
            (_safe_int(item.get("index")) or 0 for item in references),
            default=0,
        )
    last_index = _safe_int(references[-1].get("index")) if references else None
    difference_vs_expected = (
        (total - expected_max) if expected_max is not None else None
    )

    source_counter = Counter(str(item.get("structure_source") or "") for item in references)
    rows_raw_count = source_counter.get("rows_raw", 0)
    raw_fallback_count = source_counter.get("raw_reference_fallback", 0)
    inside_bibliography_count = sum(
        1
        for item in references
        if bool(_reference_final_decision(item).get("inside_bibliography_zone"))
    )
    local_anchor_count = sum(
        1 for item in references if bool(item.get("local_anchor_detected"))
    )
    page_index_count = sum(1 for item in references if _reference_has_page_location(item))
    doi_count = sum(1 for item in references if str(item.get("doi") or "").strip())
    accepted_count = sum(
        1 for item in references if bool(_reference_final_decision(item).get("accepted"))
    )
    accepted_with_cleanup_count = sum(
        1
        for item in references
        if bool(_reference_final_decision(item).get("accepted"))
        and _reference_has_cleanup(item)
    )
    crossref_match_count = sum(
        1 for item in references if _reference_has_crossref_match(item)
    )
    tail_trimmed_count = sum(1 for item in references if _reference_tail_trimmed(item))
    tail_noise_count = sum(1 for item in references if _reference_has_tail_noise(item))

    debug_zone = _coerce_dict(
        _coerce_dict((debug_payload or {}).get("phases")).get("bibliography_zone")
    )
    reading_blocks = [
        item
        for item in _coerce_list(debug_zone.get("reading_order_blocks"))
        if isinstance(item, dict)
    ]
    appendix_contamination_detected = any(
        bool(block.get("accepted"))
        and bool(block.get("section_transition_detected"))
        and _safe_float(block.get("bibliography_density")) < 0.45
        and _safe_float(block.get("paragraph_bibliography_density")) < 0.45
        for block in reading_blocks
    )

    last_reference = references[-1] if references else {}
    last_reference_tail_noise_detected = _reference_has_tail_noise(last_reference)

    reference_count_mismatch_detected = bool(
        expected_max is not None
        and (
            total != expected_max
            or (max_detected is not None and max_detected != expected_max)
            or (last_index is not None and last_index != expected_max)
        )
    )
    fallback_pct = _round_pct(raw_fallback_count, total)
    fallback_rate_high = fallback_pct > 50.0
    fallback_rate_extreme = fallback_pct >= 85.0

    metrics = {
        "run_id": run_id,
        "timestamp": run_timestamp,
        "git_revision": git_revision,
        "dataset_root": str(dataset_root),
        "dataset_source": dataset_source,
        "dataset_type": str(paper_entry.get("dataset_type") or ""),
        "paper_id": str(paper_entry.get("id") or ""),
        "pdf_file": extraction_payload.get("pdf_file"),
        "pipeline_version": debug_metadata.get("pipeline_version"),
        "document_mode": document_mode,
        "engine_requested": extraction_payload.get("engine_requested"),
        "engine_effective": extraction_payload.get("engine_effective"),
        "references_total": total,
        "references_total_serialized": total,
        "references_total_source": "final_extraction.references",
        "anchors_or_candidates_detected": anchors_or_candidates_detected,
        "references_serialized_success": serialized_useful_total,
        "failed_references": failed_total,
        "missing_references": missing_total,
        "coverage_ratio": coverage_ratio,
        "extraction_status": extraction_status,
        "expected_max_reference_index": expected_max,
        "max_reference_index_detected": max_detected,
        "last_reference_index_detected": last_index,
        "difference_vs_expected": difference_vs_expected,
        "references_numbered": bool(
            _coerce_dict(extraction_payload.get("base_reference_stats")).get(
                "references_numbered"
            )
        ),
        "bibliography_start_page": references_data.get("bibliography_start_page"),
        "pct_structure_source_rows_raw": _round_pct(rows_raw_count, total),
        "pct_structure_source_raw_reference_fallback": fallback_pct,
        "pct_accepted_with_cleanup": _round_pct(accepted_with_cleanup_count, total),
        "pct_references_with_page_index": _round_pct(page_index_count, total),
        "pct_references_with_doi": _round_pct(doi_count, total),
        "pct_references_with_crossref_match": _round_pct(crossref_match_count, total),
        "pct_references_inside_bibliography_zone": _round_pct(
            inside_bibliography_count,
            total,
        ),
        "pct_references_local_anchor_detected": _round_pct(local_anchor_count, total),
        "pct_references_tail_trimmed": _round_pct(tail_trimmed_count, total),
        "pct_references_with_tail_noise": _round_pct(tail_noise_count, total),
        "pct_accepted": _round_pct(accepted_count, total),
        "fallback_metric_source": "final_serialized_references.structure_source",
        "fallback_reference_count": raw_fallback_count,
        "fallback_rate_high": fallback_rate_high,
        "fallback_rate_extreme": fallback_rate_extreme,
        "last_reference_tail_noise_detected": last_reference_tail_noise_detected,
        "appendix_contamination_detected": appendix_contamination_detected,
        "reference_count_mismatch_detected": reference_count_mismatch_detected,
        "notes": str(paper_entry.get("notes") or ""),
        "pct_structured_rows_raw": _round_pct(rows_raw_count, total),
        "pct_raw_reference_fallback": fallback_pct,
        "pct_inside_bibliography_zone_true": _round_pct(
            inside_bibliography_count,
            total,
        ),
        "pct_local_anchor_detected_true": _round_pct(local_anchor_count, total),
    }
    metrics.update(_determine_status(metrics))
    return metrics


def _determine_status(metrics: Dict[str, Any]) -> Dict[str, Any]:
    total = int(metrics.get("references_total_serialized") or 0)
    fallback_pct = _safe_float(metrics.get("pct_structure_source_raw_reference_fallback"))
    inside_pct = _safe_float(metrics.get("pct_references_inside_bibliography_zone"))
    page_pct = _safe_float(metrics.get("pct_references_with_page_index"))
    accepted_pct = _safe_float(metrics.get("pct_accepted"))
    tail_pct = _safe_float(metrics.get("pct_references_with_tail_noise"))
    local_anchor_pct = _safe_float(metrics.get("pct_references_local_anchor_detected"))

    fail_reasons: List[str] = []
    warn_reasons: List[str] = []

    if total <= 0:
        fail_reasons.append("no_references_serialized")
    if not str(metrics.get("engine_effective") or "").strip():
        fail_reasons.append("engine_not_effective")
    if bool(metrics.get("appendix_contamination_detected")) and (
        inside_pct < 55.0 or tail_pct > 10.0
    ):
        fail_reasons.append("appendix_contamination")
    if tail_pct > 25.0:
        fail_reasons.append("tail_noise_high")
    if bool(metrics.get("fallback_rate_extreme")) and inside_pct < 30.0:
        fail_reasons.append("fallback_extreme_with_low_bibliography_alignment")
    if total >= 5 and page_pct < 20.0:
        fail_reasons.append("page_index_missing_extreme")

    if not fail_reasons:
        if bool(metrics.get("reference_count_mismatch_detected")):
            warn_reasons.append("reference_count_mismatch_detected")
        if bool(metrics.get("appendix_contamination_detected")):
            warn_reasons.append("appendix_contamination_detected")
        if bool(metrics.get("fallback_rate_high")):
            warn_reasons.append("fallback_rate_high")
        if inside_pct < 70.0 and total > 0:
            warn_reasons.append("inside_bibliography_zone_low")
        if total >= 5 and page_pct < 70.0:
            warn_reasons.append("page_index_coverage_low")
        if accepted_pct < 70.0 and total > 0:
            warn_reasons.append("accepted_rate_low")
        if tail_pct > 0.0 or bool(metrics.get("last_reference_tail_noise_detected")):
            warn_reasons.append("tail_noise_detected")
        if bool(metrics.get("references_numbered")) and local_anchor_pct < 70.0:
            warn_reasons.append("local_anchor_rate_low")

    if fail_reasons:
        status = "FAIL"
        status_reasons = fail_reasons
    elif warn_reasons:
        status = "WARN"
        status_reasons = warn_reasons
    else:
        status = "OK"
        status_reasons = []
    return {
        "status": status,
        "status_reasons": status_reasons,
    }


def _aggregate_metrics(paper_summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total_papers = len(paper_summaries)
    status_counter = Counter(
        str((item.get("metrics") or {}).get("status") or "FAIL")
        for item in paper_summaries
    )

    def _avg(metric_name: str) -> float:
        values = [
            _safe_float((item.get("metrics") or {}).get(metric_name))
            for item in paper_summaries
        ]
        if not values:
            return 0.0
        return round(sum(values) / float(len(values)), 2)

    return {
        "total_papers": total_papers,
        "total_ok": status_counter.get("OK", 0),
        "total_warn": status_counter.get("WARN", 0),
        "total_fail": status_counter.get("FAIL", 0),
        "avg_pct_structure_source_rows_raw": _avg("pct_structure_source_rows_raw"),
        "avg_pct_structure_source_raw_reference_fallback": _avg(
            "pct_structure_source_raw_reference_fallback"
        ),
        "avg_pct_references_inside_bibliography_zone": _avg(
            "pct_references_inside_bibliography_zone"
        ),
        "avg_pct_references_with_doi": _avg("pct_references_with_doi"),
        "avg_pct_accepted": _avg("pct_accepted"),
    }


def _build_summary_table_lines(paper_summaries: Sequence[Dict[str, Any]]) -> List[str]:
    lines = [
        "| paper | mode | detected | ok | failed | missing | coverage | extraction | engine | status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in paper_summaries:
        metrics = item.get("metrics") or {}
        lines.append(
            "| {paper} | {mode} | {detected} | {ok} | {failed} | {missing} | {coverage:.3f} | {extraction} | {engine} | {status} |".format(
                paper=metrics.get("paper_id") or "-",
                mode=metrics.get("document_mode") or "-",
                detected=metrics.get("anchors_or_candidates_detected") or 0,
                ok=metrics.get("references_serialized_success") or 0,
                failed=metrics.get("failed_references") or 0,
                missing=metrics.get("missing_references") or 0,
                coverage=_safe_float(metrics.get("coverage_ratio")),
                extraction=metrics.get("extraction_status") or "-",
                engine=(
                    "{requested}->{effective}".format(
                        requested=metrics.get("engine_requested") or "-",
                        effective=metrics.get("engine_effective") or "-",
                    )
                ),
                status=metrics.get("status") or "FAIL",
            )
        )
    return lines


def _build_summary_markdown(
    *,
    run_summary: Dict[str, Any],
    grouped_summaries: Dict[str, List[Dict[str, Any]]],
) -> str:
    aggregate = run_summary.get("aggregate_metrics") or {}
    lines = [
        "# Reference Regression Summary",
        "",
        f"- Run ID: `{run_summary.get('run_id')}`",
        f"- Timestamp: `{run_summary.get('timestamp')}`",
        f"- Dataset source: `{run_summary.get('dataset_source')}`",
        f"- Dataset root: `{run_summary.get('dataset_root')}`",
        f"- Dataset filter: `{run_summary.get('dataset_type_filter')}`",
        f"- PDFs discovered/selected: `{run_summary.get('discovered_pdfs_total', 0)}` / `{run_summary.get('selected_pdfs_total', 0)}`",
        f"- Engine requested: `{run_summary.get('engine_requested')}`",
        f"- Git revision: `{run_summary.get('git_revision') or '-'}`",
        f"- Total papers: `{aggregate.get('total_papers', 0)}`",
        f"- OK/WARN/FAIL: `{aggregate.get('total_ok', 0)}` / `{aggregate.get('total_warn', 0)}` / `{aggregate.get('total_fail', 0)}`",
        "",
    ]

    group_aggregate = run_summary.get("aggregate_by_dataset_type") or {}
    for dataset_type in DATASET_TYPE_VALUES:
        group_metrics = group_aggregate.get(dataset_type) or {}
        lines.extend(
            [
                f"- {dataset_type.title()}: `{group_metrics.get('total_papers', 0)}` papers | OK/WARN/FAIL `{group_metrics.get('total_ok', 0)}` / `{group_metrics.get('total_warn', 0)}` / `{group_metrics.get('total_fail', 0)}`",
            ]
        )

    for dataset_type in DATASET_TYPE_VALUES:
        paper_summaries = grouped_summaries.get(dataset_type) or []
        if not paper_summaries:
            continue
        lines.extend(
            [
                "",
                f"## {dataset_type.title()}",
                "",
            ]
        )
        lines.extend(_build_summary_table_lines(paper_summaries))
    return "\n".join(lines) + "\n"


def _build_error_metrics(
    *,
    paper_entry: Dict[str, Any],
    pdf_path: Path,
    engine: str,
    dataset_root: Path,
    dataset_source: str,
    run_id: str,
    run_timestamp: str,
    git_revision: Optional[str],
    error_message: str,
) -> Dict[str, Any]:
    metrics = {
        "run_id": run_id,
        "timestamp": run_timestamp,
        "git_revision": git_revision,
        "dataset_root": str(dataset_root),
        "dataset_source": dataset_source,
        "dataset_type": str(paper_entry.get("dataset_type") or ""),
        "paper_id": str(paper_entry.get("id") or ""),
        "pdf_file": pdf_path.name,
        "pipeline_version": None,
        "engine_requested": engine,
        "engine_effective": None,
        "references_total": 0,
        "references_total_serialized": 0,
        "references_total_source": "final_extraction.references",
        "anchors_or_candidates_detected": 0,
        "references_serialized_success": 0,
        "failed_references": 0,
        "missing_references": 0,
        "coverage_ratio": 0.0,
        "extraction_status": None,
        "expected_max_reference_index": _safe_int(
            paper_entry.get("expected_max_reference_index")
        ),
        "max_reference_index_detected": 0,
        "last_reference_index_detected": 0,
        "difference_vs_expected": None,
        "references_numbered": False,
        "bibliography_start_page": None,
        "pct_structure_source_rows_raw": 0.0,
        "pct_structure_source_raw_reference_fallback": 0.0,
        "pct_accepted_with_cleanup": 0.0,
        "pct_references_with_page_index": 0.0,
        "pct_references_with_doi": 0.0,
        "pct_references_with_crossref_match": 0.0,
        "pct_references_inside_bibliography_zone": 0.0,
        "pct_references_local_anchor_detected": 0.0,
        "pct_references_tail_trimmed": 0.0,
        "pct_references_with_tail_noise": 0.0,
        "pct_accepted": 0.0,
        "fallback_metric_source": "final_serialized_references.structure_source",
        "fallback_reference_count": 0,
        "fallback_rate_high": False,
        "fallback_rate_extreme": False,
        "last_reference_tail_noise_detected": False,
        "appendix_contamination_detected": False,
        "reference_count_mismatch_detected": False,
        "notes": str(paper_entry.get("notes") or ""),
        "pct_structured_rows_raw": 0.0,
        "pct_raw_reference_fallback": 0.0,
        "pct_inside_bibliography_zone_true": 0.0,
        "pct_local_anchor_detected_true": 0.0,
        "status": "FAIL",
        "status_reasons": ["runner_exception"],
        "error": error_message,
    }
    return metrics


def _run_regression(
    *,
    selected_paper_ids: Sequence[str],
    dataset_type: str,
    limit: Optional[int],
    output_dir: Path,
    engine: str,
) -> Dict[str, Any]:
    dataset = _discover_dataset_entries(DATASET_DIR)
    selected_entries = _filter_dataset(
        dataset,
        paper_ids=selected_paper_ids,
        dataset_type=dataset_type,
        limit=limit,
    )
    if not selected_entries:
        raise SystemExit("No hay papers seleccionados para ejecutar.")

    per_paper_root = output_dir / "per_paper"
    per_paper_root.mkdir(parents=True, exist_ok=True)

    run_id = output_dir.name
    run_timestamp = datetime.now(timezone.utc).isoformat()
    git_revision = _current_git_revision()

    paper_summaries: List[Dict[str, Any]] = []
    grouped_summaries: Dict[str, List[Dict[str, Any]]] = {
        dataset_key: [] for dataset_key in DATASET_TYPE_VALUES
    }
    for entry in selected_entries:
        paper_id = str(entry.get("id") or "").strip()
        entry_dataset_type = str(entry.get("dataset_type") or "exploratory")
        pdf_path = _resolve_pdf_path(entry)
        paper_dir = per_paper_root / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)

        try:
            run_output = _run_single_extraction(
                pdf_path=pdf_path,
                paper_entry=entry,
                engine=engine,
            )
            metrics = _calculate_metrics(
                paper_entry=entry,
                extraction_payload=run_output["extraction"],
                debug_payload=run_output["debug"],
                dataset_root=DATASET_DIR,
                dataset_source=DATASET_SOURCE_LABEL,
                run_id=run_id,
                run_timestamp=run_timestamp,
                git_revision=git_revision,
            )
            _write_json(paper_dir / "extraction.json", run_output["extraction"])
            _write_json(
                paper_dir / "reference_debug.json",
                run_output["debug"] or {"error": "debug_payload_missing"},
            )
            _write_json(paper_dir / "metrics.json", metrics)
            paper_summary = {
                "paper_id": paper_id,
                "dataset_type": entry_dataset_type,
                "pdf_file": pdf_path.name,
                "status": metrics.get("status"),
                "metrics": metrics,
                "artifacts": {
                    "extraction": str(
                        (paper_dir / "extraction.json").relative_to(output_dir)
                    ),
                    "reference_debug": str(
                        (paper_dir / "reference_debug.json").relative_to(output_dir)
                    ),
                    "metrics": str((paper_dir / "metrics.json").relative_to(output_dir)),
                },
            }
        except Exception as exc:  # pragma: no cover - el runner debe sobrevivir paper a paper
            metrics = _build_error_metrics(
                paper_entry=entry,
                pdf_path=pdf_path,
                engine=engine,
                dataset_root=DATASET_DIR,
                dataset_source=DATASET_SOURCE_LABEL,
                run_id=run_id,
                run_timestamp=run_timestamp,
                git_revision=git_revision,
                error_message=str(exc),
            )
            _write_json(paper_dir / "metrics.json", metrics)
            _write_json(
                paper_dir / "extraction.json",
                {
                    "paper_id": paper_id,
                    "dataset_type": entry_dataset_type,
                    "pdf_file": pdf_path.name,
                    "engine_requested": engine,
                    "error": str(exc),
                },
            )
            _write_json(
                paper_dir / "reference_debug.json",
                {
                    "paper_id": paper_id,
                    "dataset_type": entry_dataset_type,
                    "error": str(exc),
                },
            )
            paper_summary = {
                "paper_id": paper_id,
                "dataset_type": entry_dataset_type,
                "pdf_file": pdf_path.name,
                "status": "FAIL",
                "metrics": metrics,
                "artifacts": {
                    "extraction": str(
                        (paper_dir / "extraction.json").relative_to(output_dir)
                    ),
                    "reference_debug": str(
                        (paper_dir / "reference_debug.json").relative_to(output_dir)
                    ),
                    "metrics": str((paper_dir / "metrics.json").relative_to(output_dir)),
                },
            }

        paper_summaries.append(paper_summary)
        grouped_summaries.setdefault(entry_dataset_type, []).append(paper_summary)
        print(
            "[{status}] {paper_id} ({dataset_type}): mode={mode} detected={detected} ok={ok} failed={failed} missing={missing} coverage={coverage:.3f} extraction={extraction} engine={requested}->{effective}".format(
                status=paper_summary.get("status"),
                paper_id=paper_id,
                dataset_type=entry_dataset_type,
                mode=(paper_summary.get("metrics") or {}).get("document_mode") or "-",
                detected=(paper_summary.get("metrics") or {}).get(
                    "anchors_or_candidates_detected"
                )
                or 0,
                ok=(paper_summary.get("metrics") or {}).get(
                    "references_serialized_success"
                )
                or 0,
                failed=(paper_summary.get("metrics") or {}).get("failed_references")
                or 0,
                missing=(paper_summary.get("metrics") or {}).get("missing_references")
                or 0,
                coverage=_safe_float(
                    (paper_summary.get("metrics") or {}).get("coverage_ratio")
                ),
                extraction=(paper_summary.get("metrics") or {}).get("extraction_status")
                or "-",
                requested=(paper_summary.get("metrics") or {}).get("engine_requested")
                or "-",
                effective=(paper_summary.get("metrics") or {}).get("engine_effective")
                or "-",
            )
        )

    aggregate = _aggregate_metrics(paper_summaries)
    aggregate_by_dataset_type = {
        dataset_key: _aggregate_metrics(grouped_summaries.get(dataset_key) or [])
        for dataset_key in DATASET_TYPE_VALUES
    }
    run_summary = {
        "run_id": run_id,
        "timestamp": run_timestamp,
        "dataset_source": DATASET_SOURCE_LABEL,
        "dataset_root": str(DATASET_DIR),
        "dataset_type_filter": dataset_type,
        "selected_paper_ids": list(selected_paper_ids),
        "limit": limit,
        "engine_requested": engine,
        "git_revision": git_revision,
        "discovered_pdfs_total": len(dataset),
        "selected_pdfs_total": len(selected_entries),
        "total_papers": aggregate["total_papers"],
        "total_ok": aggregate["total_ok"],
        "total_warn": aggregate["total_warn"],
        "total_fail": aggregate["total_fail"],
        "aggregate_metrics": aggregate,
        "aggregate_by_dataset_type": aggregate_by_dataset_type,
        "papers": paper_summaries,
    }
    _write_json(output_dir / "summary.json", run_summary)
    _write_text(
        output_dir / "summary.md",
        _build_summary_markdown(
            run_summary=run_summary,
            grouped_summaries=grouped_summaries,
        ),
    )
    return run_summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runner de regresion para el extractor de referencias."
    )
    parser.add_argument(
        "--dataset-type",
        default="all",
        choices=["all", *DATASET_TYPE_VALUES],
        help="Filtra el subconjunto autodetectado; sin manifest, todos son exploratory.",
    )
    parser.add_argument(
        "--paper-id",
        action="append",
        default=[],
        help="Ejecuta solo uno o varios paper_id autodetectados desde el nombre del PDF.",
    )
    parser.add_argument(
        "--engine",
        default="papermage",
        choices=SUPPORTED_RUNNER_ENGINES,
        help="Motor de extraccion real para process_manuscript.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita el numero de papers procesados tras aplicar filtros.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directorio final de salida. Por defecto usa tmp/reference_regression/<run_id>/.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = (
        args.output_dir if args.output_dir is not None else DEFAULT_OUTPUT_ROOT / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = _run_regression(
        selected_paper_ids=args.paper_id,
        dataset_type=args.dataset_type,
        limit=args.limit,
        output_dir=output_dir,
        engine=args.engine,
    )
    print()
    print(f"Summary JSON: {output_dir / 'summary.json'}")
    print(f"Summary MD:   {output_dir / 'summary.md'}")
    print(
        "Totales -> OK: {ok}, WARN: {warn}, FAIL: {fail}".format(
            ok=summary.get("total_ok", 0),
            warn=summary.get("total_warn", 0),
            fail=summary.get("total_fail", 0),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

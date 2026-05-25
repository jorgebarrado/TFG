from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from citations.services.reader_data import extract_pdf_references

from .normalization import clean_text

PDF_FIXTURE_DIR = Path("tfg_project/citations/static/citations/PDFs-Reales")
INPUT_BUCKET_ORDER = [
    "clean_input",
    "numeric_noise",
    "likely_fused_references",
    "small_reference_set",
    "low_alpha_or_short_noise",
    "header_not_found_fallback",
    "mixed_issues",
]


def _safe_ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return value / total


def discover_all_pdf_paths(pdf_dir: Path | None = None) -> List[Path]:
    base_dir = (pdf_dir or PDF_FIXTURE_DIR).resolve()
    if not base_dir.exists():
        raise FileNotFoundError(f"PDF fixture directory not found: {base_dir}")
    paths = sorted(
        (path.resolve() for path in base_dir.rglob("*.pdf") if path.is_file()),
        key=lambda path: str(path.relative_to(base_dir)).lower(),
    )
    if not paths:
        raise FileNotFoundError(f"No PDF files found under: {base_dir}")
    return paths


def slugify_pdf_name(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "paper"


def resolve_pdf_paths(
    pdf_names: Sequence[str], pdf_dir: Path | None = None
) -> List[Path]:
    base_dir = pdf_dir or PDF_FIXTURE_DIR
    paths: List[Path] = []
    for item in pdf_names:
        candidate = Path(item)
        if candidate.is_absolute() and candidate.exists():
            paths.append(candidate)
            continue
        candidate = (base_dir / item).resolve()
        if candidate.exists():
            paths.append(candidate)
            continue
        raise FileNotFoundError(f"PDF not found: {item}")
    return paths


def _reference_quality_warnings(reference: Dict[str, Any]) -> List[str]:
    raw = clean_text(reference.get("raw"))
    warnings: List[str] = []
    if not raw:
        warnings.append("empty_raw_reference")
        return warnings
    if len(raw) < 30:
        warnings.append("very_short_reference")
    if len(raw) > 600:
        warnings.append("very_long_reference")
    if re.match(r"^\d+(?:\s+\d+){3,}", raw):
        warnings.append("starts_with_numeric_noise")
    if raw.count(";") >= 10:
        warnings.append("many_semicolon_segments")
    if sum(ch.isalpha() for ch in raw) < 20:
        warnings.append("low_alpha_content")
    return warnings


def _build_input_quality(
    *,
    normalized_references: Sequence[Dict[str, Any]],
    extractor_stats: Dict[str, Any],
    paper_warnings: Sequence[str],
) -> Dict[str, Any]:
    total_references = len(normalized_references)
    warning_counts: Dict[str, int] = {
        "empty_raw_reference": 0,
        "very_short_reference": 0,
        "very_long_reference": 0,
        "starts_with_numeric_noise": 0,
        "many_semicolon_segments": 0,
        "low_alpha_content": 0,
    }
    for item in normalized_references:
        for warning in item.get("warnings", []):
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

    short_or_low_alpha_count = warning_counts.get(
        "very_short_reference", 0
    ) + warning_counts.get(
        "low_alpha_content",
        0,
    )
    warning_ratios = {
        key: _safe_ratio(value, total_references)
        for key, value in warning_counts.items()
    }
    warning_ratios["short_or_low_alpha_combined"] = _safe_ratio(
        short_or_low_alpha_count, total_references
    )

    issue_flags = {
        "numeric_noise": "raw_references_contain_numeric_noise" in paper_warnings
        or warning_ratios.get("starts_with_numeric_noise", 0.0) >= 0.2,
        "likely_fused_references": warning_counts.get("many_semicolon_segments", 0) >= 2
        or warning_ratios.get("many_semicolon_segments", 0.0) >= 0.08,
        "small_reference_set": "very_small_reference_set" in paper_warnings
        or extractor_stats.get("references_total", 0) <= 5,
        "low_alpha_or_short_noise": "raw_references_contain_many_short_or_low_alpha_entries"
        in paper_warnings
        or warning_ratios.get("short_or_low_alpha_combined", 0.0) >= 0.15,
        "header_not_found_fallback": "reference_header_not_found_fallback_tail_used"
        in paper_warnings,
    }
    active_issue_buckets = [
        bucket
        for bucket in (
            "numeric_noise",
            "likely_fused_references",
            "small_reference_set",
            "low_alpha_or_short_noise",
            "header_not_found_fallback",
        )
        if issue_flags.get(bucket)
    ]
    if not active_issue_buckets:
        primary_bucket = "clean_input"
    elif len(active_issue_buckets) > 1:
        primary_bucket = "mixed_issues"
    else:
        primary_bucket = active_issue_buckets[0]

    quality_notes: List[str] = []
    if primary_bucket == "clean_input":
        quality_notes.append(
            "No strong degradation signals detected in raw reference input."
        )
    if issue_flags.get("numeric_noise"):
        quality_notes.append(
            f"Numeric-leading noise in {warning_counts.get('starts_with_numeric_noise', 0)}/{total_references} references."
        )
    if issue_flags.get("likely_fused_references"):
        quality_notes.append(
            f"Likely fused references in {warning_counts.get('many_semicolon_segments', 0)}/{total_references} entries."
        )
    if issue_flags.get("low_alpha_or_short_noise"):
        quality_notes.append(
            f"Short/low-alpha noisy references in {short_or_low_alpha_count}/{total_references} entries."
        )
    if issue_flags.get("small_reference_set"):
        quality_notes.append(
            f"Very small extracted reference set ({extractor_stats.get('references_total', 0)})."
        )
    if issue_flags.get("header_not_found_fallback"):
        quality_notes.append(
            "References header not found; extractor fallback tail used."
        )
    if primary_bucket == "mixed_issues":
        quality_notes.append(
            f"Mixed degradation signals: {', '.join(active_issue_buckets)}."
        )

    return {
        "primary_bucket": primary_bucket,
        "active_issue_buckets": active_issue_buckets,
        "issue_flags": issue_flags,
        "paper_warning_count": len(paper_warnings),
        "paper_warnings": list(paper_warnings),
        "reference_count": total_references,
        "extractor_references_total": extractor_stats.get("references_total", 0),
        "warning_counts": warning_counts,
        "warning_ratios": warning_ratios,
        "quality_notes": quality_notes,
        "degraded_input": primary_bucket != "clean_input",
    }


def build_common_input(pdf_path: Path) -> Dict[str, Any]:
    references, extractor_stats = extract_pdf_references(str(pdf_path))
    normalized_references: List[Dict[str, Any]] = []
    paper_warnings: List[str] = []

    for fallback_index, reference in enumerate(references, start=1):
        warnings = _reference_quality_warnings(reference)
        normalized_references.append(
            {
                "index": fallback_index - 1,
                "source_index": reference.get("index"),
                "raw_input": clean_text(reference.get("raw")),
                "extractor_doi": reference.get("doi"),
                "extractor_confidence": reference.get("confidence"),
                "numbered": bool(reference.get("numbered")),
                "warnings": warnings,
            }
        )

    if not extractor_stats.get("references_header_found"):
        paper_warnings.append("reference_header_not_found_fallback_tail_used")
    if extractor_stats.get("references_total", 0) <= 5:
        paper_warnings.append("very_small_reference_set")
    noisy_count = sum(
        1
        for item in normalized_references
        if "starts_with_numeric_noise" in item.get("warnings", [])
    )
    short_or_low_alpha_count = sum(
        1
        for item in normalized_references
        if {
            "very_short_reference",
            "low_alpha_content",
        }.intersection(item.get("warnings", []))
    )
    if normalized_references and noisy_count / len(normalized_references) >= 0.2:
        paper_warnings.append("raw_references_contain_numeric_noise")
    if (
        normalized_references
        and short_or_low_alpha_count / len(normalized_references) >= 0.15
    ):
        paper_warnings.append("raw_references_contain_many_short_or_low_alpha_entries")

    input_quality = _build_input_quality(
        normalized_references=normalized_references,
        extractor_stats=extractor_stats,
        paper_warnings=paper_warnings,
    )

    return {
        "paper_slug": slugify_pdf_name(pdf_path.name),
        "pdf_name": pdf_path.name,
        "pdf_path": str(pdf_path.resolve()),
        "extractor": "citations.services.reader_data.extract_pdf_references",
        "extractor_stats": extractor_stats,
        "warnings": paper_warnings,
        "input_quality": input_quality,
        "raw_references": normalized_references,
    }


def write_common_input_artifact(
    common_input: Dict[str, Any], output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(common_input, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

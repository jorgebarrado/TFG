from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from citations.services.reader_data import extract_pdf_references

from .normalization import clean_text


PDF_FIXTURE_DIR = Path("tfg_project/citations/static/citations/PDFs-Reales")


def slugify_pdf_name(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "paper"


def resolve_pdf_paths(pdf_names: Sequence[str], pdf_dir: Path | None = None) -> List[Path]:
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
    if normalized_references and short_or_low_alpha_count / len(normalized_references) >= 0.15:
        paper_warnings.append("raw_references_contain_many_short_or_low_alpha_entries")

    return {
        "paper_slug": slugify_pdf_name(pdf_path.name),
        "pdf_name": pdf_path.name,
        "pdf_path": str(pdf_path.resolve()),
        "extractor": "citations.services.reader_data.extract_pdf_references",
        "extractor_stats": extractor_stats,
        "warnings": paper_warnings,
        "raw_references": normalized_references,
    }


def write_common_input_artifact(common_input: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(common_input, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

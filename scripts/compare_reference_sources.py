#!/usr/bin/env python3
# Compara las referencias extraídas por reader_data (fuente base) y references_data
# (fuente estructurada) sobre PDFs reales y clasifica el resultado por PDF.
# Salida en tmp/reference_source_compare/<run-id>/summary.json y summary.md
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import patch

import django  # noqa: E402
from django.apps import apps  # noqa: E402

from citations.services.papermage_extractor import extract_pdf_data  # noqa: E402
from citations.services.reader_data import extract_pdf_references  # noqa: E402
from citations.services.references_data import build_references_data  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
DEFAULT_PDF_DIR = ROOT / "tfg_project/citations/static/citations/PDFs-Reales"
DEFAULT_OUTPUT_ROOT = ROOT / "tmp/reference_source_compare"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tfg_project.settings")
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / ".cache" / "transformers"))


if not apps.ready:
    django.setup()


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:18|19|20)\d{2}\b")
BRACKETED_ANCHOR_VALUE_RE = re.compile(r"\[\s*(\d{1,4})\s*\]")
LINE_START_ANCHOR_VALUE_RE = re.compile(
    r"(?m)^\s*(?:\[\s*(\d{1,4})\s*\]|\(\s*(\d{1,4})\s*\)|(\d{1,4})[.)])"
)
LEADING_ANCHOR_RE = re.compile(
    r"^\s*(?:\[\s*\d{1,4}\s*\]|\(\s*\d{1,4}\s*\)|\d{1,4}[.)])\s*"
)
NON_BIBLIOGRAPHIC_PHRASES = (
    "view publication stats",
    "downloaded from",
    "all content following",
    "researchgate",
    "copyright",
    "received:",
    "accepted:",
    "published online",
    "correspondence:",
    "funding:",
    "license",
)
RUN_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _round_pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def _normalize_doi(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = DOI_RE.search(raw)
    if match:
        return match.group(0).rstrip(".,;)").lower()
    return ""


def _entry_index(entry: Dict[str, Any]) -> Optional[int]:
    for key in ("index", "ref_index", "number"):
        parsed = _safe_int(entry.get(key))
        if parsed is not None and parsed > 0:
            return parsed
    raw_id = str(entry.get("id") or entry.get("ref_id") or "").strip()
    match = re.search(r"(\d+)$", raw_id)
    if match:
        return _safe_int(match.group(1))
    return None


def _entry_text(entry: Dict[str, Any]) -> str:
    for key in ("raw", "text", "label", "title"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""


def _entry_doi(entry: Dict[str, Any], text: str) -> str:
    explicit = _normalize_doi(entry.get("doi"))
    if explicit:
        return explicit
    return _normalize_doi(text)


def _compact_text(text: str, limit: int = 300) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _text_for_overlap(text: str) -> str:
    normalized = LEADING_ANCHOR_RE.sub("", str(text or "").lower())
    normalized = DOI_RE.sub(" ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _detect_suspicious_text(
    text: str,
    *,
    structure_source: str = "",
) -> List[str]:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    reasons: List[str] = []

    if not normalized:
        return ["empty"]
    if len(normalized) < 25:
        reasons.append("very_short")
    if any(phrase in lowered for phrase in NON_BIBLIOGRAPHIC_PHRASES):
        reasons.append("non_bibliographic_phrase")
    if normalized.count("\n") > 6:
        reasons.append("many_line_breaks")

    anchors = []
    for match in BRACKETED_ANCHOR_VALUE_RE.finditer(normalized):
        anchors.extend(
            int(value) for value in match.groups() if value and int(value) <= 500
        )
    for match in LINE_START_ANCHOR_VALUE_RE.finditer(normalized):
        anchors.extend(
            int(value) for value in match.groups() if value and int(value) <= 500
        )
    if len(set(anchors)) > 1:
        reasons.append("multiple_anchors")

    has_year = bool(YEAR_RE.search(normalized))
    has_doi = bool(DOI_RE.search(normalized))
    has_bibliographic_shape = (
        has_year
        or has_doi
        or " et al" in lowered
        or lowered.count(",") >= 2
        or "." in normalized
        and "," in normalized
    )
    if (
        not has_bibliographic_shape
        and "non_bibliographic_phrase" not in reasons
        and "very_short" not in reasons
    ):
        reasons.append("weak_bibliographic_signal")

    if "fallback" in str(structure_source or "").lower():
        reasons.append("structure_fallback")

    return sorted(set(reasons))


def _summarize_indices(
    entries: Sequence[Dict[str, Any]],
    *,
    expected_max_index: Optional[int] = None,
) -> Dict[str, Any]:
    indices = [
        parsed
        for entry in entries
        if (parsed := _entry_index(entry)) is not None and parsed > 0
    ]
    counter = Counter(indices)
    unique_indices = sorted(counter)
    upper_bound = expected_max_index or (max(unique_indices) if unique_indices else 0)
    missing = [value for value in range(1, upper_bound + 1) if value not in counter]
    return {
        "indexed_count": len(indices),
        "unique_count": len(unique_indices),
        "unlabeled_count": len(entries) - len(indices),
        "min_index": min(unique_indices) if unique_indices else None,
        "max_index": max(unique_indices) if unique_indices else None,
        "duplicate_indices": [
            index for index, count in sorted(counter.items()) if count > 1
        ],
        "missing_indices": missing,
    }


def _summarize_entries(
    references: Sequence[Dict[str, Any]],
    *,
    source_kind: str,
) -> Tuple[List[Dict[str, Any]], int, List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    doi_count = 0
    suspicious: List[Dict[str, Any]] = []

    for position, reference in enumerate(references, start=1):
        if not isinstance(reference, dict):
            continue
        text = _entry_text(reference)
        doi = _entry_doi(reference, text)
        if doi:
            doi_count += 1
        structure_source = str(reference.get("structure_source") or "")
        reasons = _detect_suspicious_text(
            text,
            structure_source=structure_source if source_kind == "structured" else "",
        )
        entry = {
            "position": position,
            "id": reference.get("id") or reference.get("ref_id"),
            "index": _entry_index(reference),
            "doi": doi or None,
            "text": text,
            "text_preview": _compact_text(text),
            "text_length": len(text),
            "suspicious_reasons": reasons,
        }
        if source_kind == "structured":
            validation = reference.get("reference_validation")
            entry["structure_source"] = structure_source or None
            entry["accepted"] = (
                validation.get("accepted") if isinstance(validation, dict) else None
            )
        entries.append(entry)
        if reasons:
            suspicious.append(
                {
                    "position": position,
                    "index": entry["index"],
                    "id": entry["id"],
                    "reasons": reasons,
                    "text_preview": entry["text_preview"],
                }
            )

    return entries, doi_count, suspicious


def summarize_base_source(
    references: Sequence[Dict[str, Any]],
    stats: Dict[str, Any],
) -> Dict[str, Any]:
    entries, doi_count, suspicious = _summarize_entries(
        references,
        source_kind="base",
    )
    max_reference_index = _safe_int(stats.get("max_reference_index"))
    total = len(entries)
    return {
        "source": "reader_data.extract_pdf_references",
        "total": total,
        "citation_style": stats.get("citation_style"),
        "max_reference_index": max_reference_index,
        "bibliography_start_page": stats.get("bibliography_start_page"),
        "references_numbered": bool(stats.get("references_numbered")),
        "doi_count": doi_count,
        "doi_pct": _round_pct(doi_count, total),
        "index_summary": _summarize_indices(
            entries,
            expected_max_index=max_reference_index,
        ),
        "suspicious_count": len(suspicious),
        "suspicious_pct": _round_pct(len(suspicious), total),
        "suspicious_entries": suspicious,
        "entries": entries,
    }


def summarize_structured_source(payload: Dict[str, Any]) -> Dict[str, Any]:
    references = [
        reference
        for reference in payload.get("references") or []
        if isinstance(reference, dict)
    ]
    entries, doi_count, suspicious = _summarize_entries(
        references,
        source_kind="structured",
    )
    source_counts = Counter(
        str(reference.get("structure_source") or "missing") for reference in references
    )
    accepted_count = 0
    rejected_count = 0
    unknown_validation_count = 0
    for reference in references:
        validation = reference.get("reference_validation")
        accepted = validation.get("accepted") if isinstance(validation, dict) else None
        if accepted is True:
            accepted_count += 1
        elif accepted is False:
            rejected_count += 1
        else:
            unknown_validation_count += 1

    fallback_count = sum(
        count for source, count in source_counts.items() if "fallback" in source.lower()
    )
    total = len(entries)
    max_reference_index = _safe_int(payload.get("max_reference_index"))
    return {
        "source": "references_data.build_references_data",
        "total": total,
        "citation_style": payload.get("citation_style"),
        "max_reference_index": max_reference_index,
        "bibliography_start_page": payload.get("bibliography_start_page"),
        "doi_count": doi_count,
        "doi_pct": _round_pct(doi_count, total),
        "source_counts": dict(sorted(source_counts.items())),
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "unknown_validation_count": unknown_validation_count,
        "fallback_count": fallback_count,
        "fallback_pct": _round_pct(fallback_count, total),
        "index_summary": _summarize_indices(
            entries,
            expected_max_index=max_reference_index,
        ),
        "suspicious_count": len(suspicious),
        "suspicious_pct": _round_pct(len(suspicious), total),
        "suspicious_entries": suspicious,
        "entries": entries,
    }


def _indexed_set(summary: Dict[str, Any]) -> set[int]:
    return {
        int(entry["index"])
        for entry in summary.get("entries") or []
        if entry.get("index") is not None
    }


def _compute_overlap(
    base_entries: Sequence[Dict[str, Any]],
    structured_entries: Sequence[Dict[str, Any]],
    *,
    threshold: float = 0.78,
) -> Dict[str, Any]:
    structured_pool = [
        (idx, _text_for_overlap(entry.get("text") or ""))
        for idx, entry in enumerate(structured_entries)
    ]
    used_structured: set[int] = set()
    scores: List[float] = []
    matches: List[Dict[str, Any]] = []

    for base_position, base_entry in enumerate(base_entries, start=1):
        base_text = _text_for_overlap(base_entry.get("text") or "")
        if not base_text:
            scores.append(0.0)
            continue
        best_idx: Optional[int] = None
        best_score = 0.0
        for structured_idx, structured_text in structured_pool:
            if structured_idx in used_structured or not structured_text:
                continue
            score = SequenceMatcher(None, base_text, structured_text).ratio()
            if score > best_score:
                best_score = score
                best_idx = structured_idx
        scores.append(best_score)
        if best_idx is not None and best_score >= threshold:
            used_structured.add(best_idx)
            matches.append(
                {
                    "base_position": base_position,
                    "structured_position": best_idx + 1,
                    "score": round(best_score, 3),
                    "base_index": base_entry.get("index"),
                    "structured_index": structured_entries[best_idx].get("index"),
                }
            )

    matched_count = len(matches)
    average_best_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {
        "threshold": threshold,
        "matched_count": matched_count,
        "base_coverage_pct": _round_pct(matched_count, len(base_entries)),
        "structured_coverage_pct": _round_pct(
            matched_count,
            len(structured_entries),
        ),
        "average_best_score": average_best_score,
        "sample_matches": matches[:10],
    }


def _classify_result(
    base_summary: Dict[str, Any],
    structured_summary: Dict[str, Any],
    direct: Dict[str, Any],
) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    total_delta = abs(int(direct["references_total_delta"]))
    total_limit = max(2, int(max(base_summary["total"], 1) * 0.05))
    if total_delta > total_limit:
        reasons.append("reference_total_diff")
    if not direct["citation_style_match"]:
        reasons.append("citation_style_diff")
    if direct["max_reference_index_delta"] != 0:
        reasons.append("max_reference_index_diff")
    if direct["indices_base_only"] or direct["indices_structured_only"]:
        reasons.append("index_sets_differ")
    if base_summary["index_summary"]["duplicate_indices"]:
        reasons.append("base_duplicate_indices")
    if structured_summary["index_summary"]["duplicate_indices"]:
        reasons.append("structured_duplicate_indices")
    if structured_summary["fallback_pct"] >= 20:
        reasons.append("structured_fallbacks_high")
    if structured_summary["suspicious_pct"] >= 25:
        reasons.append("structured_suspicious_high")
    if direct["overlap"]["base_coverage_pct"] < 75:
        reasons.append("low_text_overlap")

    if (
        "structured_suspicious_high" in reasons
        and structured_summary["suspicious_pct"] > base_summary["suspicious_pct"]
    ):
        return "contaminated_structured_output", reasons
    if "index_sets_differ" in reasons or "max_reference_index_diff" in reasons:
        return "needs_manual_review", reasons
    if (
        structured_summary["suspicious_pct"] > base_summary["suspicious_pct"] + 10
        or structured_summary["fallback_pct"] >= 20
    ):
        return "base_better", reasons
    if (
        base_summary["suspicious_pct"] > structured_summary["suspicious_pct"] + 10
        and structured_summary["fallback_pct"] < 10
        and not direct["indices_base_only"]
    ):
        return "structured_better", reasons
    if not reasons:
        return "stable_match", ["no_material_differences"]
    if (
        reasons == ["base_duplicate_indices"]
        and structured_summary["fallback_pct"] < 10
    ):
        return "structured_better", reasons
    return "needs_manual_review", reasons


def compare_reference_sources(
    *,
    pdf_path: Path,
    base_references: Sequence[Dict[str, Any]],
    base_stats: Dict[str, Any],
    structured_payload: Dict[str, Any],
    reader_layer_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    base_summary = summarize_base_source(base_references, base_stats)
    structured_summary = summarize_structured_source(structured_payload)
    base_indices = _indexed_set(base_summary)
    structured_indices = _indexed_set(structured_summary)
    base_max = base_summary.get("max_reference_index") or 0
    structured_max = structured_summary.get("max_reference_index") or 0
    direct = {
        "references_total_delta": structured_summary["total"] - base_summary["total"],
        "max_reference_index_delta": structured_max - base_max,
        "citation_style_match": (
            base_summary.get("citation_style")
            == structured_summary.get("citation_style")
        ),
        "indices_base_only": sorted(base_indices - structured_indices),
        "indices_structured_only": sorted(structured_indices - base_indices),
        "overlap": _compute_overlap(
            base_summary.get("entries") or [],
            structured_summary.get("entries") or [],
        ),
    }
    classification, reasons = _classify_result(
        base_summary,
        structured_summary,
        direct,
    )
    return {
        "pdf": {
            "path": str(pdf_path),
            "name": Path(pdf_path).name,
        },
        "reader_layers": reader_layer_counts or {},
        "base": base_summary,
        "structured": structured_summary,
        "comparison": direct,
        "classification": classification,
        "classification_reasons": reasons,
    }


def _disabled_crossref_fetch(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("Crossref disabled by compare_reference_sources.py")


@contextmanager
def _crossref_policy(*, allow_crossref: bool):
    if allow_crossref:
        yield
        return
    with patch(
        "citations.services.references_data.crossref_fetch_work_by_doi",
        _disabled_crossref_fetch,
    ):
        yield


def build_comparison_for_pdf(
    pdf_path: Path,
    *,
    allow_crossref: bool = False,
) -> Dict[str, Any]:
    references, stats = extract_pdf_references(str(pdf_path))
    reader_payload = extract_pdf_data(str(pdf_path))
    layers = reader_payload.get("layers") or {}
    with _crossref_policy(allow_crossref=allow_crossref):
        structured_payload = build_references_data(
            references=references,
            snippets=[],
            layers=layers,
            references_numbered=bool(stats.get("references_numbered")),
            article_doi="",
            source_filename=pdf_path.name,
            engine_used="papermage",
            debug_reference_detection=True,
        )
    layer_counts = {str(name): len(items or []) for name, items in layers.items()}
    return compare_reference_sources(
        pdf_path=pdf_path,
        base_references=references,
        base_stats=stats,
        structured_payload=structured_payload,
        reader_layer_counts=layer_counts,
    )


def resolve_pdf_paths(
    *,
    pdfs: Sequence[Path],
    directory: Optional[Path],
    glob_pattern: str,
    default_dir: Path = DEFAULT_PDF_DIR,
) -> List[Path]:
    if pdfs:
        paths = [path.expanduser().resolve() for path in pdfs]
    else:
        source_dir = (directory or default_dir).expanduser().resolve()
        paths = sorted(
            path.resolve()
            for path in source_dir.glob(glob_pattern)
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Missing PDF path(s): {missing_text}")
    if not paths:
        raise SystemExit("No PDF files matched the requested input.")
    return paths


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_id(value: Optional[str]) -> str:
    raw = value or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    normalized = RUN_ID_RE.sub("_", raw).strip("._-")
    if not normalized:
        raise SystemExit("Invalid --run-id value.")
    return normalized


def _safe_artifact_name(pdf_path: Path) -> str:
    stem = RUN_ID_RE.sub("_", pdf_path.stem).strip("._-")
    return stem or "paper"


def _summary_item(result: Dict[str, Any], artifact_path: Path) -> Dict[str, Any]:
    return {
        "pdf": result["pdf"]["name"],
        "artifact": str(artifact_path),
        "classification": result["classification"],
        "classification_reasons": result["classification_reasons"],
        "base_total": result["base"]["total"],
        "structured_total": result["structured"]["total"],
        "references_total_delta": result["comparison"]["references_total_delta"],
        "base_max_reference_index": result["base"]["max_reference_index"],
        "structured_max_reference_index": result["structured"]["max_reference_index"],
        "max_reference_index_delta": result["comparison"]["max_reference_index_delta"],
        "base_suspicious_count": result["base"]["suspicious_count"],
        "structured_suspicious_count": result["structured"]["suspicious_count"],
        "structured_fallback_count": result["structured"]["fallback_count"],
        "overlap_base_coverage_pct": result["comparison"]["overlap"][
            "base_coverage_pct"
        ],
    }


def _build_summary_payload(
    *,
    results: Sequence[Dict[str, Any]],
    artifact_paths: Sequence[Path],
    output_dir: Path,
    allow_crossref: bool,
) -> Dict[str, Any]:
    items = [
        _summary_item(result, artifact_path)
        for result, artifact_path in zip(results, artifact_paths)
    ]
    classifications = Counter(item["classification"] for item in items)
    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "pdf_count": len(items),
            "crossref_allowed": allow_crossref,
        },
        "classification_counts": dict(sorted(classifications.items())),
        "results": items,
    }


def _build_summary_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Reference Source Comparison",
        "",
        f"- PDFs: {summary['metadata']['pdf_count']}",
        f"- Crossref allowed: {summary['metadata']['crossref_allowed']}",
        "",
        "| PDF | class | base | structured | delta | max delta | fallbacks | overlap |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summary["results"]:
        lines.append(
            "| {pdf} | {classification} | {base_total} | {structured_total} | "
            "{references_total_delta} | {max_reference_index_delta} | "
            "{structured_fallback_count} | {overlap_base_coverage_pct}% |".format(
                **item
            )
        )
    lines.append("")
    return "\n".join(lines)


def _print_console_result(result: Dict[str, Any]) -> None:
    base = result["base"]
    structured = result["structured"]
    comparison = result["comparison"]
    print(f"PDF: {result['pdf']['name']}")
    print(
        f"  class: {result['classification']} ({', '.join(result['classification_reasons'])})"
    )
    print(
        "  totals: "
        f"base={base['total']} structured={structured['total']} "
        f"delta={comparison['references_total_delta']}"
    )
    print(
        "  style/max: "
        f"base={base['citation_style']}:{base['max_reference_index']} "
        f"structured={structured['citation_style']}:{structured['max_reference_index']} "
        f"max_delta={comparison['max_reference_index_delta']}"
    )
    print(
        "  structured sources: "
        f"{structured['source_counts']} fallbacks={structured['fallback_count']}"
    )
    print(
        "  suspicious: "
        f"base={base['suspicious_count']} structured={structured['suspicious_count']} "
        f"overlap={comparison['overlap']['base_coverage_pct']}%"
    )
    if comparison["indices_base_only"] or comparison["indices_structured_only"]:
        print(
            "  index diff: "
            f"base_only={comparison['indices_base_only'][:20]} "
            f"structured_only={comparison['indices_structured_only'][:20]}"
        )
    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare current reader_data references with references_data "
            "structured references over real PDFs."
        )
    )
    parser.add_argument(
        "--pdf",
        action="append",
        type=Path,
        default=[],
        help="PDF path to compare. Repeat for multiple PDFs.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help=(
            "Directory containing PDFs. Defaults to "
            "tfg_project/citations/static/citations/PDFs-Reales/."
        ),
    )
    parser.add_argument(
        "--glob",
        default="*.pdf",
        help="Glob used with --dir or the default corpus directory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root output directory for JSON and summary artifacts.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional output run id. Defaults to a UTC timestamp.",
    )
    parser.add_argument(
        "--allow-crossref",
        action="store_true",
        help="Allow references_data to query Crossref. Disabled by default.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.pdf and args.dir:
        parser.error("Use either --pdf or --dir, not both.")

    pdf_paths = resolve_pdf_paths(
        pdfs=args.pdf,
        directory=args.dir,
        glob_pattern=args.glob,
        default_dir=DEFAULT_PDF_DIR,
    )
    output_dir = args.output_root / _run_id(args.run_id)
    output_dir.mkdir(parents=True, exist_ok=False)

    results: List[Dict[str, Any]] = []
    artifact_paths: List[Path] = []
    for pdf_path in pdf_paths:
        result = build_comparison_for_pdf(
            pdf_path,
            allow_crossref=bool(args.allow_crossref),
        )
        artifact_path = output_dir / f"{_safe_artifact_name(pdf_path)}.json"
        _write_json(artifact_path, result)
        results.append(result)
        artifact_paths.append(artifact_path)
        _print_console_result(result)

    summary = _build_summary_payload(
        results=results,
        artifact_paths=artifact_paths,
        output_dir=output_dir,
        allow_crossref=bool(args.allow_crossref),
    )
    _write_json(output_dir / "summary.json", summary)
    _write_text(output_dir / "summary.md", _build_summary_markdown(summary))
    print(f"Output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

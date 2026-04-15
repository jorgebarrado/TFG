from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str((ROOT / "tfg_project").resolve()))

from citations.services.grobid_client import (  # noqa: E402
    GrobidError,
    process_fulltext_document,
    process_references,
)
from citations.services.grobid_parser import (  # noqa: E402
    GrobidParseError,
    parse_fulltext_tei,
    parse_references_tei,
)
from citations.services.reference_parsing_experiments.comparison import (  # noqa: E402
    summarize_entries,
)
from citations.services.reference_parsing_experiments.input_common import (  # noqa: E402
    build_common_input,
    resolve_pdf_paths,
    slugify_pdf_name,
)
from citations.services.reference_parsing_experiments.normalization import (  # noqa: E402
    build_normalized_entry,
    clean_text,
)
from citations.services.reference_parsing_experiments.runners import (  # noqa: E402
    run_refextract_parser,
)


DEFAULT_BUCKET_SUMMARY = Path("tmp/reference_parser_experiments/all_pdfs_eval_20260414/summary.json")
DEFAULT_OUTPUT_ROOT = Path("tmp/grobid_eval")
DEFAULT_PROBLEM_BUCKETS = [
    "low_alpha_or_short_noise",
    "small_reference_set",
    "header_not_found_fallback",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _alpha_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def _load_bucket_papers(summary_path: Path) -> List[Dict[str, Any]]:
    if not summary_path.exists():
        raise FileNotFoundError(f"Bucket summary not found: {summary_path}")
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    papers = payload.get("papers")
    if not isinstance(papers, list):
        raise ValueError(f"Invalid bucket summary format (missing papers[]): {summary_path}")
    normalized: List[Dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        pdf_name = clean_text(paper.get("pdf_name"))
        input_bucket = clean_text(
            paper.get("input_bucket")
            or ((paper.get("input_quality") or {}).get("primary_bucket"))
        )
        if pdf_name:
            normalized.append(
                {
                    "pdf_name": pdf_name,
                    "input_bucket": input_bucket or "unknown",
                    "paper_slug": clean_text(paper.get("paper_slug")) or slugify_pdf_name(pdf_name),
                }
            )
    if not normalized:
        raise ValueError(f"No papers found in bucket summary: {summary_path}")
    return normalized


def _select_sample_from_bucket_summary(
    *,
    bucket_summary_path: Path,
    problem_buckets: Sequence[str],
    clean_control_count: int,
) -> Tuple[List[str], Dict[str, str], Dict[str, Any]]:
    papers = _load_bucket_papers(bucket_summary_path)
    bucket_by_pdf: Dict[str, str] = {}
    for paper in papers:
        bucket_by_pdf[paper["pdf_name"]] = paper["input_bucket"]

    problematic = sorted(
        {
            paper["pdf_name"]
            for paper in papers
            if paper["input_bucket"] in set(problem_buckets)
        }
    )
    clean_candidates = sorted(
        {
            paper["pdf_name"]
            for paper in papers
            if paper["input_bucket"] == "clean_input"
        }
    )
    clean_selected = clean_candidates[: max(0, clean_control_count)]

    selected: List[str] = []
    for name in problematic + clean_selected:
        if name not in selected:
            selected.append(name)

    selection = {
        "bucket_summary_path": str(bucket_summary_path.resolve()),
        "problem_buckets_targeted": list(problem_buckets),
        "problematic_pdf_names": problematic,
        "clean_candidates": clean_candidates,
        "clean_selected": clean_selected,
        "selected_pdf_names": selected,
        "selected_count": len(selected),
    }
    return selected, bucket_by_pdf, selection


def _collect_health(base_url: str, timeout: int) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    endpoints = ["/api/version", "/api/isalive", "/api/health"]
    checks: Dict[str, Any] = {}
    for endpoint in endpoints:
        url = f"{base}{endpoint}"
        check: Dict[str, Any] = {
            "url": url,
            "ok": False,
            "status_code": None,
            "elapsed_ms": None,
            "body_preview": "",
            "error": "",
        }
        started = datetime.now()
        try:
            response = requests.get(url, timeout=timeout)
            elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
            body = response.text or ""
            check["elapsed_ms"] = elapsed_ms
            check["status_code"] = response.status_code
            check["body_preview"] = body[:300]
            check["ok"] = bool(response.ok)
            if endpoint == "/api/isalive":
                check["isalive_true"] = "true" in body.lower()
        except requests.RequestException as exc:
            check["error"] = clean_text(exc)
        checks[endpoint] = check

    isalive_ok = bool(checks.get("/api/isalive", {}).get("isalive_true"))
    all_http_ok = all(bool(item.get("ok")) for item in checks.values())
    return {
        "base_url": base,
        "timeout_seconds": timeout,
        "created_at": datetime.now().isoformat(),
        "checks": checks,
        "summary": {
            "isalive_true": isalive_ok,
            "all_http_ok": all_http_ok,
        },
    }


def _is_extractor_ref_valid(raw_input: str, warnings: Iterable[str]) -> bool:
    raw = clean_text(raw_input)
    warning_set = set(warnings or [])
    if not raw:
        return False
    if {"empty_raw_reference", "very_short_reference", "low_alpha_content"}.intersection(warning_set):
        return False
    if len(raw) < 30:
        return False
    if _alpha_count(raw) < 15:
        return False
    if re.match(r"^\d+(?:\s+\d+){3,}", raw):
        return False
    return True


def _summarize_extractor_common_input(common_input: Dict[str, Any]) -> Dict[str, Any]:
    raw_refs = common_input.get("raw_references") or []
    likely_valid = 0
    likely_garbage = 0
    doi_non_empty = 0
    for item in raw_refs:
        raw_input = clean_text(item.get("raw_input"))
        warnings = item.get("warnings") or []
        if item.get("extractor_doi"):
            doi_non_empty += 1
        if _is_extractor_ref_valid(raw_input, warnings):
            likely_valid += 1
        else:
            likely_garbage += 1
    stats = common_input.get("extractor_stats") or {}
    return {
        "total_references": len(raw_refs),
        "likely_valid": likely_valid,
        "likely_garbage": likely_garbage,
        "doi_non_empty": doi_non_empty,
        "references_header_found": bool(stats.get("references_header_found")),
        "references_numbered": bool(stats.get("references_numbered")),
        "citation_style": clean_text(stats.get("citation_style")) or None,
        "max_reference_index": _safe_int(stats.get("max_reference_index"), 0),
        "input_warnings": list(common_input.get("warnings") or []),
    }


def _is_grobid_ref_valid(reference: Dict[str, Any]) -> bool:
    title = clean_text(reference.get("title"))
    authors = [clean_text(item) for item in (reference.get("authors") or []) if clean_text(item)]
    year = reference.get("year")
    doi = clean_text(reference.get("doi"))
    venue = clean_text(reference.get("venue"))
    pages = clean_text(reference.get("pages"))
    raw_citation = clean_text(reference.get("raw_citation"))
    if doi:
        return True
    if title and authors:
        return True
    if title and year:
        return True
    non_empty_fields = int(bool(title)) + int(bool(authors)) + int(bool(year)) + int(bool(venue)) + int(bool(pages))
    if non_empty_fields >= 3:
        return True
    if len(raw_citation) >= 60 and _alpha_count(raw_citation) >= 25:
        return True
    return False


def _summarize_grobid_references(parsed: Dict[str, Any]) -> Dict[str, Any]:
    refs = parsed.get("references") or []
    title_non_empty = 0
    authors_non_empty = 0
    year_non_empty = 0
    doi_non_empty = 0
    likely_valid = 0
    likely_garbage = 0
    for reference in refs:
        if clean_text(reference.get("title")):
            title_non_empty += 1
        if [clean_text(item) for item in (reference.get("authors") or []) if clean_text(item)]:
            authors_non_empty += 1
        if reference.get("year"):
            year_non_empty += 1
        if clean_text(reference.get("doi")):
            doi_non_empty += 1
        if _is_grobid_ref_valid(reference):
            likely_valid += 1
        else:
            likely_garbage += 1
    total = len(refs)
    usable = bool(total) and likely_valid >= max(1, int(round(total * 0.4)))
    return {
        "total_references": total,
        "title_non_empty": title_non_empty,
        "authors_non_empty": authors_non_empty,
        "year_non_empty": year_non_empty,
        "doi_non_empty": doi_non_empty,
        "likely_valid": likely_valid,
        "likely_garbage": likely_garbage,
        "usable_bibliography": usable,
    }


def _classify_error(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, requests.Timeout):
        return {"error_type": "timeout", "error": clean_text(exc)}
    if isinstance(exc, requests.ConnectionError):
        return {"error_type": "connection", "error": clean_text(exc)}
    if isinstance(exc, requests.HTTPError):
        return {"error_type": "http", "error": clean_text(exc)}
    if isinstance(exc, GrobidParseError):
        return {"error_type": "parse_error", "error": clean_text(exc)}
    if isinstance(exc, GrobidError):
        return {"error_type": "grobid_error", "error": clean_text(exc)}
    return {"error_type": "error", "error": clean_text(exc)}


def _run_process_references(pdf_path: Path, *, base_url: str, timeout: int) -> Dict[str, Any]:
    try:
        tei_xml = process_references(pdf_path, base_url=base_url, timeout=timeout)
        parsed = parse_references_tei(tei_xml, include_raw_citation=True)
        metrics = _summarize_grobid_references(parsed)
        return {
            "status": "ok",
            "endpoint": "/api/processReferences",
            "tei_xml": tei_xml,
            "parsed": parsed,
            "metrics": metrics,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:
        error_payload = _classify_error(exc)
        return {
            "status": "error",
            "endpoint": "/api/processReferences",
            "tei_xml": "",
            "parsed": {},
            "metrics": {},
            "error_type": error_payload["error_type"],
            "error": error_payload["error"],
        }


def _run_fulltext(pdf_path: Path, *, base_url: str, timeout: int) -> Dict[str, Any]:
    try:
        tei_xml = process_fulltext_document(pdf_path, base_url=base_url, timeout=timeout)
        parsed = parse_fulltext_tei(tei_xml)
        metrics = _summarize_grobid_references(parsed)
        metrics["inline_citation_count"] = _safe_int(parsed.get("inline_citation_count"), 0)
        metrics["section_count"] = len(parsed.get("sections") or [])
        return {
            "status": "ok",
            "endpoint": "/api/processFulltextDocument",
            "tei_xml": tei_xml,
            "parsed": parsed,
            "metrics": metrics,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:
        error_payload = _classify_error(exc)
        return {
            "status": "error",
            "endpoint": "/api/processFulltextDocument",
            "tei_xml": "",
            "parsed": {},
            "metrics": {},
            "error_type": error_payload["error_type"],
            "error": error_payload["error"],
        }

def _call_process_citation_list(
    raw_references: Sequence[Dict[str, Any]],
    *,
    base_url: str,
    timeout: int,
) -> Tuple[str, Dict[str, Any], List[str], List[Dict[str, Any]]]:
    citations = [clean_text(item.get("raw_input")) for item in raw_references if clean_text(item.get("raw_input"))]
    if not citations:
        raise ValueError("No raw references available for /api/processCitationList")

    payload = [("citations", citation) for citation in citations]
    url = f"{base_url.rstrip('/')}/api/processCitationList"
    response = requests.post(
        url,
        data=payload,
        headers={"Accept": "application/xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    tei_xml = response.text or ""
    if "<TEI" not in tei_xml[:1200]:
        preview = tei_xml[:300]
        raise GrobidParseError(f"/api/processCitationList did not return TEI XML. Preview: {preview!r}")

    parsed = parse_references_tei(tei_xml, include_raw_citation=True)
    parsed_refs = parsed.get("references") or []

    entries: List[Dict[str, Any]] = []
    notes: List[str] = []
    for pos, source_item in enumerate(raw_references):
        parsed_ref = parsed_refs[pos] if pos < len(parsed_refs) else {}
        warnings: List[str] = []
        if not parsed_ref:
            warnings.append("missing_grobid_citation_output_for_input")
        entries.append(
            build_normalized_entry(
                index=_safe_int(source_item.get("index"), pos),
                raw_input=source_item.get("raw_input") or "",
                parser="grobid_citation_list",
                title=parsed_ref.get("title") if isinstance(parsed_ref, dict) else None,
                authors=(parsed_ref.get("authors") if isinstance(parsed_ref, dict) else []) or [],
                year=(parsed_ref.get("year") if isinstance(parsed_ref, dict) else None),
                doi=(parsed_ref.get("doi") if isinstance(parsed_ref, dict) else None),
                venue=(parsed_ref.get("venue") if isinstance(parsed_ref, dict) else None),
                pages=(parsed_ref.get("pages") if isinstance(parsed_ref, dict) else None),
                identifiers=(parsed_ref.get("identifiers") if isinstance(parsed_ref, dict) else {}) or {},
                raw_output=parsed_ref,
                warnings=warnings,
            )
        )

    if len(parsed_refs) != len(raw_references):
        notes.append(
            "processCitationList returned "
            f"{len(parsed_refs)} parsed references for {len(raw_references)} inputs."
        )
    return tei_xml, parsed, notes, entries


def _run_citation_list(
    common_input: Dict[str, Any],
    *,
    base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    try:
        tei_xml, parsed, notes, entries = _call_process_citation_list(
            common_input.get("raw_references") or [],
            base_url=base_url,
            timeout=timeout,
        )
        summary = summarize_entries(
            parser="grobid_citation_list",
            status="ok",
            entries=entries,
            notes=notes,
        )
        return {
            "status": "ok",
            "endpoint": "/api/processCitationList",
            "tei_xml": tei_xml,
            "parsed": parsed,
            "entries": entries,
            "summary": summary,
            "notes": notes,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:
        error_payload = _classify_error(exc)
        return {
            "status": "error",
            "endpoint": "/api/processCitationList",
            "tei_xml": "",
            "parsed": {},
            "entries": [],
            "summary": summarize_entries(
                parser="grobid_citation_list",
                status="error",
                entries=[],
                notes=[error_payload["error"]],
            ),
            "notes": [error_payload["error"]],
            "error_type": error_payload["error_type"],
            "error": error_payload["error"],
        }


def _build_extractor_vs_process_references_row(
    *,
    paper_slug: str,
    pdf_name: str,
    input_bucket: str,
    extractor_summary: Dict[str, Any],
    process_references_result: Dict[str, Any],
) -> Dict[str, Any]:
    process_metrics = process_references_result.get("metrics") or {}
    extractor_total = _safe_int(extractor_summary.get("total_references"), 0)
    process_total = _safe_int(process_metrics.get("total_references"), 0)
    extractor_valid = _safe_int(extractor_summary.get("likely_valid"), 0)
    process_valid = _safe_int(process_metrics.get("likely_valid"), 0)
    extractor_garbage = _safe_int(extractor_summary.get("likely_garbage"), 0)
    process_garbage = _safe_int(process_metrics.get("likely_garbage"), 0)
    rescue_header_case = (
        (not bool(extractor_summary.get("references_header_found")))
        and (process_valid >= extractor_valid + 2 or process_total >= extractor_total + 3)
    )
    rescue_small_set = extractor_total <= 5 and process_valid >= extractor_valid + 2
    rescue_general = process_valid >= extractor_valid + 3
    rescue = rescue_header_case or rescue_small_set or rescue_general

    segmentation = "similar"
    if process_valid > extractor_valid and process_garbage <= extractor_garbage:
        segmentation = "better"
    elif process_valid < extractor_valid and process_garbage >= extractor_garbage:
        segmentation = "worse"

    return {
        "paper_slug": paper_slug,
        "pdf_name": pdf_name,
        "input_bucket": input_bucket,
        "extractor": extractor_summary,
        "process_references": {
            "status": process_references_result.get("status"),
            "error_type": process_references_result.get("error_type"),
            "error": process_references_result.get("error"),
            **process_metrics,
        },
        "delta": {
            "references_total": process_total - extractor_total,
            "likely_valid": process_valid - extractor_valid,
            "likely_garbage": process_garbage - extractor_garbage,
        },
        "rescue": {
            "is_rescue": rescue,
            "rescue_header_case": rescue_header_case,
            "rescue_small_set": rescue_small_set,
            "rescue_general": rescue_general,
            "segmentation_assessment": segmentation,
        },
    }


def _build_citation_parser_comparison_row(
    *,
    paper_slug: str,
    pdf_name: str,
    input_bucket: str,
    refextract_summary: Dict[str, Any],
    citation_list_summary: Dict[str, Any],
) -> Dict[str, Any]:
    delta = {
        "title_non_empty": _safe_int(citation_list_summary.get("title_non_empty")) - _safe_int(refextract_summary.get("title_non_empty")),
        "authors_non_empty": _safe_int(citation_list_summary.get("authors_non_empty")) - _safe_int(refextract_summary.get("authors_non_empty")),
        "year_non_empty": _safe_int(citation_list_summary.get("year_non_empty")) - _safe_int(refextract_summary.get("year_non_empty")),
        "doi_non_empty": _safe_int(citation_list_summary.get("doi_non_empty")) - _safe_int(refextract_summary.get("doi_non_empty")),
        "almost_empty": _safe_int(citation_list_summary.get("almost_empty")) - _safe_int(refextract_summary.get("almost_empty")),
    }
    return {
        "paper_slug": paper_slug,
        "pdf_name": pdf_name,
        "input_bucket": input_bucket,
        "refextract": refextract_summary,
        "grobid_citation_list": citation_list_summary,
        "delta": delta,
    }


def _field_score(entry: Dict[str, Any]) -> int:
    score = 0
    if clean_text(entry.get("title")):
        score += 1
    if entry.get("authors"):
        score += 1
    if entry.get("year"):
        score += 1
    if clean_text(entry.get("doi")):
        score += 1
    if clean_text(entry.get("venue")):
        score += 1
    return score


def _build_difficult_reference_examples(
    *,
    refextract_entries: Sequence[Dict[str, Any]],
    citation_entries: Sequence[Dict[str, Any]],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    row_count = min(len(refextract_entries), len(citation_entries))
    for idx in range(row_count):
        left = refextract_entries[idx]
        right = citation_entries[idx]
        left_score = _field_score(left)
        right_score = _field_score(right)
        if abs(right_score - left_score) < 2 and not (
            bool(clean_text(left.get("doi"))) ^ bool(clean_text(right.get("doi")))
        ):
            continue
        examples.append(
            {
                "index": idx,
                "raw_input": left.get("raw_input") or right.get("raw_input") or "",
                "refextract": {
                    "score": left_score,
                    "title": left.get("title"),
                    "authors": left.get("authors"),
                    "year": left.get("year"),
                    "doi": left.get("doi"),
                },
                "grobid_citation_list": {
                    "score": right_score,
                    "title": right.get("title"),
                    "authors": right.get("authors"),
                    "year": right.get("year"),
                    "doi": right.get("doi"),
                },
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _aggregate_extractor_vs_process_references(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    problem_rows = [row for row in rows if row.get("input_bucket") != "clean_input"]
    ok_rows = [row for row in rows if row.get("process_references", {}).get("status") == "ok"]
    rescue_rows = [row for row in problem_rows if row.get("rescue", {}).get("is_rescue")]
    return {
        "paper_count": len(rows),
        "ok_count": len(ok_rows),
        "error_count": len(rows) - len(ok_rows),
        "problematic_paper_count": len(problem_rows),
        "rescued_problematic_paper_count": len(rescue_rows),
        "rescued_problematic_papers": [row.get("pdf_name") for row in rescue_rows],
        "avg_delta_total_refs": (
            sum(_safe_int(row.get("delta", {}).get("references_total")) for row in ok_rows) / len(ok_rows)
            if ok_rows
            else 0.0
        ),
        "avg_delta_valid_refs": (
            sum(_safe_int(row.get("delta", {}).get("likely_valid")) for row in ok_rows) / len(ok_rows)
            if ok_rows
            else 0.0
        ),
    }


def _aggregate_citation_parser_comparison(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "paper_count": 0,
            "metric_wins": {},
            "delta_sums": {},
        }

    metric_wins = {
        "title_non_empty": 0,
        "authors_non_empty": 0,
        "year_non_empty": 0,
        "doi_non_empty": 0,
        "almost_empty_lower_is_better": 0,
    }
    delta_sums = {
        "title_non_empty": 0,
        "authors_non_empty": 0,
        "year_non_empty": 0,
        "doi_non_empty": 0,
        "almost_empty": 0,
    }
    for row in rows:
        delta = row.get("delta") or {}
        for key in delta_sums:
            delta_sums[key] += _safe_int(delta.get(key), 0)
        if _safe_int(delta.get("title_non_empty")) > 0:
            metric_wins["title_non_empty"] += 1
        if _safe_int(delta.get("authors_non_empty")) > 0:
            metric_wins["authors_non_empty"] += 1
        if _safe_int(delta.get("year_non_empty")) > 0:
            metric_wins["year_non_empty"] += 1
        if _safe_int(delta.get("doi_non_empty")) > 0:
            metric_wins["doi_non_empty"] += 1
        if _safe_int(delta.get("almost_empty")) < 0:
            metric_wins["almost_empty_lower_is_better"] += 1

    return {
        "paper_count": len(rows),
        "metric_wins": metric_wins,
        "delta_sums": delta_sums,
    }

def _aggregate_fulltext_vs_references(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    comparable_rows = [row for row in rows if row.get("status_pair") == "ok_ok"]
    added_value_rows = [row for row in comparable_rows if row.get("fulltext_adds_value")]
    return {
        "paper_count": len(rows),
        "comparable_paper_count": len(comparable_rows),
        "added_value_count": len(added_value_rows),
        "added_value_papers": [row.get("pdf_name") for row in added_value_rows],
        "avg_delta_total_refs": (
            sum(_safe_int(row.get("delta_total_refs")) for row in comparable_rows) / len(comparable_rows)
            if comparable_rows
            else 0.0
        ),
        "avg_delta_valid_refs": (
            sum(_safe_int(row.get("delta_valid_refs")) for row in comparable_rows) / len(comparable_rows)
            if comparable_rows
            else 0.0
        ),
    }


def _build_decision(
    *,
    extractor_vs_refs_agg: Dict[str, Any],
    fulltext_agg: Dict[str, Any],
    citation_agg: Dict[str, Any],
) -> Dict[str, Any]:
    problematic_total = _safe_int(extractor_vs_refs_agg.get("problematic_paper_count"), 0)
    rescued_total = _safe_int(extractor_vs_refs_agg.get("rescued_problematic_paper_count"), 0)
    rescue_rate = (rescued_total / problematic_total) if problematic_total else 0.0
    q1_strong = problematic_total > 0 and rescue_rate >= 0.5
    q1_partial = rescued_total > 0

    comparable_fulltext = _safe_int(fulltext_agg.get("comparable_paper_count"), 0)
    fulltext_added = _safe_int(fulltext_agg.get("added_value_count"), 0)
    q2_positive = comparable_fulltext > 0 and (fulltext_added / comparable_fulltext) >= 0.3
    q2_partial = fulltext_added > 0

    metric_wins = citation_agg.get("metric_wins") or {}
    wins_count = sum(
        int(bool(metric_wins.get(metric)))
        for metric in (
            "title_non_empty",
            "authors_non_empty",
            "year_non_empty",
            "doi_non_empty",
            "almost_empty_lower_is_better",
        )
    )
    delta_sums = citation_agg.get("delta_sums") or {}
    total_positive_delta = (
        _safe_int(delta_sums.get("title_non_empty"))
        + _safe_int(delta_sums.get("authors_non_empty"))
        + _safe_int(delta_sums.get("year_non_empty"))
        + _safe_int(delta_sums.get("doi_non_empty"))
    )
    q3_strong = wins_count >= 3 and total_positive_delta > 0
    q3_partial = wins_count >= 2 and total_positive_delta >= 0

    if q1_strong and q3_strong and q2_positive:
        recommendation = "merece_integracion_mas_fuerte"
    elif q1_strong and not q3_strong:
        recommendation = "aporta_solo_como_fallback"
    elif q3_strong and not q1_strong:
        recommendation = "aporta_como_parser_secundario"
    elif q1_partial or q3_partial:
        recommendation = "aporta_solo_como_fallback"
    else:
        recommendation = "no_aporta_suficiente"

    q1_answer = "no"
    if q1_strong:
        q1_answer = "si"
    elif q1_partial:
        q1_answer = "parcial"

    q2_answer = "no"
    if q2_positive:
        q2_answer = "si"
    elif q2_partial:
        q2_answer = "parcial"

    q3_answer = "no"
    if q3_strong:
        q3_answer = "si"
    elif q3_partial:
        q3_answer = "parcial"

    return {
        "q1_process_references_compensa_fallos_extractor": q1_answer,
        "q2_fulltext_aporta_valor_real": q2_answer,
        "q3_citation_list_mejora_vs_refextract": q3_answer,
        "q4_recomendacion": recommendation,
        "supporting_metrics": {
            "problematic_total": problematic_total,
            "rescued_total": rescued_total,
            "rescue_rate": rescue_rate,
            "fulltext_comparable_total": comparable_fulltext,
            "fulltext_added_total": fulltext_added,
            "citation_metric_wins": metric_wins,
            "citation_delta_sums": delta_sums,
        },
    }


def _build_per_paper_notes(
    *,
    extractor_vs_refs_rows: Sequence[Dict[str, Any]],
    fulltext_rows: Sequence[Dict[str, Any]],
    citation_rows: Sequence[Dict[str, Any]],
) -> Dict[str, List[str]]:
    by_slug: Dict[str, List[str]] = {}
    fulltext_by_slug = {row.get("paper_slug"): row for row in fulltext_rows}
    citation_by_slug = {row.get("paper_slug"): row for row in citation_rows}
    for row in extractor_vs_refs_rows:
        slug = row.get("paper_slug")
        notes: List[str] = []
        input_bucket = row.get("input_bucket")
        delta = row.get("delta") or {}
        rescue = row.get("rescue") or {}
        process = row.get("process_references") or {}
        if process.get("status") != "ok":
            notes.append(
                f"/api/processReferences fallo ({process.get('error_type')}): {process.get('error')}"
            )
        else:
            notes.append(
                "processReferences delta refs="
                f"{_safe_int(delta.get('references_total')):+d}, "
                f"delta valid={_safe_int(delta.get('likely_valid')):+d}, "
                f"segmentacion={rescue.get('segmentation_assessment')}"
            )
            if rescue.get("is_rescue"):
                notes.append("processReferences rescata este PDF frente al extractor actual.")
        if input_bucket != "clean_input":
            notes.append(f"PDF de bucket problematico: {input_bucket}.")

        fulltext_row = fulltext_by_slug.get(slug) or {}
        if fulltext_row:
            status_pair = fulltext_row.get("status_pair")
            if status_pair == "ok_ok":
                notes.append(
                    "fulltext delta refs="
                    f"{_safe_int(fulltext_row.get('delta_total_refs')):+d}, "
                    f"delta valid={_safe_int(fulltext_row.get('delta_valid_refs')):+d}, "
                    f"inline={_safe_int(fulltext_row.get('inline_citation_count'))}"
                )
                if fulltext_row.get("fulltext_adds_value"):
                    notes.append("fulltext aporta valor adicional frente a processReferences en este PDF.")
            else:
                notes.append(
                    f"Comparacion fulltext vs processReferences no disponible ({status_pair})."
                )

        citation_row = citation_by_slug.get(slug) or {}
        if citation_row:
            delta_citation = citation_row.get("delta") or {}
            notes.append(
                "citation_list vs refextract delta: "
                f"title={_safe_int(delta_citation.get('title_non_empty')):+d}, "
                f"authors={_safe_int(delta_citation.get('authors_non_empty')):+d}, "
                f"year={_safe_int(delta_citation.get('year_non_empty')):+d}, "
                f"doi={_safe_int(delta_citation.get('doi_non_empty')):+d}, "
                f"almost_empty={_safe_int(delta_citation.get('almost_empty')):+d}"
            )
        by_slug[str(slug)] = notes
    return by_slug


def _build_summary_markdown(
    *,
    run_id: str,
    config: Dict[str, Any],
    health: Dict[str, Any],
    extractor_vs_refs_agg: Dict[str, Any],
    fulltext_agg: Dict[str, Any],
    citation_agg: Dict[str, Any],
    decision: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"# GROBID Evaluation `{run_id}`")
    lines.append("")
    lines.append("## Config")
    lines.append("")
    lines.append(f"- Base URL: {config.get('grobid_base_url')}")
    lines.append(f"- Timeout (s): {config.get('timeout')}")
    lines.append(f"- PDFs evaluados: {config.get('pdf_count')}")
    lines.append(
        f"- Buckets problematicos: {', '.join(config.get('problem_buckets_targeted') or [])}"
    )
    lines.append("")
    lines.append("## Health")
    lines.append("")
    checks = health.get("checks") or {}
    for endpoint in ["/api/version", "/api/isalive", "/api/health"]:
        check = checks.get(endpoint) or {}
        lines.append(
            f"- {endpoint}: ok={check.get('ok')} status={check.get('status_code')} "
            f"error={check.get('error') or '-'}"
        )
    lines.append("")
    lines.append("## Q1: processReferences")
    lines.append("")
    lines.append(f"- Problematicos: {extractor_vs_refs_agg.get('problematic_paper_count')}")
    lines.append(
        "- Rescatados: "
        f"{extractor_vs_refs_agg.get('rescued_problematic_paper_count')} "
        f"({', '.join(extractor_vs_refs_agg.get('rescued_problematic_papers') or []) or 'ninguno'})"
    )
    lines.append(f"- Avg delta refs: {extractor_vs_refs_agg.get('avg_delta_total_refs'):.2f}")
    lines.append(f"- Avg delta valid: {extractor_vs_refs_agg.get('avg_delta_valid_refs'):.2f}")
    lines.append(
        f"- Respuesta: {decision.get('q1_process_references_compensa_fallos_extractor')}"
    )
    lines.append("")
    lines.append("## Q2: processFulltextDocument")
    lines.append("")
    lines.append(f"- Comparables: {fulltext_agg.get('comparable_paper_count')}")
    lines.append(
        "- Papers con valor adicional: "
        f"{fulltext_agg.get('added_value_count')} "
        f"({', '.join(fulltext_agg.get('added_value_papers') or []) or 'ninguno'})"
    )
    lines.append(f"- Avg delta refs: {fulltext_agg.get('avg_delta_total_refs'):.2f}")
    lines.append(f"- Avg delta valid: {fulltext_agg.get('avg_delta_valid_refs'):.2f}")
    lines.append(f"- Respuesta: {decision.get('q2_fulltext_aporta_valor_real')}")
    lines.append("")
    lines.append("## Q3: processCitationList vs refextract")
    lines.append("")
    lines.append(f"- Papers comparados: {citation_agg.get('paper_count')}")
    wins = citation_agg.get("metric_wins") or {}
    delta_sums = citation_agg.get("delta_sums") or {}
    lines.append(
        "- Metric wins (citation_list): "
        f"title={wins.get('title_non_empty', 0)}, "
        f"authors={wins.get('authors_non_empty', 0)}, "
        f"year={wins.get('year_non_empty', 0)}, "
        f"doi={wins.get('doi_non_empty', 0)}, "
        f"almost_empty={wins.get('almost_empty_lower_is_better', 0)}"
    )
    lines.append(
        "- Delta sums: "
        f"title={delta_sums.get('title_non_empty', 0):+d}, "
        f"authors={delta_sums.get('authors_non_empty', 0):+d}, "
        f"year={delta_sums.get('year_non_empty', 0):+d}, "
        f"doi={delta_sums.get('doi_non_empty', 0):+d}, "
        f"almost_empty={delta_sums.get('almost_empty', 0):+d}"
    )
    lines.append(f"- Respuesta: {decision.get('q3_citation_list_mejora_vs_refextract')}")
    lines.append("")
    lines.append("## Recomendacion")
    lines.append("")
    lines.append(f"- Decision final: {decision.get('q4_recomendacion')}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated GROBID evaluation over problematic and clean-control PDFs."
    )
    parser.add_argument(
        "--run-id",
        help="Optional run id. Defaults to timestamp.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Output root for isolated GROBID artifacts.",
    )
    parser.add_argument(
        "--bucket-summary",
        default=str(DEFAULT_BUCKET_SUMMARY),
        help="Path to previous parser experiment summary.json with paper buckets.",
    )
    parser.add_argument(
        "--problem-bucket",
        action="append",
        dest="problem_buckets",
        help=(
            "Bucket to include in problematic sample. "
            "Repeat for multiple. Defaults to low_alpha_or_short_noise, small_reference_set, header_not_found_fallback."
        ),
    )
    parser.add_argument(
        "--clean-control-count",
        type=int,
        default=3,
        help="How many clean_input PDFs to include as control.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        dest="pdfs",
        help="Optional explicit PDF override. If provided, skips bucket-based selection.",
    )
    parser.add_argument(
        "--grobid-base-url",
        default="http://localhost:8070",
        help="GROBID base URL.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Timeout in seconds per endpoint request.",
    )
    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = Path(args.output_root)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    problem_buckets = args.problem_buckets or list(DEFAULT_PROBLEM_BUCKETS)

    if args.pdfs:
        selected_pdf_names = list(dict.fromkeys(args.pdfs))
        bucket_by_pdf = {name: "explicit_override" for name in selected_pdf_names}
        selection_meta = {
            "mode": "explicit_pdf_list",
            "selected_pdf_names": selected_pdf_names,
            "selected_count": len(selected_pdf_names),
        }
    else:
        selected_pdf_names, bucket_by_pdf, selection_meta = _select_sample_from_bucket_summary(
            bucket_summary_path=Path(args.bucket_summary),
            problem_buckets=problem_buckets,
            clean_control_count=args.clean_control_count,
        )

    if not selected_pdf_names:
        parser.error("No PDFs selected for evaluation.")

    resolved_pdf_paths = resolve_pdf_paths(selected_pdf_names)
    health = _collect_health(args.grobid_base_url, args.timeout)
    _write_json(run_dir / "health.json", health)

    config = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "grobid_base_url": args.grobid_base_url.rstrip("/"),
        "timeout": args.timeout,
        "problem_buckets_targeted": list(problem_buckets),
        "clean_control_count": args.clean_control_count,
        "pdf_names_final": [path.name for path in resolved_pdf_paths],
        "pdf_count": len(resolved_pdf_paths),
        "resolved_pdf_paths": [str(path.resolve()) for path in resolved_pdf_paths],
        "selection": selection_meta,
        "bucket_summary_path": str(Path(args.bucket_summary).resolve()),
    }
    _write_json(run_dir / "config.json", config)

    extractor_vs_refs_rows: List[Dict[str, Any]] = []
    citation_vs_refextract_rows: List[Dict[str, Any]] = []
    fulltext_rows: List[Dict[str, Any]] = []
    difficult_refs: Dict[str, List[Dict[str, Any]]] = {}

    for pdf_path in resolved_pdf_paths:
        common_input = build_common_input(pdf_path)
        paper_slug = common_input.get("paper_slug") or slugify_pdf_name(pdf_path.name)
        input_bucket = bucket_by_pdf.get(pdf_path.name) or common_input.get("input_quality", {}).get("primary_bucket") or "unknown"

        extractor_summary = _summarize_extractor_common_input(common_input)
        process_refs_result = _run_process_references(
            pdf_path,
            base_url=args.grobid_base_url,
            timeout=args.timeout,
        )
        fulltext_result = _run_fulltext(
            pdf_path,
            base_url=args.grobid_base_url,
            timeout=args.timeout,
        )
        citation_list_result = _run_citation_list(
            common_input,
            base_url=args.grobid_base_url,
            timeout=args.timeout,
        )
        refextract_output = run_refextract_parser(common_input)
        refextract_summary = summarize_entries(
            parser="refextract",
            status=refextract_output.get("status", "unknown"),
            entries=refextract_output.get("entries", []),
            notes=refextract_output.get("notes", []),
        )

        process_payload = {
            "paper_slug": paper_slug,
            "pdf_name": pdf_path.name,
            "pdf_path": str(pdf_path.resolve()),
            "input_bucket": input_bucket,
            "extractor_summary": extractor_summary,
            "status": process_refs_result.get("status"),
            "error_type": process_refs_result.get("error_type"),
            "error": process_refs_result.get("error"),
            "metrics": process_refs_result.get("metrics") or {},
            "parsed": process_refs_result.get("parsed") or {},
        }
        _write_json(run_dir / "process_references" / f"{paper_slug}.json", process_payload)
        if process_refs_result.get("tei_xml"):
            _write_text(run_dir / "process_references" / f"{paper_slug}.xml", process_refs_result["tei_xml"])

        fulltext_payload = {
            "paper_slug": paper_slug,
            "pdf_name": pdf_path.name,
            "pdf_path": str(pdf_path.resolve()),
            "input_bucket": input_bucket,
            "status": fulltext_result.get("status"),
            "error_type": fulltext_result.get("error_type"),
            "error": fulltext_result.get("error"),
            "metrics": fulltext_result.get("metrics") or {},
            "parsed": fulltext_result.get("parsed") or {},
        }
        _write_json(run_dir / "fulltext" / f"{paper_slug}.json", fulltext_payload)
        if fulltext_result.get("tei_xml"):
            _write_text(run_dir / "fulltext" / f"{paper_slug}.xml", fulltext_result["tei_xml"])

        citation_payload = {
            "paper_slug": paper_slug,
            "pdf_name": pdf_path.name,
            "pdf_path": str(pdf_path.resolve()),
            "input_bucket": input_bucket,
            "status": citation_list_result.get("status"),
            "error_type": citation_list_result.get("error_type"),
            "error": citation_list_result.get("error"),
            "notes": citation_list_result.get("notes") or [],
            "summary": citation_list_result.get("summary") or {},
            "parsed": citation_list_result.get("parsed") or {},
        }
        _write_json(run_dir / "citation_list" / f"{paper_slug}.json", citation_payload)
        if citation_list_result.get("tei_xml"):
            _write_text(run_dir / "citation_list" / f"{paper_slug}.xml", citation_list_result["tei_xml"])

        extractor_vs_row = _build_extractor_vs_process_references_row(
            paper_slug=paper_slug,
            pdf_name=pdf_path.name,
            input_bucket=input_bucket,
            extractor_summary=extractor_summary,
            process_references_result=process_refs_result,
        )
        extractor_vs_refs_rows.append(extractor_vs_row)

        process_status = process_refs_result.get("status")
        fulltext_status = fulltext_result.get("status")
        fulltext_metrics = fulltext_result.get("metrics") or {}
        process_metrics = process_refs_result.get("metrics") or {}
        status_pair = f"{process_status}_{fulltext_status}"
        delta_total_refs = None
        delta_valid_refs = None
        fulltext_adds_value = False
        if status_pair == "ok_ok":
            delta_total_refs = _safe_int(fulltext_metrics.get("total_references")) - _safe_int(process_metrics.get("total_references"))
            delta_valid_refs = _safe_int(fulltext_metrics.get("likely_valid")) - _safe_int(process_metrics.get("likely_valid"))
            fulltext_adds_value = (
                _safe_int(delta_valid_refs, 0) >= 2
                or _safe_int(delta_total_refs, 0) >= 3
            )
        elif process_status != "ok" and fulltext_status == "ok":
            fulltext_adds_value = True
        fulltext_rows.append(
            {
                "paper_slug": paper_slug,
                "pdf_name": pdf_path.name,
                "input_bucket": input_bucket,
                "status_pair": status_pair,
                "delta_total_refs": delta_total_refs,
                "delta_valid_refs": delta_valid_refs,
                "inline_citation_count": _safe_int(fulltext_metrics.get("inline_citation_count"), 0),
                "fulltext_adds_value": fulltext_adds_value,
                "process_references_status": process_status,
                "fulltext_status": fulltext_status,
            }
        )

        citation_row = _build_citation_parser_comparison_row(
            paper_slug=paper_slug,
            pdf_name=pdf_path.name,
            input_bucket=input_bucket,
            refextract_summary=refextract_summary,
            citation_list_summary=citation_list_result.get("summary") or {},
        )
        citation_vs_refextract_rows.append(citation_row)

        difficult_refs[paper_slug] = _build_difficult_reference_examples(
            refextract_entries=refextract_output.get("entries") or [],
            citation_entries=citation_list_result.get("entries") or [],
            limit=5,
        )

    extractor_vs_refs_agg = _aggregate_extractor_vs_process_references(extractor_vs_refs_rows)
    citation_agg = _aggregate_citation_parser_comparison(citation_vs_refextract_rows)
    fulltext_agg = _aggregate_fulltext_vs_references(fulltext_rows)
    decision = _build_decision(
        extractor_vs_refs_agg=extractor_vs_refs_agg,
        fulltext_agg=fulltext_agg,
        citation_agg=citation_agg,
    )

    per_paper_notes = _build_per_paper_notes(
        extractor_vs_refs_rows=extractor_vs_refs_rows,
        fulltext_rows=fulltext_rows,
        citation_rows=citation_vs_refextract_rows,
    )

    extractor_vs_payload = {
        "run_id": run_id,
        "rows": extractor_vs_refs_rows,
        "aggregate": extractor_vs_refs_agg,
    }
    citation_vs_payload = {
        "run_id": run_id,
        "rows": citation_vs_refextract_rows,
        "aggregate": citation_agg,
        "difficult_reference_examples": difficult_refs,
    }
    aggregate_payload = {
        "run_id": run_id,
        "extractor_vs_process_references": extractor_vs_refs_agg,
        "fulltext_vs_process_references": fulltext_agg,
        "refextract_vs_citation_list": citation_agg,
        "decision": decision,
    }
    fulltext_vs_payload = {
        "run_id": run_id,
        "rows": fulltext_rows,
        "aggregate": fulltext_agg,
    }

    _write_json(run_dir / "comparisons" / "extractor_vs_process_references.json", extractor_vs_payload)
    _write_json(run_dir / "comparisons" / "fulltext_vs_process_references.json", fulltext_vs_payload)
    _write_json(run_dir / "comparisons" / "refextract_vs_citation_list.json", citation_vs_payload)
    _write_json(run_dir / "comparisons" / "per_paper_notes.json", per_paper_notes)
    _write_json(run_dir / "comparisons" / "aggregate.json", aggregate_payload)

    summary_payload = {
        "run_id": run_id,
        "config": config,
        "health": health,
        "decision": decision,
        "aggregates": {
            "extractor_vs_process_references": extractor_vs_refs_agg,
            "fulltext_vs_process_references": fulltext_agg,
            "refextract_vs_citation_list": citation_agg,
        },
    }
    _write_json(run_dir / "summary.json", summary_payload)
    _write_text(
        run_dir / "summary.md",
        _build_summary_markdown(
            run_id=run_id,
            config=config,
            health=health,
            extractor_vs_refs_agg=extractor_vs_refs_agg,
            fulltext_agg=fulltext_agg,
            citation_agg=citation_agg,
            decision=decision,
        ),
    )

    print(json.dumps(summary_payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

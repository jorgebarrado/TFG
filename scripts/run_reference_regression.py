#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
DATASET_DIR = ROOT / "tfg_project/citations/static/citations/PDFs-Reales"
DEFAULT_DATASET_PATH = ROOT / "scripts/reference_regression_dataset.json"
DEFAULT_OUTPUT_ROOT = ROOT / "tmp/reference_regression"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tfg_project.settings")
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / ".cache" / "transformers"))

import django  # noqa: E402

django.setup()

from citations.services.papermage_extractor import extract_pdf_data  # noqa: E402
from citations.services.reader_data import extract_pdf_references  # noqa: E402
from citations.services.references_data import (  # noqa: E402
    build_references_data,
    finalize_reference_detection_debug_payload,
)


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


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _safe_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


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


def _load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    raw = _read_json(dataset_path)
    if not isinstance(raw, list):
        raise ValueError(f"El dataset debe ser una lista JSON: {dataset_path}")
    dataset: List[Dict[str, Any]] = []
    for idx, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Entrada {idx} invalida en {dataset_path}")
        paper_id = str(entry.get("id") or "").strip()
        pdf_name = str(entry.get("pdf") or "").strip()
        if not paper_id or not pdf_name:
            raise ValueError(
                f"Entrada {idx} debe incluir 'id' y 'pdf' en {dataset_path}"
            )
        dataset.append(dict(entry))
    return dataset


def _filter_dataset(
    dataset: Sequence[Dict[str, Any]],
    *,
    paper_ids: Sequence[str],
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    selected = list(dataset)
    if paper_ids:
        selected_ids = {paper_id.strip() for paper_id in paper_ids if paper_id.strip()}
        selected = [
            entry for entry in selected if str(entry.get("id") or "").strip() in selected_ids
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


def _run_single_extraction(
    *,
    pdf_path: Path,
    paper_entry: Dict[str, Any],
    engine: str,
) -> Dict[str, Any]:
    article_doi = str(paper_entry.get("article_doi") or "").strip()
    base_references, base_stats = extract_pdf_references(str(pdf_path))
    reader_data = extract_pdf_data(str(pdf_path))
    references_data = build_references_data(
        references=base_references,
        snippets=[],
        layers=reader_data.get("layers", {}),
        references_numbered=bool(base_stats.get("references_numbered")),
        article_doi=article_doi,
        source_filename=pdf_path.name,
        engine_used=engine,
        debug_reference_detection=True,
    )
    debug_payload = finalize_reference_detection_debug_payload(
        references_data.pop("debug_payload", None),
        references=references_data.get("references") or [],
    )
    extraction_payload = {
        "paper_id": str(paper_entry.get("id") or ""),
        "pdf_file": pdf_path.name,
        "pdf_path": str(pdf_path),
        "dataset_entry": dict(paper_entry),
        "engine_used": engine,
        "base_reference_stats": base_stats,
        "base_reference_count": len(base_references),
        "final_extraction": references_data,
    }
    return {
        "extraction": extraction_payload,
        "debug": debug_payload,
        "base_references": base_references,
        "base_stats": base_stats,
        "references_data": references_data,
    }


def _calculate_metrics(
    *,
    paper_entry: Dict[str, Any],
    extraction_payload: Dict[str, Any],
    debug_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    references_data = extraction_payload.get("final_extraction") or {}
    references = [
        item
        for item in (references_data.get("references") or [])
        if isinstance(item, dict)
    ]
    total = len(references)
    expected_max = _safe_int(paper_entry.get("expected_max_reference_index"))
    max_detected = _safe_int(references_data.get("max_reference_index"))
    if max_detected is None:
        max_detected = max(
            (_safe_int(item.get("index")) or 0 for item in references),
            default=0,
        )
    difference_vs_expected = (
        (max_detected - expected_max)
        if expected_max is not None and max_detected is not None
        else None
    )

    source_counter = Counter(str(item.get("structure_source") or "") for item in references)
    rows_raw_count = source_counter.get("rows_raw", 0)
    raw_fallback_count = source_counter.get("raw_reference_fallback", 0)
    inside_bibliography_count = sum(
        1
        for item in references
        if bool((item.get("scores") or {}).get("inside_bibliography_zone"))
    )
    local_anchor_count = sum(1 for item in references if bool(item.get("local_anchor_detected")))
    page_index_count = sum(
        1 for item in references if _safe_int(item.get("page_index")) is not None
    )
    doi_count = sum(1 for item in references if str(item.get("doi") or "").strip())
    accepted_count = sum(
        1
        for item in references
        if bool(
            (item.get("final_decision") or item.get("scores") or {}).get("accepted")
        )
    )

    debug_zone = ((debug_payload or {}).get("phases") or {}).get("bibliography_zone") or {}
    reading_blocks = debug_zone.get("reading_order_blocks") or []
    appendix_contamination_detected = any(
        bool(block.get("accepted"))
        and bool(block.get("section_transition_detected"))
        and float(block.get("bibliography_density") or 0.0) < 0.45
        for block in reading_blocks
        if isinstance(block, dict)
    )

    last_reference = references[-1] if references else {}
    last_reference_text = _first_non_empty_text(
        [
            last_reference.get("text"),
            (last_reference.get("token_reconstruction") or {}).get("final_text"),
        ]
    )
    last_reference_anomalies = (
        last_reference.get("anomalies")
        if isinstance(last_reference.get("anomalies"), dict)
        else {}
    )
    last_segment = None
    segments = debug_zone.get("segments") or []
    if segments:
        last_segment = segments[-1] if isinstance(segments[-1], dict) else None
    last_reference_tail_noise_detected = bool(
        _contains_tail_noise(last_reference_text)
        or bool(last_reference_anomalies.get("tail_trim_applied"))
        or (
            isinstance(last_segment, dict)
            and (
                bool(last_segment.get("tail_trim_applied"))
                or _contains_tail_noise(str(last_segment.get("tail_trim_removed_text") or ""))
            )
        )
    )

    reference_count_mismatch_detected = bool(
        expected_max is not None
        and max_detected is not None
        and max_detected != expected_max
    )
    fallback_rate_high = _round_pct(raw_fallback_count, total) > 15.0

    fail_reasons: List[str] = []
    warn_reasons: List[str] = []
    if total <= 0:
        fail_reasons.append("no_references_serialized")
    if reference_count_mismatch_detected:
        fail_reasons.append("reference_count_mismatch")
    if appendix_contamination_detected and (
        fallback_rate_high
        or _round_pct(inside_bibliography_count, total) < 60.0
    ):
        fail_reasons.append("appendix_contamination")
    elif appendix_contamination_detected:
        warn_reasons.append("appendix_contamination_detected")
    if fallback_rate_high:
        warn_reasons.append("fallback_rate_high")
    if last_reference_tail_noise_detected:
        warn_reasons.append("last_reference_tail_noise_detected")
    if _round_pct(accepted_count, total) < 60.0:
        warn_reasons.append("accepted_rate_low")

    if fail_reasons:
        status = "FAIL"
    elif warn_reasons:
        status = "WARN"
    else:
        status = "OK"

    return {
        "paper_id": str(paper_entry.get("id") or ""),
        "pdf_file": extraction_payload.get("pdf_file"),
        "engine_used": extraction_payload.get("engine_used"),
        "references_total": total,
        "expected_max_reference_index": expected_max,
        "max_reference_index_detected": max_detected,
        "difference_vs_expected": difference_vs_expected,
        "references_numbered": bool(
            (extraction_payload.get("base_reference_stats") or {}).get("references_numbered")
        ),
        "bibliography_start_page": references_data.get("bibliography_start_page"),
        "pct_structured_rows_raw": _round_pct(rows_raw_count, total),
        "pct_raw_reference_fallback": _round_pct(raw_fallback_count, total),
        "pct_inside_bibliography_zone_true": _round_pct(
            inside_bibliography_count,
            total,
        ),
        "pct_local_anchor_detected_true": _round_pct(local_anchor_count, total),
        "pct_references_with_page_index": _round_pct(page_index_count, total),
        "pct_references_with_doi": _round_pct(doi_count, total),
        "pct_accepted": _round_pct(accepted_count, total),
        "last_reference_tail_noise_detected": last_reference_tail_noise_detected,
        "appendix_contamination_detected": appendix_contamination_detected,
        "reference_count_mismatch_detected": reference_count_mismatch_detected,
        "fallback_rate_high": fallback_rate_high,
        "status": status,
        "status_reasons": fail_reasons or warn_reasons,
        "notes": str(paper_entry.get("notes") or ""),
    }


def _build_summary_markdown(
    *,
    run_id: str,
    dataset_path: Path,
    paper_summaries: Sequence[Dict[str, Any]],
    aggregate: Dict[str, Any],
) -> str:
    lines = [
        f"# Reference Regression Summary",
        "",
        f"- Run ID: `{run_id}`",
        f"- Dataset: `{dataset_path}`",
        f"- Total papers: `{aggregate['total_papers']}`",
        f"- OK/WARN/FAIL: `{aggregate['total_ok']}` / `{aggregate['total_warn']}` / `{aggregate['total_fail']}`",
        "",
        "| paper | expected | detected | fallback % | inside bib % | doi % | status | notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in paper_summaries:
        metrics = item.get("metrics") or {}
        lines.append(
            "| {paper} | {expected} | {detected} | {fallback:.2f} | {inside:.2f} | {doi:.2f} | {status} | {notes} |".format(
                paper=metrics.get("paper_id") or "-",
                expected=(
                    metrics.get("expected_max_reference_index")
                    if metrics.get("expected_max_reference_index") is not None
                    else "-"
                ),
                detected=metrics.get("references_total") or 0,
                fallback=float(metrics.get("pct_raw_reference_fallback") or 0.0),
                inside=float(metrics.get("pct_inside_bibliography_zone_true") or 0.0),
                doi=float(metrics.get("pct_references_with_doi") or 0.0),
                status=metrics.get("status") or "FAIL",
                notes=str(metrics.get("notes") or "").replace("|", "/"),
            )
        )
    return "\n".join(lines) + "\n"


def _aggregate_metrics(paper_summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total_papers = len(paper_summaries)
    status_counter = Counter(
        str((item.get("metrics") or {}).get("status") or "FAIL") for item in paper_summaries
    )

    def _avg(metric_name: str) -> float:
        values = [
            float((item.get("metrics") or {}).get(metric_name) or 0.0)
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
        "avg_pct_raw_reference_fallback": _avg("pct_raw_reference_fallback"),
        "avg_pct_inside_bibliography_zone_true": _avg(
            "pct_inside_bibliography_zone_true"
        ),
        "avg_pct_references_with_doi": _avg("pct_references_with_doi"),
        "avg_pct_accepted": _avg("pct_accepted"),
    }


def _run_regression(
    *,
    dataset_path: Path,
    selected_paper_ids: Sequence[str],
    limit: Optional[int],
    output_dir: Path,
    engine: str,
) -> Dict[str, Any]:
    dataset = _load_dataset(dataset_path)
    selected_entries = _filter_dataset(
        dataset,
        paper_ids=selected_paper_ids,
        limit=limit,
    )
    if not selected_entries:
        raise SystemExit("No hay papers seleccionados para ejecutar.")

    per_paper_root = output_dir / "per_paper"
    per_paper_root.mkdir(parents=True, exist_ok=True)

    paper_summaries: List[Dict[str, Any]] = []
    for entry in selected_entries:
        paper_id = str(entry.get("id") or "").strip()
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
            )
            _write_json(paper_dir / "extraction.json", run_output["extraction"])
            _write_json(
                paper_dir / "reference_debug.json",
                run_output["debug"] or {"error": "debug_payload_missing"},
            )
            _write_json(paper_dir / "metrics.json", metrics)
            paper_summary = {
                "paper_id": paper_id,
                "pdf_file": pdf_path.name,
                "status": metrics.get("status"),
                "metrics": metrics,
                "artifacts": {
                    "extraction": str((paper_dir / "extraction.json").relative_to(output_dir)),
                    "reference_debug": str(
                        (paper_dir / "reference_debug.json").relative_to(output_dir)
                    ),
                    "metrics": str((paper_dir / "metrics.json").relative_to(output_dir)),
                },
            }
        except Exception as exc:  # pragma: no cover - regression runner must survive per-paper failures
            metrics = {
                "paper_id": paper_id,
                "pdf_file": pdf_path.name,
                "engine_used": engine,
                "references_total": 0,
                "expected_max_reference_index": _safe_int(
                    entry.get("expected_max_reference_index")
                ),
                "max_reference_index_detected": 0,
                "difference_vs_expected": None,
                "references_numbered": False,
                "bibliography_start_page": None,
                "pct_structured_rows_raw": 0.0,
                "pct_raw_reference_fallback": 0.0,
                "pct_inside_bibliography_zone_true": 0.0,
                "pct_local_anchor_detected_true": 0.0,
                "pct_references_with_page_index": 0.0,
                "pct_references_with_doi": 0.0,
                "pct_accepted": 0.0,
                "last_reference_tail_noise_detected": False,
                "appendix_contamination_detected": False,
                "reference_count_mismatch_detected": True,
                "fallback_rate_high": False,
                "status": "FAIL",
                "status_reasons": ["runner_exception"],
                "notes": str(entry.get("notes") or ""),
                "error": str(exc),
            }
            _write_json(paper_dir / "metrics.json", metrics)
            _write_json(
                paper_dir / "extraction.json",
                {
                    "paper_id": paper_id,
                    "pdf_file": pdf_path.name,
                    "error": str(exc),
                },
            )
            _write_json(
                paper_dir / "reference_debug.json",
                {"paper_id": paper_id, "error": str(exc)},
            )
            paper_summary = {
                "paper_id": paper_id,
                "pdf_file": pdf_path.name,
                "status": "FAIL",
                "metrics": metrics,
                "artifacts": {
                    "extraction": str((paper_dir / "extraction.json").relative_to(output_dir)),
                    "reference_debug": str(
                        (paper_dir / "reference_debug.json").relative_to(output_dir)
                    ),
                    "metrics": str((paper_dir / "metrics.json").relative_to(output_dir)),
                },
            }

        paper_summaries.append(paper_summary)
        print(
            "[{status}] {paper_id}: detected={detected} expected={expected} fallback={fallback:.2f}%".format(
                status=paper_summary.get("status"),
                paper_id=paper_id,
                detected=(paper_summary.get("metrics") or {}).get("references_total") or 0,
                expected=(
                    (paper_summary.get("metrics") or {}).get("expected_max_reference_index")
                    if (paper_summary.get("metrics") or {}).get("expected_max_reference_index") is not None
                    else "-"
                ),
                fallback=float(
                    (paper_summary.get("metrics") or {}).get("pct_raw_reference_fallback")
                    or 0.0
                ),
            )
        )

    aggregate = _aggregate_metrics(paper_summaries)
    run_summary = {
        "run_id": output_dir.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "dataset_root": str(DATASET_DIR),
        "total_papers": aggregate["total_papers"],
        "total_ok": aggregate["total_ok"],
        "total_warn": aggregate["total_warn"],
        "total_fail": aggregate["total_fail"],
        "aggregate_metrics": aggregate,
        "papers": paper_summaries,
    }
    _write_json(output_dir / "summary.json", run_summary)
    _write_text(
        output_dir / "summary.md",
        _build_summary_markdown(
            run_id=output_dir.name,
            dataset_path=dataset_path,
            paper_summaries=paper_summaries,
            aggregate=aggregate,
        ),
    )
    return run_summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Runner de regresion para el extractor de referencias."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Manifest JSON del dataset de regresion.",
    )
    parser.add_argument(
        "--paper-id",
        action="append",
        default=[],
        help="Ejecuta solo uno o varios paper_id del manifest.",
    )
    parser.add_argument(
        "--engine",
        default="papermage",
        choices=["papermage"],
        help="Motor de extraccion a usar.",
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
        args.output_dir
        if args.output_dir is not None
        else DEFAULT_OUTPUT_ROOT / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = _run_regression(
        dataset_path=args.dataset,
        selected_paper_ids=args.paper_id,
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

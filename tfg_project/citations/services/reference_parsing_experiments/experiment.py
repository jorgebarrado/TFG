from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .comparison import build_reference_comparison, summarize_entries
from .input_common import (
    INPUT_BUCKET_ORDER,
    build_common_input,
    discover_all_pdf_paths,
    resolve_pdf_paths,
    write_common_input_artifact,
)
from .runners import run_anystyle_parser, run_llm_parser, run_refextract_parser


DEFAULT_PDFS = [
    "2017-CT-development-computational-thinking_RG.pdf",
    "2023.emnlp-demo.45.pdf",
    "JScientometRes-14-3-838.pdf",
    "Kelemen_Subramanian_19.09.2023.pdf",
]
PARSER_ORDER = ("refextract", "anystyle", "llm")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _merge_status(current: str | None, new_status: str | None) -> str:
    normalized = (new_status or "unknown").strip() or "unknown"
    if not current:
        return normalized
    if current == normalized:
        return current
    return "mixed"


def _build_recommendation(aggregate_summaries: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    refextract = aggregate_summaries.get("refextract", {})
    anystyle = aggregate_summaries.get("anystyle", {})
    llm = aggregate_summaries.get("llm", {})

    if refextract.get("status") == "ok" and refextract.get("title_non_empty", 0) > 0:
        refextract_note = "refextract was the only alternative executed end-to-end in this environment"
    else:
        refextract_note = "refextract could not be validated cleanly"

    if llm.get("status") != "ok":
        llm_note = "LLM wiring is ready but no API execution happened because credentials are missing"
    else:
        llm_note = "LLM execution happened and should be compared directly against refextract"

    if anystyle.get("status") != "ok":
        anystyle_note = "AnyStyle is blocked by the lack of Ruby/anystyle-cli on this machine"
    else:
        anystyle_note = "AnyStyle executed successfully"

    next_candidate = "llm"
    discard_now = "anystyle"
    rationale = (
        f"{refextract_note}; {llm_note}; {anystyle_note}. "
        "For this stack, the most promising next real integration candidate is an LLM parser over already segmented references because it matches the desired architecture, avoids a Ruby dependency, and can return a schema tailored to CiteCheck. "
        "Refextract is useful as a bounded benchmark, but its parsing is biased toward journal-style patterns and required environment-specific shimming. "
        "AnyStyle should be deferred unless you provision a separate Ruby-capable sandbox specifically for it."
    )
    return {
        "next_candidate": next_candidate,
        "discard_now": discard_now,
        "rationale": rationale,
    }


def _build_input_quality_overview(paper_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    bucket_counts = {bucket: 0 for bucket in INPUT_BUCKET_ORDER}
    degraded_papers: List[Dict[str, Any]] = []
    signal_counts = {
        "numeric_noise": 0,
        "likely_fused_references": 0,
        "small_reference_set": 0,
        "low_alpha_or_short_noise": 0,
        "header_not_found_fallback": 0,
    }

    for paper in paper_results:
        input_quality = paper.get("input_quality", {})
        primary_bucket = input_quality.get("primary_bucket", "mixed_issues")
        if primary_bucket not in bucket_counts:
            bucket_counts[primary_bucket] = 0
        bucket_counts[primary_bucket] += 1

        issue_flags = input_quality.get("issue_flags", {})
        for signal_name in signal_counts:
            if issue_flags.get(signal_name):
                signal_counts[signal_name] += 1

        if input_quality.get("degraded_input", primary_bucket != "clean_input"):
            degraded_papers.append(
                {
                    "paper_slug": paper.get("paper_slug"),
                    "pdf_name": paper.get("pdf_name"),
                    "primary_bucket": primary_bucket,
                    "active_issue_buckets": input_quality.get("active_issue_buckets", []),
                    "quality_notes": input_quality.get("quality_notes", []),
                }
            )

    return {
        "total_papers": len(paper_results),
        "bucket_counts": bucket_counts,
        "degraded_paper_count": len(degraded_papers),
        "degraded_papers": degraded_papers,
        "signal_counts": signal_counts,
        "quality_caveat": (
            "Global parser coverage can be misleading when raw reference input is degraded; "
            "consult per-bucket metrics before drawing integration conclusions."
        ),
    }


def _build_paper_input_buckets(
    *,
    run_id: str,
    paper_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = {
        bucket: {
            "paper_count": 0,
            "reference_count_total": 0,
            "papers": [],
        }
        for bucket in INPUT_BUCKET_ORDER
    }
    paper_entries: List[Dict[str, Any]] = []

    for paper in paper_results:
        input_quality = paper.get("input_quality", {})
        primary_bucket = input_quality.get("primary_bucket", "mixed_issues")
        if primary_bucket not in buckets:
            buckets[primary_bucket] = {
                "paper_count": 0,
                "reference_count_total": 0,
                "papers": [],
            }

        paper_entry = {
            "paper_slug": paper.get("paper_slug"),
            "pdf_name": paper.get("pdf_name"),
            "primary_bucket": primary_bucket,
            "active_issue_buckets": input_quality.get("active_issue_buckets", []),
            "reference_count": input_quality.get("reference_count", 0),
            "paper_warnings": paper.get("input_warnings", []),
            "warning_counts": input_quality.get("warning_counts", {}),
            "warning_ratios": input_quality.get("warning_ratios", {}),
            "quality_notes": input_quality.get("quality_notes", []),
        }
        paper_entries.append(paper_entry)
        buckets[primary_bucket]["paper_count"] += 1
        buckets[primary_bucket]["reference_count_total"] += paper_entry["reference_count"]
        buckets[primary_bucket]["papers"].append(paper_entry)

    return {
        "run_id": run_id,
        "bucket_order": INPUT_BUCKET_ORDER,
        "total_papers": len(paper_entries),
        "papers": paper_entries,
        "buckets": buckets,
    }


def _build_aggregate_by_bucket(
    *,
    run_id: str,
    paper_input_buckets: Dict[str, Any],
    bucket_entries: Dict[str, Dict[str, List[Dict[str, Any]]]],
    bucket_notes: Dict[str, Dict[str, List[str]]],
    bucket_statuses: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    bucket_order = list(INPUT_BUCKET_ORDER)
    buckets_payload: Dict[str, Dict[str, Any]] = {}
    non_empty_buckets: List[str] = []

    for bucket in bucket_order:
        bucket_info = paper_input_buckets["buckets"].get(bucket, {})
        paper_count = bucket_info.get("paper_count", 0)
        if paper_count:
            non_empty_buckets.append(bucket)

        parser_summaries: List[Dict[str, Any]] = []
        for parser_name in PARSER_ORDER:
            parser_summaries.append(
                summarize_entries(
                    parser=parser_name,
                    status=bucket_statuses.get(bucket, {}).get(parser_name, "unknown"),
                    entries=bucket_entries.get(bucket, {}).get(parser_name, []),
                    notes=bucket_notes.get(bucket, {}).get(parser_name, []),
                )
            )

        bucket_observations: List[str] = []
        if bucket == "clean_input" and paper_count:
            bucket_observations.append("Baseline bucket with cleaner extracted references.")
        if bucket == "mixed_issues" and paper_count:
            bucket_observations.append(
                "Multiple degradation signals in the same papers; parser coverage in this bucket is especially sensitive to input quality."
            )
        if bucket in {"numeric_noise", "likely_fused_references", "low_alpha_or_short_noise"} and paper_count:
            bucket_observations.append(
                "Coverage drops here should be interpreted primarily as input degradation effects, not only parser capability limits."
            )
        if not paper_count:
            bucket_observations.append("No papers matched this bucket in this run.")

        buckets_payload[bucket] = {
            "paper_count": paper_count,
            "reference_count_total": bucket_info.get("reference_count_total", 0),
            "papers": [paper.get("pdf_name") for paper in bucket_info.get("papers", [])],
            "parser_summaries": parser_summaries,
            "observations": bucket_observations,
        }

    return {
        "run_id": run_id,
        "bucket_order": bucket_order,
        "non_empty_buckets": non_empty_buckets,
        "buckets": buckets_payload,
    }


def _build_aggregate_by_bucket_markdown(aggregate_by_bucket: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Aggregate By Input Bucket")
    lines.append("")
    lines.append(
        "Global metrics can hide parser behavior differences when papers start from degraded reference text. "
        "Use this breakdown to compare parsers per input quality bucket."
    )
    lines.append("")

    for bucket in aggregate_by_bucket.get("bucket_order", []):
        bucket_payload = aggregate_by_bucket.get("buckets", {}).get(bucket, {})
        lines.append(f"## {bucket}")
        lines.append("")
        lines.append(f"- Papers: {bucket_payload.get('paper_count', 0)}")
        lines.append(f"- Total references: {bucket_payload.get('reference_count_total', 0)}")
        paper_names = bucket_payload.get("papers", [])
        lines.append(f"- Papers list: {', '.join(paper_names) if paper_names else '(none)'}")
        observations = bucket_payload.get("observations", [])
        if observations:
            lines.append(f"- Observations: {' | '.join(observations)}")
        lines.append("")
        for parser_summary in bucket_payload.get("parser_summaries", []):
            lines.append(f"### {parser_summary['parser']}")
            lines.append("")
            lines.append(f"- Status: {parser_summary['status']}")
            lines.append(f"- Total references processed: {parser_summary['total_references']}")
            lines.append(f"- Title non-empty: {parser_summary['title_non_empty']}")
            lines.append(f"- Authors non-empty: {parser_summary['authors_non_empty']}")
            lines.append(f"- Year non-empty: {parser_summary['year_non_empty']}")
            lines.append(f"- DOI non-empty: {parser_summary['doi_non_empty']}")
            lines.append(f"- Almost empty: {parser_summary['almost_empty']}")
            parser_observations = parser_summary.get("observations") or []
            if parser_observations:
                lines.append(f"- Parser observations: {' | '.join(parser_observations)}")
            lines.append("")
    return "\n".join(lines)


def _build_summary_markdown(
    *,
    run_id: str,
    config: Dict[str, Any],
    aggregate: Dict[str, Any],
    aggregate_by_bucket: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"# Reference Parser Experiment `{run_id}`")
    lines.append("")
    lines.append("## Config")
    lines.append("")
    lines.append(f"- PDF selection mode: {config.get('pdf_selection_mode')}")
    lines.append(f"- PDFs selected: {config.get('pdf_count')}")
    lines.append(f"- PDFs: {', '.join(config.get('pdf_names_final', []))}")
    lines.append(f"- Comparison limit: {config['comparison_limit']}")
    lines.append(f"- LLM model: {config['llm_model']}")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    for parser_summary in aggregate.get("parser_summaries", []):
        lines.append(f"### {parser_summary['parser']}")
        lines.append("")
        lines.append(f"- Status: {parser_summary['status']}")
        lines.append(f"- Total references processed: {parser_summary['total_references']}")
        lines.append(f"- Title non-empty: {parser_summary['title_non_empty']}")
        lines.append(f"- Authors non-empty: {parser_summary['authors_non_empty']}")
        lines.append(f"- Year non-empty: {parser_summary['year_non_empty']}")
        lines.append(f"- DOI non-empty: {parser_summary['doi_non_empty']}")
        lines.append(f"- Almost empty: {parser_summary['almost_empty']}")
        observations = parser_summary.get("observations") or []
        if observations:
            lines.append(f"- Observations: {' | '.join(observations)}")
        lines.append("")

    quality = aggregate.get("input_quality_overview", {})
    lines.append("## Input Quality Overview")
    lines.append("")
    lines.append(f"- Total papers: {quality.get('total_papers', 0)}")
    lines.append(f"- Degraded papers: {quality.get('degraded_paper_count', 0)}")
    signal_counts = quality.get("signal_counts", {})
    lines.append(f"- Papers with numeric-noise signal: {signal_counts.get('numeric_noise', 0)}")
    lines.append(
        f"- Papers with likely-fused-references signal: {signal_counts.get('likely_fused_references', 0)}"
    )
    lines.append(f"- Caveat: {quality.get('quality_caveat')}")
    lines.append("")
    lines.append("### Papers By Primary Bucket")
    lines.append("")
    bucket_counts = quality.get("bucket_counts", {})
    for bucket in INPUT_BUCKET_ORDER:
        lines.append(f"- {bucket}: {bucket_counts.get(bucket, 0)}")
    lines.append("")

    degraded_papers = quality.get("degraded_papers", [])
    if degraded_papers:
        lines.append("### Papers With Degraded Input")
        lines.append("")
        for paper in degraded_papers:
            lines.append(
                f"- {paper.get('pdf_name')} ({paper.get('primary_bucket')}): "
                f"{', '.join(paper.get('active_issue_buckets', [])) or 'no active tags'}"
            )
        lines.append("")

    lines.append("## Aggregate By Bucket")
    lines.append("")
    for bucket in aggregate_by_bucket.get("bucket_order", []):
        bucket_payload = aggregate_by_bucket.get("buckets", {}).get(bucket, {})
        paper_count = bucket_payload.get("paper_count", 0)
        if not paper_count:
            continue
        lines.append(f"### {bucket}")
        lines.append("")
        lines.append(f"- Papers: {paper_count}")
        lines.append(f"- Total references: {bucket_payload.get('reference_count_total', 0)}")
        lines.append(f"- Papers list: {', '.join(bucket_payload.get('papers', []))}")
        for parser_summary in bucket_payload.get("parser_summaries", []):
            lines.append(
                f"- {parser_summary['parser']}: "
                f"title={parser_summary['title_non_empty']}, "
                f"authors={parser_summary['authors_non_empty']}, "
                f"year={parser_summary['year_non_empty']}, "
                f"doi={parser_summary['doi_non_empty']}, "
                f"almost_empty={parser_summary['almost_empty']}"
            )
        lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    recommendation = aggregate.get("recommendation") or {}
    lines.append(f"- Next candidate: {recommendation.get('next_candidate')}")
    lines.append(f"- Discard now: {recommendation.get('discard_now')}")
    lines.append(f"- Rationale: {recommendation.get('rationale')}")
    lines.append("")
    return "\n".join(lines)


def run_reference_parsing_experiment(
    *,
    pdf_names: Sequence[str] | None = None,
    all_pdfs: bool = False,
    output_root: str | Path = "tmp/reference_parser_experiments",
    run_id: str | None = None,
    comparison_limit: int = 8,
    llm_model: str = "gpt-4.1-mini",
) -> Dict[str, Any]:
    if all_pdfs and pdf_names:
        raise ValueError("Use either --all-pdfs or --pdf, not both.")

    if all_pdfs:
        resolved_paths = discover_all_pdf_paths()
        selected_pdf_names = [path.name for path in resolved_paths]
        pdf_selection_mode = "all_pdfs"
        requested_pdf_names: List[str] = []
    else:
        selected_pdf_names = list(pdf_names or DEFAULT_PDFS)
        resolved_paths = resolve_pdf_paths(selected_pdf_names)
        pdf_selection_mode = "explicit_list" if pdf_names else "default_sample"
        requested_pdf_names = list(pdf_names or [])

    effective_run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(output_root) / effective_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    final_pdf_names = [path.name for path in resolved_paths]
    config = {
        "run_id": effective_run_id,
        "pdf_selection_mode": pdf_selection_mode,
        "all_pdfs": all_pdfs,
        "pdf_names_requested": requested_pdf_names,
        "pdf_names_final": final_pdf_names,
        "pdf_count": len(final_pdf_names),
        "resolved_pdf_paths": [str(path.resolve()) for path in resolved_paths],
        "comparison_limit": comparison_limit,
        "llm_model": llm_model,
        "created_at": datetime.now().isoformat(),
    }
    _write_json(run_dir / "config.json", config)

    paper_results: List[Dict[str, Any]] = []
    aggregate_entries: Dict[str, List[Dict[str, Any]]] = {parser_name: [] for parser_name in PARSER_ORDER}
    aggregate_notes: Dict[str, List[str]] = {parser_name: [] for parser_name in PARSER_ORDER}
    aggregate_statuses: Dict[str, str] = {}
    bucket_entries: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        bucket: {parser_name: [] for parser_name in PARSER_ORDER}
        for bucket in INPUT_BUCKET_ORDER
    }
    bucket_notes: Dict[str, Dict[str, List[str]]] = {
        bucket: {parser_name: [] for parser_name in PARSER_ORDER}
        for bucket in INPUT_BUCKET_ORDER
    }
    bucket_statuses: Dict[str, Dict[str, str]] = {
        bucket: {}
        for bucket in INPUT_BUCKET_ORDER
    }

    for pdf_path in resolved_paths:
        common_input = build_common_input(pdf_path)
        slug = common_input["paper_slug"]
        input_quality = common_input.get("input_quality", {})
        primary_bucket = input_quality.get("primary_bucket", "mixed_issues")
        if primary_bucket not in bucket_entries:
            primary_bucket = "mixed_issues"

        write_common_input_artifact(
            common_input,
            run_dir / "inputs" / f"{slug}_raw_references.json",
        )

        refextract_output = run_refextract_parser(common_input)
        anystyle_output = run_anystyle_parser(common_input)
        llm_output = run_llm_parser(common_input, model=llm_model)

        parser_outputs = {
            "refextract": refextract_output,
            "anystyle": anystyle_output,
            "llm": llm_output,
        }

        _write_json(run_dir / "refextract" / f"{slug}.json", refextract_output)
        _write_json(run_dir / "anystyle" / f"{slug}.json", anystyle_output)
        _write_json(run_dir / "llm" / f"{slug}.json", llm_output)
        _write_text(run_dir / "llm" / f"{slug}_prompt.txt", llm_output.get("prompt_text", ""))
        _write_text(
            run_dir / "llm" / f"{slug}_raw_response.txt",
            llm_output.get("raw_response_text", ""),
        )

        per_parser_summaries: Dict[str, Dict[str, Any]] = {}
        for parser_name, parser_output in parser_outputs.items():
            parser_status = parser_output.get("status", "unknown")
            summary = summarize_entries(
                parser=parser_name,
                status=parser_status,
                entries=parser_output.get("entries", []),
                notes=parser_output.get("notes", []),
            )
            per_parser_summaries[parser_name] = summary
            aggregate_entries[parser_name].extend(parser_output.get("entries", []))
            aggregate_notes[parser_name].extend(summary.get("observations", []))
            aggregate_statuses[parser_name] = _merge_status(
                aggregate_statuses.get(parser_name),
                parser_status,
            )
            bucket_entries[primary_bucket][parser_name].extend(parser_output.get("entries", []))
            bucket_notes[primary_bucket][parser_name].extend(summary.get("observations", []))
            bucket_statuses[primary_bucket][parser_name] = _merge_status(
                bucket_statuses[primary_bucket].get(parser_name),
                parser_status,
            )

        comparison = build_reference_comparison(
            common_input,
            parser_outputs,
            limit=comparison_limit,
        )
        _write_json(run_dir / "comparisons" / f"{slug}.json", comparison)

        paper_result = {
            "paper_slug": slug,
            "pdf_name": common_input["pdf_name"],
            "pdf_path": common_input["pdf_path"],
            "input_warnings": common_input.get("warnings", []),
            "input_quality": input_quality,
            "input_bucket": primary_bucket,
            "extractor_stats": common_input.get("extractor_stats", {}),
            "parser_summaries": per_parser_summaries,
        }
        paper_results.append(paper_result)

    parser_summaries: List[Dict[str, Any]] = []
    aggregate_summary_map: Dict[str, Dict[str, Any]] = {}
    for parser_name in PARSER_ORDER:
        summary = summarize_entries(
            parser=parser_name,
            status=aggregate_statuses.get(parser_name, "unknown"),
            entries=aggregate_entries[parser_name],
            notes=aggregate_notes[parser_name],
        )
        parser_summaries.append(summary)
        aggregate_summary_map[parser_name] = summary

    paper_input_buckets = _build_paper_input_buckets(
        run_id=effective_run_id,
        paper_results=paper_results,
    )
    aggregate_by_bucket = _build_aggregate_by_bucket(
        run_id=effective_run_id,
        paper_input_buckets=paper_input_buckets,
        bucket_entries=bucket_entries,
        bucket_notes=bucket_notes,
        bucket_statuses=bucket_statuses,
    )
    input_quality_overview = _build_input_quality_overview(paper_results)

    aggregate = {
        "run_id": effective_run_id,
        "papers": paper_results,
        "parser_summaries": parser_summaries,
        "input_quality_overview": input_quality_overview,
        "recommendation": _build_recommendation(aggregate_summary_map),
    }
    _write_json(run_dir / "comparisons" / "aggregate.json", aggregate)
    _write_json(run_dir / "comparisons" / "aggregate_by_bucket.json", aggregate_by_bucket)
    _write_json(run_dir / "comparisons" / "paper_input_buckets.json", paper_input_buckets)
    _write_text(
        run_dir / "comparisons" / "aggregate_by_bucket.md",
        _build_aggregate_by_bucket_markdown(aggregate_by_bucket),
    )
    _write_json(run_dir / "summary.json", aggregate)
    _write_text(
        run_dir / "summary.md",
        _build_summary_markdown(
            run_id=effective_run_id,
            config=config,
            aggregate=aggregate,
            aggregate_by_bucket=aggregate_by_bucket,
        ),
    )
    return aggregate

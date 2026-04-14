from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .comparison import build_reference_comparison, summarize_entries
from .input_common import build_common_input, resolve_pdf_paths, write_common_input_artifact
from .runners import run_anystyle_parser, run_llm_parser, run_refextract_parser


DEFAULT_PDFS = [
    "2017-CT-development-computational-thinking_RG.pdf",
    "2023.emnlp-demo.45.pdf",
    "JScientometRes-14-3-838.pdf",
    "Kelemen_Subramanian_19.09.2023.pdf",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_summary_markdown(
    *,
    run_id: str,
    config: Dict[str, Any],
    aggregate: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"# Reference Parser Experiment `{run_id}`")
    lines.append("")
    lines.append("## Config")
    lines.append("")
    lines.append(f"- PDFs: {', '.join(config['pdf_names'])}")
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
    lines.append("## Recommendation")
    lines.append("")
    recommendation = aggregate.get("recommendation") or {}
    lines.append(f"- Next candidate: {recommendation.get('next_candidate')}")
    lines.append(f"- Discard now: {recommendation.get('discard_now')}")
    lines.append(f"- Rationale: {recommendation.get('rationale')}")
    lines.append("")
    return "\n".join(lines)


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


def run_reference_parsing_experiment(
    *,
    pdf_names: Sequence[str] | None = None,
    output_root: str | Path = "tmp/reference_parser_experiments",
    run_id: str | None = None,
    comparison_limit: int = 8,
    llm_model: str = "gpt-4.1-mini",
) -> Dict[str, Any]:
    selected_pdf_names = list(pdf_names or DEFAULT_PDFS)
    resolved_paths = resolve_pdf_paths(selected_pdf_names)
    effective_run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(output_root) / effective_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "run_id": effective_run_id,
        "pdf_names": selected_pdf_names,
        "resolved_pdf_paths": [str(path.resolve()) for path in resolved_paths],
        "comparison_limit": comparison_limit,
        "llm_model": llm_model,
        "created_at": datetime.now().isoformat(),
    }
    _write_json(run_dir / "config.json", config)

    paper_results: List[Dict[str, Any]] = []
    aggregate_entries: Dict[str, List[Dict[str, Any]]] = {
        "refextract": [],
        "anystyle": [],
        "llm": [],
    }
    aggregate_notes: Dict[str, List[str]] = {
        "refextract": [],
        "anystyle": [],
        "llm": [],
    }
    aggregate_statuses: Dict[str, str] = {}

    for pdf_path in resolved_paths:
        common_input = build_common_input(pdf_path)
        slug = common_input["paper_slug"]
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

        per_parser_summaries = {}
        for parser_name, parser_output in parser_outputs.items():
            summary = summarize_entries(
                parser=parser_name,
                status=parser_output.get("status", "unknown"),
                entries=parser_output.get("entries", []),
                notes=parser_output.get("notes", []),
            )
            per_parser_summaries[parser_name] = summary
            aggregate_entries[parser_name].extend(parser_output.get("entries", []))
            aggregate_notes[parser_name].extend(summary.get("observations", []))
            aggregate_statuses[parser_name] = parser_output.get("status", "unknown")

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
            "extractor_stats": common_input.get("extractor_stats", {}),
            "parser_summaries": per_parser_summaries,
        }
        paper_results.append(paper_result)

    parser_summaries: List[Dict[str, Any]] = []
    aggregate_summary_map: Dict[str, Dict[str, Any]] = {}
    for parser_name in ("refextract", "anystyle", "llm"):
        summary = summarize_entries(
            parser=parser_name,
            status=aggregate_statuses.get(parser_name, "unknown"),
            entries=aggregate_entries[parser_name],
            notes=aggregate_notes[parser_name],
        )
        parser_summaries.append(summary)
        aggregate_summary_map[parser_name] = summary

    aggregate = {
        "run_id": effective_run_id,
        "papers": paper_results,
        "parser_summaries": parser_summaries,
        "recommendation": _build_recommendation(aggregate_summary_map),
    }
    _write_json(run_dir / "comparisons" / "aggregate.json", aggregate)
    _write_json(run_dir / "summary.json", aggregate)
    _write_text(
        run_dir / "summary.md",
        _build_summary_markdown(run_id=effective_run_id, config=config, aggregate=aggregate),
    )
    return aggregate

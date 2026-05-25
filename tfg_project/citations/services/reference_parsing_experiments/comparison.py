from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .normalization import clean_text, is_almost_empty


def summarize_entries(
    parser: str, status: str, entries: Iterable[Dict[str, Any]], notes: Iterable[str]
) -> Dict[str, Any]:
    entry_list = list(entries)
    summary = {
        "parser": parser,
        "status": status,
        "total_references": len(entry_list),
        "title_non_empty": 0,
        "authors_non_empty": 0,
        "year_non_empty": 0,
        "doi_non_empty": 0,
        "almost_empty": 0,
        "observations": [clean_text(item) for item in notes if clean_text(item)],
    }
    for entry in entry_list:
        if clean_text(entry.get("title")):
            summary["title_non_empty"] += 1
        if entry.get("authors"):
            summary["authors_non_empty"] += 1
        if entry.get("year"):
            summary["year_non_empty"] += 1
        if clean_text(entry.get("doi")):
            summary["doi_non_empty"] += 1
        if is_almost_empty(entry):
            summary["almost_empty"] += 1

    if status != "ok":
        summary["observations"].append(f"{parser} status: {status}")
    elif summary["title_non_empty"] == 0:
        summary["observations"].append("No structured titles were recovered.")
    elif summary["title_non_empty"] < max(1, len(entry_list) // 3):
        summary["observations"].append("Title coverage is low.")
    if summary["doi_non_empty"] and summary["doi_non_empty"] >= max(
        1, len(entry_list) // 2
    ):
        summary["observations"].append("DOI coverage is relatively strong.")
    if summary["almost_empty"] >= max(1, len(entry_list) // 2):
        summary["observations"].append(
            "A large share of entries remained close to raw text."
        )
    return summary


def build_reference_comparison(
    common_input: Dict[str, Any],
    parser_outputs: Dict[str, Dict[str, Any]],
    *,
    limit: int,
) -> Dict[str, Any]:
    raw_refs = common_input.get("raw_references", [])
    comparison_rows: List[Dict[str, Any]] = []
    for item in raw_refs[:limit]:
        row: Dict[str, Any] = {
            "index": item["index"],
            "raw_input": item["raw_input"],
        }
        for parser_name, parser_output in parser_outputs.items():
            entries = parser_output.get("entries", [])
            matched = next(
                (entry for entry in entries if entry.get("index") == item["index"]),
                None,
            )
            row[parser_name] = matched
        comparison_rows.append(row)
    return {
        "paper_slug": common_input.get("paper_slug"),
        "pdf_name": common_input.get("pdf_name"),
        "rows": comparison_rows,
    }

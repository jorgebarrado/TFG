# Runner experimental de refextract: parsea referencias bibliográficas usando la librería Python refextract.
from __future__ import annotations

import importlib
import sys
import types
from typing import Any, Dict, List

from ..normalization import (
    build_normalized_entry,
    clean_doi,
    clean_text,
    coerce_year,
    first_text,
    normalize_authors,
)


def _import_refextract_api():
    shim_used = False
    try:
        return importlib.import_module("refextract.references.api"), shim_used
    except ImportError as exc:
        if "libmagic" not in str(exc).lower():
            raise
        shim_used = True
        for module_name in (
            "refextract",
            "refextract.references",
            "refextract.references.api",
        ):
            sys.modules.pop(module_name, None)
        magic_stub = types.ModuleType("magic")

        def _unsupported(*args, **kwargs):
            raise RuntimeError(
                "libmagic unavailable; file-based refextract paths are disabled"
            )

        magic_stub.from_file = _unsupported
        sys.modules["magic"] = magic_stub
        return importlib.import_module("refextract.references.api"), shim_used


def _build_refextract_source(raw_input: str, index: int) -> str:
    raw = clean_text(raw_input)
    if not raw:
        return ""
    if raw.startswith("[") or raw[:2].isdigit():
        return raw
    return f"[{index + 1}] {raw}"


def _score_refextract_output(raw_output: Dict[str, Any]) -> int:
    score = 0
    for key in ("author", "journal_title", "year", "doi", "title", "reportnumber"):
        value = raw_output.get(key)
        if isinstance(value, list) and value:
            score += 1
        elif value:
            score += 1
    return score


def _normalize_refextract_record(
    raw_input: str,
    index: int,
    raw_output: Dict[str, Any],
    shim_used: bool,
) -> Dict[str, Any]:
    warnings: List[str] = []
    title = first_text(raw_output.get("title"))
    if not title:
        misc_values = [
            clean_text(item)
            for item in raw_output.get("misc", [])
            if clean_text(item) and len(clean_text(item)) >= 12
        ]
        if misc_values:
            title = misc_values[0]
            warnings.append("title_inferred_from_misc")
    authors = normalize_authors(raw_output.get("author", []))
    year = coerce_year(raw_output.get("year") or raw_output.get("journal_year"))
    doi = None
    doi_values = raw_output.get("doi") or []
    if doi_values:
        doi = clean_doi(doi_values[0])
    venue = first_text(
        raw_output.get("journal_title"), raw_output.get("journal_reference")
    )
    pages = first_text(raw_output.get("journal_page"), raw_output.get("page"))
    identifiers: Dict[str, Any] = {}
    for key in ("reportnumber", "texkey", "isbn", "url", "hdl"):
        if raw_output.get(key):
            identifiers[key] = raw_output.get(key)
    if raw_output.get("linemarker"):
        identifiers["linemarker"] = raw_output.get("linemarker")
    if shim_used:
        warnings.append("refextract_loaded_with_magic_shim_string_mode_only")
    if not title and not authors and not venue and not doi:
        warnings.append("low_structuring_signal")
    entry_type = "journal" if raw_output.get("journal_title") else None
    return build_normalized_entry(
        index=index,
        raw_input=raw_input,
        parser="refextract",
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        pages=pages,
        entry_type=entry_type,
        identifiers=identifiers,
        raw_output=raw_output,
        warnings=warnings,
    )


def run_refextract_parser(common_input: Dict[str, Any]) -> Dict[str, Any]:
    try:
        api, shim_used = _import_refextract_api()
    except Exception as exc:
        return {
            "parser": "refextract",
            "status": "unavailable",
            "availability": {
                "available": False,
                "reason": clean_text(exc),
            },
            "entries": [
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="refextract",
                    raw_output=None,
                    warnings=[f"refextract_unavailable: {clean_text(exc)}"],
                )
                for item in common_input.get("raw_references", [])
            ],
            "notes": [
                "Refextract could not be imported in this environment.",
            ],
        }

    entries: List[Dict[str, Any]] = []
    raw_references = common_input.get("raw_references", [])
    raw_parser_output: List[Any] = []

    for item in raw_references:
        source = _build_refextract_source(item["raw_input"], item["index"])
        try:
            parsed_candidates = api.extract_references_from_string(
                source,
                is_only_references=True,
            )
        except Exception as exc:
            entries.append(
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="refextract",
                    raw_output=None,
                    warnings=[f"refextract_error: {clean_text(exc)}"],
                )
            )
            raw_parser_output.append({"error": clean_text(exc)})
            continue

        parsed_candidates = parsed_candidates or []
        raw_parser_output.append(parsed_candidates)
        selected_output: Dict[str, Any] = {}
        if parsed_candidates:
            selected_output = max(parsed_candidates, key=_score_refextract_output)
        entry = _normalize_refextract_record(
            raw_input=item["raw_input"],
            index=item["index"],
            raw_output=selected_output,
            shim_used=shim_used,
        )
        if not parsed_candidates:
            entry["warnings"].append("refextract_returned_no_candidate")
        elif len(parsed_candidates) > 1:
            entry["warnings"].append(
                f"refextract_multiple_candidates_for_single_input:{len(parsed_candidates)}"
            )
        entry["raw_output"] = parsed_candidates
        entries.append(entry)

    notes = [
        "Executed with refextract string mode over already segmented references.",
    ]
    if shim_used:
        notes.append(
            "Refextract required a local magic shim because libmagic is not installed on this Windows environment."
        )
    multi_candidate_count = sum(
        1
        for entry in entries
        if any(
            warning.startswith("refextract_multiple_candidates_for_single_input:")
            for warning in entry.get("warnings", [])
        )
    )
    if multi_candidate_count:
        notes.append(
            f"Refextract produced multiple candidate parses for {multi_candidate_count} segmented inputs, which usually indicates that the shared extractor fused more than one reference into a single raw string."
        )

    return {
        "parser": "refextract",
        "status": "ok",
        "availability": {
            "available": True,
            "shim_used": shim_used,
            "mode": "string",
        },
        "entries": entries,
        "notes": notes,
        "raw_parser_output": raw_parser_output,
    }

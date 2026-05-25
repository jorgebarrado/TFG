from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ..normalization import (
    build_normalized_entry,
    clean_doi,
    clean_text,
    coerce_year,
    first_text,
    normalize_authors,
)


def _normalize_anystyle_entry(
    raw_input: str,
    index: int,
    raw_output: Dict[str, Any],
) -> Dict[str, Any]:
    warnings: List[str] = []
    authors = normalize_authors(raw_output.get("author", []))
    year = coerce_year(raw_output.get("date"))
    doi = clean_doi(first_text(raw_output.get("doi")))
    venue = first_text(
        raw_output.get("container-title"),
        raw_output.get("journal"),
        raw_output.get("collection-title"),
        raw_output.get("publisher"),
    )
    pages = first_text(raw_output.get("pages"), raw_output.get("page"))
    title = first_text(raw_output.get("title"))
    if not title:
        warnings.append("no_title_from_anystyle")
    identifiers: Dict[str, Any] = {}
    for key in ("isbn", "issn", "url"):
        value = raw_output.get(key)
        if value:
            identifiers[key] = value
    return build_normalized_entry(
        index=index,
        raw_input=raw_input,
        parser="anystyle",
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        pages=pages,
        entry_type=clean_text(raw_output.get("type")) or None,
        identifiers=identifiers,
        raw_output=raw_output,
        warnings=warnings,
    )


def run_anystyle_parser(common_input: Dict[str, Any]) -> Dict[str, Any]:
    command = shutil.which("anystyle")
    raw_references = common_input.get("raw_references", [])
    if not command:
        reason = "anystyle command not found; AnyStyle requires Ruby/anystyle-cli and is not installed in this environment"
        return {
            "parser": "anystyle",
            "status": "unavailable",
            "availability": {
                "available": False,
                "reason": reason,
            },
            "entries": [
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="anystyle",
                    raw_output=None,
                    warnings=[reason],
                )
                for item in raw_references
            ],
            "notes": [
                "AnyStyle was not executed because Ruby/anystyle-cli is absent.",
            ],
        }

    temp_dir = Path(tempfile.mkdtemp(prefix="anystyle_parse_"))
    input_path = temp_dir / "references.txt"
    input_text = "\n".join(
        clean_text(item.get("raw_input"))
        for item in raw_references
        if clean_text(item.get("raw_input"))
    )
    input_path.write_text(input_text, encoding="utf-8")

    try:
        completed = subprocess.run(
            [command, "--stdout", "-f", "json", "parse", str(input_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    finally:
        try:
            input_path.unlink(missing_ok=True)
            temp_dir.rmdir()
        except OSError:
            pass

    stderr_text = clean_text(completed.stderr)
    stdout_text = completed.stdout or ""
    if completed.returncode != 0:
        reason = stderr_text or f"anystyle exited with code {completed.returncode}"
        return {
            "parser": "anystyle",
            "status": "error",
            "availability": {
                "available": True,
                "command": command,
            },
            "entries": [
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="anystyle",
                    raw_output=None,
                    warnings=[reason],
                )
                for item in raw_references
            ],
            "notes": [
                "AnyStyle execution failed.",
            ],
            "stderr": stderr_text,
        }

    parsed = json.loads(stdout_text or "[]")
    entries: List[Dict[str, Any]] = []
    count_mismatch = len(parsed) != len(raw_references)
    for position, item in enumerate(raw_references):
        raw_output = parsed[position] if position < len(parsed) else {}
        entry = _normalize_anystyle_entry(
            raw_input=item["raw_input"],
            index=item["index"],
            raw_output=raw_output,
        )
        if count_mismatch:
            entry["warnings"].append("parsed_count_mismatch_with_input")
        entries.append(entry)

    notes = ["Executed via `anystyle parse` over one-reference-per-line input."]
    if stderr_text:
        notes.append(f"AnyStyle stderr: {stderr_text}")
    if count_mismatch:
        notes.append(
            f"AnyStyle returned {len(parsed)} records for {len(raw_references)} inputs."
        )

    return {
        "parser": "anystyle",
        "status": "ok",
        "availability": {
            "available": True,
            "command": command,
        },
        "entries": entries,
        "notes": notes,
        "raw_parser_output": parsed,
        "stderr": stderr_text,
    }

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Tuple

from ..normalization import build_normalized_entry, clean_doi, clean_text, coerce_year


def _build_prompt(common_input: Dict[str, Any]) -> str:
    pdf_name = common_input.get("pdf_name")
    refs = common_input.get("raw_references", [])
    lines = [
        "You are parsing already-segmented bibliographic references.",
        "Return JSON only. No markdown. No commentary.",
        "Output must be a JSON array with exactly one object per input reference in the same order.",
        "Each object must use this schema:",
        '{"index": <integer>, "raw_input": <string>, "title": <string|null>, "authors": <array of strings>, "year": <integer|null>, "doi": <string|null>, "venue": <string|null>, "pages": <string|null>, "type": <string|null>, "identifiers": <object>, "confidence": <number|null>, "notes": <array of strings>}',
        "Rules:",
        "- Do not invent data.",
        "- If a field is unclear, use null or an empty array/object.",
        "- Keep the DOI normalized without URL prefixes if present.",
        "- raw_input must exactly match the input string.",
        "- index must exactly match the provided index.",
        "- authors must contain plain strings, not objects.",
        "",
        f"PDF source: {pdf_name}",
        "References:",
    ]
    for item in refs:
        lines.append(f"{item['index']}: {item['raw_input']}")
    return "\n".join(lines)


def _validate_llm_json(
    parsed: Any,
    raw_references: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    if not isinstance(parsed, list):
        raise ValueError("LLM output is not a JSON array")
    raw_reference_list = list(raw_references)
    if len(parsed) != len(raw_reference_list):
        warnings.append(
            f"llm_output_length_mismatch: expected {len(raw_reference_list)} got {len(parsed)}"
        )

    normalized_entries: List[Dict[str, Any]] = []
    for position, item in enumerate(raw_reference_list):
        candidate = parsed[position] if position < len(parsed) else {}
        if not isinstance(candidate, dict):
            candidate = {}
        entry_warnings = list(candidate.get("notes") or [])
        if candidate.get("index") != item["index"]:
            entry_warnings.append("index_mismatch_in_llm_output")
        if clean_text(candidate.get("raw_input")) != item["raw_input"]:
            entry_warnings.append("raw_input_mismatch_in_llm_output")
        normalized_entries.append(
            build_normalized_entry(
                index=item["index"],
                raw_input=item["raw_input"],
                parser="llm",
                title=clean_text(candidate.get("title")) or None,
                authors=[
                    clean_text(author)
                    for author in (candidate.get("authors") or [])
                    if clean_text(author)
                ],
                year=coerce_year(candidate.get("year")),
                doi=clean_doi(candidate.get("doi")),
                venue=clean_text(candidate.get("venue")) or None,
                pages=clean_text(candidate.get("pages")) or None,
                entry_type=clean_text(candidate.get("type")) or None,
                identifiers=(
                    candidate.get("identifiers")
                    if isinstance(candidate.get("identifiers"), dict)
                    else {}
                ),
                raw_output=candidate,
                warnings=entry_warnings,
                confidence=(
                    float(candidate["confidence"])
                    if isinstance(candidate.get("confidence"), (int, float))
                    else None
                ),
            )
        )
    return normalized_entries, warnings


def _call_openai_chat(prompt: str, model: str, api_key: str) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        OpenAI = None

    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    import openai  # type: ignore

    openai.api_key = api_key
    response = openai.ChatCompletion.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
    )
    return response["choices"][0]["message"]["content"] or ""


def run_llm_parser(common_input: Dict[str, Any], *, model: str) -> Dict[str, Any]:
    prompt = _build_prompt(common_input)
    raw_references = common_input.get("raw_references", [])
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        reason = "OPENAI_API_KEY is not set; LLM parser was wired but not executed"
        return {
            "parser": "llm",
            "status": "unavailable",
            "availability": {
                "available": False,
                "reason": reason,
                "model": model,
            },
            "entries": [
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="llm",
                    raw_output=None,
                    warnings=[reason],
                )
                for item in raw_references
            ],
            "notes": [
                "LLM prompt was generated but no API call was made.",
            ],
            "prompt_text": prompt,
            "raw_response_text": reason,
        }

    try:
        raw_response_text = _call_openai_chat(
            prompt=prompt, model=model, api_key=api_key
        )
        parsed = json.loads(raw_response_text)
        entries, validation_warnings = _validate_llm_json(parsed, raw_references)
        notes = [
            "Executed over already segmented references with a strict JSON-only prompt."
        ]
        notes.extend(validation_warnings)
        return {
            "parser": "llm",
            "status": "ok",
            "availability": {
                "available": True,
                "model": model,
            },
            "entries": entries,
            "notes": notes,
            "prompt_text": prompt,
            "raw_response_text": raw_response_text,
            "raw_parser_output": parsed,
        }
    except Exception as exc:
        reason = clean_text(exc)
        return {
            "parser": "llm",
            "status": "error",
            "availability": {
                "available": True,
                "model": model,
            },
            "entries": [
                build_normalized_entry(
                    index=item["index"],
                    raw_input=item["raw_input"],
                    parser="llm",
                    raw_output=None,
                    warnings=[f"llm_error: {reason}"],
                )
                for item in raw_references
            ],
            "notes": [
                "LLM call failed.",
            ],
            "prompt_text": prompt,
            "raw_response_text": reason,
        }

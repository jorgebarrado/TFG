"""Helpers for report evidence stored in IncorrectCitation.citation_contexts."""

from __future__ import annotations

import json
from typing import Any

SOURCE_LABELS = {
    "semantic_scholar": "Semantic Scholar",
    "pdf_extractor": "PDF",
    "reader_selection": "PDF",
    "manual": "Manual",
}

ARTICLE_LABELS = {
    "original": "Artículo original",
    "citing": "Artículo citante",
    "incorrect": "Artículo citante",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _coerce_boxes(item: dict[str, Any]) -> list:
    boxes = item.get("boxes")
    if isinstance(boxes, list):
        return boxes
    box = item.get("box")
    if isinstance(box, list):
        return [box]
    return []


def _parse_raw_value(raw_value: Any) -> Any:
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, str):
        raw_value = raw_value.strip()
        if not raw_value:
            return []
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value
    return raw_value


def _text_from_item(item: dict[str, Any]) -> str:
    for key in ("text", "paragraph", "snippet", "context", "quote"):
        text = _clean_text(item.get(key))
        if text:
            return text
    return ""


def _kind_for_source(source: str, fallback: str) -> str:
    if fallback:
        return fallback
    if source == "semantic_scholar":
        return "citation_context"
    if source == "reader_selection":
        return "pdf_selection"
    if source == "manual":
        return "manual_text"
    if source == "pdf_extractor":
        return "pdf_extracted_context"
    return "evidence"


def normalize_evidence_items(
    raw_value: Any,
    *,
    default_source: str = "",
    default_article: str = "citing",
    default_kind: str = "",
    default_doi: str = "",
) -> list[dict[str, Any]]:
    """
    Normalize legacy paragraph/context payloads into evidence objects.

    Accepts JSON strings, plain text, lists, dicts, and old extractor rows with
    paragraph/snippet fields. Empty text items are ignored.
    """
    parsed = _parse_raw_value(raw_value)
    if parsed in (None, ""):
        return []

    if isinstance(parsed, dict):
        items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = [parsed]

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in items:
        if isinstance(item, str):
            text = _clean_text(item)
            source = default_source or "manual"
            evidence = {
                "source": source,
                "article": default_article,
                "kind": _kind_for_source(source, default_kind),
                "text": text,
                "page": None,
            }
            if default_doi:
                evidence["doi"] = default_doi
        elif isinstance(item, dict):
            text = _text_from_item(item)
            source = _clean_text(item.get("source")) or default_source
            if not source:
                source = (
                    "pdf_extractor"
                    if (item.get("paragraph") or item.get("snippet"))
                    else "manual"
                )
            kind = _clean_text(item.get("kind")) or _kind_for_source(
                source, default_kind
            )
            article = _clean_text(item.get("article")) or default_article
            evidence = {
                "source": source,
                "article": article,
                "kind": kind,
                "text": text,
                "page": _coerce_page(item.get("page")),
            }
            boxes = _coerce_boxes(item)
            if boxes:
                evidence["boxes"] = boxes
            doi = _clean_text(item.get("doi")) or default_doi
            if doi:
                evidence["doi"] = doi
            for key in (
                "title",
                "pattern",
                "confidence",
                "citation_numbers",
                "citation_block",
                "start",
                "end",
            ):
                if item.get(key) not in (None, "", []):
                    evidence[key] = item.get(key)
        else:
            continue

        if not evidence.get("text"):
            continue
        dedupe_key = (
            str(evidence.get("source") or ""),
            str(evidence.get("page") or ""),
            " ".join(str(evidence.get("text") or "").split()).lower(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(evidence)

    return normalized


def evidence_source_label(source: str) -> str:
    return SOURCE_LABELS.get(str(source or "").strip(), str(source or "Evidencia"))


def evidence_article_label(article: str) -> str:
    return ARTICLE_LABELS.get(str(article or "").strip(), str(article or ""))

"""Helpers to handle multi-tag report classification without schema changes."""

from __future__ import annotations

from typing import Iterable

from ..models import AREA_CHOICES, IncorrectCitation

CITATION_TYPE_CHOICES = tuple(
    IncorrectCitation._meta.get_field("citation_type").choices
)
CITATION_TYPE_LABELS = {
    str(value): str(label) for value, label in CITATION_TYPE_CHOICES
}
PUBLICATION_AREA_LABELS = {str(value): str(label) for value, label in AREA_CHOICES}


def normalize_tag_values(
    values: Iterable[str] | None,
    allowed_labels: dict[str, str],
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        value = str(raw or "").strip()
        if not value or value not in allowed_labels or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def extract_report_tag_values(
    citation: IncorrectCitation,
) -> tuple[list[str], list[str]]:
    metadata = (
        citation.metadata_original
        if isinstance(citation.metadata_original, dict)
        else {}
    )
    type_values = normalize_tag_values(
        metadata.get("citation_type_tags"), CITATION_TYPE_LABELS
    )
    area_values = normalize_tag_values(
        metadata.get("publication_area_tags"), PUBLICATION_AREA_LABELS
    )

    if (
        not type_values
        and str(citation.citation_type or "").strip() in CITATION_TYPE_LABELS
    ):
        type_values = [citation.citation_type]
    if (
        not area_values
        and str(citation.publication_area or "").strip() in PUBLICATION_AREA_LABELS
    ):
        area_values = [citation.publication_area]

    return type_values, area_values


def extract_report_tag_labels(
    citation: IncorrectCitation,
) -> tuple[list[str], list[str]]:
    type_values, area_values = extract_report_tag_values(citation)
    type_labels = [
        CITATION_TYPE_LABELS[value]
        for value in type_values
        if value in CITATION_TYPE_LABELS
    ]
    area_labels = [
        PUBLICATION_AREA_LABELS[value]
        for value in area_values
        if value in PUBLICATION_AREA_LABELS
    ]
    return type_labels, area_labels


def apply_report_tags(
    citation: IncorrectCitation,
    citation_type_values: Iterable[str] | None,
    publication_area_values: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    type_values = normalize_tag_values(citation_type_values, CITATION_TYPE_LABELS)
    area_values = normalize_tag_values(publication_area_values, PUBLICATION_AREA_LABELS)

    metadata = (
        citation.metadata_original
        if isinstance(citation.metadata_original, dict)
        else {}
    )
    metadata = dict(metadata)
    metadata["citation_type_tags"] = type_values
    metadata["publication_area_tags"] = area_values
    citation.metadata_original = metadata

    if type_values:
        citation.citation_type = type_values[0]
    if area_values:
        citation.publication_area = area_values[0]

    return type_values, area_values

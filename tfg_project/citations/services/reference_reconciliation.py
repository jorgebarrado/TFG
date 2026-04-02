from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Sequence, Tuple

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
WORD_RE = re.compile(r"[a-z0-9]{3,}")
NUMBERED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")

TITLE_STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "using",
    "between",
    "towards",
    "about",
    "over",
    "under",
    "through",
    "analysis",
    "study",
    "approach",
    "method",
    "methods",
    "model",
    "models",
    "paper",
    "proceedings",
    "international",
    "conference",
    "journal",
    "system",
    "systems",
    "based",
}


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def normalize_doi(raw_doi: Any) -> str:
    value = str(raw_doi or "").strip()
    if not value:
        return ""
    value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
    url_match = DOI_URL_REGEX.search(value)
    if url_match:
        value = url_match.group(1)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    value = value.rstrip(").,;:]").strip().lower()
    return value


def extract_year(value: Any) -> Optional[int]:
    if isinstance(value, int) and 1500 <= value <= 2100:
        return value
    match = YEAR_RE.search(str(value or ""))
    if not match:
        return None
    try:
        parsed = int(match.group(0))
    except ValueError:
        return None
    return parsed if 1500 <= parsed <= 2100 else None


def _text_tokens(value: Any, *, min_len: int = 3) -> set[str]:
    if min_len <= 3:
        return set(WORD_RE.findall(normalize_text(value)))
    return {
        token
        for token in re.findall(rf"[a-z0-9]{{{int(min_len)},}}", normalize_text(value))
        if token
    }


def _strong_title_tokens(value: Any) -> set[str]:
    tokens = _text_tokens(value, min_len=4)
    return {
        token
        for token in tokens
        if token not in TITLE_STOPWORDS and not token.isdigit()
    }


def _author_surnames(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    surnames: set[str] = set()
    for author in value:
        parts = re.findall(r"[A-Za-z]{3,}", str(author or "").lower())
        if not parts:
            continue
        surnames.add(parts[-1])
    return surnames


def _extract_dois_from_text(value: str) -> set[str]:
    if not value:
        return set()
    dois: set[str] = set()
    for url_match in DOI_URL_REGEX.finditer(value):
        normalized = normalize_doi(url_match.group(1))
        if normalized:
            dois.add(normalized)
    for match in DOI_REGEX.finditer(value):
        normalized = normalize_doi(match.group(0))
        if normalized:
            dois.add(normalized)
    return dois


def _round3(value: float) -> float:
    return round(max(0.0, min(float(value), 1.0)), 3)


def _coerce_expected_index(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def validate_reference_against_metadata(
    local_rows_text: str,
    metadata: Optional[Dict[str, Any]],
    *,
    expected_index: Optional[int] = None,
    other_metadata_candidates: Sequence[Tuple[int, Dict[str, Any]]] = (),
) -> Dict[str, Any]:
    text = re.sub(r"\s+", " ", str(local_rows_text or "")).strip()
    if not text:
        return {
            "match_score": 0.0,
            "mixed_reference_score": 1.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": "empty_local_text",
        }

    metadata = metadata if isinstance(metadata, dict) else {}
    expected = _coerce_expected_index(expected_index)
    local_norm = normalize_text(text)
    local_tokens = _text_tokens(local_norm, min_len=4)

    candidate_doi = normalize_doi(metadata.get("doi"))
    candidate_title = str(metadata.get("title") or metadata.get("raw_text") or "").strip()
    candidate_authors = metadata.get("authors")
    candidate_year = extract_year(metadata.get("year"))
    candidate_venue = str(metadata.get("venue") or "").strip()

    weighted_score = 0.0
    total_weight = 0.0

    doi_match = False
    title_score = 0.0
    author_score = 0.0
    year_score = 0.0
    venue_score = 0.0

    local_dois = _extract_dois_from_text(text)
    if candidate_doi:
        total_weight += 0.42
        if candidate_doi in local_dois:
            doi_match = True
            weighted_score += 0.42

    if candidate_title:
        total_weight += 0.28
        title_tokens = _strong_title_tokens(candidate_title)
        if title_tokens and local_tokens:
            title_overlap = len(local_tokens.intersection(title_tokens)) / max(
                len(title_tokens),
                1,
            )
        else:
            title_overlap = 0.0
        seq_ratio = SequenceMatcher(
            None,
            local_norm[:500],
            normalize_text(candidate_title)[:360],
        ).ratio()
        title_score = max(title_overlap, seq_ratio * 0.85)
        weighted_score += 0.28 * max(0.0, min(title_score, 1.0))

    author_surnames = _author_surnames(candidate_authors)
    if author_surnames:
        total_weight += 0.16
        local_author_tokens = {
            token
            for token in re.findall(r"[a-z]{3,}", local_norm.split(".")[0])
            if token
        }
        if local_author_tokens:
            author_score = len(local_author_tokens.intersection(author_surnames)) / max(
                len(author_surnames),
                1,
            )
            weighted_score += 0.16 * max(0.0, min(author_score, 1.0))

    if candidate_year:
        total_weight += 0.08
        year_mentions = {int(value.group(0)) for value in YEAR_RE.finditer(text)}
        if candidate_year in year_mentions:
            year_score = 1.0
        elif (candidate_year - 1) in year_mentions or (candidate_year + 1) in year_mentions:
            year_score = 0.4
        weighted_score += 0.08 * year_score

    if candidate_venue:
        total_weight += 0.06
        venue_tokens = _strong_title_tokens(candidate_venue)
        if venue_tokens and local_tokens:
            venue_score = len(local_tokens.intersection(venue_tokens)) / max(
                len(venue_tokens),
                1,
            )
            weighted_score += 0.06 * max(0.0, min(venue_score, 1.0))

    match_score = weighted_score / total_weight if total_weight > 0 else 0.0

    anchors = [
        int(match.group(1))
        for match in NUMBERED_ANCHOR_RE.finditer(text)
        if match.group(1).isdigit()
    ]
    foreign_anchors = [value for value in anchors if expected is None or value != expected]
    has_nested_anchor = len(foreign_anchors) > 0

    mixed_score = 0.0
    if has_nested_anchor:
        mixed_score += 0.55 + min(0.15, 0.05 * len(foreign_anchors))

    if candidate_doi and local_dois:
        if candidate_doi not in local_dois:
            mixed_score += 0.35
        elif len({doi for doi in local_dois if doi != candidate_doi}) > 0:
            mixed_score += 0.2

    all_years = sorted({int(match.group(0)) for match in YEAR_RE.finditer(text)})
    if len(all_years) >= 3:
        mixed_score += 0.15

    if candidate_title and title_score < 0.2:
        mixed_score += 0.12
    if author_surnames and author_score < 0.15:
        mixed_score += 0.08
    if candidate_year and year_score <= 0.0:
        mixed_score += 0.07
    if candidate_venue and venue_score < 0.12:
        mixed_score += 0.05

    best_foreign_overlap = 0.0
    for foreign_index, foreign_meta in other_metadata_candidates:
        if expected is not None and int(foreign_index) == expected:
            continue
        if not isinstance(foreign_meta, dict):
            continue
        foreign_title_tokens = _strong_title_tokens(foreign_meta.get("title") or "")
        if len(foreign_title_tokens) < 3 or not local_tokens:
            continue
        overlap = len(local_tokens.intersection(foreign_title_tokens)) / max(
            len(foreign_title_tokens),
            1,
        )
        if overlap > best_foreign_overlap:
            best_foreign_overlap = overlap
    if best_foreign_overlap >= 0.45:
        mixed_score += 0.2 + min(0.2, (best_foreign_overlap - 0.45))

    mixed_score = max(0.0, min(mixed_score, 1.0))

    accepted = False
    reason: Optional[str] = None
    if total_weight <= 0:
        accepted = not has_nested_anchor
        if not accepted:
            reason = "mixed_rows_multiple_references"
    elif has_nested_anchor and not doi_match:
        accepted = False
        reason = "mixed_rows_multiple_references"
    elif mixed_score >= 0.68:
        accepted = False
        reason = "mixed_rows_multiple_references"
    elif match_score >= 0.72 and mixed_score < 0.55:
        accepted = True
    elif doi_match and match_score >= 0.52 and mixed_score < 0.5:
        accepted = True
    elif title_score >= 0.66 and mixed_score < 0.45:
        accepted = True
    else:
        accepted = False
        reason = "metadata_mismatch"

    return {
        "match_score": _round3(match_score),
        "mixed_reference_score": _round3(mixed_score),
        "has_nested_anchor": bool(has_nested_anchor),
        "accepted": bool(accepted),
        "reason": reason,
    }

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Sequence, Tuple

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
WORD_RE = re.compile(r"[a-z0-9]{3,}")
NUMBERED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")
NON_BIBLIOGRAPHIC_PHRASES = (
    "view publication stats",
    "downloaded from",
    "researchgate",
    "copyright",
    "received:",
    "accepted:",
    "published online",
    "correspondence:",
    "funding:",
    "license",
)

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


def _doi_matches(candidate: str, observed: str) -> bool:
    left = normalize_doi(candidate)
    right = normalize_doi(observed)
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 12:
        return False
    return left.startswith(right) or right.startswith(left)


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
    candidate_title = str(
        metadata.get("title") or metadata.get("raw_text") or ""
    ).strip()
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
        if any(_doi_matches(candidate_doi, local_doi) for local_doi in local_dois):
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
        elif (candidate_year - 1) in year_mentions or (
            candidate_year + 1
        ) in year_mentions:
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
    foreign_anchors = [
        value for value in anchors if expected is None or value != expected
    ]
    has_nested_anchor = len(foreign_anchors) > 0

    mixed_score = 0.0
    if has_nested_anchor:
        mixed_score += 0.55 + min(0.15, 0.05 * len(foreign_anchors))

    if candidate_doi and local_dois:
        if not any(_doi_matches(candidate_doi, local_doi) for local_doi in local_dois):
            mixed_score += 0.35
        elif (
            len({doi for doi in local_dois if not _doi_matches(candidate_doi, doi)}) > 0
        ):
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


def _reference_index(entry: Dict[str, Any]) -> Optional[int]:
    for key in ("index", "ref_index", "number"):
        parsed = _coerce_expected_index(entry.get(key))
        if parsed is not None:
            return parsed
    raw_id = str(entry.get("id") or entry.get("ref_id") or "").strip()
    match = re.search(r"(\d+)$", raw_id)
    if not match:
        return None
    return _coerce_expected_index(match.group(1))


def _reference_text(entry: Dict[str, Any]) -> str:
    for key in ("text", "raw", "raw_text"):
        text = re.sub(r"\s+", " ", str(entry.get(key) or "")).strip()
        if text:
            return text
    return ""


def _is_fallback_source(entry: Dict[str, Any]) -> bool:
    return "fallback" in str(entry.get("structure_source") or "").lower()


def _validation_accepted(entry: Dict[str, Any]) -> Optional[bool]:
    validation = entry.get("reference_validation")
    if not isinstance(validation, dict):
        return None
    accepted = validation.get("accepted")
    return accepted if isinstance(accepted, bool) else None


def _index_diagnostics(
    entries: Sequence[Dict[str, Any]],
    *,
    expected_max_index: Optional[int] = None,
) -> Dict[str, Any]:
    indices = [
        index
        for entry in entries
        if isinstance(entry, dict)
        for index in [_reference_index(entry)]
        if index is not None and index > 0
    ]
    counts: Dict[int, int] = {}
    for index in indices:
        counts[index] = counts.get(index, 0) + 1
    unique_indices = sorted(counts)
    upper_bound = (
        expected_max_index
        if expected_max_index is not None and expected_max_index > 0
        else (max(unique_indices) if unique_indices else 0)
    )
    return {
        "indexed_count": len(indices),
        "unique_count": len(unique_indices),
        "unlabeled_count": len(entries) - len(indices),
        "duplicate_indices": [
            index for index, count in sorted(counts.items()) if count > 1
        ],
        "missing_indices": [
            index for index in range(1, upper_bound + 1) if index not in counts
        ],
        "max_index": max(unique_indices) if unique_indices else 0,
    }


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def _citation_style_from_base(base_stats: Dict[str, Any]) -> str:
    style = str(base_stats.get("citation_style") or "").strip().lower()
    if style in {"numeric", "non_numeric", "non-numeric"}:
        return "non_numeric" if style == "non-numeric" else style
    return "numeric" if base_stats.get("references_numbered") else "non_numeric"


def _max_index_from_stats(stats: Dict[str, Any], fallback: int = 0) -> int:
    for key in ("max_reference_index", "references_total"):
        parsed = _coerce_expected_index(stats.get(key))
        if parsed is not None:
            return parsed
    return int(fallback or 0)


def _structured_reference_is_usable(entry: Dict[str, Any]) -> bool:
    if not _reference_text(entry):
        return False
    if _is_fallback_source(entry):
        return False
    return True


def _candidate_score(entry: Dict[str, Any]) -> Tuple[int, int, int]:
    accepted = _validation_accepted(entry)
    text_len = len(_reference_text(entry))
    return (
        1 if not _is_fallback_source(entry) else 0,
        1 if accepted is True else 0,
        text_len,
    )


def _dedupe_numbered_entries(
    entries: Sequence[Dict[str, Any]],
    *,
    numbered: bool,
) -> list[Dict[str, Any]]:
    if not numbered:
        return [entry for entry in entries if isinstance(entry, dict)]

    by_index: Dict[int, Dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index = _reference_index(entry)
        if index is None or index <= 0:
            continue
        current = by_index.get(index)
        if current is None or _candidate_score(entry) > _candidate_score(current):
            by_index[index] = entry
    return [by_index[index] for index in sorted(by_index)]


def _local_reference_from_structured(entry: Dict[str, Any]) -> Dict[str, Any]:
    text = _reference_text(entry)
    doi = normalize_doi(entry.get("doi"))
    index = _reference_index(entry)
    return {
        "index": index,
        "raw": text,
        "doi": doi or None,
        "doi_source": "regex" if doi else None,
        "confidence": 1.0 if text else 0.0,
        "numbered": bool(index),
        "structure_source": str(entry.get("structure_source") or "").strip() or None,
    }


def _local_reference_from_base(entry: Dict[str, Any]) -> Dict[str, Any]:
    text = _reference_text(entry)
    doi = normalize_doi(entry.get("doi"))
    index = _reference_index(entry)
    return {
        "index": index,
        "raw": text,
        "doi": doi or None,
        "doi_source": entry.get("doi_source") or ("regex" if doi else None),
        "confidence": float(entry.get("confidence") or (1.0 if text else 0.0)),
        "numbered": bool(entry.get("numbered") or index),
        "structure_source": "base_reconciled",
    }


def _structured_reference_from_base(entry: Dict[str, Any]) -> Dict[str, Any]:
    index = _reference_index(entry)
    text = _reference_text(entry)
    doi = normalize_doi(entry.get("doi"))
    return {
        "id": f"ref-{index}" if index is not None else None,
        "ref_id": f"ref-{index}" if index is not None else None,
        "index": index,
        "text": text,
        "doi": doi or "",
        "structure_source": "base_reconciled",
        "reference_validation": {
            "accepted": True,
            "reason": "base_selected_by_reconciliation",
        },
    }


def _local_reference_from_base_rescue(entry: Dict[str, Any]) -> Dict[str, Any]:
    rescued = _local_reference_from_base(entry)
    rescued["structure_source"] = "base_rescue"
    return rescued


def _structured_reference_from_base_rescue(entry: Dict[str, Any]) -> Dict[str, Any]:
    rescued = _structured_reference_from_base(entry)
    rescued["structure_source"] = "base_rescue"
    rescued["reference_validation"] = {
        "accepted": True,
        "reason": "rescued_from_base",
    }
    return rescued


def _has_bibliographic_signal(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return bool(
        _extract_dois_from_text(text)
        or extract_year(text)
        or " et al" in normalized
        or normalized.count(",") >= 2
        or ("." in normalized and "," in normalized)
    )


def _foreign_bracketed_anchor_reason(text: str, expected_index: int) -> Optional[str]:
    anchors = [
        int(match.group(1))
        for match in NUMBERED_ANCHOR_RE.finditer(str(text or ""))
        if match.group(1).isdigit()
    ]
    foreign = [index for index in anchors if index != expected_index]
    return "mixed_anchors" if foreign else None


def _existing_reference_dois(entries: Sequence[Dict[str, Any]]) -> set[str]:
    dois: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        doi = normalize_doi(entry.get("doi"))
        if doi:
            dois.add(doi)
    return dois


def _existing_reference_texts(entries: Sequence[Dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = normalize_text(_reference_text(entry))
        if text:
            texts.append(text)
    return texts


def _duplicate_rescue_reason(
    candidate: Dict[str, Any],
    *,
    existing_dois: set[str],
    existing_texts: Sequence[str],
) -> Optional[str]:
    doi = normalize_doi(candidate.get("doi"))
    if doi and doi in existing_dois:
        return "duplicates_existing_doi"
    normalized = normalize_text(_reference_text(candidate))
    if not normalized:
        return None
    for existing_text in existing_texts:
        if SequenceMatcher(None, normalized[:700], existing_text[:700]).ratio() >= 0.94:
            return "duplicates_existing_text"
    return None


def _rescue_rejection_reason(
    candidate: Dict[str, Any],
    *,
    expected_index: int,
    source: str,
    existing_dois: set[str],
    existing_texts: Sequence[str],
) -> Optional[str]:
    text = _reference_text(candidate)
    if not text:
        return "empty_text"
    if source == "structured_discarded" and _is_fallback_source(candidate):
        return "fallback_candidate_rejected"
    lowered = text.lower()
    if any(phrase in lowered for phrase in NON_BIBLIOGRAPHIC_PHRASES):
        return "non_bibliographic_phrase"
    if len(text) < 25 and not normalize_doi(candidate.get("doi")):
        return "very_short"
    anchor_reason = _foreign_bracketed_anchor_reason(text, expected_index)
    if anchor_reason:
        return anchor_reason
    if not _has_bibliographic_signal(text):
        return "weak_bibliographic_signal"
    return _duplicate_rescue_reason(
        candidate,
        existing_dois=existing_dois,
        existing_texts=existing_texts,
    )


def _reasonable_rescue_candidates(
    candidates: Sequence[Dict[str, Any]],
    *,
    expected_index: int,
    source: str,
    existing_dois: set[str],
    existing_texts: Sequence[str],
) -> list[Dict[str, Any]]:
    reasonable: list[Dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _rescue_rejection_reason(
            candidate,
            expected_index=expected_index,
            source=source,
            existing_dois=existing_dois,
            existing_texts=existing_texts,
        ):
            continue
        reasonable.append(candidate)
    return reasonable


def _rescue_missing_numeric_indices(
    *,
    final_references: list[Dict[str, Any]],
    final_structured_references: list[Dict[str, Any]],
    missing_indices: Sequence[int],
    structured_items: Sequence[Dict[str, Any]],
    base_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    rescued_indices: list[int] = []
    rescue_reasons: list[Dict[str, Any]] = []
    candidates_seen = 0

    for index in sorted({int(value) for value in missing_indices if int(value) > 0}):
        existing_dois = _existing_reference_dois(final_references)
        existing_texts = _existing_reference_texts(final_references)
        structured_candidates = [
            item
            for item in structured_items
            if isinstance(item, dict) and _reference_index(item) == index
        ]
        base_candidates = [
            item
            for item in base_items
            if isinstance(item, dict) and _reference_index(item) == index
        ]
        candidates_seen += len(structured_candidates) + len(base_candidates)

        structured_reasonable = _reasonable_rescue_candidates(
            structured_candidates,
            expected_index=index,
            source="structured_discarded",
            existing_dois=existing_dois,
            existing_texts=existing_texts,
        )
        if len(structured_reasonable) == 1:
            candidate = structured_reasonable[0]
            final_structured_references.append(dict(candidate))
            final_references.append(_local_reference_from_structured(candidate))
            rescued_indices.append(index)
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "structured_discarded",
                    "action": "rescued",
                    "reason": "unique_reasonable_candidate",
                }
            )
            continue
        if len(structured_reasonable) > 1:
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "structured_discarded",
                    "action": "skipped",
                    "reason": "ambiguous_candidates",
                }
            )
            continue
        if structured_candidates:
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "structured_discarded",
                    "action": "skipped",
                    "reason": "no_reasonable_candidate",
                }
            )

        base_reasonable = _reasonable_rescue_candidates(
            base_candidates,
            expected_index=index,
            source="base",
            existing_dois=existing_dois,
            existing_texts=existing_texts,
        )
        if len(base_reasonable) == 1:
            candidate = base_reasonable[0]
            final_structured_references.append(
                _structured_reference_from_base_rescue(candidate)
            )
            final_references.append(_local_reference_from_base_rescue(candidate))
            rescued_indices.append(index)
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "base",
                    "action": "rescued",
                    "reason": "unique_reasonable_candidate",
                }
            )
        elif len(base_reasonable) > 1:
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "base",
                    "action": "skipped",
                    "reason": "ambiguous_candidates",
                }
            )
        elif base_candidates:
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "base",
                    "action": "skipped",
                    "reason": "no_reasonable_candidate",
                }
            )
        else:
            rescue_reasons.append(
                {
                    "index": index,
                    "source": "base",
                    "action": "skipped",
                    "reason": "no_candidates",
                }
            )

    final_references.sort(
        key=lambda item: (
            _reference_index(item) if _reference_index(item) is not None else 10**9,
            _reference_text(item),
        )
    )
    final_structured_references.sort(
        key=lambda item: (
            _reference_index(item) if _reference_index(item) is not None else 10**9,
            _reference_text(item),
        )
    )
    return {
        "rescued_indices": rescued_indices,
        "rescue_candidates_seen": candidates_seen,
        "rescue_reasons": rescue_reasons,
    }


def _final_max_reference_index(
    final_references: Sequence[Dict[str, Any]],
    *,
    citation_style: str,
) -> int:
    if citation_style != "numeric":
        return len(final_references)
    indices = [
        index
        for ref in final_references
        if isinstance(ref, dict)
        for index in [_reference_index(ref)]
        if index is not None and index > 0
    ]
    return max(indices) if indices else len(final_references)


def reconcile_reference_sources(
    *,
    base_references: Sequence[Dict[str, Any]],
    base_stats: Dict[str, Any],
    structured_references_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Pick a small, explicit final reference contract for the preview.

    The deep extraction stages are left untouched. This function only reconciles
    the already-built base references and structured references so final preview
    metrics do not blindly inherit rejected fallback rows or duplicate numeric
    indices from the base universe.
    """

    base_items = [item for item in base_references or [] if isinstance(item, dict)]
    structured_payload = (
        structured_references_data
        if isinstance(structured_references_data, dict)
        else {}
    )
    structured_items = [
        item
        for item in (structured_payload.get("references") or [])
        if isinstance(item, dict)
    ]

    base_citation_style = _citation_style_from_base(base_stats or {})
    structured_citation_style = (
        str(structured_payload.get("citation_style") or base_citation_style)
        .strip()
        .lower()
    )
    if structured_citation_style == "non-numeric":
        structured_citation_style = "non_numeric"
    if structured_citation_style not in {"numeric", "non_numeric"}:
        structured_citation_style = base_citation_style

    base_max_reference_index = _max_index_from_stats(
        base_stats or {},
        fallback=len(base_items),
    )
    structured_max_reference_index = (
        _coerce_expected_index(structured_payload.get("max_reference_index"))
        or _index_diagnostics(structured_items)["max_index"]
    )

    base_index_info = _index_diagnostics(
        base_items,
        expected_max_index=base_max_reference_index,
    )
    structured_index_info = _index_diagnostics(
        structured_items,
        expected_max_index=structured_max_reference_index,
    )

    structured_fallback_count = sum(
        1 for item in structured_items if _is_fallback_source(item)
    )
    structured_empty_count = sum(
        1 for item in structured_items if not _reference_text(item)
    )
    structured_rejected_count = sum(
        1 for item in structured_items if _validation_accepted(item) is False
    )
    structured_nonfallback_rejected_count = sum(
        1
        for item in structured_items
        if _validation_accepted(item) is False and not _is_fallback_source(item)
    )
    usable_structured = [
        item for item in structured_items if _structured_reference_is_usable(item)
    ]

    structured_total = len(structured_items)
    base_total = len(base_items)
    fallback_pct = _pct(structured_fallback_count, structured_total)
    empty_pct = _pct(structured_empty_count, structured_total)
    usable_pct = _pct(len(usable_structured), structured_total)
    coverage_floor = max(1, int(max(base_total, 1) * 0.5))
    duplicate_index_limit = max(
        10, int(max(structured_index_info["unique_count"], 1) * 0.2)
    )
    structured_healthy = (
        structured_total > 0
        and len(usable_structured) >= coverage_floor
        and fallback_pct <= 30.0
        and empty_pct <= 20.0
        and len(structured_index_info["duplicate_indices"]) <= duplicate_index_limit
    )

    selection_reasons: list[str] = []
    if structured_healthy:
        source_selected = "structured"
        selected_citation_style = structured_citation_style
        selected_structured = _dedupe_numbered_entries(
            usable_structured,
            numbered=selected_citation_style == "numeric",
        )
        final_structured_references = [dict(item) for item in selected_structured]
        final_references = [
            _local_reference_from_structured(item)
            for item in final_structured_references
        ]
        selection_reasons.append("structured_healthy")
        if structured_fallback_count:
            selection_reasons.append("filtered_structured_fallbacks")
        if structured_empty_count:
            selection_reasons.append("filtered_empty_structured_references")
        if structured_index_info["duplicate_indices"]:
            selection_reasons.append("deduplicated_structured_indices")
        if structured_nonfallback_rejected_count:
            selection_reasons.append("retained_nonfallback_rejected_rows")
    else:
        source_selected = "base"
        selected_citation_style = base_citation_style
        usable_base = [item for item in base_items if _reference_text(item)]
        selected_base = _dedupe_numbered_entries(
            usable_base,
            numbered=selected_citation_style == "numeric",
        )
        final_references = [_local_reference_from_base(item) for item in selected_base]
        final_structured_references = [
            _structured_reference_from_base(item) for item in selected_base
        ]
        selection_reasons.append("structured_weak")
        if structured_fallback_count:
            selection_reasons.append("structured_fallbacks_too_high_or_unusable")
        if structured_empty_count:
            selection_reasons.append("structured_empty_references")
        if len(usable_structured) < coverage_floor:
            selection_reasons.append("structured_coverage_too_low")

    preliminary_max_reference_index = _final_max_reference_index(
        final_references,
        citation_style=selected_citation_style,
    )
    preliminary_index_info = _index_diagnostics(
        final_references,
        expected_max_index=(
            preliminary_max_reference_index
            if selected_citation_style == "numeric"
            else None
        ),
    )
    rescue_attempted = (
        source_selected == "structured"
        and selected_citation_style == "numeric"
        and bool(preliminary_index_info["missing_indices"])
    )
    rescue_result = {
        "rescued_indices": [],
        "rescue_candidates_seen": 0,
        "rescue_reasons": [],
    }
    if rescue_attempted:
        rescue_result = _rescue_missing_numeric_indices(
            final_references=final_references,
            final_structured_references=final_structured_references,
            missing_indices=preliminary_index_info["missing_indices"],
            structured_items=structured_items,
            base_items=base_items,
        )
        if rescue_result["rescued_indices"]:
            selection_reasons.append("rescued_missing_numeric_indices")

    final_max_reference_index = _final_max_reference_index(
        final_references,
        citation_style=selected_citation_style,
    )
    final_index_info = _index_diagnostics(
        final_references,
        expected_max_index=(
            final_max_reference_index if selected_citation_style == "numeric" else None
        ),
    )
    final_total = len(final_references)
    summary = {
        "base_total": base_total,
        "structured_total": structured_total,
        "final_total": final_total,
        "base_max_reference_index": base_max_reference_index,
        "structured_max_reference_index": structured_max_reference_index,
        "final_max_reference_index": final_max_reference_index,
        "base_citation_style": base_citation_style,
        "structured_citation_style": structured_citation_style,
        "final_citation_style": selected_citation_style,
        "structured_fallback_count": structured_fallback_count,
        "structured_fallback_pct": fallback_pct,
        "structured_empty_count": structured_empty_count,
        "structured_empty_pct": empty_pct,
        "structured_rejected_count": structured_rejected_count,
        "structured_nonfallback_rejected_count": structured_nonfallback_rejected_count,
        "usable_structured_total": len(usable_structured),
        "usable_structured_pct": usable_pct,
        "base_duplicate_indices": base_index_info["duplicate_indices"],
        "base_missing_indices": base_index_info["missing_indices"],
        "structured_duplicate_indices": structured_index_info["duplicate_indices"],
        "structured_missing_indices": structured_index_info["missing_indices"],
        "final_duplicate_indices": final_index_info["duplicate_indices"],
        "final_missing_indices": final_index_info["missing_indices"],
        "rescue_attempted": rescue_attempted,
        "rescued_indices": rescue_result["rescued_indices"],
        "rescue_candidates_seen": rescue_result["rescue_candidates_seen"],
        "rescue_reasons": rescue_result["rescue_reasons"],
        "source_selected": source_selected,
        "selection_reasons": selection_reasons,
    }
    return {
        "final_references": final_references,
        "final_structured_references": final_structured_references,
        "final_references_total": final_total,
        "final_citation_style": selected_citation_style,
        "final_max_reference_index": final_max_reference_index,
        "reconciliation_summary": summary,
    }

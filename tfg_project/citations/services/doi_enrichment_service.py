from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .crossref_client import (
    fetch_cited_by_for_doi,
    fetch_work_by_doi as crossref_fetch_work_by_doi,
    search_works_by_bibliographic_text,
)
from .semantic_scholar_client import (
    SemanticScholarError,
    get_citing_papers_for_doi_paginated,
    get_work_by_doi as semantic_fetch_work_by_doi,
)
from .reference_reconciliation import validate_reference_against_metadata

logger = logging.getLogger("citations.doi_enrichment")

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
LEADING_REFERENCE_LABEL_RE = re.compile(r"^\s*(\[\s*\d+\s*\]|\d+\s*[\.\)])\s*")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
WORD_RE = re.compile(r"[a-z0-9]{3,}")


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


def is_valid_doi(raw_doi: Any) -> bool:
    normalized = normalize_doi(raw_doi)
    if not normalized:
        return False
    return bool(re.fullmatch(r"10\.\d{4,9}/\S+", normalized, flags=re.IGNORECASE))


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _text_tokens(value: Any) -> set[str]:
    return set(WORD_RE.findall(_normalize_text(value)))


def _extract_reference_text(reference: Dict[str, Any]) -> str:
    text = (
        reference.get("text")
        or reference.get("raw")
        or reference.get("reference")
        or reference.get("title")
        or ""
    )
    cleaned = LEADING_REFERENCE_LABEL_RE.sub("", str(text)).strip()
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_year(value: Any) -> Optional[int]:
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


def _author_tokens_from_names(names: Any) -> set[str]:
    if not isinstance(names, list):
        return set()
    tokens: set[str] = set()
    for name in names:
        parts = re.findall(r"[A-Za-z]{3,}", str(name or "").lower())
        if parts:
            tokens.add(parts[-1])
    return tokens


def _author_tokens_from_text(text: str) -> set[str]:
    left_part = text.split(".")[0]
    tokens = [token for token in re.findall(r"[A-Za-z]{3,}", left_part.lower())]
    return set(tokens[:8])


def _work_key(work: Dict[str, Any]) -> str:
    doi = normalize_doi(work.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = _normalize_text(work.get("title"))
    year = work.get("year")
    if title:
        return f"title:{title}|year:{year or ''}"
    raw_text = _normalize_text(work.get("raw_text"))
    return f"raw:{raw_text[:220]}"


def _merge_unique_work_items(
    primary: Sequence[Dict[str, Any]],
    secondary: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in list(primary) + list(secondary):
        if not isinstance(item, dict):
            continue
        key = _work_key(item)
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(item)
            continue
        current = merged[key]
        for field in ("doi", "title", "year", "venue", "url", "raw_text"):
            if not current.get(field) and item.get(field):
                current[field] = item.get(field)
        if not current.get("authors") and item.get("authors"):
            current["authors"] = item.get("authors")
        if not current.get("source") and item.get("source"):
            current["source"] = item.get("source")
    return list(merged.values())


def _score_external_reference_match(
    local_ref: Dict[str, Any],
    external_ref: Dict[str, Any],
) -> float:
    local_doi = normalize_doi(local_ref.get("doi"))
    external_doi = normalize_doi(external_ref.get("doi"))
    if local_doi and external_doi and local_doi == external_doi:
        return 0.99

    local_text = _extract_reference_text(local_ref)
    external_title = str(
        external_ref.get("title") or external_ref.get("raw_text") or ""
    ).strip()
    if not local_text or not external_title:
        return 0.0

    local_norm = _normalize_text(local_text)
    title_norm = _normalize_text(external_title)
    if not local_norm or not title_norm:
        return 0.0

    title_ratio = SequenceMatcher(None, local_norm[:420], title_norm[:320]).ratio()
    score = title_ratio * 0.68
    if title_norm and title_norm in local_norm:
        score = max(score, 0.82)

    local_tokens = _text_tokens(local_norm)
    title_tokens = _text_tokens(title_norm)
    if local_tokens and title_tokens:
        overlap = len(local_tokens.intersection(title_tokens))
        token_ratio = overlap / max(len(title_tokens), 1)
        score += token_ratio * 0.22

    local_year = _extract_year(local_ref.get("year") or local_text)
    external_year = _extract_year(external_ref.get("year"))
    if local_year and external_year and local_year == external_year:
        score += 0.08

    local_author_tokens = _author_tokens_from_text(local_text)
    external_author_tokens = _author_tokens_from_names(external_ref.get("authors"))
    if local_author_tokens and external_author_tokens:
        overlap = len(local_author_tokens.intersection(external_author_tokens))
        author_ratio = overlap / max(len(external_author_tokens), 1)
        score += author_ratio * 0.08

    crossref_score = float(external_ref.get("crossref_score") or 0.0)
    if crossref_score > 0:
        score += min(crossref_score / 100.0, 0.06)

    return max(0.0, min(score, 0.98))


def _pick_best_external_reference_match(
    local_ref: Dict[str, Any],
    candidates: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], float]:
    best_ref: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        score = _score_external_reference_match(local_ref, candidate)
        if score > best_score:
            best_score = score
            best_ref = candidate
    return best_ref, best_score


def _as_reference_candidate_from_work(
    work_item: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(work_item, dict):
        return None
    doi = normalize_doi(work_item.get("doi"))
    title = str(work_item.get("title") or "").strip()
    if not doi and not title:
        return None
    return {
        "doi": doi,
        "title": title,
        "authors": work_item.get("authors")
        if isinstance(work_item.get("authors"), list)
        else [],
        "year": _extract_year(work_item.get("year")),
        "venue": str(work_item.get("venue") or "").strip() or None,
        "source": str(work_item.get("source") or "").strip() or "crossref",
    }


def _apply_reference_metadata(
    local_ref: Dict[str, Any],
    match: Dict[str, Any],
    *,
    source: str,
    confidence: float,
) -> Dict[str, Any]:
    out = dict(local_ref)
    match_doi = normalize_doi(match.get("doi"))
    if match_doi and confidence >= 0.62:
        out["doi"] = match_doi
        if not out.get("doi_source"):
            out["doi_source"] = f"enrichment:{source}"
    if match.get("title"):
        out["title"] = str(match.get("title")).strip()
    if isinstance(match.get("authors"), list) and match.get("authors"):
        out["authors"] = [
            str(author).strip()
            for author in match.get("authors")
            if str(author).strip()
        ]
    year = _extract_year(match.get("year"))
    if year:
        out["year"] = year
    venue = str(match.get("venue") or "").strip()
    if venue:
        out["venue"] = venue
    out["enrichment_source"] = source
    out["enrichment_confidence"] = round(float(confidence), 3)
    return out


def _coerce_reference_validation(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "match_score": 0.0,
            "mixed_reference_score": 0.0,
            "has_nested_anchor": False,
            "accepted": False,
            "reason": None,
        }
    return {
        "match_score": float(value.get("match_score") or 0.0),
        "mixed_reference_score": float(value.get("mixed_reference_score") or 0.0),
        "has_nested_anchor": bool(value.get("has_nested_anchor")),
        "accepted": bool(value.get("accepted")),
        "reason": value.get("reason"),
    }


def _build_merged_reference_validation(
    *,
    structural_validation: Dict[str, Any],
    metadata_validation: Dict[str, Any],
    accepted: bool,
    reason: Optional[str],
) -> Dict[str, Any]:
    merged_match = max(
        float(structural_validation.get("match_score") or 0.0),
        float(metadata_validation.get("match_score") or 0.0),
    )
    merged_mixed = max(
        float(structural_validation.get("mixed_reference_score") or 0.0),
        float(metadata_validation.get("mixed_reference_score") or 0.0),
    )
    merged_nested = bool(
        structural_validation.get("has_nested_anchor")
        or metadata_validation.get("has_nested_anchor")
    )
    return {
        "match_score": round(max(0.0, min(merged_match, 1.0)), 3),
        "mixed_reference_score": round(max(0.0, min(merged_mixed, 1.0)), 3),
        "has_nested_anchor": merged_nested,
        "accepted": bool(accepted),
        "reason": reason if not accepted else None,
    }


def _evaluate_enrichment_acceptance(
    *,
    current: Dict[str, Any],
    match: Dict[str, Any],
    score: float,
    candidates: Sequence[Dict[str, Any]],
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    local_text = _extract_reference_text(current)
    expected_index_raw = current.get("index")
    try:
        expected_index = int(expected_index_raw)
    except (TypeError, ValueError):
        expected_index = None
    other_candidates: List[Tuple[int, Dict[str, Any]]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        raw_idx = candidate.get("index")
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            idx = 0
        if idx > 0:
            other_candidates.append((idx, candidate))
    metadata_validation = validate_reference_against_metadata(
        local_text,
        match,
        expected_index=expected_index,
        other_metadata_candidates=other_candidates,
    )
    structural_validation = _coerce_reference_validation(
        current.get("reference_validation")
    )
    structure_source = str(current.get("structure_source") or "").strip().lower()
    local_row_count = int(current.get("local_row_count") or 0)
    local_anchor_detected = bool(current.get("local_anchor_detected"))
    rows_reconstruction_available = (
        structure_source.startswith("rows")
        and local_row_count >= 1
        and local_anchor_detected
    )
    rows_reconstruction_reasonable = (
        rows_reconstruction_available
        and float(structural_validation.get("mixed_reference_score") or 0.0) < 0.72
        and not bool(structural_validation.get("has_nested_anchor"))
    )
    if structure_source.startswith("rows") and not rows_reconstruction_reasonable:
        accepted = False
        reason = "unreliable_rows_structure"
    else:
        combined_mixed = max(
            float(structural_validation.get("mixed_reference_score") or 0.0),
            float(metadata_validation.get("mixed_reference_score") or 0.0),
        )
        has_nested = bool(
            structural_validation.get("has_nested_anchor")
            or metadata_validation.get("has_nested_anchor")
        )
        metadata_match = float(metadata_validation.get("match_score") or 0.0)
        direct_doi_match = bool(normalize_doi(current.get("doi"))) and normalize_doi(
            current.get("doi")
        ) == normalize_doi(match.get("doi"))
        high_confidence = float(score or 0.0) >= 0.72
        metadata_accepted = bool(metadata_validation.get("accepted"))
        accepted = bool(
            metadata_accepted
            and combined_mixed < 0.72
            and (
                metadata_match >= 0.72
                or (direct_doi_match and metadata_match >= 0.52)
                or high_confidence
            )
            and not (has_nested and not direct_doi_match)
        )
        if accepted:
            reason = None
        elif has_nested or combined_mixed >= 0.72:
            reason = "mixed_rows_multiple_references"
        else:
            reason = str(
                metadata_validation.get("reason") or "metadata_validation_failed"
            )

    merged = _build_merged_reference_validation(
        structural_validation=structural_validation,
        metadata_validation=metadata_validation,
        accepted=accepted,
        reason=reason,
    )
    return accepted, merged, reason


def resolve_work_by_doi(doi: str) -> Dict[str, Any]:
    normalized_doi = normalize_doi(doi)
    resolved: Dict[str, Any] = {
        "doi": normalized_doi,
        "title": "",
        "authors": [],
        "year": None,
        "venue": "",
        "references": [],
        "citations": [],
        "source": "none",
        "sources_used": [],
    }
    if not is_valid_doi(normalized_doi):
        return resolved

    crossref_work: Optional[Dict[str, Any]] = None
    semantic_work: Optional[Dict[str, Any]] = None

    try:
        crossref_work = crossref_fetch_work_by_doi(normalized_doi)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("crossref resolve failed doi=%s error=%s", normalized_doi, exc)
    if crossref_work:
        resolved["sources_used"].append("crossref")
        logger.info("crossref resolved doi=%s", normalized_doi)
    else:
        logger.info("crossref resolve miss doi=%s", normalized_doi)

    try:
        semantic_work = semantic_fetch_work_by_doi(normalized_doi)
    except SemanticScholarError as exc:
        logger.warning(
            "semantic scholar resolve failed doi=%s error=%s", normalized_doi, exc
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "semantic scholar unexpected error doi=%s error=%s", normalized_doi, exc
        )
    if semantic_work:
        resolved["sources_used"].append("semantic_scholar")
        logger.info("semantic scholar resolved doi=%s", normalized_doi)
    else:
        logger.info("semantic scholar resolve miss doi=%s", normalized_doi)

    preferred = crossref_work or semantic_work or {}
    secondary = semantic_work if crossref_work else {}
    if crossref_work and semantic_work:
        secondary = semantic_work

    resolved["title"] = str(
        preferred.get("title") or secondary.get("title") or ""
    ).strip()
    resolved["authors"] = (
        preferred.get("authors")
        if isinstance(preferred.get("authors"), list) and preferred.get("authors")
        else secondary.get("authors")
        if isinstance(secondary.get("authors"), list)
        else []
    )
    resolved["year"] = preferred.get("year") or secondary.get("year")
    resolved["venue"] = str(
        preferred.get("venue") or secondary.get("venue") or ""
    ).strip()
    resolved["source"] = (
        "crossref"
        if crossref_work
        else ("semantic_scholar" if semantic_work else "none")
    )

    references = _merge_unique_work_items(
        crossref_work.get("references", []) if isinstance(crossref_work, dict) else [],
        semantic_work.get("references", []) if isinstance(semantic_work, dict) else [],
    )
    resolved["references"] = references

    crossref_cited_by = fetch_cited_by_for_doi(normalized_doi, rows=25)
    if crossref_cited_by and "crossref" not in resolved["sources_used"]:
        resolved["sources_used"].append("crossref")

    semantic_citations = (
        semantic_work.get("citations", []) if isinstance(semantic_work, dict) else []
    )
    if not semantic_citations:
        try:
            cited_page, _ = get_citing_papers_for_doi_paginated(
                normalized_doi,
                limit=25,
                offset=0,
            )
            semantic_citations = [
                {
                    "title": str(item.get("title") or "").strip(),
                    "authors": [
                        name.strip()
                        for name in str(item.get("authors") or "").split(",")
                        if name.strip()
                    ],
                    "year": _extract_year(item.get("year")),
                    "doi": normalize_doi(item.get("doi")),
                    "venue": "",
                    "url": item.get("url"),
                    "source": "semantic_scholar",
                }
                for item in cited_page
                if isinstance(item, dict)
            ]
            if (
                semantic_citations
                and "semantic_scholar" not in resolved["sources_used"]
            ):
                resolved["sources_used"].append("semantic_scholar")
        except Exception:
            semantic_citations = []

    citations = _merge_unique_work_items(crossref_cited_by, semantic_citations)
    resolved["citations"] = citations
    return resolved


def enrich_references_with_doi_data(
    local_references: Sequence[Dict[str, Any]],
    external_work_data: Dict[str, Any],
) -> Dict[str, Any]:
    candidates = (
        external_work_data.get("references")
        if isinstance(external_work_data, dict)
        else []
    )
    candidates = candidates if isinstance(candidates, list) else []

    by_doi: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        doi = normalize_doi(candidate.get("doi"))
        if doi and doi not in by_doi:
            by_doi[doi] = candidate

    query_cache: Dict[str, List[Dict[str, Any]]] = {}
    doi_lookup_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    enriched: List[Dict[str, Any]] = []
    enriched_count = 0
    failed_matches = 0
    sources_used: set[str] = set()
    crossref_query_lookups = 0
    max_crossref_queries = 12
    doi_lookups = 0
    max_doi_lookups = 20

    for local_ref in local_references:
        if not isinstance(local_ref, dict):
            continue
        current = dict(local_ref)
        local_text = _extract_reference_text(current)
        local_doi = normalize_doi(current.get("doi"))
        best_match: Optional[Dict[str, Any]] = None
        best_score = 0.0
        source = ""
        validation_candidates: List[Dict[str, Any]] = [
            candidate for candidate in candidates if isinstance(candidate, dict)
        ]

        if local_doi:
            direct = by_doi.get(local_doi)
            if direct:
                best_match = direct
                best_score = 0.99
                source = str(direct.get("source") or "crossref")
            else:
                if local_doi in doi_lookup_cache:
                    lookup_match = doi_lookup_cache.get(local_doi)
                else:
                    lookup_match = None
                if local_doi not in doi_lookup_cache and doi_lookups < max_doi_lookups:
                    doi_lookups += 1
                    fetched_work = None
                    try:
                        fetched_work = crossref_fetch_work_by_doi(local_doi)
                    except Exception as exc:  # pragma: no cover - defensive guard
                        logger.warning(
                            "crossref doi lookup failed doi=%s error=%s", local_doi, exc
                        )
                    if not fetched_work:
                        try:
                            fetched_work = semantic_fetch_work_by_doi(local_doi)
                        except SemanticScholarError as exc:
                            logger.warning(
                                "semantic scholar doi lookup failed doi=%s error=%s",
                                local_doi,
                                exc,
                            )
                        except Exception as exc:  # pragma: no cover - defensive guard
                            logger.warning(
                                "semantic scholar doi lookup unexpected doi=%s error=%s",
                                local_doi,
                                exc,
                            )
                    lookup_match = _as_reference_candidate_from_work(fetched_work)
                    doi_lookup_cache[local_doi] = lookup_match
                if lookup_match:
                    best_match = lookup_match
                    best_score = 0.99
                    source = str(lookup_match.get("source") or "crossref")

        if best_match is None and candidates:
            best_match, best_score = _pick_best_external_reference_match(
                current, candidates
            )
            if best_match and best_score >= 0.72:
                source = str(
                    best_match.get("source")
                    or external_work_data.get("source")
                    or "crossref"
                )
            else:
                best_match = None

        if (
            best_match is None
            and local_text
            and crossref_query_lookups < max_crossref_queries
        ):
            query_key = _normalize_text(local_text)[:300]
            query_results = query_cache.get(query_key)
            if query_results is None:
                query_results = search_works_by_bibliographic_text(
                    local_text[:320], rows=4
                )
                query_cache[query_key] = query_results
                crossref_query_lookups += 1
            if query_results:
                validation_candidates.extend(
                    [item for item in query_results if isinstance(item, dict)]
                )
                query_match, query_score = _pick_best_external_reference_match(
                    current, query_results
                )
                if query_match and query_score >= 0.62:
                    best_match = query_match
                    best_score = query_score
                    source = str(query_match.get("source") or "crossref")

        if best_match is not None:
            accepted, merged_validation, rejection_reason = (
                _evaluate_enrichment_acceptance(
                    current=current,
                    match=best_match,
                    score=best_score,
                    candidates=validation_candidates,
                )
            )
            if accepted:
                updated = _apply_reference_metadata(
                    current,
                    best_match,
                    source=source or "crossref",
                    confidence=best_score,
                )
                updated["reference_validation"] = merged_validation
                updated["enrichment_accepted"] = True
                enriched.append(updated)
                enriched_count += 1
                if source:
                    sources_used.add(source)
            else:
                rejected = dict(current)
                rejected.pop("enrichment_source", None)
                rejected.pop("enrichment_confidence", None)
                rejected["reference_validation"] = merged_validation
                rejected["enrichment_accepted"] = False
                rejected["enrichment_candidate"] = {
                    "source": source or str(best_match.get("source") or "crossref"),
                    "confidence": round(float(best_score), 3),
                    "doi": normalize_doi(best_match.get("doi")) or None,
                    "title": str(best_match.get("title") or "").strip() or None,
                    "authors": best_match.get("authors")
                    if isinstance(best_match.get("authors"), list)
                    else [],
                    "year": _extract_year(best_match.get("year")),
                    "venue": str(best_match.get("venue") or "").strip() or None,
                    "reason": rejection_reason or "metadata_validation_failed",
                }
                enriched.append(rejected)
                failed_matches += 1
        else:
            enriched.append(current)
            failed_matches += 1

    return {
        "references": enriched,
        "enriched_count": enriched_count,
        "failed_matches": failed_matches,
        "sources_used": sorted(sources_used),
        "crossref_query_lookups": crossref_query_lookups,
        "doi_lookups": doi_lookups,
    }


def _project_enrichment_to_local_references(
    local_references: Sequence[Dict[str, Any]],
    enriched_reference_entries: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    by_index: Dict[int, Dict[str, Any]] = {}
    by_doi: Dict[str, Dict[str, Any]] = {}
    by_position: List[Dict[str, Any]] = []
    for ref in enriched_reference_entries:
        if not isinstance(ref, dict):
            continue
        by_position.append(ref)
        idx_raw = ref.get("index")
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            idx = 0
        if idx > 0 and idx not in by_index:
            by_index[idx] = ref
        doi = normalize_doi(ref.get("doi"))
        if doi and doi not in by_doi:
            by_doi[doi] = ref

    out: List[Dict[str, Any]] = []
    changed = 0
    for position, local_ref in enumerate(local_references):
        if not isinstance(local_ref, dict):
            continue
        current = dict(local_ref)
        idx_raw = current.get("index")
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            idx = 0

        match = by_index.get(idx) if idx > 0 else None
        if match is None:
            doi = normalize_doi(current.get("doi"))
            if doi:
                match = by_doi.get(doi)
        if match is None and len(local_references) == len(by_position):
            match = by_position[position] if position < len(by_position) else None

        if match and match.get("enrichment_source"):
            updated = _apply_reference_metadata(
                current,
                {
                    "doi": match.get("doi"),
                    "title": match.get("title"),
                    "authors": match.get("authors"),
                    "year": match.get("year"),
                    "venue": match.get("venue"),
                },
                source=str(match.get("enrichment_source") or "crossref"),
                confidence=float(match.get("enrichment_confidence") or 0.0),
            )
            out.append(updated)
            changed += 1
        else:
            out.append(current)
    return {"references": out, "enriched_count": changed}


def enrich_extraction_with_doi(
    *,
    doi_input: str,
    local_references: Sequence[Dict[str, Any]],
    references_data_references: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    doi_provided = bool(str(doi_input or "").strip())
    enrichment_meta: Dict[str, Any] = {
        "doi_provided": doi_provided,
        "doi_normalized": "",
        "paper_resolved": False,
        "references_enriched": 0,
        "cited_by_count": 0,
        "sources_used": [],
    }

    safe_local = [dict(item) for item in local_references if isinstance(item, dict)]
    safe_visual = [
        dict(item) for item in references_data_references if isinstance(item, dict)
    ]
    if not doi_provided:
        return {
            "local_references": safe_local,
            "references_data_references": safe_visual,
            "cited_by": [],
            "enrichment": enrichment_meta,
        }

    normalized_doi = normalize_doi(doi_input)
    enrichment_meta["doi_normalized"] = normalized_doi
    logger.info(
        "doi enrichment requested raw=%s normalized=%s", doi_input, normalized_doi
    )
    if not is_valid_doi(normalized_doi):
        enrichment_meta["warning"] = "invalid_doi"
        logger.info("doi enrichment skipped invalid doi=%s", doi_input)
        return {
            "local_references": safe_local,
            "references_data_references": safe_visual,
            "cited_by": [],
            "enrichment": enrichment_meta,
        }

    external_work = resolve_work_by_doi(normalized_doi)
    paper_resolved = bool(
        external_work.get("title")
        or external_work.get("references")
        or external_work.get("citations")
    )
    enrichment_meta["paper_resolved"] = paper_resolved
    enrichment_meta["sources_used"] = list(external_work.get("sources_used") or [])
    cited_by = (
        external_work.get("citations")
        if isinstance(external_work.get("citations"), list)
        else []
    )
    enrichment_meta["cited_by_count"] = len(cited_by)

    if not paper_resolved:
        logger.info("doi enrichment fallback no external data doi=%s", normalized_doi)
        return {
            "local_references": safe_local,
            "references_data_references": safe_visual,
            "cited_by": cited_by,
            "enrichment": enrichment_meta,
        }

    target_references = safe_visual if safe_visual else safe_local
    enriched_visual_result = enrich_references_with_doi_data(
        target_references,
        external_work,
    )
    enriched_visual_references = list(enriched_visual_result["references"])
    projected_local = _project_enrichment_to_local_references(
        safe_local,
        enriched_visual_references,
    )
    references_enriched = max(
        int(enriched_visual_result.get("enriched_count") or 0),
        int(projected_local.get("enriched_count") or 0),
    )
    enrichment_meta["references_enriched"] = references_enriched

    sources = set(enrichment_meta["sources_used"])
    for source in enriched_visual_result.get("sources_used") or []:
        if source:
            sources.add(str(source))
    enrichment_meta["sources_used"] = sorted(sources)

    logger.info(
        (
            "doi enrichment doi=%s resolved=%s enriched=%s failed=%s "
            "doi_lookups=%s text_queries=%s cited_by=%s sources=%s"
        ),
        normalized_doi,
        paper_resolved,
        references_enriched,
        int(enriched_visual_result.get("failed_matches") or 0),
        int(enriched_visual_result.get("doi_lookups") or 0),
        int(enriched_visual_result.get("crossref_query_lookups") or 0),
        enrichment_meta["cited_by_count"],
        ",".join(enrichment_meta["sources_used"]),
    )

    return {
        "local_references": projected_local["references"],
        "references_data_references": enriched_visual_references
        if safe_visual
        else safe_visual,
        "cited_by": cited_by,
        "enrichment": enrichment_meta,
    }

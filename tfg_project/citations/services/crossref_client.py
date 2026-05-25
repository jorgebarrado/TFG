from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

CROSSREF_API_BASE = "https://api.crossref.org"
DEFAULT_TIMEOUT = 12
DEFAULT_USER_AGENT = os.getenv(
    "CITECHECK_USER_AGENT",
    "CiteCheck/1.0 (mailto:citecheck@example.com)",
)
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)

logger = logging.getLogger("citations.doi_enrichment")


def _headers() -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }


def _safe_json_response(response: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _first_non_empty_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _normalize_doi(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = DOI_URL_RE.sub("", candidate)
    candidate = candidate.rstrip(").,;:]").strip().lower()
    return candidate


def _extract_year(message: Dict[str, Any]) -> Optional[int]:
    for key in ("issued", "published-print", "published-online", "created"):
        candidate = message.get(key)
        if not isinstance(candidate, dict):
            continue
        date_parts = candidate.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts:
            continue
        first = date_parts[0]
        if not isinstance(first, list) or not first:
            continue
        try:
            year = int(first[0])
        except (TypeError, ValueError):
            continue
        if 1500 <= year <= 2100:
            return year
    return None


def _normalize_authors(raw_authors: Any) -> List[str]:
    if not isinstance(raw_authors, list):
        return []
    authors: List[str] = []
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        literal = str(author.get("literal") or "").strip()
        name = " ".join(part for part in [given, family] if part).strip() or literal
        if not name:
            continue
        authors.append(name)
    return authors


def _normalize_work_item(message: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    return {
        "doi": _normalize_doi(message.get("DOI")),
        "title": _first_non_empty_text(message.get("title")),
        "authors": _normalize_authors(message.get("author")),
        "year": _extract_year(message),
        "venue": _first_non_empty_text(message.get("container-title")),
        "url": str(message.get("URL") or "").strip() or None,
        "source": source,
    }


def _normalize_reference_item(reference: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(reference, dict):
        return {}
    unstructured = str(reference.get("unstructured") or "").strip()
    title = str(
        reference.get("article-title") or reference.get("volume-title") or ""
    ).strip()
    author = str(reference.get("author") or "").strip()
    year: Optional[int] = None
    try:
        parsed_year = int(reference.get("year"))
        if 1500 <= parsed_year <= 2100:
            year = parsed_year
    except (TypeError, ValueError):
        year = None
    normalized = {
        "doi": _normalize_doi(reference.get("DOI")),
        "title": title or "",
        "authors": [author] if author else [],
        "year": year,
        "venue": str(
            reference.get("journal-title") or reference.get("series-title") or ""
        ).strip()
        or None,
        "raw_text": unstructured or title or author or "",
        "source": "crossref",
    }
    if not normalized["doi"] and not normalized["title"] and not normalized["raw_text"]:
        return {}
    return normalized


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _request_json(
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    url = f"{CROSSREF_API_BASE}{path}"
    try:
        response = requests.get(
            url,
            params=params or {},
            headers=_headers(),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("crossref request failed path=%s error=%s", path, exc)
        return None

    if response.status_code == 404:
        return None
    if response.status_code == 429:
        logger.warning("crossref rate limit path=%s", path)
        return None
    if response.status_code >= 500:
        logger.warning(
            "crossref server error path=%s status=%s", path, response.status_code
        )
        return None
    if response.status_code != 200:
        logger.info("crossref non-200 path=%s status=%s", path, response.status_code)
        return None
    return _safe_json_response(response)


def fetch_work_by_doi(
    doi: str, *, timeout: int = DEFAULT_TIMEOUT
) -> Optional[Dict[str, Any]]:
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi:
        return None
    payload = _request_json(f"/works/{quote(normalized_doi, safe='')}", timeout=timeout)
    message = (payload or {}).get("message")
    if not isinstance(message, dict):
        return None
    work = _normalize_work_item(message, source="crossref")
    work["doi"] = work.get("doi") or normalized_doi
    references = []
    for ref in message.get("reference") or []:
        normalized_ref = _normalize_reference_item(ref)
        if normalized_ref:
            references.append(normalized_ref)
    work["references"] = references
    work["reference_count"] = _safe_int(message.get("reference-count"), len(references))
    work["citation_count"] = _safe_int(message.get("is-referenced-by-count"), 0)
    return work


def search_works_by_bibliographic_text(
    query_text: str,
    *,
    rows: int = 5,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    query = str(query_text or "").strip()
    if not query:
        return []
    payload = _request_json(
        "/works",
        params={
            "query.bibliographic": query,
            "rows": max(1, min(rows, 10)),
            "select": "DOI,title,author,issued,container-title,URL,score",
        },
        timeout=timeout,
    )
    items = ((payload or {}).get("message") or {}).get("items") or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_work_item(item, source="crossref")
        normalized["crossref_score"] = float(item.get("score") or 0.0)
        out.append(normalized)
    return out


def fetch_cited_by_for_doi(
    doi: str,
    *,
    rows: int = 25,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi:
        return []
    payload = _request_json(
        "/works",
        params={
            "filter": f"reference.doi:{normalized_doi}",
            "rows": max(1, min(rows, 100)),
            "select": "DOI,title,author,issued,container-title,URL",
        },
        timeout=timeout,
    )
    items = ((payload or {}).get("message") or {}).get("items") or []
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(_normalize_work_item(item, source="crossref"))
    return out

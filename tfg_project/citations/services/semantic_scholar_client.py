"""Cliente defensivo para Semantic Scholar.

Todas las llamadas pasan por este mÃ³dulo para centralizar cachÃ©, cuotas,
reintentos y normalizaciÃ³n de DOI. Las vistas y pipelines consumen funciones de
alto nivel para evitar duplicar manejo de errores HTTP.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from .external_api import build_external_api_session

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
CITATION_COUNT_CACHE_TIMEOUT = 24 * 60 * 60
CITATION_COUNT_BATCH_SIZE = 100
PAPER_ID_CACHE_TIMEOUT = 24 * 60 * 60
PAPER_METADATA_CACHE_TIMEOUT = 24 * 60 * 60
WORK_BY_DOI_CACHE_TIMEOUT = 24 * 60 * 60
CITING_PAPERS_CACHE_TIMEOUT = 60 * 60
DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
RATE_LIMIT_INTERVAL_SECONDS = 1.1
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
PAPER_DEFAULT_FIELDS = (
    "title,authors,year,venue,publicationDate,externalIds,url,abstract,"
    "citationCount,referenceCount,openAccessPdf,fieldsOfStudy"
)
CITATION_DEFAULT_FIELDS = (
    "contexts,intents,isInfluential,citingPaper.title,citingPaper.authors,"
    "citingPaper.year,citingPaper.venue,citingPaper.externalIds,citingPaper.url,"
    "citingPaper.abstract,citingPaper.citationCount,citingPaper.openAccessPdf"
)
REFERENCE_DEFAULT_FIELDS = (
    "contexts,intents,isInfluential,citedPaper.title,citedPaper.authors,"
    "citedPaper.year,citedPaper.venue,citedPaper.externalIds,citedPaper.url,"
    "citedPaper.abstract,citedPaper.citationCount,citedPaper.openAccessPdf"
)

logger = logging.getLogger("citations.semantic_scholar")
_rate_limit_lock = threading.Lock()
# Rate limit por proceso suficiente para desarrollo/TFG. En produccion multi-worker
# se podria sustituir por Redis o una cache distribuida para coordinar workers.
_last_request_monotonic = 0.0


class SemanticScholarError(RuntimeError):
    """Errores relacionados con la API de Semantic Scholar."""


class SemanticScholarHTTPError(SemanticScholarError):
    """Error HTTP controlado de Semantic Scholar."""

    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        suffix = f": {detail}" if detail else "."
        super().__init__(
            f"Error en la API de Semantic Scholar (HTTP {status_code}){suffix}"
        )


class CitingPaper(TypedDict):
    title: str
    year: Optional[int]
    doi: Optional[str]
    authors: Optional[str]
    url: Optional[str]
    open_access_pdf_url: Optional[str]


def _get_api_key() -> str:
    try:
        if hasattr(settings, "SEMANTIC_SCHOLAR_API_KEY"):
            return str(settings.SEMANTIC_SCHOLAR_API_KEY or "").strip()
    except ImproperlyConfigured:
        pass
    return str(os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()


def _build_headers() -> dict:
    headers: dict = {"Accept": "application/json"}
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _reset_rate_limiter_for_tests() -> None:
    global _last_request_monotonic
    with _rate_limit_lock:
        _last_request_monotonic = 0.0


def _apply_rate_limit() -> None:
    global _last_request_monotonic
    with _rate_limit_lock:
        now = time.monotonic()
        wait_seconds = RATE_LIMIT_INTERVAL_SECONDS - (now - _last_request_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_request_monotonic = time.monotonic()


def _retry_after_seconds(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw)
        return max(0.0, retry_at.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None


def _request_semantic_scholar_json(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> Any:
    method = str(method or "").upper()
    if method not in {"GET", "POST"}:
        raise ValueError("Semantic Scholar solo soporta GET y POST en este cliente.")

    normalized_path = "/" + str(path or "").lstrip("/")
    url = f"{SEMANTIC_SCHOLAR_API_URL}{normalized_path}"
    session = build_external_api_session()
    attempts = max(0, int(retries)) + 1

    for attempt in range(attempts):
        try:
            _apply_rate_limit()
            request_kwargs: Dict[str, Any] = {
                "headers": _build_headers(),
                "params": params or {},
                "timeout": timeout,
            }
            if method == "POST":
                request_kwargs["json"] = json or {}
                response = session.post(url, **request_kwargs)
            else:
                response = session.get(url, **request_kwargs)
        except requests.RequestException as exc:
            if attempt < attempts - 1:
                wait_seconds = float(2**attempt)
                logger.warning(
                    "Error temporal de red en Semantic Scholar; reintentando",
                    extra={
                        "event_context": {
                            "method": method,
                            "path": normalized_path,
                            "attempt": attempt + 1,
                            "wait_seconds": wait_seconds,
                        }
                    },
                )
                time.sleep(wait_seconds)
                continue
            raise SemanticScholarError(
                f"Error de conexion con Semantic Scholar: {exc}"
            ) from exc

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 200:
            if not getattr(response, "content", b""):
                return {}
            return response.json()

        detail = _response_error_detail(response)
        if status_code in {401, 403}:
            logger.warning(
                "Semantic Scholar devolvio HTTP %s; posible problema con la API key.",
                status_code,
                extra={
                    "event_context": {
                        "method": method,
                        "path": normalized_path,
                        "status_code": status_code,
                    }
                },
            )

        if status_code in TRANSIENT_STATUS_CODES and attempt < attempts - 1:
            retry_after = _retry_after_seconds(
                str(getattr(response, "headers", {}).get("Retry-After", ""))
            )
            wait_seconds = retry_after if retry_after is not None else float(2**attempt)
            logger.warning(
                "Respuesta temporal de Semantic Scholar; reintentando",
                extra={
                    "event_context": {
                        "method": method,
                        "path": normalized_path,
                        "status_code": status_code,
                        "attempt": attempt + 1,
                        "wait_seconds": wait_seconds,
                    }
                },
            )
            time.sleep(wait_seconds)
            continue

        raise SemanticScholarHTTPError(status_code, detail)

    raise SemanticScholarError("Error inesperado en la peticion a Semantic Scholar.")


def _normalize_doi(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = DOI_URL_RE.sub("", candidate)
    candidate = candidate.rstrip(").,;:]").strip().lower()
    return candidate


def _doi_paper_identifier(value: Any) -> tuple[str, str]:
    normalized_doi = _normalize_doi(value)
    if not normalized_doi:
        return "", ""
    return normalized_doi, f"DOI:{quote(normalized_doi, safe='')}"


def _response_error_detail(response: requests.Response) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        return ""
    return " ".join(text.split())[:300]


def _citation_count_cache_key(normalized_doi: str) -> str:
    digest = sha1(normalized_doi.encode("utf-8")).hexdigest()
    return f"semantic_scholar:citation_count:{digest}"


def _paper_id_cache_key(normalized_doi: str) -> str:
    digest = sha1(normalized_doi.encode("utf-8")).hexdigest()
    return f"semantic_scholar:paper_id:{digest}"


def _paper_metadata_cache_key(normalized_doi: str) -> str:
    digest = sha1(normalized_doi.encode("utf-8")).hexdigest()
    return f"semantic_scholar:paper_metadata:{digest}"


def _work_by_doi_cache_key(normalized_doi: str) -> str:
    digest = sha1(normalized_doi.encode("utf-8")).hexdigest()
    return f"semantic_scholar:work_by_doi:{digest}"


def _citing_papers_page_cache_key(paper_id: str, limit: int, offset: int) -> str:
    digest = sha1(f"{paper_id}:{limit}:{offset}".encode("utf-8")).hexdigest()
    return f"semantic_scholar:citing_papers:{digest}"


def _citing_papers_doi_page_cache_key(
    normalized_doi: str, limit: int, offset: int
) -> str:
    digest = sha1(f"{normalized_doi}:{limit}:{offset}".encode("utf-8")).hexdigest()
    return f"semantic_scholar:citing_papers_by_doi:{digest}"


def _normalize_authors(raw_authors: Any) -> List[str]:
    if not isinstance(raw_authors, list):
        return []
    out: List[str] = []
    for author in raw_authors:
        if isinstance(author, dict):
            name = str(author.get("name") or "").strip()
            if name:
                out.append(name)
    return out


def _normalize_paper_item(
    item: Dict[str, Any], *, source: str = "semantic_scholar"
) -> Dict[str, Any]:
    external_ids = item.get("externalIds") or {}
    return {
        "doi": _normalize_doi(external_ids.get("DOI")),
        "title": str(item.get("title") or "").strip(),
        "authors": _normalize_authors(item.get("authors")),
        "year": item.get("year") if isinstance(item.get("year"), int) else None,
        "venue": str(item.get("venue") or "").strip() or None,
        "url": str(item.get("url") or "").strip() or None,
        "source": source,
    }


def get_paper_by_id(
    paper_id: str, fields: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    paper_id = str(paper_id or "").strip()
    if not paper_id:
        return None
    data = _request_semantic_scholar_json(
        "GET",
        f"/paper/{quote(paper_id, safe=':%')}",
        params={"fields": fields or PAPER_DEFAULT_FIELDS},
    )
    return data if isinstance(data, dict) else None


def get_paper_by_doi(
    doi: str, fields: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    normalized_doi, paper_identifier = _doi_paper_identifier(doi)
    if not normalized_doi:
        return None
    return get_paper_by_id(paper_identifier, fields=fields)


def search_papers(
    query: str, limit: int = 10, fields: Optional[str] = None
) -> Dict[str, Any]:
    data = _request_semantic_scholar_json(
        "GET",
        "/paper/search",
        params={
            "query": query,
            "limit": limit,
            "fields": fields or PAPER_DEFAULT_FIELDS,
        },
    )
    return data if isinstance(data, dict) else {"data": []}


def get_paper_citations(
    paper_id: str,
    limit: int = 100,
    fields: Optional[str] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    data = _request_semantic_scholar_json(
        "GET",
        f"/paper/{quote(str(paper_id or '').strip(), safe='')}/citations",
        params={
            "fields": fields or CITATION_DEFAULT_FIELDS,
            "limit": limit,
            "offset": offset,
        },
    )
    return data if isinstance(data, dict) else {"data": []}


def get_paper_references(
    paper_id: str,
    limit: int = 100,
    fields: Optional[str] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    data = _request_semantic_scholar_json(
        "GET",
        f"/paper/{quote(str(paper_id or '').strip(), safe='')}/references",
        params={
            "fields": fields or REFERENCE_DEFAULT_FIELDS,
            "limit": limit,
            "offset": offset,
        },
    )
    return data if isinstance(data, dict) else {"data": []}


def search_author(
    query: str, limit: int = 10, fields: Optional[str] = None
) -> Dict[str, Any]:
    data = _request_semantic_scholar_json(
        "GET",
        "/author/search",
        params={
            "query": query,
            "limit": limit,
            "fields": fields or "name,aliases,paperCount,citationCount,hIndex",
        },
    )
    return data if isinstance(data, dict) else {"data": []}


def get_author_papers(
    author_id: str,
    limit: int = 100,
    fields: Optional[str] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    data = _request_semantic_scholar_json(
        "GET",
        f"/author/{quote(str(author_id or '').strip(), safe='')}/papers",
        params={
            "fields": fields or PAPER_DEFAULT_FIELDS,
            "limit": limit,
            "offset": offset,
        },
    )
    return data if isinstance(data, dict) else {"data": []}


def get_citation_counts_for_dois(
    dois: List[str],
    timeout: int = 20,
) -> Dict[str, int]:
    """
    Obtiene citationCount para varios DOI en una sola llamada batch.
    """
    raw_to_normalized: Dict[str, str] = {}
    normalized_dois: List[str] = []
    seen: set[str] = set()

    for raw_doi in dois:
        raw_key = str(raw_doi or "").strip()
        normalized_doi = _normalize_doi(raw_doi)
        if not normalized_doi:
            continue
        raw_to_normalized[raw_key] = normalized_doi
        if normalized_doi not in seen:
            normalized_dois.append(normalized_doi)
            seen.add(normalized_doi)

    if not normalized_dois:
        return {}

    key_by_doi = {doi: _citation_count_cache_key(doi) for doi in normalized_dois}
    paper_id_key_by_doi = {doi: _paper_id_cache_key(doi) for doi in normalized_dois}
    cached_values = cache.get_many(key_by_doi.values())
    cached_paper_ids = cache.get_many(paper_id_key_by_doi.values())
    counts_by_doi: Dict[str, int] = {}
    lookup_dois: List[str] = []
    lookup_seen: set[str] = set()

    def _add_lookup_doi(doi: str) -> None:
        if doi not in lookup_seen:
            lookup_dois.append(doi)
            lookup_seen.add(doi)

    for doi in normalized_dois:
        cache_key = key_by_doi[doi]
        if cache_key in cached_values:
            citation_count = int(cached_values[cache_key] or 0)
            counts_by_doi[doi] = citation_count
            if citation_count > 0 and paper_id_key_by_doi[doi] not in cached_paper_ids:
                _add_lookup_doi(doi)
        else:
            _add_lookup_doi(doi)

    if lookup_dois:
        for start in range(0, len(lookup_dois), CITATION_COUNT_BATCH_SIZE):
            chunk = lookup_dois[start : start + CITATION_COUNT_BATCH_SIZE]
            try:
                items = _request_semantic_scholar_json(
                    "POST",
                    "/paper/batch",
                    params={"fields": "paperId,externalIds,citationCount"},
                    json={"ids": [f"DOI:{doi}" for doi in chunk]},
                    timeout=timeout,
                )
            except SemanticScholarHTTPError as exc:
                if exc.status_code == 429:
                    raise SemanticScholarError(
                        "Rate limit en Semantic Scholar al consultar citas. Espera unos segundos e intentalo de nuevo."
                    ) from exc
                suffix = f": {exc.detail}" if exc.detail else "."
                raise SemanticScholarError(
                    f"Error en la API de Semantic Scholar al consultar citas (HTTP {exc.status_code}){suffix}"
                ) from exc
            if not isinstance(items, list):
                items = []

            values_to_cache = {}
            for index, doi in enumerate(chunk):
                item = items[index] if index < len(items) else None
                has_cached_count = doi in counts_by_doi
                citation_count = counts_by_doi.get(doi, 0)
                if isinstance(item, dict):
                    try:
                        citation_count = int(item.get("citationCount") or 0)
                    except (TypeError, ValueError):
                        citation_count = 0
                    paper_id = str(item.get("paperId") or "").strip()
                    if paper_id:
                        values_to_cache[_paper_id_cache_key(doi)] = paper_id

                counts_by_doi[doi] = citation_count
                if not has_cached_count or isinstance(item, dict):
                    values_to_cache[key_by_doi[doi]] = citation_count

            if values_to_cache:
                cache.set_many(values_to_cache, CITATION_COUNT_CACHE_TIMEOUT)

    counts: Dict[str, int] = {doi: counts_by_doi.get(doi, 0) for doi in normalized_dois}
    for raw_key, normalized_doi in raw_to_normalized.items():
        counts[raw_key] = counts_by_doi.get(normalized_doi, 0)

    return counts


def get_citing_papers_for_doi(doi: str, limit: int = 10) -> List[CitingPaper]:
    """
    Devuelve una lista de artículos que citan al paper identificado por este DOI.
    """
    normalized_doi, paper_identifier = _doi_paper_identifier(doi)
    if not normalized_doi:
        raise ValueError("El DOI no puede estar vacío.")

    fields = (
        "title,year,"
        "citations.title,"
        "citations.year,"
        "citations.externalIds,"
        "citations.openAccessPdf"
    )
    params = {
        "fields": fields,
        "limit": limit,
    }
    try:
        data = _request_semantic_scholar_json(
            "GET",
            f"/paper/{paper_identifier}",
            params=params,
            timeout=20,
        )
    except SemanticScholarHTTPError as exc:
        if exc.status_code == 404:
            raise SemanticScholarError(
                f"No se ha encontrado ningún paper con DOI '{doi}'."
            ) from exc
        suffix = f": {exc.detail}" if exc.detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {exc.status_code}){suffix}"
        ) from exc

    citation_items = data.get("citations") or []
    citing_papers: List[CitingPaper] = []

    for item in citation_items[:limit]:
        external_ids = item.get("externalIds") or {}
        open_access = item.get("openAccessPdf") or {}
        pdf_url = open_access.get("url")

        citing_papers.append(
            {
                "title": item.get("title") or "",
                "year": item.get("year"),
                "doi": external_ids.get("DOI"),
                "authors": None,
                "url": None,
                "open_access_pdf_url": pdf_url,
            }
        )

    return citing_papers


def get_work_by_doi(doi: str, timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Resuelve metadatos de un paper por DOI e incluye references/citations normalizadas.
    """
    normalized_doi, paper_identifier = _doi_paper_identifier(doi)
    if not normalized_doi:
        return None

    cache_key = _work_by_doi_cache_key(normalized_doi)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    fields = (
        "title,year,venue,externalIds,authors.name,url,"
        "references.title,references.year,references.venue,references.externalIds,references.authors.name,references.url,"
        "citations.title,citations.year,citations.venue,citations.externalIds,citations.authors.name,citations.url"
    )
    try:
        data = _request_semantic_scholar_json(
            "GET",
            f"/paper/{paper_identifier}",
            params={"fields": fields},
            timeout=timeout,
        )
    except SemanticScholarHTTPError as exc:
        if exc.status_code == 404:
            return None
        if exc.status_code == 429:
            raise SemanticScholarError("Rate limit en Semantic Scholar.") from exc
        suffix = f": {exc.detail}" if exc.detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {exc.status_code}){suffix}"
        ) from exc

    if not isinstance(data, dict):
        return None

    work = _normalize_paper_item(data, source="semantic_scholar")
    work["doi"] = work.get("doi") or normalized_doi

    references: List[Dict[str, Any]] = []
    for reference in data.get("references") or []:
        if not isinstance(reference, dict):
            continue
        references.append(_normalize_paper_item(reference, source="semantic_scholar"))

    citations: List[Dict[str, Any]] = []
    for citation in data.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        citations.append(_normalize_paper_item(citation, source="semantic_scholar"))

    work["references"] = references
    work["citations"] = citations
    cache.set(cache_key, work, WORK_BY_DOI_CACHE_TIMEOUT)
    return work


def get_paper_metadata_by_doi(doi: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """Devuelve solo los metadatos básicos de un paper (sin referencias ni citas)."""
    normalized_doi, paper_identifier = _doi_paper_identifier(doi)
    if not normalized_doi:
        return None

    cache_key = _paper_metadata_cache_key(normalized_doi)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        data = _request_semantic_scholar_json(
            "GET",
            f"/paper/{paper_identifier}",
            params={
                "fields": "title,year,venue,externalIds,authors.name,url,citationCount"
            },
            timeout=timeout,
        )
    except SemanticScholarHTTPError as exc:
        if exc.status_code == 404:
            return None
        if exc.status_code == 429:
            raise SemanticScholarError(
                "Rate limit en Semantic Scholar. Espera unos segundos e inténtalo de nuevo."
            ) from exc
        suffix = f": {exc.detail}" if exc.detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {exc.status_code}){suffix}"
        ) from exc

    if not isinstance(data, dict):
        return None

    paper = _normalize_paper_item(data, source="semantic_scholar")
    paper["doi"] = paper.get("doi") or normalized_doi
    paper["citation_count"] = data.get("citationCount", 0)
    cache.set(cache_key, paper, PAPER_METADATA_CACHE_TIMEOUT)
    return paper


def get_citing_papers_for_doi_paginated(
    doi: str, limit: int = 10, offset: int = 0
) -> tuple[List[CitingPaper], Optional[int]]:
    """
    Devuelve una lista paginada de articulos que citan un DOI y el total estimado.
    """
    normalized_doi, paper_identifier = _doi_paper_identifier(doi)
    if not normalized_doi:
        raise ValueError("El DOI no puede estar vacio.")

    doi_page_cache_key = _citing_papers_doi_page_cache_key(
        normalized_doi, limit, offset
    )
    paper_id_cache_key = _paper_id_cache_key(normalized_doi)
    paper_id: Optional[str] = cache.get(paper_id_cache_key)

    if not paper_id:
        try:
            paper_data = _request_semantic_scholar_json(
                "GET",
                f"/paper/{paper_identifier}",
                params={"fields": "paperId"},
                timeout=15,
            )
        except SemanticScholarHTTPError as exc:
            if exc.status_code == 404:
                raise SemanticScholarError(
                    f"No se ha encontrado ningun paper con DOI '{normalized_doi}'."
                ) from exc
            if exc.status_code == 429:
                cached_page = cache.get(doi_page_cache_key)
                if cached_page is not None:
                    return cached_page
                raise SemanticScholarError(
                    "Rate limit en Semantic Scholar al resolver el paper. Espera unos segundos e intentalo de nuevo."
                ) from exc
            suffix = f": {exc.detail}" if exc.detail else "."
            raise SemanticScholarError(
                f"Error en la API de Semantic Scholar al resolver el paper (HTTP {exc.status_code}){suffix}"
            ) from exc

        paper_id = (paper_data or {}).get("paperId")
        if not paper_id:
            raise SemanticScholarError(
                "No se pudo resolver el paperId en Semantic Scholar."
            )
        cache.set(paper_id_cache_key, paper_id, PAPER_ID_CACHE_TIMEOUT)

    page_cache_key = _citing_papers_page_cache_key(paper_id, limit, offset)
    cached_page = cache.get(page_cache_key)
    if cached_page is not None:
        cache.set(doi_page_cache_key, cached_page, CITING_PAPERS_CACHE_TIMEOUT)
        return cached_page

    fields = (
        "citingPaper.title,"
        "citingPaper.year,"
        "citingPaper.externalIds,"
        "citingPaper.authors,"
        "citingPaper.url,"
        "contexts"
    )
    params = {
        "fields": fields,
        "limit": limit,
        "offset": offset,
    }

    try:
        data = _request_semantic_scholar_json(
            "GET",
            f"/paper/{paper_id}/citations",
            params=params,
            timeout=20,
        )
    except SemanticScholarHTTPError as exc:
        if exc.status_code == 429:
            cached_page = cache.get(doi_page_cache_key)
            if cached_page is not None:
                return cached_page
            raise SemanticScholarError(
                "Rate limit en Semantic Scholar al cargar citantes. Espera unos segundos e intentalo de nuevo."
            ) from exc
        suffix = f": {exc.detail}" if exc.detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar al cargar citantes (HTTP {exc.status_code}){suffix}"
        ) from exc

    items = data.get("data") or []
    # La API devuelve "next" (offset siguiente) en lugar de "total"
    next_page_offset: Optional[int] = data.get("next")

    citing_papers: List[CitingPaper] = []
    for row in items:
        cp = row.get("citingPaper") or {}
        external_ids = cp.get("externalIds") or {}
        authors = ", ".join(a.get("name", "") for a in (cp.get("authors") or []))
        contexts = [
            c for c in (row.get("contexts") or []) if isinstance(c, str) and c.strip()
        ]
        citing_papers.append(
            {
                "title": cp.get("title") or "",
                "year": cp.get("year"),
                "doi": external_ids.get("DOI"),
                "authors": authors or None,
                "url": cp.get("url"),
                "open_access_pdf_url": None,
                "contexts": contexts,
            }
        )

    result = (citing_papers, next_page_offset)
    cache.set_many(
        {
            page_cache_key: result,
            doi_page_cache_key: result,
        },
        CITING_PAPERS_CACHE_TIMEOUT,
    )
    return result

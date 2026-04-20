from __future__ import annotations

import os
import re
from hashlib import sha1
from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import quote

import requests
from django.core.cache import cache

from .external_api import build_external_api_session

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
CITATION_COUNT_CACHE_TIMEOUT = 24 * 60 * 60
CITATION_COUNT_BATCH_SIZE = 100
PAPER_ID_CACHE_TIMEOUT = 24 * 60 * 60
PAPER_METADATA_CACHE_TIMEOUT = 24 * 60 * 60
WORK_BY_DOI_CACHE_TIMEOUT = 24 * 60 * 60
CITING_PAPERS_CACHE_TIMEOUT = 60 * 60


class SemanticScholarError(RuntimeError):
    """Errores relacionados con la API de Semantic Scholar."""


class CitingPaper(TypedDict):
    title: str
    year: Optional[int]
    doi: Optional[str]
    authors: Optional[str]
    url: Optional[str]
    open_access_pdf_url: Optional[str]


def _build_headers() -> dict:
    headers: dict = {"Accept": "application/json"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


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


def _normalize_paper_item(item: Dict[str, Any], *, source: str = "semantic_scholar") -> Dict[str, Any]:
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

    key_by_doi = {
        doi: _citation_count_cache_key(doi)
        for doi in normalized_dois
    }
    cached_values = cache.get_many(key_by_doi.values())
    counts_by_doi: Dict[str, int] = {}
    missing_dois: List[str] = []

    for doi in normalized_dois:
        cache_key = key_by_doi[doi]
        if cache_key in cached_values:
            counts_by_doi[doi] = int(cached_values[cache_key] or 0)
        else:
            missing_dois.append(doi)

    if missing_dois:
        session = build_external_api_session()
        url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/batch"

        for start in range(0, len(missing_dois), CITATION_COUNT_BATCH_SIZE):
            chunk = missing_dois[start:start + CITATION_COUNT_BATCH_SIZE]
            try:
                response = session.post(
                    url,
                    headers=_build_headers(),
                    params={"fields": "externalIds,citationCount"},
                    json={"ids": [f"DOI:{doi}" for doi in chunk]},
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise SemanticScholarError(
                    f"Error de conexion con Semantic Scholar: {exc}"
                ) from exc

            if response.status_code == 429:
                raise SemanticScholarError(
                    "Rate limit en Semantic Scholar al consultar citas. Espera unos segundos e intentalo de nuevo."
                )
            if response.status_code != 200:
                detail = _response_error_detail(response)
                suffix = f": {detail}" if detail else "."
                raise SemanticScholarError(
                    f"Error en la API de Semantic Scholar al consultar citas (HTTP {response.status_code}){suffix}"
                )

            items = response.json() if response.content else []
            if not isinstance(items, list):
                items = []

            values_to_cache = {}
            for index, doi in enumerate(chunk):
                item = items[index] if index < len(items) else None
                citation_count = 0
                if isinstance(item, dict):
                    try:
                        citation_count = int(item.get("citationCount") or 0)
                    except (TypeError, ValueError):
                        citation_count = 0

                counts_by_doi[doi] = citation_count
                values_to_cache[key_by_doi[doi]] = citation_count

            if values_to_cache:
                cache.set_many(values_to_cache, CITATION_COUNT_CACHE_TIMEOUT)

    counts: Dict[str, int] = {
        doi: counts_by_doi.get(doi, 0)
        for doi in normalized_dois
    }
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

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_identifier}"
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
    session = build_external_api_session()

    try:
        response = session.get(
            url,
            headers=_build_headers(),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(
            f"Error de conexión con Semantic Scholar: {exc}"
        ) from exc

    if response.status_code == 404:
        raise SemanticScholarError(f"No se ha encontrado ningún paper con DOI '{doi}'.")
    if response.status_code != 200:
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {response.status_code}): {response.text}"
        )

    data = response.json()

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

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_identifier}"
    fields = (
        "title,year,venue,externalIds,authors.name,url,"
        "references.title,references.year,references.venue,references.externalIds,references.authors.name,references.url,"
        "citations.title,citations.year,citations.venue,citations.externalIds,citations.authors.name,citations.url"
    )
    session = build_external_api_session()
    try:
        response = session.get(
            url,
            headers=_build_headers(),
            params={"fields": fields},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(f"Error de conexion con Semantic Scholar: {exc}") from exc

    if response.status_code == 404:
        return None
    if response.status_code == 429:
        raise SemanticScholarError("Rate limit en Semantic Scholar.")
    if response.status_code != 200:
        detail = _response_error_detail(response)
        suffix = f": {detail}" if detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {response.status_code}){suffix}"
        )

    data = response.json() if response.content else {}
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

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_identifier}"
    session = build_external_api_session()
    try:
        response = session.get(
            url,
            headers=_build_headers(),
            params={"fields": "title,year,venue,externalIds,authors.name,url,citationCount"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(f"Error de conexión con Semantic Scholar: {exc}") from exc

    if response.status_code == 404:
        return None
    if response.status_code == 429:
        raise SemanticScholarError("Rate limit en Semantic Scholar. Espera unos segundos e inténtalo de nuevo.")
    if response.status_code != 200:
        detail = _response_error_detail(response)
        suffix = f": {detail}" if detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {response.status_code}){suffix}"
        )

    data = response.json() if response.content else {}
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

    paper_id_cache_key = _paper_id_cache_key(normalized_doi)
    paper_id: Optional[str] = cache.get(paper_id_cache_key)

    session = build_external_api_session()
    if not paper_id:
        paper_url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_identifier}"
        try:
            paper_response = session.get(
                paper_url,
                headers=_build_headers(),
                params={"fields": "paperId"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise SemanticScholarError(
                f"Error de conexion con Semantic Scholar: {exc}"
            ) from exc

        if paper_response.status_code == 404:
            raise SemanticScholarError(f"No se ha encontrado ningun paper con DOI '{normalized_doi}'.")
        if paper_response.status_code == 429:
            raise SemanticScholarError(
                "Rate limit en Semantic Scholar al resolver el paper. Espera unos segundos e intentalo de nuevo."
            )
        if paper_response.status_code != 200:
            detail = _response_error_detail(paper_response)
            suffix = f": {detail}" if detail else "."
            raise SemanticScholarError(
                f"Error en la API de Semantic Scholar al resolver el paper (HTTP {paper_response.status_code}){suffix}"
            )

        paper_id = (paper_response.json() or {}).get("paperId")
        if not paper_id:
            raise SemanticScholarError(
                "No se pudo resolver el paperId en Semantic Scholar."
            )
        cache.set(paper_id_cache_key, paper_id, PAPER_ID_CACHE_TIMEOUT)

    page_cache_key = _citing_papers_page_cache_key(paper_id, limit, offset)
    cached_page = cache.get(page_cache_key)
    if cached_page is not None:
        return cached_page

    citations_url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_id}/citations"
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
        response = session.get(
            citations_url,
            headers=_build_headers(),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(
            f"Error de conexion con Semantic Scholar: {exc}"
        ) from exc

    if response.status_code == 429:
        raise SemanticScholarError(
            "Rate limit en Semantic Scholar al cargar citantes. Espera unos segundos e intentalo de nuevo."
        )
    if response.status_code != 200:
        detail = _response_error_detail(response)
        suffix = f": {detail}" if detail else "."
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar al cargar citantes (HTTP {response.status_code}){suffix}"
        )

    data = response.json() or {}
    items = data.get("data") or []
    # La API devuelve "next" (offset siguiente) en lugar de "total"
    next_page_offset: Optional[int] = data.get("next")

    citing_papers: List[CitingPaper] = []
    for row in items:
        cp = row.get("citingPaper") or {}
        external_ids = cp.get("externalIds") or {}
        authors = ", ".join(a.get("name", "") for a in (cp.get("authors") or []))
        contexts = [c for c in (row.get("contexts") or []) if isinstance(c, str) and c.strip()]
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
    cache.set(page_cache_key, result, CITING_PAPERS_CACHE_TIMEOUT)
    return result

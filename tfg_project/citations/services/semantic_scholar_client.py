from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, TypedDict

import requests

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)


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


def get_citing_papers_for_doi(doi: str, limit: int = 10) -> List[CitingPaper]:
    """
    Devuelve una lista de artículos que citan al paper identificado por este DOI.
    """
    if not doi:
        raise ValueError("El DOI no puede estar vacío.")

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/DOI:{doi}"
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
        response = requests.get(
            url,
            headers=_build_headers(),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(f"Error de conexión con Semantic Scholar: {exc}") from exc

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
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi:
        return None

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/DOI:{normalized_doi}"
    fields = (
        "title,year,venue,externalIds,authors.name,url,"
        "references.title,references.year,references.venue,references.externalIds,references.authors.name,references.url,"
        "citations.title,citations.year,citations.venue,citations.externalIds,citations.authors.name,citations.url"
    )
    try:
        response = requests.get(
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
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {response.status_code})."
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
    return work


def get_citing_papers_for_doi_paginated(
    doi: str, limit: int = 10, offset: int = 0
) -> tuple[List[CitingPaper], int]:
    """
    Devuelve una lista paginada de articulos que citan un DOI y el total estimado.
    """
    if not doi:
        raise ValueError("El DOI no puede estar vacio.")

    paper_url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/DOI:{doi}"
    try:
        paper_response = requests.get(
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
        raise SemanticScholarError(f"No se ha encontrado ningun paper con DOI '{doi}'.")
    if paper_response.status_code != 200:
        raise SemanticScholarError(
            "Error en la API de Semantic Scholar al resolver el paper."
        )

    paper_id = (paper_response.json() or {}).get("paperId")
    if not paper_id:
        raise SemanticScholarError("No se pudo resolver el paperId en Semantic Scholar.")

    citations_url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/{paper_id}/citations"
    fields = (
        "citingPaper.title,"
        "citingPaper.year,"
        "citingPaper.externalIds,"
        "citingPaper.authors,"
        "citingPaper.url"
    )
    params = {
        "fields": fields,
        "limit": limit,
        "offset": offset,
    }

    try:
        response = requests.get(
            citations_url,
            headers=_build_headers(),
            params=params,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise SemanticScholarError(
            f"Error de conexion con Semantic Scholar: {exc}"
        ) from exc

    if response.status_code != 200:
        raise SemanticScholarError(
            f"Error en la API de Semantic Scholar (HTTP {response.status_code})."
        )

    data = response.json() or {}
    items = data.get("data") or []
    total = int(data.get("total") or 0)

    citing_papers: List[CitingPaper] = []
    for row in items:
        cp = row.get("citingPaper") or {}
        external_ids = cp.get("externalIds") or {}
        authors = ", ".join(a.get("name", "") for a in (cp.get("authors") or []))
        citing_papers.append(
            {
                "title": cp.get("title") or "",
                "year": cp.get("year"),
                "doi": external_ids.get("DOI"),
                "authors": authors or None,
                "url": cp.get("url"),
                "open_access_pdf_url": None,
            }
        )

    return citing_papers, total

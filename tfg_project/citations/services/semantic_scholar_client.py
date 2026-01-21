from __future__ import annotations

import os
from typing import List, Optional, TypedDict

import requests

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")


class SemanticScholarError(RuntimeError):
    """Errores relacionados con la API de Semantic Scholar."""


class CitingPaper(TypedDict):
    """
    Estructura de datos para un artículo que cita, obtenido de Semantic Scholar.
    """

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

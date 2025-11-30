from __future__ import annotations

import os
from typing import List, Optional, TypedDict

import requests

SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")


class SemanticScholarError(RuntimeError):
    """Errores relacionados con la API de Semantic Scholar."""


class CitingPaper(TypedDict):
    title: str
    year: Optional[int]
    doi: Optional[str]
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
                "open_access_pdf_url": pdf_url,
            }
        )

    return citing_papers

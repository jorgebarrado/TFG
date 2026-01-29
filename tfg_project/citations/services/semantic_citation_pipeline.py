"""Pipeline de análisis semántico de citas.

Orquesta la obtención de artículos que citan a un original y el análisis
de sus PDFs para extraer los contextos específicos de las citas.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict

from .semantic_scholar_client import (
    CitingPaper,
    SemanticScholarError,
    get_citing_papers_for_doi,
)
from .pdf_citation_analyzer import (
    analyze_pdf_citations_from_url,
    PDFDownloadError,
)
from .papermage_extractor import ContextHit


class AnalyzedCitation(TypedDict):
    """Estructura de datos para un artículo citador analizado."""

    citing_title: str
    citing_year: Optional[int]
    citing_doi: Optional[str]
    pdf_url: Optional[str]
    contexts: List[ContextHit]


class SemanticCitationAnalysisResult(TypedDict):
    """Estructura del resultado global del análisis."""

    original_doi: str
    citing_count: int
    analyzed: List[AnalyzedCitation]
    errors: List[str]


def analyze_citations_for_original_doi(
    original_doi: str,
    max_citing_papers: int = 5,
) -> SemanticCitationAnalysisResult:
    """Obtiene y analiza los citadores de un artículo por su DOI.

    Busca quién cita al artículo en Semantic Scholar y, para aquellos con
    PDF Open Access, descarga y analiza el documento en busca de los contextos
    textuales de la cita.

    Args:
        original_doi (str): DOI del artículo citado (original).
        max_citing_papers (int, optional): Límite de citadores a analizar. Default 5.

    Returns:
        SemanticCitationAnalysisResult: Resultados del análisis incluyendo contextos y errores.
    """
    result: SemanticCitationAnalysisResult = {
        "original_doi": original_doi,
        "citing_count": 0,
        "analyzed": [],
        "errors": [],
    }

    try:
        citing_papers: List[CitingPaper] = get_citing_papers_for_doi(
            doi=original_doi,
            limit=max_citing_papers,
        )
    except (ValueError, SemanticScholarError) as exc:
        result["errors"].append(str(exc))
        return result

    result["citing_count"] = len(citing_papers)

    for paper in citing_papers:
        pdf_url = paper.get("open_access_pdf_url")
        if not pdf_url:
            result["errors"].append(
                f"No hay PDF open access para el artículo que cita: '{paper.get('title', '')}'."
            )
            continue

        try:
            contexts = analyze_pdf_citations_from_url(pdf_url)
        except (PDFDownloadError, RuntimeError, FileNotFoundError, ValueError) as exc:
            result["errors"].append(
                f"Error al analizar PDF '{pdf_url}' para el paper '{paper.get('title', '')}': {exc}"
            )
            continue

        analyzed_entry: AnalyzedCitation = {
            "citing_title": paper.get("title", ""),
            "citing_year": paper.get("year"),
            "citing_doi": paper.get("doi"),
            "pdf_url": pdf_url,
            "contexts": contexts,
        }
        result["analyzed"].append(analyzed_entry)

    return result

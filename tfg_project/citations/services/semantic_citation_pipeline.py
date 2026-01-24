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
    """Representa el resultado del análisis de una cita.

    Attributes:
        citing_title (str): Título del artículo citante.
        citing_year (Optional[int]): Año del artículo citante.
        citing_doi (Optional[str]): DOI del artículo citante.
        pdf_url (Optional[str]): URL del PDF analizado.
        contexts (List[ContextHit]): Lista de contextos de cita encontrados en el PDF.
    """
    citing_title: str
    citing_year: Optional[int]
    citing_doi: Optional[str]
    pdf_url: Optional[str]
    contexts: List[ContextHit]


class SemanticCitationAnalysisResult(TypedDict):
    """Representa el resultado global del análisis de citas para un DOI.

    Attributes:
        original_doi (str): DOI del artículo original (citado).
        citing_count (int): Número de artículos citantes encontrados en Semantic Scholar.
        analyzed (List[AnalyzedCitation]): Lista de análisis exitosos de artículos citantes.
        errors (List[str]): Lista de errores encontrados durante el proceso.
    """
    original_doi: str
    citing_count: int
    analyzed: List[AnalyzedCitation]
    errors: List[str]


def analyze_citations_for_original_doi(
    original_doi: str,
    max_citing_papers: int = 5,
) -> SemanticCitationAnalysisResult:
    """Orquesta el análisis de citas para un DOI dado.

    1. Busca artículos que citan al original_doi usando Semantic Scholar.
    2. Para cada artículo citante con PDF Open Access, descarga y analiza el PDF.
    3. Extrae los contextos donde se cita al artículo original.
    4. Compila los resultados y errores.

    Args:
        original_doi (str): DOI del artículo a analizar (el que recibe las citas).
        max_citing_papers (int, optional): Máximo de artículos citantes a procesar. Por defecto 5.

    Returns:
        SemanticCitationAnalysisResult: Diccionario con los resultados del análisis.
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

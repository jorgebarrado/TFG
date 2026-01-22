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
    """
    Representa el resultado del análisis de un artículo citante.

    Attributes:
        citing_title (str): Título del artículo que cita.
        citing_year (Optional[int]): Año de publicación del artículo que cita.
        citing_doi (Optional[str]): DOI del artículo que cita.
        pdf_url (Optional[str]): URL del PDF de acceso abierto utilizado.
        contexts (List[ContextHit]): Lista de contextos donde se encontró la cita original.
    """
    citing_title: str
    citing_year: Optional[int]
    citing_doi: Optional[str]
    pdf_url: Optional[str]
    contexts: List[ContextHit]


class SemanticCitationAnalysisResult(TypedDict):
    """
    Resultado global del análisis de citas para un DOI original.

    Attributes:
        original_doi (str): El DOI del artículo analizado.
        citing_count (int): Número de artículos citantes encontrados en Semantic Scholar (limitado por la petición).
        analyzed (List[AnalyzedCitation]): Lista de análisis detallados por artículo citante.
        errors (List[str]): Lista de mensajes de error ocurridos durante el proceso.
    """
    original_doi: str
    citing_count: int
    analyzed: List[AnalyzedCitation]
    errors: List[str]


def analyze_citations_for_original_doi(
    original_doi: str,
    max_citing_papers: int = 5,
) -> SemanticCitationAnalysisResult:
    """
    Realiza un análisis profundo de cómo es citado un artículo original.

    1. Busca en Semantic Scholar quién cita al DOI original.
    2. Para cada artículo citante (hasta max_citing_papers), intenta obtener su PDF de acceso abierto.
    3. Descarga y analiza el PDF buscando contextos donde se cita al original.

    Args:
        original_doi (str): DOI del artículo original 'A'.
        max_citing_papers (int, optional): Límite de artículos citantes 'B' a analizar. Defaults to 5.

    Returns:
        SemanticCitationAnalysisResult: Estructura con los resultados del análisis.
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

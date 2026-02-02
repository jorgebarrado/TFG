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
    """Representa un artículo que cita al original, junto con el análisis de su contexto.

    Attributes:
        citing_title (str): Título del artículo citador.
        citing_year (int, optional): Año de publicación.
        citing_doi (str, optional): DOI del citador.
        pdf_url (str, optional): URL del PDF de acceso abierto (si existe).
        contexts (list): Lista de contextos (ContextHit) hallados en el PDF.
    """

    citing_title: str
    citing_year: Optional[int]
    citing_doi: Optional[str]
    pdf_url: Optional[str]
    contexts: List[ContextHit]


class SemanticCitationAnalysisResult(TypedDict):
    """Resultado global del análisis de citaciones semánticas para un DOI.

    Attributes:
        original_doi (str): El DOI analizado.
        citing_count (int): Número total de citadores analizados.
        analyzed (list): Lista de AnalyzedCitation con los resultados por paper.
        errors (list): Lista de mensajes de error ocurridos durante el proceso.
    """

    original_doi: str
    citing_count: int
    analyzed: List[AnalyzedCitation]
    errors: List[str]


def analyze_citations_for_original_doi(
    original_doi: str,
    max_citing_papers: int = 5,
) -> SemanticCitationAnalysisResult:
    """Obtiene artículos que citan a un DOI dado y analiza sus contextos de cita.

    Utiliza Semantic Scholar para encontrar quién cita al artículo original (A),
    y luego intenta descargar y analizar el PDF de cada citador (B) para encontrar
    dónde y cómo se menciona a (A).

    Args:
        original_doi (str): DOI del artículo original (A).
        max_citing_papers (int, optional): Límite de papers citadores a analizar. Defaults to 5.

    Returns:
        SemanticCitationAnalysisResult: Estructura con los resultados del análisis y posibles errores.
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

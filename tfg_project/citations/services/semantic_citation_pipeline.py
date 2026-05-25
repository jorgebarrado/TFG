from __future__ import annotations

from typing import List, Optional, TypedDict

from citations.logging_utils import get_logger, log_phase

from .papermage_extractor import ContextHit
from .pdf_citation_analyzer import (
    PDFDownloadError,
    analyze_pdf_citations_from_url,
)
from .semantic_scholar_client import (
    CitingPaper,
    SemanticScholarError,
    get_citing_papers_for_doi,
)

logger = get_logger("citations.pipeline")


class AnalyzedCitation(TypedDict):
    citing_title: str
    citing_year: Optional[int]
    citing_doi: Optional[str]
    pdf_url: Optional[str]
    contexts: List[ContextHit]


class SemanticCitationAnalysisResult(TypedDict):
    original_doi: str
    citing_count: int
    analyzed: List[AnalyzedCitation]
    errors: List[str]


def analyze_citations_for_original_doi(
    original_doi: str,
    max_citing_papers: int = 5,
) -> SemanticCitationAnalysisResult:
    """
    Dado el DOI de un artículo 'A', obtiene citadores desde Semantic Scholar y analiza sus PDFs.
    """
    with log_phase(
        logger,
        "analyze_citations_for_original_doi",
        original_doi=original_doi,
        max_citing_papers=max_citing_papers,
    ):
        result: SemanticCitationAnalysisResult = {
            "original_doi": original_doi,
            "citing_count": 0,
            "analyzed": [],
            "errors": [],
        }

        try:
            logger.debug(
                f"Pidiendo a SemanticScholar los papers que citan al DOI {original_doi}"
            )
            citing_papers: List[CitingPaper] = get_citing_papers_for_doi(
                doi=original_doi,
                limit=max_citing_papers,
            )
            logger.info(
                f"SemanticScholar devolvió {len(citing_papers)} citadores para el DOI {original_doi}"
            )
        except (ValueError, SemanticScholarError) as exc:
            logger.error(
                f"Fallo al obtener papers citadores para el DOI {original_doi}: {exc}",
                exc_info=True,
            )
            result["errors"].append(str(exc))
            return result

        result["citing_count"] = len(citing_papers)

        for paper in citing_papers:
            title = paper.get("title", "")
            pdf_url = paper.get("open_access_pdf_url")
            logger.debug(
                f"Procesando citador: '{title[:100]}' (DOI: {paper.get('doi')})"
            )

            if not pdf_url:
                msg = f"No hay PDF open access para el artículo que cita: '{title}'."
                logger.warning(msg)
                result["errors"].append(msg)
                continue

            try:
                logger.debug(
                    f"Iniciando análisis de PDF para citador '{title[:50]}' en {pdf_url}"
                )
                contexts = analyze_pdf_citations_from_url(pdf_url)
                logger.info(
                    f"Análisis de PDF completado para citador '{title[:50]}'. {len(contexts)} contextos encontrados."
                )
            except (
                PDFDownloadError,
                RuntimeError,
                FileNotFoundError,
                ValueError,
            ) as exc:
                msg = f"Error al analizar PDF '{pdf_url}' para el paper '{title[:50]}': {exc}"
                logger.error(msg, exc_info=True)
                result["errors"].append(msg)
                continue

            analyzed_entry: AnalyzedCitation = {
                "citing_title": title,
                "citing_year": paper.get("year"),
                "citing_doi": paper.get("doi"),
                "pdf_url": pdf_url,
                "contexts": contexts,
            }
            result["analyzed"].append(analyzed_entry)

        logger.info(
            f"Pipeline completado para {original_doi}: {len(result['analyzed'])} citadores analizados exitosamente, {len(result['errors'])} errores."
        )
        return result

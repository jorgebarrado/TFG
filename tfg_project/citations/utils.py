import logging
import xml.etree.ElementTree as ET

from .services.external_api import build_external_api_session
from .services.semantic_scholar_client import (
    SemanticScholarError,
    get_citation_counts_for_dois,
    get_paper_by_doi,
    get_paper_citations,
)

logger = logging.getLogger("citations.semantic_scholar")


def get_articles_from_dblp(dblp_url):
    """Obtiene la lista de publicaciones de un autor desde su perfil de DBLP.

    Args:
        dblp_url (str): La URL de la página de perfil del autor en DBLP
            (puede ser la versión .html o .xml).

    Returns:
        list: Una lista de diccionarios, donde cada diccionario representa
            una publicación y contiene 'title', 'doi' y 'type'.
            Retorna una lista vacía si ocurre un error.
    """
    try:
        session = build_external_api_session()
        # Convertir la URL HTML en URL XML
        if dblp_url.endswith(".html"):
            dblp_xml_url = dblp_url.replace(".html", ".xml")
        elif dblp_url.endswith(".xml"):
            dblp_xml_url = dblp_url
        else:
            return []

        response = session.get(dblp_xml_url, timeout=10)
        response.raise_for_status()

        root = ET.fromstring(response.content)

        publications = []
        for publ in root.findall("r"):
            entry = publ[0]

            title_elem = entry.find("title")
            doi_elem = entry.find("ee")

            title = title_elem.text if title_elem is not None else "Sin título"
            doi = doi_elem.text if doi_elem is not None else None
            if doi_elem is not None and doi_elem.text and "doi.org/" in doi_elem.text:
                doi = doi_elem.text.split("doi.org/")[-1].strip()
            else:
                doi = None

            publications.append(
                {
                    "title": title,
                    "doi": doi,
                    "type": entry.tag,
                }
            )

        return publications

    except Exception:
        logger.exception("Error al obtener publicaciones desde DBLP")
        return []


def get_citing_articles(doi):
    """Recupera los artículos que citan a un DOI específico usando la API de Semantic Scholar.

    Args:
        doi (str): El DOI del artículo para el cual se buscan las citas.

    Returns:
        list: Una lista de diccionarios, cada uno representando un artículo
            citador con su 'title', 'authors', 'year', 'doi' y 'url'.
            Retorna una lista vacía si la API falla o no hay citas.
    """
    try:
        paper = get_paper_by_doi(doi, fields="paperId,citationCount")
        if not paper:
            return []
        paper_id = paper.get("paperId")
        if not paper_id:
            return []
        data = get_paper_citations(
            paper_id,
            limit=100,
            fields=(
                "citingPaper.title,citingPaper.authors,"
                "citingPaper.year,citingPaper.externalIds,citingPaper.url"
            ),
        )
        citations = data.get("data", [])

        result = []
        for row in citations:
            c = row.get("citingPaper") or {}
            external_ids = c.get("externalIds") or {}
            result.append(
                {
                    "title": c.get("title"),
                    "authors": ", ".join(a["name"] for a in c.get("authors", [])),
                    "year": c.get("year"),
                    "doi": external_ids.get("DOI"),
                    "url": c.get("url"),
                }
            )

        return result

    except (SemanticScholarError, ValueError, TypeError) as exc:
        logger.warning(
            "Error en Semantic Scholar al obtener citantes doi=%s error=%s", doi, exc
        )
        return []


def check_doi_has_citations(doi):
    """Verifica si un artículo tiene al menos una cita según Semantic Scholar.

    Args:
        doi (str): El DOI del artículo a verificar.

    Returns:
        bool: True si el artículo tiene una o más citas, False en caso
            contrario o si ocurre un error.
    """
    try:
        data = get_paper_by_doi(doi, fields="citationCount")
        return bool(data and data.get("citationCount", 0) > 0)
    except (SemanticScholarError, ValueError, TypeError) as exc:
        logger.warning(
            "Error consultando DOI en Semantic Scholar doi=%s error=%s", doi, exc
        )
        return False


def get_citation_count(doi):
    """Obtiene el número total de citas para un DOI específico desde Semantic Scholar.

    Args:
        doi (str): El DOI del artículo cuyo conteo de citas se desea obtener.

    Returns:
        int: El número total de citas. Retorna 0 si no se encuentra el
            artículo, no tiene citas o hay un error en la solicitud.
    """
    try:
        return get_citation_counts_for_dois([doi]).get(str(doi or "").strip(), 0)
    except (SemanticScholarError, ValueError, TypeError) as e:
        logger.warning(
            "Error al obtener citationCount en Semantic Scholar doi=%s error=%s", doi, e
        )
        return 0

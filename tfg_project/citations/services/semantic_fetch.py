import requests
import logging

from citations.logging_utils import get_logger, log_event

logger = get_logger("citations.services.semantic_fetch")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
CR_BASE = "https://api.crossref.org"


def _safe_get(url, params=None, timeout=12):
    """
    Realiza una solicitud GET a una URL de forma segura, manejando errores de conexión y timeouts.

    Args:
        url (str): La URL a la que se realizará la solicitud.
        params (dict, optional): Un diccionario de parámetros para la solicitud. Defaults to None.
        timeout (int, optional): El tiempo de espera para la solicitud. Defaults to 12.

    Returns:
        dict: El JSON de la respuesta si la solicitud es exitosa, de lo contrario None.
    """
    headers = {"User-Agent": "CiteCheck/1.0 (mailto:you@example.com)"}
    try:
        r = requests.get(url, params=params or {}, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log_event(
            logger,
            logging.WARNING,
            "external_request_failed",
            message=f"Petición externa fallida con estado {r.status_code}",
            url=url,
            status_code=r.status_code,
        )
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            "external_request_failed",
            message=f"Excepción en petición externa: {e}",
            exc_info=True,
            url=url,
            error=str(e),
        )
    return None


def get_s2_paperid_and_count(doi: str) -> tuple[str | None, int]:
    """
    Obtiene el paperId y el número de citas de un artículo desde Semantic Scholar.

    Args:
        doi (str): El DOI del artículo.

    Returns:
        tuple[str | None, int]: Una tupla con el paperId y el número de citas, o (None, 0) si no se encuentra.
    """
    url = f"{S2_BASE}/paper/DOI:{doi}"
    data = _safe_get(url, params={"fields": "paperId,citationCount"})
    if not data:
        log_event(
            logger,
            logging.WARNING,
            "s2_paperid_not_found",
            message=f"No se encontró paperId en S2 para el DOI: {doi}",
            doi=doi,
        )
        return None, 0

    paper_id = data.get("paperId")
    count = int(data.get("citationCount") or 0)
    log_event(
        logger,
        logging.DEBUG,
        "s2_paperid_fetched",
        message=f"PaperId obtenido para {doi}: {paper_id} ({count} citas)",
        doi=doi,
        paper_id=paper_id,
        count=count,
    )
    return paper_id, count


def get_s2_citations(doi: str, limit: int = 100) -> list[dict]:
    """
    Obtiene una lista de citas para un artículo desde Semantic Scholar.

    Args:
        doi (str): El DOI del artículo.
        limit (int, optional): El número máximo de citas a obtener. Defaults to 100.

    Returns:
        list[dict]: Una lista de diccionarios, donde cada uno representa una cita.
    """
    paper_id, count = get_s2_paperid_and_count(doi)
    if not paper_id or count == 0:
        return []

    out: list[dict] = []
    offset = 0
    while True:
        url = f"{S2_BASE}/paper/{paper_id}/citations"
        params = {
            "fields": "citingPaper.title,citingPaper.authors,"
            "citingPaper.year,citingPaper.externalIds,citingPaper.url",
            "limit": min(limit, 100),
            "offset": offset,
        }
        data = _safe_get(url, params=params)
        if not data or not data.get("data"):
            break

        for row in data["data"]:
            cp = row.get("citingPaper") or {}
            ext = cp.get("externalIds") or {}
            out.append(
                {
                    "title": cp.get("title"),
                    "authors": ", ".join(
                        a.get("name", "") for a in (cp.get("authors") or [])
                    ),
                    "year": cp.get("year"),
                    "doi": ext.get("DOI"),
                    "url": cp.get("url"),
                }
            )
        offset += params["limit"]
        if offset >= count or offset >= 1000:  # cota de seguridad
            break
    return out


def get_crossref_citations(doi: str, rows: int = 100) -> list[dict]:
    """
    Obtiene citas de CrossRef como alternativa si Semantic Scholar no devuelve resultados.

    Args:
        doi (str): El DOI del artículo.
        rows (int, optional): El número máximo de citas a obtener. Defaults to 100.

    Returns:
        list[dict]: Una lista de diccionarios, donde cada uno representa una cita.
    """
    url = f"{CR_BASE}/works"
    # Nota: rows máx ~1000; aquí 100 es razonable para UI
    params = {
        "filter": f"reference.doi:{doi}",
        "rows": rows,
        "select": "title,author,issued,DOI,URL",
    }
    data = _safe_get(url, params=params)
    items = (data or {}).get("message", {}).get("items", [])
    out: list[dict] = []
    for it in items:
        title = (it.get("title") or [""])[0]
        authors = ", ".join(
            [
                f"{a.get('family', '')}" if isinstance(a, dict) else ""
                for a in (it.get("author") or [])
            ]
        )
        year = None
        try:
            year = it.get("issued", {}).get("date-parts", [[None]])[0][0]
        except Exception:
            pass
        out.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "doi": it.get("DOI"),
                "url": it.get("URL"),
                "source": "crossref",
            }
        )
    return out


def get_citations_with_fallback(doi: str) -> tuple[int, list[dict], str]:
    """
    Obtiene citas para un DOI, intentando primero con Semantic Scholar y luego con CrossRef.

    Args:
        doi (str): El DOI del artículo.

    Returns:
        tuple[int, list[dict], str]: Una tupla que contiene el número estimado de citas,
        la lista de citas y la fuente de datos utilizada ('s2', 'crossref', o 'none').
    """
    s2_list = get_s2_citations(doi)
    if s2_list:
        return len(s2_list), s2_list, "s2"

    # Si S2 no devuelve nada pero el contador era >0, probamos Crossref:
    cr_list = get_crossref_citations(doi)
    if cr_list:
        return len(cr_list), cr_list, "crossref"

    # Nada
    _, count = get_s2_paperid_and_count(doi)  # para reportar el count si existe

    log_event(
        logger,
        logging.INFO,
        "citations_fetch_fallback_none",
        message=f"No se encontraron citas tras fallbacks para DOI: {doi}",
        doi=doi,
        count=count,
    )
    return count, [], "none"

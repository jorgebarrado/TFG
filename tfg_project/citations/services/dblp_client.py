from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional, TypedDict

import requests


class DBLPClientError(RuntimeError):
    """Errores relacionados con la comunicación o procesamiento de DBLP."""


class DBLPPaper(TypedDict):
    """Estructura de datos para un artículo obtenido de DBLP.

    Attributes:
        title (str): Título del artículo.
        year (Optional[int]): Año de publicación.
        doi (Optional[str]): DOI del artículo.
        type (str): Tipo de publicación (e.g., 'article', 'inproceedings').
        authors (List[str]): Lista de nombres de autores.
        url (Optional[str]): URL del recurso.
        dblp_key (Optional[str]): Clave única en DBLP.
    """
    title: str
    year: Optional[int]
    doi: Optional[str]
    type: str
    authors: List[str]
    url: Optional[str]
    dblp_key: Optional[str]


def _normalize_dblp_url(dblp_url: str) -> Optional[str]:
    """Normaliza una URL de DBLP para asegurarse de que apunta al formato XML.

    Convierte URLs de perfil HTML a su versión XML para facilitar el parseo.

    Args:
        dblp_url (str): La URL proporcionada (puede ser .html o .xml).

    Returns:
        Optional[str]: La URL normalizada terminada en .xml, o None si la entrada es inválida.
    """
    if not dblp_url:
        return None
    if dblp_url.endswith(".xml"):
        return dblp_url
    if dblp_url.endswith(".html"):
        return dblp_url.replace(".html", ".xml")
    return None


def _extract_doi(ee_text: str) -> Optional[str]:
    """Extrae el DOI de un texto de enlace electrónico (ee) de DBLP.

    Args:
        ee_text (str): El texto del campo 'ee' del XML de DBLP.

    Returns:
        Optional[str]: El DOI extraído si se encuentra, o None.
    """
    if not ee_text:
        return None
    if "doi.org/" in ee_text:
        return ee_text.split("doi.org/")[-1].strip()
    if ee_text.startswith("DOI:"):
        return ee_text.replace("DOI:", "").strip()
    return None


def get_author_papers(dblp_url: str, timeout: int = 12) -> List[DBLPPaper]:
    """Obtiene la lista de publicaciones de un autor desde DBLP.

    Realiza una petición HTTP al perfil XML del autor en DBLP y parseea
    sus publicaciones.

    Args:
        dblp_url (str): URL del perfil del autor en DBLP.
        timeout (int, optional): Tiempo máximo de espera en segundos. Por defecto 12.

    Returns:
        List[DBLPPaper]: Lista de diccionarios con la información de cada publicación.

    Raises:
        DBLPClientError: Si la URL es inválida, hay error de conexión o el XML está mal formado.
    """
    dblp_xml_url = _normalize_dblp_url(dblp_url)
    if not dblp_xml_url:
        raise DBLPClientError("La URL de DBLP no es valida. Usa el enlace .html o .xml.")

    try:
        response = requests.get(dblp_xml_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DBLPClientError(
            f"No se pudo conectar con DBLP. Intenta de nuevo mas tarde. ({exc})"
        ) from exc

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise DBLPClientError(
            "No se pudo interpretar la respuesta de DBLP. Verifica la URL."
        ) from exc

    publications: List[DBLPPaper] = []

    for publ in root.findall("r"):
        entry = publ[0]
        title = entry.findtext("title") or "Sin titulo"
        year_raw = entry.findtext("year") or ""
        year = int(year_raw) if year_raw.isdigit() else None
        authors = [a.text for a in entry.findall("author") if a.text]
        ee_items = [e.text for e in entry.findall("ee") if e.text]

        doi = None
        url = None
        for ee in ee_items:
            doi = doi or _extract_doi(ee)
            if not url and ee and not doi:
                url = ee

        publications.append(
            {
                "title": title,
                "year": year,
                "doi": doi,
                "type": entry.tag,
                "authors": authors,
                "url": url,
                "dblp_key": entry.attrib.get("key"),
            }
        )

    return publications

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional, TypedDict

import requests


class DBLPClientError(RuntimeError):
    """Errores relacionados con DBLP."""


class DBLPPaper(TypedDict):
    """Representa un artículo académico obtenido de DBLP."""
    title: str
    year: Optional[int]
    doi: Optional[str]
    type: str
    authors: List[str]
    url: Optional[str]
    dblp_key: Optional[str]


def _normalize_dblp_url(dblp_url: str) -> Optional[str]:
    """Convierte una URL de perfil DBLP (.html) a su versión XML."""
    if not dblp_url:
        return None
    if dblp_url.endswith(".xml"):
        return dblp_url
    if dblp_url.endswith(".html"):
        return dblp_url.replace(".html", ".xml")
    return None


def _extract_doi(ee_text: str) -> Optional[str]:
    """Extrae el DOI de un campo 'ee' (electronic edition) de DBLP."""
    if not ee_text:
        return None
    if "doi.org/" in ee_text:
        return ee_text.split("doi.org/")[-1].strip()
    if ee_text.startswith("DOI:"):
        return ee_text.replace("DOI:", "").strip()
    return None


def get_author_papers(dblp_url: str, timeout: int = 12) -> List[DBLPPaper]:
    """
    Obtiene la lista completa de publicaciones de un autor desde DBLP.

    Parsea el XML del perfil del autor para extraer título, año, DOI, autores
    y otros metadatos relevantes de cada publicación.

    Args:
        dblp_url (str): URL del perfil de DBLP (puede ser .html o .xml).
        timeout (int): Tiempo máximo de espera para la solicitud.

    Returns:
        List[DBLPPaper]: Lista de diccionarios con la información de los artículos.

    Raises:
        DBLPClientError: Si la URL es inválida, falla la conexión o el parseo XML.
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

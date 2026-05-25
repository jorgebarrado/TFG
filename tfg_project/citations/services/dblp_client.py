from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from hashlib import sha1
from typing import List, Optional, TypedDict
from urllib.parse import urlsplit, urlunsplit

import requests
from django.core.cache import cache

from .external_api import build_external_api_session


class DBLPClientError(RuntimeError):
    """Errores relacionados con DBLP."""


class DBLPPaper(TypedDict):
    title: str
    year: Optional[int]
    doi: Optional[str]
    type: str
    authors: List[str]
    url: Optional[str]
    dblp_key: Optional[str]


DBLP_CACHE_TIMEOUT = 30 * 60
DBLP_MAX_ATTEMPTS = 3
DBLP_RETRY_DELAYS = (0.7, 1.5)
DBLP_REQUEST_HEADERS = {
    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "TFG-Citations/1.0",
}


def _normalize_dblp_url(dblp_url: str) -> Optional[str]:
    candidate = str(dblp_url or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if not parsed.scheme or not parsed.netloc:
        return None

    path = parsed.path.rstrip("/")
    if path.endswith(".xml"):
        normalized_path = path
    elif path.endswith(".html"):
        normalized_path = f"{path[:-5]}.xml"
    elif "/pid/" in path:
        normalized_path = f"{path}.xml"
    else:
        return None

    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def _dblp_cache_key(dblp_xml_url: str) -> str:
    digest = sha1(dblp_xml_url.encode("utf-8")).hexdigest()
    return f"dblp:author-papers:{digest}"


def _extract_doi(ee_text: str) -> Optional[str]:
    if not ee_text:
        return None
    if "doi.org/" in ee_text:
        return ee_text.split("doi.org/")[-1].strip()
    if ee_text.startswith("DOI:"):
        return ee_text.replace("DOI:", "").strip()
    return None


def _raise_for_dblp_http_error(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            wait_hint = (
                f" Espera {retry_after} segundos antes de reintentarlo."
                if retry_after
                else ""
            )
            raise DBLPClientError(
                "DBLP esta limitando temporalmente las peticiones." f"{wait_hint}"
            ) from exc
        raise


def _fetch_dblp_xml(dblp_xml_url: str, timeout: int) -> bytes:
    session = build_external_api_session()
    last_error: Optional[requests.RequestException] = None

    for attempt in range(DBLP_MAX_ATTEMPTS):
        try:
            response = session.get(
                dblp_xml_url,
                headers=DBLP_REQUEST_HEADERS,
                timeout=timeout,
            )
            _raise_for_dblp_http_error(response)
            return response.content
        except DBLPClientError:
            raise
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
            if attempt >= DBLP_MAX_ATTEMPTS - 1:
                break
            time.sleep(DBLP_RETRY_DELAYS[attempt])
        except requests.RequestException as exc:
            raise DBLPClientError(
                f"No se pudo conectar con DBLP. Intenta de nuevo mas tarde. ({exc})"
            ) from exc

    raise DBLPClientError(
        "No se pudo conectar con DBLP tras varios intentos. "
        f"Intenta de nuevo mas tarde. ({last_error})"
    )


def get_author_papers(dblp_url: str, timeout: int = 12) -> List[DBLPPaper]:
    """
    Obtiene la lista de publicaciones de un autor desde DBLP.
    """
    dblp_xml_url = _normalize_dblp_url(dblp_url)
    if not dblp_xml_url:
        raise DBLPClientError(
            "La URL de DBLP no es valida. Usa el enlace .html o .xml."
        )

    cache_key = _dblp_cache_key(dblp_xml_url)
    cached_publications = cache.get(cache_key)
    if cached_publications is not None:
        return cached_publications

    try:
        root = ET.fromstring(_fetch_dblp_xml(dblp_xml_url, timeout))
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

    cache.set(cache_key, publications, DBLP_CACHE_TIMEOUT)
    return publications

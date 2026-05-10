# citations/services/semanticscholar.py
from __future__ import annotations

import os
import tempfile
from typing import Optional

import requests

from .semantic_scholar_client import SemanticScholarError, get_paper_by_doi


def get_openaccess_pdf_url(doi: str, timeout: int = 15) -> Optional[str]:
    """
    Obtiene la URL de un PDF de acceso abierto desde Semantic Scholar usando el DOI del artículo.

    Args:
        doi (str): El DOI del artículo.
        timeout (int, optional): El tiempo de espera para la solicitud. Defaults to 15.

    Returns:
        Optional[str]: La URL del PDF si se encuentra, de lo contrario None.
    """
    try:
        data = get_paper_by_doi(doi, fields="openAccessPdf")
    except SemanticScholarError:
        return None
    pdf = data.get("openAccessPdf") or {}
    return pdf.get("url")


def download_pdf_to_temp(url: str, timeout: int = 30) -> Optional[str]:
    """
    Descarga un archivo PDF desde una URL a un archivo temporal.

    Args:
        url (str): La URL del PDF a descargar.
        timeout (int, optional): El tiempo de espera para la solicitud. Defaults to 30.

    Returns:
        Optional[str]: La ruta al archivo temporal si la descarga es exitosa, de lo contrario None.
    """
    try:
        with requests.get(
            url, stream=True, timeout=timeout, headers={"User-Agent": "CiteCheck/1.0"}
        ) as r:
            r.raise_for_status()
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return tmp_path
    except Exception:
        return None

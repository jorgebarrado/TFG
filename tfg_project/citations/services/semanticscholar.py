# citations/services/semanticscholar.py
from __future__ import annotations

import os
import tempfile
from typing import Optional

import requests


S2_GRAPH = "https://api.semanticscholar.org/graph/v1"


def get_openaccess_pdf_url(doi: str, timeout: int = 15) -> Optional[str]:
    """Obtiene la URL de un PDF de acceso abierto desde Semantic Scholar usando el DOI.

    Args:
        doi (str): El DOI del artículo.
        timeout (int, optional): El tiempo de espera para la solicitud. Defaults to 15.

    Returns:
        Optional[str]: La URL del PDF si se encuentra, de lo contrario None.
    """
    # Nota: DOI debe ir con el prefijo DOI:
    url = f"{S2_GRAPH}/paper/DOI:{doi}?fields=openAccessPdf"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "CiteCheck/1.0"})
    if r.status_code != 200:
        return None
    data = r.json() or {}
    pdf = data.get("openAccessPdf") or {}
    return pdf.get("url")


def download_pdf_to_temp(url: str, timeout: int = 30) -> Optional[str]:
    """Descarga un archivo PDF desde una URL a un archivo temporal del sistema.

    Args:
        url (str): La URL del PDF a descargar.
        timeout (int, optional): El tiempo de espera para la solicitud. Defaults to 30.

    Returns:
        Optional[str]: La ruta absoluta al archivo temporal si la descarga es exitosa, de lo contrario None.
            El archivo no se borra automáticamente.
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

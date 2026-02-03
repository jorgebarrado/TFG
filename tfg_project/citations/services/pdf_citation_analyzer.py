from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

import requests

from .papermage_extractor import ContextHit, extract_contexts_from_pdf

# Patrones por defecto para buscar citas en el PDF
DEFAULT_PATTERNS: List[str] = [
    r"\[(\d+)\]",  # citas numéricas tipo [12]
    r"\b[A-Z][a-z]+ et al\., \d{4}\b",  # citas autor-año tipo "Smith et al., 2017"
    r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+",  # DOI dentro del texto
]


class PDFDownloadError(RuntimeError):
    """Error al descargar el PDF desde una URL remota."""


def _download_pdf_to_temp(pdf_url: str) -> Path:
    """Descarga un PDF desde una URL a un archivo temporal y devuelve su ruta.

    Args:
        pdf_url (str): URL del PDF a descargar.

    Returns:
        Path: Ruta al archivo temporal descargado.

    Raises:
        PDFDownloadError: Si hay un error de conexión, timeout o código de estado HTTP no 200.
    """
    try:
        response = requests.get(pdf_url, stream=True, timeout=20)
    except requests.RequestException as exc:
        raise PDFDownloadError(f"No se pudo conectar con la URL del PDF: {exc}") from exc

    if response.status_code != 200:
        raise PDFDownloadError(
            f"No se pudo descargar el PDF. Código de estado HTTP: {response.status_code}"
        )

    tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                tmp_file.write(chunk)
    finally:
        tmp_file.close()

    return Path(tmp_file.name)


def analyze_pdf_citations_from_url(
    pdf_url: str,
    patterns: Optional[List[str]] = None,
) -> List[ContextHit]:
    """Descarga un PDF desde una URL y devuelve los contextos de cita detectados.

    Coordina la descarga del PDF y la extracción de citas usando PaperMage.

    Args:
        pdf_url (str): URL del PDF.
        patterns (Optional[List[str]], optional): Lista de patrones regex personalizados.
            Si es None, usa DEFAULT_PATTERNS.

    Returns:
        List[ContextHit]: Lista de contextos de citas encontrados.
    """
    if patterns is None:
        patterns = DEFAULT_PATTERNS

    tmp_path: Path | None = None
    try:
        tmp_path = _download_pdf_to_temp(pdf_url)
        contexts = extract_contexts_from_pdf(str(tmp_path), patterns)
        return contexts
    finally:
        if tmp_path is not None and tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass

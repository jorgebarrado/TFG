from __future__ import annotations
from typing import List
import re

try:
    import pdfplumber  # mas fiable en Windows para texto
except Exception:
    pdfplumber = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

GENERIC_AVAILABLE = pdfplumber is not None or fitz is not None


def _split_paragraphs(text: str) -> List[str]:
    """Divide un texto en párrafos usando saltos de línea dobles.

    Args:
        text (str): Texto completo.

    Returns:
        List[str]: Lista de párrafos limpios.
    """
    parts = re.split(r"\n\s*\n", text)
    out = []
    for p in parts:
        p = re.sub(r"[ \t]*\n[ \t]*", " ", p.strip())
        if p:
            out.append(p)
    return out


def _extract_with_pdfplumber(pdf_path: str) -> str:
    """Extrae texto de un PDF usando pdfplumber.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        str: Texto extraído.
    """
    chunks: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return "\n".join(chunks)


def _extract_pages_with_pdfplumber(pdf_path: str) -> List[tuple[int, str]]:
    """Extrae páginas y su texto con pdfplumber.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[tuple[int, str]]: Lista de tuplas (número de página, texto).
    """
    pages: List[tuple[int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            pages.append((idx, txt))
    return pages


def _extract_with_pymupdf(pdf_path: str) -> str:
    """Extrae texto de un PDF usando PyMuPDF (fitz).

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        str: Texto extraído.
    """
    text_parts: List[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text_parts.append(page.get_text() or "")
    return "\n".join(text_parts)


def _extract_pages_with_pymupdf(pdf_path: str) -> List[tuple[int, str]]:
    """Extrae páginas y su texto con PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[tuple[int, str]]: Lista de tuplas (número de página, texto).
    """
    pages: List[tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            pages.append((idx, page.get_text() or ""))
    return pages


def generic_extract_paragraphs_with_positions(pdf_path: str) -> List[dict]:
    """Extrae párrafos con metadatos posicionales usando una estrategia genérica.

    Intenta usar `pdfplumber` primero, y si no está disponible, `fitz` (PyMuPDF).

    Args:
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        List[dict]: Lista de diccionarios con claves 'page', 'index' y 'text'.
    """
    if pdfplumber is not None:
        page_texts = _extract_pages_with_pdfplumber(pdf_path)
    elif fitz is not None:
        page_texts = _extract_pages_with_pymupdf(pdf_path)
    else:
        return []

    paragraphs: List[dict] = []
    index = 0
    for page_number, text in page_texts:
        for paragraph in _split_paragraphs(text):
            paragraphs.append(
                {
                    "page": page_number,
                    "index": index,
                    "text": paragraph,
                }
            )
            index += 1
    return paragraphs


def generic_extract_paragraphs(pdf_path: str) -> List[str]:
    """Extrae lista simple de párrafos usando una estrategia genérica.

    Args:
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        List[str]: Lista de cadenas de texto (párrafos).
    """
    paragraphs = generic_extract_paragraphs_with_positions(pdf_path)
    if paragraphs:
        return [item["text"] for item in paragraphs]
    if pdfplumber is not None:
        text = _extract_with_pdfplumber(pdf_path)
    elif fitz is not None:
        text = _extract_with_pymupdf(pdf_path)
    else:
        return []
    return _split_paragraphs(text)

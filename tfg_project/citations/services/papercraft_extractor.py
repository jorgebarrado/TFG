"""Motor de extracción de texto PaperCraft.

Intenta extraer texto preservando estructura de bloques y párrafos utilizando
PyMuPDF (fitz) o PyPDF2 como fallback. Prioriza la detección de bloques
de texto coherentes.
"""

from __future__ import annotations
from typing import List
import re

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

PC_AVAILABLE = fitz is not None or PyPDF2 is not None


def _clean_text(raw: str) -> str:
    """Limpia saltos de línea y espacios múltiples de un texto raw.

    Args:
        raw (str): Texto crudo.

    Returns:
        str: Texto limpio.
    """
    text = raw.replace("\r\n", "\n")
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_paragraphs(text: str) -> List[str]:
    """Divide texto en párrafos usando doble salto de línea como delimitador.

    Args:
        text (str): Texto completo.

    Returns:
        List[str]: Lista de párrafos.
    """
    parts = re.split(r"\n\s*\n", text)
    out: List[str] = []
    for part in parts:
        cleaned = _clean_text(part)
        if cleaned:
            out.append(cleaned)
    return out


def _extract_blocks_with_pymupdf(pdf_path: str) -> List[dict]:
    """Extrae bloques de texto usando la funcionalidad 'blocks' de PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[dict]: Lista de párrafos con metadatos de página.
    """
    paragraphs: List[dict] = []
    index = 0
    with fitz.open(pdf_path) as doc:
        for page_number, page in enumerate(doc, start=1):
            blocks = page.get_text("blocks") or []
            blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
            for block in blocks:
                if len(block) < 5:
                    continue
                text = block[4] or ""
                cleaned = _clean_text(text)
                if cleaned:
                    paragraphs.append(
                        {
                            "page": page_number,
                            "index": index,
                            "text": cleaned,
                        }
                    )
                    index += 1
    return paragraphs


def _extract_text_with_pymupdf(pdf_path: str) -> List[dict]:
    """Extrae texto plano por página usando PyMuPDF y luego divide en párrafos.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[dict]: Lista de párrafos con metadatos.
    """
    paragraphs: List[dict] = []
    index = 0
    with fitz.open(pdf_path) as doc:
        for page_number, page in enumerate(doc, start=1):
            page_text = page.get_text() or ""
            for paragraph in _split_paragraphs(page_text):
                paragraphs.append(
                    {
                        "page": page_number,
                        "index": index,
                        "text": paragraph,
                    }
                )
                index += 1
    return paragraphs


def _extract_text_with_pypdf2(pdf_path: str) -> str:
    """Extrae todo el texto del PDF usando PyPDF2.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        str: Texto completo.
    """
    text_parts: List[str] = []
    with open(pdf_path, "rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        for page in reader.pages:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                pass
    return "\n".join(text_parts)


def _extract_text_with_pypdf2_with_positions(pdf_path: str) -> List[dict]:
    """Extrae párrafos con info de página usando PyPDF2.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[dict]: Lista de párrafos.
    """
    paragraphs: List[dict] = []
    index = 0
    with open(pdf_path, "rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            for paragraph in _split_paragraphs(page_text):
                paragraphs.append(
                    {
                        "page": page_number,
                        "index": index,
                        "text": paragraph,
                    }
                )
                index += 1
    return paragraphs


def _score_paragraphs(paragraphs: List[dict]) -> tuple[int, int]:
    """Calcula una puntuación simple para un conjunto de párrafos (caracteres totales, cantidad).

    Args:
        paragraphs (List[dict]): Lista de párrafos.

    Returns:
        tuple[int, int]: (total_chars, num_paragraphs).
    """
    total_chars = sum(len(p.get("text", "")) for p in paragraphs)
    return total_chars, len(paragraphs)


def pc_extract_paragraphs_with_positions(pdf_path: str) -> List[dict]:
    """Extrae párrafos intentando obtener la mejor calidad posible entre métodos.

    Compara extracción por bloques vs texto plano en PyMuPDF si está disponible.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[dict]: Lista de párrafos con posiciones.

    Raises:
        RuntimeError: Si PaperCraft no está disponible.
    """
    if not PC_AVAILABLE:
        raise RuntimeError("PaperCraft not available in this environment.")

    if fitz is not None:
        try:
            blocks = _extract_blocks_with_pymupdf(pdf_path)
        except Exception:
            blocks = []
        try:
            text_paras = _extract_text_with_pymupdf(pdf_path)
        except Exception:
            text_paras = []

        if blocks or text_paras:
            if not blocks:
                return text_paras
            if not text_paras:
                return blocks
            return max((blocks, text_paras), key=_score_paragraphs)

    if PyPDF2 is not None:
        try:
            return _extract_text_with_pypdf2_with_positions(pdf_path)
        except Exception:
            return []

    return []


def pc_extract_paragraphs(pdf_path: str) -> List[str]:
    """Extrae solo el texto de los párrafos usando la mejor estrategia disponible.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[str]: Lista de textos de párrafos.
    """
    paragraphs = pc_extract_paragraphs_with_positions(pdf_path)
    return [item["text"] for item in paragraphs]

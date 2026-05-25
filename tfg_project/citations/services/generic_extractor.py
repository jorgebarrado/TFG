from __future__ import annotations

import re
from typing import List

from citations.logging_utils import get_logger, log_phase

logger = get_logger("citations.extractor.generic")

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
    parts = re.split(r"\n\s*\n", text)
    out = []
    for p in parts:
        p = re.sub(r"[ \t]*\n[ \t]*", " ", p.strip())
        if p:
            out.append(p)
    return out


def _extract_with_pdfplumber(pdf_path: str) -> str:
    chunks: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return "\n".join(chunks)


def _extract_pages_with_pdfplumber(pdf_path: str) -> List[tuple[int, str]]:
    pages: List[tuple[int, str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            txt = page.extract_text() or ""
            pages.append((idx, txt))
    return pages


def _extract_with_pymupdf(pdf_path: str) -> str:
    text_parts: List[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text_parts.append(page.get_text() or "")
    return "\n".join(text_parts)


def _extract_pages_with_pymupdf(pdf_path: str) -> List[tuple[int, str]]:
    pages: List[tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc, start=1):
            pages.append((idx, page.get_text() or ""))
    return pages


def generic_extract_paragraphs_with_positions(pdf_path: str) -> List[dict]:
    with log_phase(
        logger,
        "generic_extract_paragraphs_with_positions",
        engine="generic",
        pdf=pdf_path,
    ):
        if pdfplumber is not None:
            try:
                page_texts = _extract_pages_with_pdfplumber(pdf_path)
                logger.info(f"Usado pdfplumber: extraídas {len(page_texts)} páginas.")
            except Exception as e:
                logger.error(
                    f"Error usando pdfplumber en generic_extractor: {e}", exc_info=True
                )
                page_texts = []
        elif fitz is not None:
            try:
                page_texts = _extract_pages_with_pymupdf(pdf_path)
                logger.info(f"Usado fitz: extraídas {len(page_texts)} páginas.")
            except Exception as e:
                logger.error(
                    f"Error usando fitz en generic_extractor: {e}", exc_info=True
                )
                page_texts = []
        else:
            logger.error(
                "No hay ningún motor de extracción disponible (pdfplumber/fitz)"
            )
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

        logger.info(
            f"Párrafos extraídos: {len(paragraphs)} de {len(page_texts)} páginas"
        )
        return paragraphs


def generic_extract_paragraphs(pdf_path: str) -> List[str]:
    with log_phase(
        logger, "generic_extract_paragraphs", engine="generic", pdf=pdf_path
    ):
        paragraphs = generic_extract_paragraphs_with_positions(pdf_path)
        if paragraphs:
            return [item["text"] for item in paragraphs]

        logger.debug("Usando extracción plana (fallback)")
        if pdfplumber is not None:
            text = _extract_with_pdfplumber(pdf_path)
        elif fitz is not None:
            text = _extract_with_pymupdf(pdf_path)
        else:
            return []

        res = _split_paragraphs(text)
        logger.info(f"Extraídos {len(res)} párrafos mediante fallback plano.")
        return res

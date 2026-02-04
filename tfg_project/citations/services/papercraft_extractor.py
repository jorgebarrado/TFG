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
    """
    Limpia y normaliza el texto extraído.

    Reemplaza saltos de línea y tabulaciones con espacios y reduce
    múltiples espacios consecutivos a uno solo.

    Args:
        raw (str): El texto en bruto a limpiar.

    Returns:
        str: El texto limpio y sin espacios en los extremos.
    """
    text = raw.replace("\r\n", "\n")
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_paragraphs(text: str) -> List[str]:
    """
    Divide un texto en párrafos basándose en dobles saltos de línea.

    Args:
        text (str): El texto completo a dividir.

    Returns:
        List[str]: Una lista de cadenas, donde cada cadena es un párrafo limpio.
    """
    parts = re.split(r"\n\s*\n", text)
    out: List[str] = []
    for part in parts:
        cleaned = _clean_text(part)
        if cleaned:
            out.append(cleaned)
    return out


def _extract_blocks_with_pymupdf(pdf_path: str) -> List[dict]:
    """
    Extrae bloques de texto de un PDF utilizando PyMuPDF (fitz).

    Los bloques se ordenan por posición vertical y luego horizontal en la página.
    Se ignoran los bloques muy cortos (menos de 5 caracteres).

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        List[dict]: Lista de diccionarios con claves 'page', 'index' y 'text'.
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
    """
    Extrae texto plano de un PDF utilizando PyMuPDF y lo divide en párrafos.

    Este método es una alternativa a la extracción por bloques, útil cuando
    la estructura de bloques no es fiable.

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        List[dict]: Lista de diccionarios con claves 'page', 'index' y 'text'.
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
    """
    Extrae todo el texto de un PDF utilizando PyPDF2.

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        str: El texto completo del PDF concatenado.
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
    """
    Extrae texto de un PDF con PyPDF2, manteniendo la información de la página.

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        List[dict]: Lista de diccionarios con claves 'page', 'index' y 'text'.
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
    """
    Calcula una puntuación para un conjunto de párrafos extraídos.

    La puntuación se basa en la cantidad total de caracteres y el número
    de párrafos. Se utiliza para decidir qué método de extracción fue mejor.

    Args:
        paragraphs (List[dict]): Lista de párrafos extraídos.

    Returns:
        tuple[int, int]: Una tupla (total_caracteres, num_parrafos).
    """
    total_chars = sum(len(p.get("text", "")) for p in paragraphs)
    return total_chars, len(paragraphs)


def pc_extract_paragraphs_with_positions(pdf_path: str) -> List[dict]:
    """
    Extrae párrafos de un PDF intentando usar el mejor método disponible.

    Intenta usar PyMuPDF (fitz) primero, probando tanto la extracción por
    bloques como por texto plano y eligiendo la que produzca más contenido.
    Si fitz no está disponible, recurre a PyPDF2.

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        List[dict]: Lista de párrafos, donde cada elemento es un diccionario
            con:
            - page (int): Número de página (1-based).
            - index (int): Índice secuencial del párrafo.
            - text (str): Contenido del párrafo.

    Raises:
        RuntimeError: Si ninguna librería de extracción (PyMuPDF o PyPDF2)
            está disponible.
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
    """
    Extrae solo el texto de los párrafos de un PDF.

    Utiliza `pc_extract_paragraphs_with_positions` internamente pero
    descarta la información de metadatos (página, índice).

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        List[str]: Lista de cadenas de texto con el contenido de los párrafos.
    """
    paragraphs = pc_extract_paragraphs_with_positions(pdf_path)
    return [item["text"] for item in paragraphs]

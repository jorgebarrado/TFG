"""Módulo de integración con PaperMage para la extracción de contextos de citas.

Proporciona funciones para cargar PDFs, iterar sobre sus párrafos y buscar
patrones de citas utilizando expresiones regulares, todo ello preservando
la información de paginación y posición.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple, TypedDict

try:
    from papermage.magelib import Document, Entity
    from papermage.parsers.pdfplumber_parser import PDFPlumberParser

    PM_AVAILABLE = True
except Exception:
    PM_AVAILABLE = False

SNIPPET_PADDING = 80


@dataclass(frozen=True)
class _Paragraph:
    """Representación inmutable de un párrafo extraído.

    Attributes:
        text (str): El contenido textual del párrafo.
        page (int): El número de página (base 1) donde se encuentra.
    """

    text: str
    page: int


class ContextHit(TypedDict):
    """Estructura de datos para una coincidencia de cita detectada.

    Attributes:
        paragraph (str): Texto completo del párrafo que contiene la cita.
        snippet (str): Fragmento de texto alrededor de la cita.
        page (int): Número de página donde aparece.
        start (int): Índice de inicio de la cita en el párrafo.
        end (int): Índice de fin de la cita en el párrafo.
        pattern (str): El patrón de expresión regular que coincidió.
        section (str): Sección estimada ("body" o "references").
    """

    paragraph: str
    snippet: str
    page: int
    start: int
    end: int
    pattern: str
    section: str  # "body" o "references"


def _ensure_papermage_available() -> None:
    """Verifica si PaperMage está disponible en el entorno.

    Raises:
        RuntimeError: Si la librería papermage no está instalada.
    """
    if not PM_AVAILABLE:
        raise RuntimeError(
            "PaperMage no está disponible en este entorno (no instalado)."
        )


def _load_document(pdf_path: str) -> Document:
    """Carga un documento PDF usando PaperMage y PDFPlumberParser.

    Args:
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        Document: Objeto Document de PaperMage.

    Raises:
        FileNotFoundError: si la ruta no existe o no es un archivo.
        RuntimeError: si PaperMage no está disponible o falla el parseo.
    """
    _ensure_papermage_available()
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No se encontró el PDF en la ruta proporcionada: {pdf_path}"
        )
    try:
        parser = PDFPlumberParser()
        return parser.parse(input_pdf_path=str(path))
    except Exception as exc:  # pragma: no cover - defensivo frente a fallos de librería
        raise RuntimeError(f"No se pudo leer el PDF con PaperMage: {exc}") from exc


def _clean_paragraph(raw: str) -> str:
    """Normaliza un bloque de texto eliminando saltos raros y espacios duplicados.

    Args:
        raw (str): Texto crudo del párrafo.

    Returns:
        str: Texto limpio y normalizado.
    """
    normalized = raw.replace("\r\n", "\n")
    # Unir líneas en un mismo párrafo
    normalized = re.sub(r"[ \t]*\n[ \t]*", " ", normalized)
    # Colapsar espacios en blanco múltiples
    normalized = re.sub(r"\s+", " ", normalized)
    # Pequeña corrección para ' - ' que a veces aparece separado en PDFs
    normalized = normalized.replace(" - ", "-")
    return normalized.strip()


def _split_paragraphs(text: str) -> List[str]:
    """Divide un bloque grande de texto en párrafos.

    Utiliza dobles saltos de línea como separador lógico.

    Args:
        text (str): Texto completo a dividir.

    Returns:
        List[str]: Lista de párrafos limpios.
    """
    chunks = re.split(r"\n\s*\n", text)
    paragraphs: List[str] = []
    for chunk in chunks:
        cleaned = _clean_paragraph(chunk)
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def _page_text(page: Entity, symbols: str) -> str:
    """Reconstruye el texto de una página a partir de sus spans.

    Respeta el orden de lectura y realiza recortes defensivos de índices.

    Args:
        page (Entity): Entidad de página de PaperMage.
        symbols (str): Cadena completa de símbolos del documento.

    Returns:
        str: Texto reconstruido de la página.
    """
    spans = sorted(page.spans, key=lambda span: span.start)
    page_text_parts: List[str] = []
    length = len(symbols)

    for span in spans:
        start = max(int(span.start), 0)
        end = min(int(span.end), length)
        if start < end:
            page_text_parts.append(symbols[start:end])

    return "".join(page_text_parts)


def _iter_paragraphs(doc: Document) -> Iterable[_Paragraph]:
    """Itera sobre todos los párrafos del documento, preservando el número de página.

    Args:
        doc (Document): Documento de PaperMage cargado.

    Yields:
        _Paragraph: Objetos párrafo con texto y número de página.

    Raises:
        RuntimeError: Si no se puede extraer texto del documento.
    """
    symbols = getattr(doc, "symbols", None)
    if not symbols:
        # Sin texto extraído: probablemente PDF vacío o basado en imagen escaneada.
        raise RuntimeError(
            "No se pudo extraer texto del PDF (documento vacío o escaneado sin OCR)."
        )

    pages_layer = getattr(doc, "pages", None)
    if pages_layer is None:
        # Sin capa de páginas, tratamos todo el documento como una única página.
        for paragraph in _split_paragraphs(symbols):
            yield _Paragraph(text=paragraph, page=1)
        return

    for page_number, page in enumerate(pages_layer, start=1):
        page_text = _page_text(page, symbols)
        for paragraph in _split_paragraphs(page_text):
            yield _Paragraph(text=paragraph, page=page_number)


def _compile_patterns(patterns: Sequence[str]) -> List[Tuple[str, re.Pattern[str]]]:
    """Compila una lista de patrones regex.

    Args:
        patterns (Sequence[str]): Lista de patrones en formato string.

    Returns:
        List[Tuple[str, re.Pattern[str]]]: Lista de tuplas (patrón_original, objeto_regex).

    Raises:
        ValueError: Si algún patrón no es válido.
    """
    compiled: List[Tuple[str, re.Pattern[str]]] = []
    for pattern in patterns:
        try:
            compiled.append((pattern, re.compile(pattern)))
        except re.error as exc:
            raise ValueError(f"Patrón inválido '{pattern}': {exc}") from exc
    return compiled


def _make_snippet(
    text: str, start: int, end: int, padding: int = SNIPPET_PADDING
) -> str:
    """Construye un snippet alrededor del match con un padding dado.

    Añade '…' al inicio o final si el snippet ha sido recortado.

    Args:
        text (str): Texto completo del párrafo.
        start (int): Índice de inicio del match.
        end (int): Índice de fin del match.
        padding (int, optional): Caracteres de contexto a cada lado. Default 80.

    Returns:
        str: Fragmento de texto con elipsis si corresponde.
    """
    left = max(start - padding, 0)
    right = min(end + padding, len(text))

    snippet = text[left:right]

    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""

    return f"{prefix}{snippet}{suffix}"


def pm_extract_paragraphs(pdf_path: str) -> List[str]:
    """Extrae párrafos limpios de un PDF usando PaperMage en orden de lectura.

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[str]: Lista de textos de los párrafos.
    """
    document = _load_document(pdf_path)
    return [paragraph.text for paragraph in _iter_paragraphs(document)]


def extract_contexts_from_pdf(pdf_path: str, patterns: List[str]) -> List[ContextHit]:
    """Busca patrones regex dentro de los párrafos extraídos con PaperMage.

    Identifica si la cita está en el cuerpo del texto o en las referencias.

    Args:
        pdf_path (str): Ruta al PDF a analizar.
        patterns (List[str]): Lista de patrones regex a buscar.

    Returns:
        List[ContextHit]: Lista de coincidencias encontradas con contexto detallado.
    """
    document = _load_document(pdf_path)
    compiled_patterns = _compile_patterns(patterns)
    if not compiled_patterns:
        return []

    contexts: List[ContextHit] = []
    in_references = False
    for paragraph in _iter_paragraphs(document):
        text = paragraph.text or ""
        stripped = text.strip()

        if not in_references:
            if re.match(r"^(references|bibliography)\b", stripped, flags=re.IGNORECASE):
                in_references = True
                continue

        section = "references" if in_references else "body"

        for pattern_str, pattern in compiled_patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                contexts.append(
                    {
                        "paragraph": text,
                        "snippet": _make_snippet(text, start, end),
                        "page": paragraph.page,
                        "start": start,
                        "end": end,
                        "pattern": pattern_str,
                        "section": section,
                    }
                )

    return contexts


def pm_extract_paragraphs_with_positions(pdf_path: str) -> List[dict]:
    """Extrae párrafos con metadatos de posición (página e índice).

    Args:
        pdf_path (str): Ruta al PDF.

    Returns:
        List[dict]: Lista de diccionarios con 'page', 'index' y 'text'.
    """
    document = _load_document(pdf_path)
    paragraphs: List[dict] = []
    global_index = 0

    for paragraph in _iter_paragraphs(document):
        paragraphs.append(
            {
                "page": paragraph.page,
                "index": global_index,
                "text": paragraph.text,
            }
        )
        global_index += 1

    return paragraphs

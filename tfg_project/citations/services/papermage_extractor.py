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
    text: str
    page: int


class ContextHit(TypedDict):
    """Representa una coincidencia de contexto de cita hallada en el PDF.

    Attributes:
        paragraph (str): El texto completo del párrafo donde se encontró la cita.
        snippet (str): Un fragmento recortado alrededor de la coincidencia.
        page (int): Número de página (1-based).
        start (int): Índice de inicio de la coincidencia en el párrafo.
        end (int): Índice de fin de la coincidencia en el párrafo.
        pattern (str): El patrón regex que produjo la coincidencia.
        section (str): Sección del documento ('body' o 'references').
    """

    paragraph: str
    snippet: str
    page: int
    start: int
    end: int
    pattern: str
    section: str  # "body" o "references"


def _ensure_papermage_available() -> None:
    if not PM_AVAILABLE:
        raise RuntimeError(
            "PaperMage no está disponible en este entorno (no instalado)."
        )


def _load_document(pdf_path: str) -> Document:
    """
    Carga un documento PDF usando PaperMage y PDFPlumberParser.

    Lanza:
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
    """
    Normaliza un bloque de texto eliminando saltos raros y espacios duplicados.
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
    """
    Divide un bloque grande de texto en párrafos, usando dobles saltos de línea
    como separador lógico.
    """
    chunks = re.split(r"\n\s*\n", text)
    paragraphs: List[str] = []
    for chunk in chunks:
        cleaned = _clean_paragraph(chunk)
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def _page_text(page: Entity, symbols: str) -> str:
    """
    Reconstruye el texto de una página a partir de sus spans, respetando
    el orden de lectura. Hace un recorte defensivo de los índices.
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
    """
    Itera sobre todos los párrafos del documento, preservando el número de página.
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
    """
    Compila una lista de patrones regex, devolviendo (pattern_str, pattern_compilado).

    Lanza:
        ValueError: si alguno de los patrones no es válido.
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
    """
    Construye un snippet alrededor del match [start, end), con un padding dado.

    Añade '…' al inicio o final si el snippet ha sido recortado respecto al texto
    original.
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
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        list: Lista de strings, cada uno representando un párrafo normalizado.
    """
    document = _load_document(pdf_path)
    return [paragraph.text for paragraph in _iter_paragraphs(document)]


def extract_contexts_from_pdf(pdf_path: str, patterns: List[str]) -> List[ContextHit]:
    """Busca patrones regex dentro de los párrafos extraídos con PaperMage.

    Args:
        pdf_path (str): Ruta al PDF a analizar.
        patterns (list): Lista de patrones regex (strings) para buscar.

    Returns:
        list: Lista de objetos ContextHit describiendo las coincidencias encontradas.
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
    """Variante que devuelve página e índice global por párrafo.

    Args:
        pdf_path (str): Ruta al archivo PDF.

    Returns:
        list: Lista de diccionarios con claves 'page', 'index', 'text'.
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

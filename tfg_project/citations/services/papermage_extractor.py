from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Tuple, TypedDict

try:
    from papermage.magelib import Document, Entity
    from papermage.parsers.pdfplumber_parser import PDFPlumberParser

    PM_AVAILABLE = True
except Exception:
    Document = Any  # type: ignore[assignment]
    Entity = Any  # type: ignore[assignment]
    PDFPlumberParser = None  # type: ignore[assignment]
    PM_AVAILABLE = False

try:
    from papermage.recipes import CoreRecipe
except Exception:
    CoreRecipe = None  # type: ignore[assignment]

SNIPPET_PADDING = 80


@dataclass(frozen=True)
class _Paragraph:
    text: str
    page: int


class ContextHit(TypedDict):
    paragraph: str
    snippet: str
    page: int
    start: int
    end: int
    pattern: str
    section: str  # "body" o "references"


class ReaderPage(TypedDict):
    page: int
    width: float
    height: float


class ReaderItem(TypedDict):
    id: str
    text: str
    page: int
    box: List[float]
    type: str


class ReaderData(TypedDict):
    pages: List[ReaderPage]
    items: List[ReaderItem]


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
    if PDFPlumberParser is None:
        raise RuntimeError(
            "PaperMage está instalado parcialmente y no se pudo inicializar PDFPlumberParser."
        )
    try:
        parser = PDFPlumberParser()
        return parser.parse(input_pdf_path=str(path))
    except Exception as exc:
        raise RuntimeError(f"No se pudo leer el PDF con PaperMage: {exc}") from exc


def _load_reader_document(pdf_path: str) -> Document:
    """
    Carga un documento para el reader usando el parser más estable para
    esta primera versión: PDFPlumberParser.

    Para el JSON v1 del reader necesitamos sobre todo:
    - páginas
    - palabras/tokens
    - boxes

    `CoreRecipe` puede ser útil para pipelines más ricos, pero en esta fase
    priorizamos un parser más estable y predecible.
    """
    return _load_document(pdf_path)


def _num(value: Any, default: float = 0.0) -> float:
    """Convierte valores numéricos a `float` de forma defensiva."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_page_dimensions(page: Entity) -> tuple[float, float]:
    """
    Recupera el tamaño de una página de la forma más compatible posible.
    """
    # 1. Atributos directos
    width = _num(getattr(page, "width", None))
    height = _num(getattr(page, "height", None))
    if width > 0 and height > 0:
        return width, height

    # 2. Metadata
    metadata = getattr(page, "metadata", None) or {}
    if isinstance(metadata, dict):
        width = _num(metadata.get("width"))
        height = _num(metadata.get("height"))
        if width > 0 and height > 0:
            return width, height

    # 3. Primer box asociado a la página
    boxes = getattr(page, "boxes", None) or []
    if boxes:
        box = boxes[0]

        # Variante 1: width / height
        width = _num(getattr(box, "width", None))
        height = _num(getattr(box, "height", None))
        if width > 0 and height > 0:
            return width, height

        # Variante 2: w / h
        width = _num(getattr(box, "w", None))
        height = _num(getattr(box, "h", None))
        if width > 0 and height > 0:
            return width, height

        # Variante 3: x0/x1 y top/bottom o y0/y1
        x0 = _num(getattr(box, "x0", None))
        x1 = _num(getattr(box, "x1", None))
        top = _num(getattr(box, "top", None))
        bottom = _num(getattr(box, "bottom", None))
        y0 = _num(getattr(box, "y0", None))
        y1 = _num(getattr(box, "y1", None))

        computed_width = x1 - x0 if x1 > x0 else 0.0
        computed_height = (
            bottom - top if bottom > top else (y1 - y0 if y1 > y0 else 0.0)
        )

        if computed_width > 0 and computed_height > 0:
            return computed_width, computed_height

    return 0.0, 0.0


def _extract_first_box(entity: Entity) -> list[float] | None:
    """
    Devuelve la primera caja de una entidad en formato [x, y, width, height].
    Compatible con varias representaciones de box.
    """
    boxes = getattr(entity, "boxes", None) or []
    if not boxes:
        return None

    box = boxes[0]

    # Variante 1: left/top/width/height
    left = _num(getattr(box, "left", None), default=-1)
    top = _num(getattr(box, "top", None), default=-1)
    width = _num(getattr(box, "width", None), default=-1)
    height = _num(getattr(box, "height", None), default=-1)
    if left >= 0 and top >= 0 and width > 0 and height > 0:
        return [left, top, width, height]

    # Variante 2: l/t/w/h
    left = _num(getattr(box, "l", None), default=-1)
    top = _num(getattr(box, "t", None), default=-1)
    width = _num(getattr(box, "w", None), default=-1)
    height = _num(getattr(box, "h", None), default=-1)
    if left >= 0 and top >= 0 and width > 0 and height > 0:
        return [left, top, width, height]

    # Variante 3: x0/x1/top/bottom
    x0 = _num(getattr(box, "x0", None), default=-1)
    x1 = _num(getattr(box, "x1", None), default=-1)
    top = _num(getattr(box, "top", None), default=-1)
    bottom = _num(getattr(box, "bottom", None), default=-1)
    if x0 >= 0 and x1 > x0 and top >= 0 and bottom > top:
        return [x0, top, x1 - x0, bottom - top]

    # Variante 4: x0/x1/y0/y1
    y0 = _num(getattr(box, "y0", None), default=-1)
    y1 = _num(getattr(box, "y1", None), default=-1)
    if x0 >= 0 and x1 > x0 and y0 >= 0 and y1 > y0:
        return [x0, y0, x1 - x0, y1 - y0]

    return None


def _normalize_box_page(raw_page: Any, pages_total: int) -> int:
    """
    Normaliza el índice de página a base 0.

    En algunos parsers el número ya viene 0-based; en otros puede venir 1-based.
    Aquí lo mantenemos estable y acotado al número total de páginas detectadas.
    """
    if raw_page is None:
        return 0

    try:
        page_index = int(raw_page)
    except (TypeError, ValueError):
        return 0

    if page_index < 0:
        return 0

    if pages_total and page_index >= pages_total:
        if 1 <= page_index <= pages_total:
            return page_index - 1
        return max(pages_total - 1, 0)

    return page_index


def extract_pdf_data(pdf_path: str) -> ReaderData:
    """
    Extrae una estructura mínima y estable para alimentar el reader frontend.

    Salida:
    {
      "pages": [{"page": 0, "width": 595.0, "height": 842.0}, ...],
      "items": [
        {
          "id": "word_0",
          "text": "Quantum",
          "page": 0,
          "box": [x, y, width, height],
          "type": "word",
        },
        ...
      ]
    }

    Notas de esta primera versión:
    - Solo exporta páginas y palabras/tokens.
    - Usa la primera caja de cada entidad.
    - Mantiene las coordenadas originales del PDF, sin viewport ni escalado.
    - Página en base 0 para encajar mejor con el reader React.
    """
    document = _load_reader_document(pdf_path)

    pages: List[ReaderPage] = []
    raw_pages = getattr(document, "pages", []) or []
    for page_index, page in enumerate(raw_pages):
        width, height = _extract_page_dimensions(page)
        pages.append(
            {
                "page": page_index,
                "width": width,
                "height": height,
            }
        )

    items: List[ReaderItem] = []

    # Algunas versiones/parsers exponen words, otras tokens.
    raw_items = getattr(document, "words", None) or getattr(document, "tokens", None) or []

    for item_index, item in enumerate(raw_items):
        box = _extract_first_box(item)
        if not box:
            continue

        item_boxes = getattr(item, "boxes", None) or []
        raw_page = getattr(item_boxes[0], "page", None) if item_boxes else None
        page_index = _normalize_box_page(raw_page, len(pages))

        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue

        items.append(
            {
                "id": f"word_{item_index}",
                "text": text,
                "page": page_index,
                "box": box,
                "type": "word",
            }
        )

    return {"pages": pages, "items": items}


def _clean_paragraph(raw: str) -> str:
    """
    Normaliza un bloque de texto eliminando saltos raros y espacios duplicados.
    """
    normalized = raw.replace("\r\n", "\n")
    normalized = re.sub(r"[ \t]*\n[ \t]*", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
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
        raise RuntimeError(
            "No se pudo extraer texto del PDF (documento vacío o escaneado sin OCR)."
        )

    pages_layer = getattr(doc, "pages", None)
    if pages_layer is None:
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
    """
    Extrae párrafos limpios de un PDF usando PaperMage en orden de lectura.

    Devuelve:
        Lista de strings, cada uno representando un párrafo normalizado.
    """
    document = _load_document(pdf_path)
    return [paragraph.text for paragraph in _iter_paragraphs(document)]


def extract_contexts_from_pdf(pdf_path: str, patterns: List[str]) -> List[ContextHit]:
    """
    Busca patrones regex dentro de los párrafos extraídos con PaperMage.

    Args:
        pdf_path: Ruta al PDF a analizar.
        patterns: Lista de patrones regex en forma de string.

    Devuelve:
        Lista de ContextHit con:
            - paragraph: texto completo del párrafo.
            - snippet: fragmento alrededor del match.
            - page: número de página (1-based).
            - start: índice de inicio del match dentro del párrafo.
            - end: índice final del match dentro del párrafo.
            - pattern: patrón que produjo el match.
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
    """
    Variante que devuelve página e índice global por párrafo.
    Formato: [{"page": int, "index": int, "text": str}, ...]
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
from __future__ import annotations

import re
from collections import defaultdict
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
    layers: dict[str, List[ReaderItem]]


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


def _normalize_box_to_page(
    box: list[float],
    page_width: float,
    page_height: float,
) -> list[float] | None:
    """
    Normaliza una caja [x, y, width, height] al rango [0, 1] relativo a la página.
    """
    if len(box) < 4:
        return None

    x = _num(box[0], default=-1.0)
    y = _num(box[1], default=-1.0)
    width = _num(box[2], default=-1.0)
    height = _num(box[3], default=-1.0)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None

    looks_normalized = x <= 1.05 and y <= 1.05 and width <= 1.05 and height <= 1.05
    if not looks_normalized:
        if page_width <= 0 or page_height <= 0:
            return None
        x /= page_width
        y /= page_height
        width /= page_width
        height /= page_height

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    width = max(0.0, min(1.0 - x, width))
    height = max(0.0, min(1.0 - y, height))
    if width <= 0 or height <= 0:
        return None

    return [x, y, width, height]


def _build_reader_layer_items(
    entities: Sequence[Any],
    *,
    item_prefix: str,
    item_type: str,
    pages: List[ReaderPage],
) -> List[ReaderItem]:
    """
    Convierte una capa de entidades de PaperMage a items del reader.
    """
    pages_total = len(pages)
    layer_items: List[ReaderItem] = []

    for entity_index, entity in enumerate(entities):
        box = _extract_first_box(entity)
        if not box:
            continue

        entity_boxes = getattr(entity, "boxes", None) or []
        raw_page = (
            getattr(entity_boxes[0], "page", None)
            if entity_boxes
            else getattr(entity, "page", None)
        )
        page_index = _normalize_box_page(raw_page, pages_total)

        page_width = pages[page_index]["width"] if 0 <= page_index < pages_total else 0.0
        page_height = pages[page_index]["height"] if 0 <= page_index < pages_total else 0.0
        normalized_box = _normalize_box_to_page(box, page_width, page_height)
        if not normalized_box:
            continue

        layer_items.append(
            {
                "id": f"{item_prefix}_{entity_index}",
                "text": str(getattr(entity, "text", "") or ""),
                "page": page_index,
                "box": normalized_box,
                "type": item_type,
            }
        )

    return layer_items


_SECTION_NUMBERED_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVXLCM]+)\.?\s+\S+")
_BIBLIO_HEADER_RE = re.compile(r"^(references|bibliography)\b", re.IGNORECASE)
_BIBLIO_ENTRY_START_RE = re.compile(
    r"^(?:\[\d+\]|\d+\.\s|[A-Z][A-Za-z'`-]+,\s*(?:[A-Z]\.|[A-Z][a-z]))"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _box_right(box: Sequence[float]) -> float:
    return _num(box[0]) + _num(box[2])


def _box_bottom(box: Sequence[float]) -> float:
    return _num(box[1]) + _num(box[3])


def _union_boxes(boxes: Sequence[Sequence[float]]) -> List[float] | None:
    if not boxes:
        return None

    left = min(_num(box[0], default=1.0) for box in boxes)
    top = min(_num(box[1], default=1.0) for box in boxes)
    right = max(_box_right(box) for box in boxes)
    bottom = max(_box_bottom(box) for box in boxes)
    width = right - left
    height = bottom - top

    if width <= 0 or height <= 0:
        return None
    return [left, top, width, height]


def _horizontal_overlap_ratio(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    left = max(_num(box_a[0]), _num(box_b[0]))
    right = min(_box_right(box_a), _box_right(box_b))
    overlap = max(0.0, right - left)
    min_width = min(_num(box_a[2]), _num(box_b[2]))
    if min_width <= 0:
        return 0.0
    return overlap / min_width


def _is_probably_two_column_page(rows: Sequence[ReaderItem]) -> bool:
    if len(rows) < 20:
        return False

    narrow_centers: List[float] = []
    for row in rows:
        x, _, width, _ = row["box"]
        if width >= 0.75:
            continue
        narrow_centers.append(x + width / 2)

    if len(narrow_centers) < 20:
        return False

    left_count = sum(1 for center in narrow_centers if center < 0.5)
    right_count = len(narrow_centers) - left_count
    return left_count >= len(narrow_centers) * 0.25 and right_count >= len(
        narrow_centers
    ) * 0.25


def _assign_row_stream(row: ReaderItem, two_column: bool) -> int:
    x, _, width, _ = row["box"]
    if width >= 0.75:
        return -1
    if not two_column:
        return 0
    center = x + width / 2
    return 0 if center < 0.5 else 1


def _build_paragraph_item(
    rows: Sequence[ReaderItem],
    index: int,
) -> ReaderItem | None:
    if not rows:
        return None

    boxes = [row["box"] for row in rows]
    merged_box = _union_boxes(boxes)
    if not merged_box:
        return None

    text = _normalize_whitespace(
        " ".join(_normalize_whitespace(row.get("text", "")) for row in rows)
    )
    page = rows[0]["page"]
    return {
        "id": f"paragraph_{index}",
        "text": text,
        "page": page,
        "box": merged_box,
        "type": "paragraph",
    }


def _infer_paragraphs_from_rows(rows: Sequence[ReaderItem]) -> List[ReaderItem]:
    if not rows:
        return []

    rows_by_page: dict[int, list[ReaderItem]] = defaultdict(list)
    for row in rows:
        rows_by_page[row["page"]].append(row)

    paragraphs: List[ReaderItem] = []
    paragraph_index = 0

    for page in sorted(rows_by_page):
        page_rows = rows_by_page[page]
        two_column = _is_probably_two_column_page(page_rows)

        streams: dict[int, list[ReaderItem]] = defaultdict(list)
        for row in page_rows:
            streams[_assign_row_stream(row, two_column)].append(row)

        for stream_key in sorted(streams):
            stream_rows = sorted(
                streams[stream_key], key=lambda row: (row["box"][1], row["box"][0])
            )

            current_group: List[ReaderItem] = []
            for row in stream_rows:
                if not current_group:
                    current_group.append(row)
                    continue

                prev = current_group[-1]
                prev_box = prev["box"]
                row_box = row["box"]
                vertical_gap = row_box[1] - _box_bottom(prev_box)
                overlap_ratio = _horizontal_overlap_ratio(prev_box, row_box)
                reference_height = max(prev_box[3], row_box[3], 0.006)
                max_gap = reference_height * 1.35 + 0.003

                first_box = current_group[0]["box"]
                left_delta = abs(row_box[0] - first_box[0])
                should_merge = (
                    vertical_gap <= max_gap
                    and vertical_gap >= -reference_height * 0.75
                    and (overlap_ratio >= 0.25 or left_delta <= 0.07)
                )

                if should_merge:
                    current_group.append(row)
                else:
                    paragraph_item = _build_paragraph_item(
                        rows=current_group,
                        index=paragraph_index,
                    )
                    if paragraph_item:
                        paragraphs.append(paragraph_item)
                        paragraph_index += 1
                    current_group = [row]

            paragraph_item = _build_paragraph_item(
                rows=current_group,
                index=paragraph_index,
            )
            if paragraph_item:
                paragraphs.append(paragraph_item)
                paragraph_index += 1

    return paragraphs


def _looks_like_section_heading(text: str, box: Sequence[float]) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return False

    lowered = cleaned.lower()
    if _BIBLIO_HEADER_RE.match(lowered):
        return True

    if len(cleaned) < 2 or len(cleaned) > 120:
        return False

    words = cleaned.split()
    if len(words) > 16:
        return False

    if cleaned.endswith((".", "?", "!", ",")):
        return False

    if _SECTION_NUMBERED_RE.match(cleaned):
        return True

    alpha_chars = [ch for ch in cleaned if ch.isalpha()]
    if not alpha_chars:
        return False

    uppercase_ratio = sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars)
    titlecase_ratio = sum(1 for word in words if word and word[0].isupper()) / len(words)
    looks_reference_line = _YEAR_RE.search(cleaned) and "," in cleaned

    if looks_reference_line:
        return False

    if uppercase_ratio >= 0.65 and len(words) <= 12:
        return True

    if titlecase_ratio >= 0.8 and len(words) <= 12:
        return True

    _, y, width, _ = box
    return y <= 0.12 and width >= 0.45 and titlecase_ratio >= 0.7


def _infer_sections_from_rows(rows: Sequence[ReaderItem]) -> List[ReaderItem]:
    if not rows:
        return []

    section_items: List[ReaderItem] = []
    seen_keys: set[tuple[int, str, int]] = set()

    sorted_rows = sorted(rows, key=lambda row: (row["page"], row["box"][1], row["box"][0]))
    for row in sorted_rows:
        text = _normalize_whitespace(row.get("text", ""))
        box = row["box"]
        if not _looks_like_section_heading(text, box):
            continue

        key = (row["page"], text.lower(), int(round(box[1] * 1000)))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        section_items.append(
            {
                "id": f"section_{len(section_items)}",
                "text": text,
                "page": row["page"],
                "box": box,
                "type": "section",
            }
        )

    return section_items


def _find_bibliography_anchor(
    rows: Sequence[ReaderItem],
    sections: Sequence[ReaderItem],
) -> tuple[int, float] | None:
    for section in sections:
        text = _normalize_whitespace(section.get("text", "")).lower()
        if _BIBLIO_HEADER_RE.match(text):
            return section["page"], section["box"][1]

    sorted_rows = sorted(rows, key=lambda row: (row["page"], row["box"][1], row["box"][0]))
    for row in sorted_rows:
        text = _normalize_whitespace(row.get("text", "")).lower()
        if _BIBLIO_HEADER_RE.match(text):
            return row["page"], row["box"][1]

    return None


def _starts_new_bibliography_entry(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return False
    if _BIBLIO_ENTRY_START_RE.match(cleaned):
        return True
    if cleaned.startswith("(") and _YEAR_RE.search(cleaned):
        return True
    return False


def _build_bibliography_item(
    rows: Sequence[ReaderItem],
    index: int,
) -> ReaderItem | None:
    if not rows:
        return None
    merged_box = _union_boxes([row["box"] for row in rows])
    if not merged_box:
        return None

    text = _normalize_whitespace(
        " ".join(_normalize_whitespace(row.get("text", "")) for row in rows)
    )

    return {
        "id": f"bibliography_{index}",
        "text": text,
        "page": rows[0]["page"],
        "box": merged_box,
        "type": "bibliography",
    }


def _infer_bibliographies_from_rows(
    rows: Sequence[ReaderItem],
    sections: Sequence[ReaderItem],
) -> List[ReaderItem]:
    anchor = _find_bibliography_anchor(rows, sections)
    if anchor is None:
        return []

    anchor_page, anchor_y = anchor
    candidate_rows = [
        row
        for row in sorted(rows, key=lambda item: (item["page"], item["box"][1], item["box"][0]))
        if row["page"] > anchor_page or (row["page"] == anchor_page and row["box"][1] >= anchor_y)
    ]
    if not candidate_rows:
        return []

    entries: List[ReaderItem] = []
    current_rows: List[ReaderItem] = []
    for row in candidate_rows:
        row_text = _normalize_whitespace(row.get("text", ""))
        if not row_text:
            continue
        if _BIBLIO_HEADER_RE.match(row_text.lower()):
            continue

        if not current_rows:
            current_rows.append(row)
            continue

        prev_row = current_rows[-1]
        prev_box = prev_row["box"]
        row_box = row["box"]
        vertical_gap = row_box[1] - _box_bottom(prev_box)
        reference_height = max(prev_box[3], row_box[3], 0.006)
        large_gap = vertical_gap > reference_height * 1.8 + 0.005
        page_jump = row["page"] != prev_row["page"]
        new_entry = (
            _starts_new_bibliography_entry(row_text)
            and not _starts_new_bibliography_entry(prev_row.get("text", ""))
        )
        if page_jump or large_gap or new_entry:
            item = _build_bibliography_item(rows=current_rows, index=len(entries))
            if item:
                entries.append(item)
            current_rows = [row]
        else:
            current_rows.append(row)

    item = _build_bibliography_item(rows=current_rows, index=len(entries))
    if item:
        entries.append(item)

    return entries


def extract_pdf_data(pdf_path: str) -> ReaderData:
    """
    Extrae una estructura estable para alimentar el reader V2 con capas.

    Salida:
    {
      "pages": [{"page": 0, "width": 595.0, "height": 842.0}, ...],
      "layers": {
        "tokens": [{...}],
        "rows": [{...}],
        "paragraphs": [{...}],
        "bibliographies": [{...}],
        "sections": [{...}]
      }
    }

    Reglas:
    - `page` siempre base 0.
    - `box` siempre normalizado (0..1) respecto a la página.
    - Solo se exportan capas que existen en el `Document`.
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

    layers: dict[str, List[ReaderItem]] = {}
    layer_specs = (
        ("tokens", "token", "token"),
        ("rows", "row", "row"),
        ("paragraphs", "paragraph", "paragraph"),
        ("bibliographies", "bibliography", "bibliography"),
        ("sections", "section", "section"),
    )
    for layer_name, item_prefix, item_type in layer_specs:
        raw_layer = getattr(document, layer_name, None)
        if raw_layer is None:
            continue
        try:
            entities = list(raw_layer)
        except TypeError:
            entities = []

        layer_items = _build_reader_layer_items(
            entities,
            item_prefix=item_prefix,
            item_type=item_type,
            pages=pages,
        )
        if layer_items:
            layers[layer_name] = layer_items

    rows_layer = layers.get("rows", [])
    if rows_layer:
        if "paragraphs" not in layers:
            inferred_paragraphs = _infer_paragraphs_from_rows(rows_layer)
            if inferred_paragraphs:
                layers["paragraphs"] = inferred_paragraphs

        if "sections" not in layers:
            inferred_sections = _infer_sections_from_rows(rows_layer)
            if inferred_sections:
                layers["sections"] = inferred_sections

        if "bibliographies" not in layers:
            inferred_bibliographies = _infer_bibliographies_from_rows(
                rows_layer,
                layers.get("sections", []),
            )
            if inferred_bibliographies:
                layers["bibliographies"] = inferred_bibliographies

    return {"pages": pages, "layers": layers}


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

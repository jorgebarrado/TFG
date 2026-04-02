from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import os
import re
import unicodedata

from .semanticscholar import download_pdf_to_temp, get_openaccess_pdf_url
from citations.logging_utils import get_logger, log_phase

logger = get_logger("citations.citations")
TRACE_CITATIONS = os.getenv("TRACE_CITATIONS", "0") == "1"

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s]+)", re.IGNORECASE)
NUMERIC_REF_INLINE_REGEX = re.compile(r"(?:^|\s{2,}|\t)(\[(\d+)\]|(\d+)[\.\)])\s*")
LEADING_REFERENCE_LABEL_REGEX = re.compile(r"^\s*(\[(\d{1,4})\]|(\d{1,4})[\.\)])\s*")
REFERENCE_HEADERS = (
    "references",
    "bibliography",
    "referencias",
    "bibliografia",
    "works cited",
)


def _first_title(metadata: Dict[str, Any]) -> str:
    title = metadata.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    if not title:
        title = metadata.get("container-title")
        if isinstance(title, list):
            title = title[0] if title else ""
    return str(title or "")


def extract_pdf_url_from_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[str]:
    if not metadata:
        return None

    links = metadata.get("link") or []
    for link in links:
        url = link.get("URL") or link.get("url")
        content_type = (link.get("content-type") or "").lower()
        if url and ("pdf" in content_type or url.lower().endswith(".pdf")):
            return url

    url = metadata.get("URL") or metadata.get("url")
    if url and str(url).lower().endswith(".pdf"):
        return url

    return None


def resolve_pdf_url(
    metadata: Optional[Dict[str, Any]], doi: str | None
) -> Optional[str]:
    url = extract_pdf_url_from_metadata(metadata)
    if url:
        return url
    if doi:
        return get_openaccess_pdf_url(doi)
    return None


def _normalize_text(value: str) -> str:
    stripped = unicodedata.normalize("NFKD", value)
    stripped = stripped.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _is_reference_header(line: str) -> bool:
    normalized = _normalize_text(line)
    if not normalized:
        return False
    return any(normalized.startswith(header) for header in REFERENCE_HEADERS)


def _extract_reference_section(
    page_texts: List[str],
) -> Tuple[str, bool, Optional[int]]:
    for page_idx, text in enumerate(page_texts):
        lines = text.splitlines()
        for line_idx, line in enumerate(lines):
            if _is_reference_header(line):
                remaining_lines = lines[line_idx + 1 :]
                tail_pages = page_texts[page_idx + 1 :]
                section = "\n".join(remaining_lines)
                if tail_pages:
                    section = "\n".join([section] + tail_pages)
                return section, True, page_idx
    return "", False, None


def _fallback_reference_section(page_texts: List[str]) -> str:
    if not page_texts:
        return ""
    page_count = len(page_texts)
    tail_count = max(2, int(page_count * 0.25))
    start_idx = max(0, page_count - tail_count)
    return "\n\n".join(page_texts[start_idx:])


def _normalize_doi(value: str) -> str:
    candidate = value.strip()
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^https?://(?:dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE
    )
    candidate = candidate.rstrip(").,;:]")
    return candidate.strip().lower()


def _extract_doi(text: str) -> Optional[str]:
    if not text:
        return None
    url_match = DOI_URL_REGEX.search(text)
    if url_match:
        return _normalize_doi(url_match.group(1))
    match = DOI_REGEX.search(text)
    if match:
        return _normalize_doi(match.group(0))
    return None


def parse_reference_leading_label(text: str) -> Tuple[Optional[int], Optional[str]]:
    if not text:
        return None, None

    match = LEADING_REFERENCE_LABEL_REGEX.match(text)
    if not match:
        return None, None

    label = (match.group(1) or "").strip()
    numeric = match.group(2) or match.group(3) or ""
    try:
        value = int(numeric)
    except (TypeError, ValueError):
        return None, None

    # Evita usar anios o etiquetas absurdamente grandes como id de referencia.
    if value <= 0 or value > 999:
        return None, None
    if 1900 <= value <= 2099:
        return None, None
    return value, label


def _strip_reference_leading_label(text: str) -> str:
    if not text:
        return ""
    return LEADING_REFERENCE_LABEL_REGEX.sub("", text, count=1).strip()


def _has_coherent_numbered_sequence(labels: List[int]) -> bool:
    if len(labels) < 3:
        return False
    if labels[0] > 75:
        return False

    longest = 1
    run = 1
    for idx in range(1, len(labels)):
        if labels[idx] == labels[idx - 1] + 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1
    return longest >= 3


def _split_references(
    section_text: str,
) -> Tuple[List[Tuple[Optional[int], str]], bool]:
    if not section_text:
        return [], False
    lines = [line.strip() for line in section_text.splitlines()]
    lines = [line for line in lines if line]
    expanded_lines: List[str] = []
    for line in lines:
        matches = list(NUMERIC_REF_INLINE_REGEX.finditer(line))
        if len(matches) <= 1:
            expanded_lines.append(line)
            continue
        for idx, match in enumerate(matches):
            start = match.start(1)
            end = matches[idx + 1].start(1) if idx + 1 < len(matches) else len(line)
            chunk = line[start:end].strip()
            if chunk:
                expanded_lines.append(chunk)
    lines = expanded_lines
    parsed_labels = [parse_reference_leading_label(line)[0] for line in lines]
    numeric_labels = [label for label in parsed_labels if isinstance(label, int)]
    numbered = _has_coherent_numbered_sequence(numeric_labels)
    if not numbered:
        blocks = [
            re.sub(r"\s+", " ", block.strip())
            for block in re.split(r"\n\s*\n", section_text)
            if block.strip()
        ]
        return [(None, block) for block in blocks], False

    references: List[Tuple[Optional[int], str]] = []
    current: List[str] = []
    current_index: Optional[int] = None
    started = False
    for line in lines:
        line_index, _ = parse_reference_leading_label(line)
        if line_index is not None:
            if current:
                references.append((current_index, " ".join(current).strip()))
            started = True
            current_index = line_index
            line = _strip_reference_leading_label(line)
            current = [line] if line else []
        elif started:
            current.append(line)
    if current:
        references.append((current_index, " ".join(current).strip()))

    normalized: List[Tuple[Optional[int], str]] = []
    for idx, raw in references:
        if not raw:
            continue
        normalized.append((idx, raw))
    return normalized, True


def _normalize_reference_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip().lower()
    return cleaned


def extract_pdf_references(
    pdf_path: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if fitz is None or not pdf_path:
        logger.error("extract_pdf_references: fitz no disponible o pdf_path nulo")
        return [], {
            "pages_total": 0,
            "references_total": 0,
            "dois_total": 0,
            "references_numbered": False,
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
        }

    page_texts: List[str] = []
    with log_phase(logger, "extract_pdf_references_text", pdf=pdf_path):
        try:
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    page_texts.append(page.get_text() or "")
                page_count = doc.page_count
            logger.info(f"Texto extraído de {page_count} páginas mediante fitz.")
        except Exception as e:
            logger.error(f"Error al leer el PDF para referencias: {e}", exc_info=True)
            return [], {
                "pages_total": 0,
                "references_total": 0,
                "dois_total": 0,
                "references_numbered": False,
                "citation_style": "non_numeric",
                "max_reference_index": 0,
                "bibliography_start_page": None,
            }

    section, found_header, bibliography_start_page = _extract_reference_section(
        page_texts
    )
    if not section:
        logger.warning(
            f"No se detectó sección de referencias, usando fallback de texto en el documento de {page_count} páginas."
        )
        section = _fallback_reference_section(page_texts)

    logger.debug(f"Bibliografía detectada en la página {bibliography_start_page}")
    refs_raw, numbered = _split_references(section)
    references: List[Dict[str, Any]] = []
    seen_doi: set[str] = set()
    seen_raw: set[str] = set()

    for index, raw in refs_raw:
        if not raw:
            continue
        doi = _extract_doi(raw)
        if doi:
            if doi in seen_doi:
                continue
            seen_doi.add(doi)
        else:
            normalized = _normalize_reference_text(raw)
            if normalized in seen_raw:
                continue
            seen_raw.add(normalized)
        references.append(
            {
                "index": int(index) if isinstance(index, int) and index > 0 else None,
                "raw": raw,
                "doi": doi,
                "doi_source": "regex" if doi else None,
                "confidence": 1.0 if doi else 0.5,
                "numbered": bool(numbered and isinstance(index, int) and index > 0),
            }
        )

    max_reference_index = 0
    for reference in references:
        raw_index = reference.get("index")
        if isinstance(raw_index, int) and raw_index > max_reference_index:
            max_reference_index = raw_index

    dois_total = sum(1 for ref in references if ref.get("doi"))
    stats = {
        "pages_total": page_count,
        "references_total": len(references),
        "dois_total": dois_total,
        "references_numbered": bool(numbered),
        "references_header_found": bool(found_header),
        "citation_style": "numeric" if numbered else "non_numeric",
        "max_reference_index": max_reference_index or len(references),
        "bibliography_start_page": (
            bibliography_start_page + 1
            if isinstance(bibliography_start_page, int)
            else None
        ),
    }
    return references, stats


def extract_pdf_references_from_url(
    pdf_url: str | None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not pdf_url:
        return [], {
            "pages_total": 0,
            "references_total": 0,
            "dois_total": 0,
            "references_numbered": False,
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
        }
    tmp_path = download_pdf_to_temp(pdf_url)
    if not tmp_path:
        return [], {
            "pages_total": 0,
            "references_total": 0,
            "dois_total": 0,
            "references_numbered": False,
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
        }
    try:
        return extract_pdf_references(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def build_references(
    metadata: Optional[Dict[str, Any]], doi: str | None
) -> List[Dict[str, Any]]:
    if not metadata and not doi:
        return []

    return [
        {
            "doi": doi or "",
            "title": _first_title(metadata or {}),
            "raw": metadata or {},
            "confidence": 0.0,
        }
    ]


def build_mentions(contexts: Any) -> List[Dict[str, Any]]:
    if not isinstance(contexts, list):
        return []

    mentions: List[Dict[str, Any]] = []
    for ctx in contexts:
        if not isinstance(ctx, dict):
            continue
        paragraph = ctx.get("paragraph") or ""
        snippet = ctx.get("snippet") or ctx.get("fragment") or paragraph[:200]
        page = ctx.get("page") or ctx.get("page_num") or ctx.get("page_number")
        mentions.append(
            {
                "page": page,
                "snippet": snippet,
                "reference_index": 0,
                "confidence": float(ctx.get("confidence") or 0.0),
                "raw": ctx,
            }
        )
    return mentions


def build_snippets_from_results(results: Any) -> List[Dict[str, Any]]:
    if not isinstance(results, list):
        return []
    snippets: List[Dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        snippet = (
            item.get("snippet")
            or item.get("fragment")
            or item.get("raw", {}).get("snippet")
        )
        if not snippet:
            continue
        snippets.append(
            {
                "id": item.get("id") or f"snippet-{index}",
                "page": page,
                "snippet": snippet,
                "type": item.get("type") or item.get("pattern") or item.get("kind"),
                "confidence": float(item.get("confidence") or 0.0),
            }
        )
    return snippets


def build_snippets_from_mentions(mentions: Any) -> List[Dict[str, Any]]:
    if not isinstance(mentions, list):
        return []
    snippets: List[Dict[str, Any]] = []
    for index, mention in enumerate(mentions, start=1):
        if not isinstance(mention, dict):
            continue
        snippet = mention.get("snippet") or ""
        if not snippet:
            continue
        snippets.append(
            {
                "id": mention.get("id") or f"snippet-{index}",
                "page": mention.get("page"),
                "snippet": snippet,
                "type": mention.get("type")
                or mention.get("pattern")
                or mention.get("kind"),
                "confidence": float(mention.get("confidence") or 0.0),
            }
        )
    return snippets

from __future__ import annotations
from typing import Any, Dict, List, Tuple
import re
from .engines import run_engine

try:
    from .papermage_extractor import pm_extract_paragraphs
except Exception:
    pm_extract_paragraphs = None
# ====== Imports de extractores específicos (opcionales) ======
# PaperMage (si tu módulo actual está orientado a "target matching", NO lo uses aquí)
try:
    from .papermage_extractor import (
        extract_contexts_from_pdf as pm_ctx,
    )  # puede requerir params extra
except Exception:
    pm_ctx = None

# PaperCraft (si no existe, quedará None)
try:
    from .papercraft_extractor import extract_contexts_from_pdf as pc_extract  # type: ignore
except Exception:
    pc_extract = None

# ====== Dependencia ligera para el extractor genérico ======
try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# ====== Regex básicos: [n] y Autor (Año) ======
NUMERIC_CITE = re.compile(r"\[(\d+)\]")
AUTHOR_YEAR = re.compile(
    r"\b([A-Z][A-Za-z-]+(?:\s(?:and|&)\s[A-Z][A-Za-z-]+|(?:\s+et al\.)?)?)\s*\(((?:19|20)\d{2})\)"
)

CIT_NUMERIC = re.compile(r"\[(\d{1,3})\]")
CIT_AUTHORYEAR = re.compile(r"\b([A-Z][A-Za-z\-]+)\s*\(\s*(19|20)\d{2}\s*\)")
CIT_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def _make_snippet(text: str, start: int, end: int, padding: int = 80) -> str:
    """Crea un fragmento de texto alrededor de una coincidencia encontrada.

    Args:
        text (str): El texto completo del párrafo.
        start (int): La posición inicial de la coincidencia.
        end (int): La posición final de la coincidencia.
        padding (int, optional): Número de caracteres a incluir antes y después. Defaults to 80.

    Returns:
        str: El fragmento de texto con puntos suspensivos si se recorta.
    """
    left = max(start - padding, 0)
    right = min(end + padding, len(text))
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _find_hits(paragraph: str) -> List[Dict[str, Any]]:
    """Busca patrones de citas (numéricas, autor-año, DOI) en un párrafo.

    Args:
        paragraph (str): El texto del párrafo a analizar.

    Returns:
        List[Dict[str, Any]]: Una lista de diccionarios con información sobre cada coincidencia encontrada.
    """
    hits: List[Dict[str, Any]] = []
    for m in CIT_NUMERIC.finditer(paragraph):
        hits.append(
            {
                "type": "numeric",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
            }
        )
    for m in CIT_AUTHORYEAR.finditer(paragraph):
        hits.append(
            {
                "type": "authoryear",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
            }
        )
    for m in CIT_DOI.finditer(paragraph):
        hits.append(
            {
                "type": "doi",
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "snippet": _make_snippet(paragraph, m.start(), m.end()),
                "confidence": 0.0,
            }
        )
    return hits


def _extract_text_from_pdf_generic(path: str) -> str:
    """Extrae todo el texto de un PDF utilizando PyPDF2 (método genérico).

    Args:
        path (str): Ruta al archivo PDF.

    Returns:
        str: El texto extraído concatenado, o cadena vacía si falla.
    """
    if PyPDF2 is None:
        return ""
    text_parts: list[str] = []
    try:
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    pass
    except Exception:
        return ""
    return "\n".join(text_parts)


def _build_results(
    paragraphs: List[str],
    paragraphs_with_positions: List[dict] | None = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Procesa una lista de párrafos para encontrar citas y estructurar los resultados.

    Args:
        paragraphs (List[str]): Lista de cadenas de texto (párrafos).
        paragraphs_with_positions (List[dict] | None, optional): Lista opcional de diccionarios
            con metadatos posicionales de los párrafos.

    Returns:
        Tuple[List[Dict[str, Any]], int]: Una tupla conteniendo la lista de resultados
        (citas encontradas con metadatos) y el conteo total de coincidencias.
    """
    flat: List[Dict[str, Any]] = []
    total = 0
    if paragraphs_with_positions:
        items = [
            {
                "text": item.get("text", ""),
                "page": item.get("page"),
            }
            for item in paragraphs_with_positions
        ]
    else:
        items = [{"text": p, "page": None} for p in paragraphs]

    for ref, item in enumerate(items, start=1):
        text = item["text"]
        page = item.get("page")
        hs = _find_hits(text)
        if not hs:
            continue
        total += len(hs)
        for i, h in enumerate(hs, start=1):
            flat.append(
                {
                    "ref": ref,
                    "idx": i,
                    "page": page,
                    "type": h["type"],
                    "confidence": h.get("confidence", 0.0),
                    "snippet": h.get("snippet", h["match"]),
                    "paragraph": text,
                    "start": h["start"],
                    "end": h["end"],
                    "raw": h,
                }
            )
    return flat, total


def _split_paragraphs(text: str) -> list[str]:
    """Divide un texto largo en párrafos basándose en saltos de línea dobles.

    Args:
        text (str): Texto completo a dividir.

    Returns:
        list[str]: Lista de párrafos limpios.
    """
    # separa por doble salto o líneas largas
    raw = re.split(r"\n\s*\n", text)
    paras: list[str] = []
    for p in raw:
        p = p.strip()
        if not p:
            continue
        # une líneas cortadas
        p = re.sub(r"[ \t]*\n[ \t]*", " ", p).strip()
        if p:
            paras.append(p)
    return paras


def _find_citations_in_paragraph(p: str) -> list[dict]:
    """Busca citas numéricas y de tipo autor-año en un único párrafo.

    Args:
        p (str): El párrafo a analizar.

    Returns:
        list[dict]: Lista de coincidencias encontradas.
    """
    out: list[dict] = []
    # [n]
    for m in NUMERIC_CITE.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s - 80) : min(len(p), e + 80)]
        out.append(
            {
                "ref": int(m.group(1)),
                "snippet": snippet,
                "paragraph": p,
                "start": s,
                "end": e,
                "pattern": "numeric",
            }
        )
    # Autor (Año)
    for m in AUTHOR_YEAR.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s - 80) : min(len(p), e + 80)]
        out.append(
            {
                "ref": 0,
                "snippet": snippet,
                "paragraph": p,
                "start": s,
                "end": e,
                "pattern": "author-year",
                "author": m.group(1),
                "year": m.group(2),
            }
        )
    return out


def _generic_extract_contexts(path: str) -> list[dict]:
    """Extrae contextos de citas usando el método genérico (PyPDF2 + Regex).

    Args:
        path (str): Ruta al PDF.

    Returns:
        list[dict]: Lista de contextos de citas encontrados.
    """
    text = _extract_text_from_pdf_generic(path)
    if not text:
        return []
    contexts: list[dict] = []
    for p in _split_paragraphs(text):
        hits = _find_citations_in_paragraph(p)
        if hits:
            contexts.extend(hits)
    return contexts


def _pm_loose_extract(path: str) -> list[dict]:
    """Extrae contextos de citas usando PaperMage (extracción suelta).

    Args:
        path (str): Ruta al PDF.

    Returns:
        list[dict]: Lista de contextos de citas encontrados.
    """
    if pm_extract_paragraphs is None:
        return []
    try:
        paragraphs = pm_extract_paragraphs(path) or []
        out = []
        for p in paragraphs:
            out.extend(_find_citations_in_paragraph(p))
        return out
    except Exception:
        return []


def process_manuscript(
    pdf_path: str, *, engine: str = "auto", debug: bool = False
) -> Dict[str, Any]:
    """Procesa un manuscrito PDF para extraer citas utilizando un motor específico o automático.

    Args:
        pdf_path (str): Ruta al archivo PDF en el sistema de archivos local.
        engine (str, optional): Motor a utilizar ('auto', 'papermage', 'papercraft', 'generic').
            Defaults to "auto".
        debug (bool, optional): Si es True, incluye información de traza sobre los intentos realizados.
            Defaults to False.

    Returns:
        Dict[str, Any]: Un diccionario con el resultado del procesamiento. Contiene claves como:
            - 'ok' (bool): Éxito de la operación.
            - 'results' (list): Lista de citas encontradas.
            - 'summary' (dict): Resumen de conteos.
            - 'error' (str, opcional): Mensaje de error si falló.
    """
    engine_used, paragraphs, attempts, err, paragraphs_with_positions = run_engine(
        engine, pdf_path
    )

    # Si NO estamos en 'auto' y hubo error → NO hay fallback, devolvemos error
    if engine.lower() != "auto" and err:
        payload: Dict[str, Any] = {
            "ok": False,
            "engine_requested": engine,
            "engine_used": None,
            "error": err,
        }
        if debug:
            payload["trace"] = {"engines": attempts}
        return payload

    # AUTO (o motor explícito sin error): construimos resultados (aunque paragraphs pueda estar vacío)
    results, total = _build_results(paragraphs, paragraphs_with_positions)
    payload = {
        "ok": True,
        "engine_requested": engine,
        "engine_used": engine_used,
        "summary": {"paragraphs": len(paragraphs), "count": total},
        "results": results,
    }
    if debug:
        payload["trace"] = {"engines": attempts}
    return payload

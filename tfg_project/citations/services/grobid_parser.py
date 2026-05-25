"""
Parser de TEI XML producido por GROBID (integración EXPERIMENTAL).

Transforma el XML en una estructura Python sencilla de inspeccionar.
No normaliza al modelo interno del proyecto ni usa las clases/modelos existentes.

Estructura retornada por parse_tei():
    {
        "metadata": {
            "title": str,
            "authors": [str],
            "abstract": str,
        },
        "sections": [
            {"head": str, "paragraphs": [str]},
        ],
        "references": [
            {
                "id": str,           # e.g. "b0", "b1"...
                "title": str,
                "authors": [str],
                "doi": str | None,
                "year": int | None,
                "venue": str,
                "pages": str,
                "identifiers": {str: str},  # otros ids (arxiv, pmid, etc.)
            }
        ],
        "inline_citations": [
            {"target_id": str, "anchor_text": str}
        ],
        "inline_citation_count": int,
        "reference_count": int,
        "_warnings": [str],         # avisos del parser
    }

Limitaciones conocidas:
- El contexto textual de las citas inline no se extrae (ElementTree no navega al padre).
- Abstract puede aparecer truncado si es muy largo.
- Algunos campos de biblStruct pueden estar vacíos si GROBID no los detecta.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger("citations.grobid")


class GrobidParseError(Exception):
    """
    El input a parse_tei() no es XML válido o no es un documento TEI reconocible.
    Se lanza cuando el fallo es estructural (XML roto), no cuando el TEI
    simplemente carece de algunos campos opcionales.
    """


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_ABSTRACT_MAX_CHARS = 2000


def _tag(local: str) -> str:
    return f"{{{TEI_NS}}}{local}"


def _text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_authors(parent: ET.Element) -> List[str]:
    """Extrae nombres de autores de un elemento padre."""
    authors: List[str] = []
    for author in parent.findall(f".//{_tag('author')}"):
        persname = author.find(f"{_tag('persName')}")
        if persname is None:
            continue
        surname = _text(persname.find(f"{_tag('surname')}"))
        forenames = [
            _text(fn) for fn in persname.findall(f"{_tag('forename')}") if _text(fn)
        ]
        if surname:
            name = surname
            if forenames:
                name = f"{surname}, {' '.join(forenames)}"
        else:
            name = " ".join(forenames)
        if name:
            authors.append(name)
    return authors


def _parse_bibstruct(bs: ET.Element) -> Dict[str, Any]:
    """Parsea un <biblStruct> y retorna un dict con los campos clave."""
    # xml:id puede venir con o sin namespace
    ref_id = (
        bs.get(f"{{{XML_NS}}}id")
        or bs.get("{http://www.w3.org/XML/1998/namespace}id")
        or ""
    )

    analytic = bs.find(f"{_tag('analytic')}")
    monogr = bs.find(f"{_tag('monogr')}")

    # Título: primero analytic (artículo), luego monogr (libro/revista)
    title = ""
    for section in [analytic, monogr]:
        if section is None:
            continue
        t = section.find(f"{_tag('title')}")
        if t is not None:
            title = _text(t)
            if title:
                break

    # Autores: primero analytic, luego monogr
    authors: List[str] = []
    for section in [analytic, monogr]:
        if section is None:
            continue
        authors = _parse_authors(section)
        if authors:
            break

    # DOI e identificadores extra
    doi: Optional[str] = None
    identifiers: Dict[str, str] = {}
    for idno in bs.findall(f".//{_tag('idno')}"):
        id_type = (idno.get("type") or "").lower()
        id_val = _text(idno)
        if id_val:
            identifiers[id_type] = id_val
            if id_type == "doi":
                doi = id_val

    # Venue (título de la revista, si es artículo de journal)
    venue = ""
    if monogr is not None:
        for t in monogr.findall(f"{_tag('title')}"):
            if t.get("level") == "j":
                venue = _text(t)
                break

    # Año de publicación
    year: Optional[int] = None
    for date_el in bs.findall(f".//{_tag('date')}"):
        when = date_el.get("when", "")
        m = re.search(r"((?:19|20)\d{2})", when)
        if m:
            year = int(m.group(1))
            break

    # Páginas
    pages = ""
    for scope in bs.findall(f".//{_tag('biblScope')}"):
        if scope.get("unit") == "page":
            frm = scope.get("from", "")
            to = scope.get("to", "")
            if frm and to:
                pages = f"{frm}\u2013{to}"
            elif frm:
                pages = frm
            break

    return {
        "id": ref_id,
        "title": title,
        "authors": authors,
        "doi": doi,
        "year": year,
        "venue": venue,
        "pages": pages,
        "identifiers": identifiers,
    }


def _extract_inline_citations(body: ET.Element) -> List[Dict[str, Any]]:
    """
    Extrae todas las citas inline (<ref type="bibr" target="#bN">) del body.

    Nota: ElementTree no expone el elemento padre, por lo que no podemos
    obtener fácilmente el contexto textual circundante. Se devuelve solo
    el target_id y el texto del anchor.
    """
    seen: set = set()
    citations: List[Dict[str, Any]] = []
    for ref in body.findall(f".//{_tag('ref')}"):
        if ref.get("type") != "bibr":
            continue
        target = ref.get("target", "").lstrip("#")
        anchor_text = _text(ref)
        key = (target, anchor_text)
        if key not in seen:
            seen.add(key)
            citations.append({"target_id": target, "anchor_text": anchor_text})
    return citations


def _parse_tei_root(tei_xml: str) -> ET.Element:
    """Parsea el XML y valida que la raíz sea <TEI>."""
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError as exc:
        logger.error("Error parseando TEI XML de GROBID: %s", exc)
        raise GrobidParseError(f"El input no es XML válido: {exc}") from exc

    root_tag = root.tag
    if "TEI" not in root_tag:
        preview = tei_xml[:200]
        raise GrobidParseError(
            f"El documento XML no tiene <TEI> como raíz (raíz encontrada: {root_tag!r}). "
            f"Preview: {preview!r}"
        )
    return root


def _extract_references(
    root: ET.Element, *, include_raw_citation: bool = False
) -> List[Dict[str, Any]]:
    """
    Extrae referencias desde listBibl.
    Soporta biblStruct (habitual) y bibl (fallback mínimo).
    """
    references: List[Dict[str, Any]] = []
    list_bibl = root.find(f".//{_tag('listBibl')}")
    if list_bibl is None:
        return references

    for bs in list_bibl.findall(f"{_tag('biblStruct')}"):
        ref = _parse_bibstruct(bs)
        if include_raw_citation:
            raw_note = bs.find(f".//{_tag('note')}[@type='raw_reference']")
            if raw_note is None:
                raw_note = bs.find(f".//{_tag('note')}[@type='raw']")
            if raw_note is None:
                raw_note = bs.find(f".//{_tag('note')}")
            raw_citation = _text(raw_note)
            if raw_citation:
                ref["raw_citation"] = raw_citation
        references.append(ref)

    for bibl in list_bibl.findall(f"{_tag('bibl')}"):
        raw_citation = _text(bibl)
        if not raw_citation:
            continue
        ref_id = (
            bibl.get(f"{{{XML_NS}}}id")
            or bibl.get("{http://www.w3.org/XML/1998/namespace}id")
            or ""
        )
        ref: Dict[str, Any] = {
            "id": ref_id,
            "title": "",
            "authors": [],
            "doi": None,
            "year": None,
            "venue": "",
            "pages": "",
            "identifiers": {},
        }
        if include_raw_citation:
            ref["raw_citation"] = raw_citation
        references.append(ref)

    return references


def parse_tei(tei_xml: str) -> Dict[str, Any]:
    """
    Parsea el TEI XML de GROBID y devuelve una estructura Python sencilla.

    Args:
        tei_xml: String con el TEI XML devuelto por GROBID.

    Returns:
        Dict estructurado (ver docstring del módulo para el esquema completo).
        En caso de error de parseo, retorna una estructura vacía con _warnings.
    """
    warnings: List[str] = []

    root = _parse_tei_root(tei_xml)

    # -------------------------------------------------------------------------
    # Metadatos del paper
    # -------------------------------------------------------------------------
    metadata: Dict[str, Any] = {}

    # Título: buscar en teiHeader > titleStmt > title, o en el primer analytic
    title_el = root.find(f".//{_tag('teiHeader')}//{_tag('titleStmt')}/{_tag('title')}")
    if title_el is None:
        title_el = root.find(f".//{_tag('analytic')}/{_tag('title')}")
    metadata["title"] = _text(title_el)

    # Autores del header (sourceDesc o profileDesc)
    header_authors: List[str] = []
    source_desc = root.find(f".//{_tag('sourceDesc')}")
    if source_desc is not None:
        header_authors = _parse_authors(source_desc)
    if not header_authors:
        profile = root.find(f".//{_tag('profileDesc')}")
        if profile is not None:
            header_authors = _parse_authors(profile)
    metadata["authors"] = header_authors

    # Abstract
    abstract_el = root.find(f".//{_tag('abstract')}")
    abstract = _text(abstract_el) if abstract_el is not None else ""
    if len(abstract) > _ABSTRACT_MAX_CHARS:
        abstract = abstract[:_ABSTRACT_MAX_CHARS]
        warnings.append(f"Abstract truncado a {_ABSTRACT_MAX_CHARS} caracteres.")
    metadata["abstract"] = abstract

    # -------------------------------------------------------------------------
    # Secciones del body
    # -------------------------------------------------------------------------
    sections: List[Dict[str, Any]] = []
    body = root.find(f".//{_tag('body')}")
    if body is not None:
        for div in body.findall(f"{_tag('div')}"):
            head_el = div.find(f"{_tag('head')}")
            head = _text(head_el) if head_el is not None else ""
            paragraphs = [_text(p) for p in div.findall(f"{_tag('p')}") if _text(p)]
            sections.append({"head": head, "paragraphs": paragraphs})
    else:
        warnings.append("No se encontró <body> en el TEI XML.")

    # -------------------------------------------------------------------------
    # Citas inline en el texto
    # -------------------------------------------------------------------------
    inline_citations: List[Dict[str, Any]] = []
    if body is not None:
        inline_citations = _extract_inline_citations(body)

    # -------------------------------------------------------------------------
    # Bibliografía (back > listBibl)
    # -------------------------------------------------------------------------
    references = _extract_references(root, include_raw_citation=False)
    if not references:
        warnings.append("No se encontró <listBibl> en el TEI XML (sin bibliografía).")

    # -------------------------------------------------------------------------
    # Validaciones básicas
    # -------------------------------------------------------------------------
    if not metadata.get("title"):
        warnings.append("GROBID no extrajo título del paper.")
    if not metadata.get("authors"):
        warnings.append("GROBID no extrajo autores del paper.")
    if not references:
        warnings.append("GROBID no encontró referencias bibliográficas.")
    if not inline_citations:
        warnings.append("GROBID no encontró citas inline en el texto.")

    logger.debug(
        "TEI parseado: %d referencias, %d citas inline, %d secciones.",
        len(references),
        len(inline_citations),
        len(sections),
    )

    return {
        "mode": "fulltext",
        "metadata": metadata,
        "sections": sections,
        "references": references,
        "inline_citations": inline_citations,
        "inline_citation_count": len(inline_citations),
        "reference_count": len(references),
        "_warnings": warnings,
    }


def parse_fulltext_tei(tei_xml: str) -> Dict[str, Any]:
    """Alias explícito para parsear respuesta de /api/processFulltextDocument."""
    return parse_tei(tei_xml)


def parse_header_tei(tei_xml: str) -> Dict[str, Any]:
    """
    Parser para TEI de /api/processHeaderDocument.
    Devuelve estructura simple de metadatos.
    """
    warnings: List[str] = []
    root = _parse_tei_root(tei_xml)

    title_el = root.find(f".//{_tag('teiHeader')}//{_tag('titleStmt')}/{_tag('title')}")
    if title_el is None:
        title_el = root.find(f".//{_tag('analytic')}/{_tag('title')}")
    title = _text(title_el)

    authors: List[str] = []
    source_desc = root.find(f".//{_tag('sourceDesc')}")
    if source_desc is not None:
        authors = _parse_authors(source_desc)
    if not authors:
        profile = root.find(f".//{_tag('profileDesc')}")
        if profile is not None:
            authors = _parse_authors(profile)

    abstract_el = root.find(f".//{_tag('abstract')}")
    abstract = _text(abstract_el) if abstract_el is not None else ""
    if len(abstract) > _ABSTRACT_MAX_CHARS:
        abstract = abstract[:_ABSTRACT_MAX_CHARS]
        warnings.append(f"Abstract truncado a {_ABSTRACT_MAX_CHARS} caracteres.")

    identifiers: Dict[str, str] = {}
    doi: Optional[str] = None
    for idno in root.findall(f".//{_tag('idno')}"):
        id_type = (idno.get("type") or "").lower().strip() or "unknown"
        id_val = _text(idno)
        if not id_val:
            continue
        if id_type not in identifiers:
            identifiers[id_type] = id_val
        if id_type == "doi" and not doi:
            doi = id_val

    if not title:
        warnings.append("GROBID no extrajo título del paper.")
    if not authors:
        warnings.append("GROBID no extrajo autores del paper.")

    return {
        "mode": "header",
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "doi": doi,
        "identifiers": identifiers,
        "_warnings": warnings,
    }


def parse_references_tei(
    tei_xml: str, *, include_raw_citation: bool = True
) -> Dict[str, Any]:
    """
    Parser para TEI de /api/processReferences.
    Devuelve una estructura centrada en bibliografía.
    """
    warnings: List[str] = []
    root = _parse_tei_root(tei_xml)
    references = _extract_references(root, include_raw_citation=include_raw_citation)

    if not references:
        warnings.append(
            "GROBID no encontró referencias bibliográficas en /api/processReferences."
        )

    return {
        "mode": "references",
        "metadata": {},
        "sections": [],
        "references": references,
        "inline_citations": [],
        "inline_citation_count": 0,
        "reference_count": len(references),
        "_warnings": warnings,
    }

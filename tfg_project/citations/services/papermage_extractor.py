# citations/services/papermage_extractor.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# Fallbacks
try:
    # PaperMage API (simplificado: CoreRecipe produce texto estructurado)
    # Documentación: https://github.com/allenai/papermage
    from papermage.magelib import Span
    from papermage.recipes.core import CoreRecipe
    PAPERMAGE_AVAILABLE = True
except Exception:
    PAPERMAGE_AVAILABLE = False

try:
    from PyPDF2 import PdfReader  # type: ignore
    PYPDF2_AVAILABLE = True
except Exception:
    PYPDF2_AVAILABLE = False


@dataclass
class CitationHit:
    paragraph: str
    snippet: str
    start_char: int
    end_char: int
    boxes: Optional[List[List[float]]] = None


def _spans_overlap(span1: Span, span2: Span) -> bool:
    return span1.start < span2.end and span2.start < span1.end


def _build_patterns(
    target_title: Optional[str],
    target_first_author: Optional[str],
    target_year: Optional[str],
    target_doi: Optional[str],
) -> List[re.Pattern]:
    """
    Construye patrones razonables para encontrar la cita en texto:
    - DOI (si hay)
    - estilo autor-año: 'Apellido, 2020' o '(Apellido 2020)'
    - fragmento del título (3-6 palabras iniciales)
    """
    patterns: List[re.Pattern] = []

    if target_doi:
        safe = re.escape(target_doi.lower())
        patterns.append(re.compile(safe, re.IGNORECASE))

    if target_first_author and target_year:
        # Variantes: "Smith, 2020" / "(Smith 2020)" / "Smith (2020)"
        auth = re.escape(target_first_author.strip())
        yr = re.escape(str(target_year).strip())
        pats = [
            rf"\b{auth}\s*,\s*{yr}\b",
            rf"\({auth}\s*,?\s*{yr}\)",
            rf"\b{auth}\s*\(\s*{yr}\s*\)",
            rf"\b{auth}\s+et al\.\s*,?\s*{yr}\b",
            rf"\({auth}\s+et al\.\s*,?\s*{yr}\)",
        ]
        patterns.extend([re.compile(p, re.IGNORECASE) for p in pats])

    if target_title:
        # Usamos 3-6 primeras palabras del título como indicio
        words = re.findall(r"\w+", target_title)
        head = " ".join(words[:6]).strip()
        if len(head) >= 12:  # sólo si es lo bastante distintivo
            patterns.append(re.compile(re.escape(head), re.IGNORECASE))

    return patterns


def _paragraphs_from_text(text: str) -> List[str]:
    # División robusta por párrafos
    parts = re.split(r"\n\s*\n+", text.strip())
    # Limpieza de espacios
    return [re.sub(r"[ \t]+", " ", p).strip() for p in parts if p.strip()]


def _hits_from_text(
    text: str,
    patterns: List[re.Pattern],
    window: int = 120,
) -> List[CitationHit]:
    hits: List[CitationHit] = []
    paragraphs = _paragraphs_from_text(text)
    cursor = 0
    for p in paragraphs:
        p_start = cursor
        p_end = cursor + len(p)
        for pat in patterns:
            for m in pat.finditer(p):
                s = p_start + m.start()
                e = p_start + m.end()
                left = max(0, s - window)
                right = min(len(text), e + window)
                snippet = text[left:right].replace("\n", " ")
                hits.append(
                    CitationHit(
                        paragraph=p, snippet=snippet, start_char=s, end_char=e, boxes=None
                    )
                )
        cursor = p_end + 2  # aprox: suma salto de párrafo
    return hits


def _extract_with_pypdf2(pdf_path: str) -> str:
    if not PYPDF2_AVAILABLE:
        return ""
    reader = PdfReader(pdf_path)
    texts = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        texts.append(t)
    return "\n\n".join(texts)


def extract_contexts_from_pdf(
    pdf_path: str,
    *,
    target_title: Optional[str],
    target_first_author: Optional[str],
    target_year: Optional[str],
    target_doi: Optional[str],
    max_hits: int = 12,
    window: int = 120,
) -> List[dict]:
    """
    Devuelve una lista de dicts con:
    - paragraph
    - snippet (±120)
    - start / end
    - boxes (coordenadas en el PDF)
    """
    patterns = _build_patterns(target_title, target_first_author, target_year, target_doi)
    hits: List[CitationHit] = []

    # 1) Intento con PaperMage (texto estructurado + coordenadas)
    if PAPERMAGE_AVAILABLE:
        try:
            doc = CoreRecipe().run(pdf_path)
            doc_text = doc.text
            tokens = doc.tokens

            if hasattr(doc, "paragraphs") and doc.paragraphs:
                for para in doc.paragraphs:
                    para_text = para.text
                    for pat in patterns:
                        for m in pat.finditer(para_text):
                            match_span_in_para = Span(m.start(), m.end())
                            match_span_in_doc = Span(
                                start=para.spans[0].start + match_span_in_para.start,
                                end=para.spans[0].start + match_span_in_para.end,
                            )
                            # Bounding boxes de los tokens que se solapan con el match
                            match_boxes = [
                                tok.box.to_list()
                                for tok in tokens
                                if _spans_overlap(tok.spans[0], match_span_in_doc)
                            ]
                            # Snippet con ventana
                            left = max(0, match_span_in_doc.start - window)
                            right = min(len(doc_text), match_span_in_doc.end + window)
                            snippet = doc_text[left:right].replace("\n", " ")

                            hits.append(
                                CitationHit(
                                    paragraph=para_text,
                                    snippet=snippet,
                                    start_char=match_span_in_doc.start,
                                    end_char=match_span_in_doc.end,
                                    boxes=match_boxes,
                                )
                            )
            if hits:
                return [
                    {
                        "paragraph": h.paragraph,
                        "snippet": h.snippet,
                        "start": h.start_char,
                        "end": h.end_char,
                        "boxes": h.boxes,
                    }
                    for h in hits[:max_hits]
                ]
        except Exception:
            pass  # Fallback a PyPDF2

    # 2) Fallback: PyPDF2 + regex (sin coordenadas)
    plain_text = _extract_with_pypdf2(pdf_path)
    text_hits = _hits_from_text(plain_text, patterns)
    return [
        {
            "paragraph": h.paragraph,
            "snippet": h.snippet,
            "start": h.start_char,
            "end": h.end_char,
            "boxes": None,  # No hay coordenadas en este modo
        }
        for h in text_hits[:max_hits]
    ]

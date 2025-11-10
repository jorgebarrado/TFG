# citations/services/papermage_extractor.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# Fallbacks
try:
    # PaperMage API (simplificado: CoreRecipe produce texto estructurado)
    # Documentación: https://github.com/allenai/papermage
    from papermage.recipes.core import CoreRecipe  # type: ignore
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
    """
    Representa una coincidencia de cita encontrada en el texto.

    Atributos:
        paragraph (str): El párrafo donde se encontró la cita.
        snippet (str): Un fragmento de texto alrededor de la cita.
        start_char (int): El índice del caracter de inicio de la cita.
        end_char (int): El índice del caracter de fin de la cita.
    """
    paragraph: str
    snippet: str
    start_char: int
    end_char: int


def _build_patterns(
    target_title: Optional[str],
    target_first_author: Optional[str],
    target_year: Optional[str],
    target_doi: Optional[str],
) -> List[re.Pattern]:
    """
    Construye una lista de patrones de expresiones regulares para encontrar citas en el texto.

    Args:
        target_title (Optional[str]): El título del artículo citado.
        target_first_author (Optional[str]): El primer autor del artículo citado.
        target_year (Optional[str]): El año de publicación del artículo citado.
        target_doi (Optional[str]): El DOI del artículo citado.

    Returns:
        List[re.Pattern]: Una lista de patrones de expresiones regulares.
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
    """
    Divide un texto en párrafos y limpia los espacios en blanco.

    Args:
        text (str): El texto a procesar.

    Returns:
        List[str]: Una lista de párrafos limpios.
    """
    # División robusta por párrafos
    parts = re.split(r"\n\s*\n+", text.strip())
    # Limpieza de espacios
    return [re.sub(r"[ \t]+", " ", p).strip() for p in parts if p.strip()]


def _hits_from_text(
    text: str,
    patterns: List[re.Pattern],
    window: int = 120,
) -> List[CitationHit]:
    """
    Encuentra todas las coincidencias de citas en un texto, utilizando una lista de patrones.

    Args:
        text (str): El texto en el que buscar.
        patterns (List[re.Pattern]): La lista de patrones de expresiones regulares a utilizar.
        window (int, optional): El número de caracteres a cada lado de la coincidencia para crear el snippet. Defaults to 120.

    Returns:
        List[CitationHit]: Una lista de objetos CitationHit con las coincidencias encontradas.
    """
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
                hits.append(CitationHit(paragraph=p, snippet=snippet, start_char=s, end_char=e))
        cursor = p_end + 2  # aprox: suma salto de párrafo
    return hits


def _extract_with_pypdf2(pdf_path: str) -> str:
    """
    Extrae el texto de un archivo PDF utilizando PyPDF2.

    Args:
        pdf_path (str): La ruta al archivo PDF.

    Returns:
        str: El texto extraído del PDF.
    """
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
) -> List[dict]:
    """
    Extrae los contextos de una cita de un archivo PDF, utilizando PaperMage si está disponible,
    o PyPDF2 como alternativa.

    Args:
        pdf_path (str): La ruta al archivo PDF.
        target_title (Optional[str]): El título del artículo citado.
        target_first_author (Optional[str]): El primer autor del artículo citado.
        target_year (Optional[str]): El año de publicación del artículo citado.
        target_doi (Optional[str]): El DOI del artículo citado.
        max_hits (int, optional): El número máximo de coincidencias a devolver. Defaults to 12.

    Returns:
        List[dict]: Una lista de diccionarios, cada uno representando un contexto de cita.
    """

    patterns = _build_patterns(target_title, target_first_author, target_year, target_doi)

    # 1) Intento con PaperMage (texto estructurado)
    if PAPERMAGE_AVAILABLE:
        try:
            doc = CoreRecipe().run(pdf_path)  # produce un objeto con secciones/paragraphs
            # Extraemos texto "lógico" por párrafo; fallback si no hay estructura
            paragraphs: List[str] = []
            if hasattr(doc, "paragraphs") and doc.paragraphs:
                for para in doc.paragraphs:
                    txt = getattr(para, "text", None) or ""
                    txt = re.sub(r"[ \t]+", " ", txt).strip()
                    if txt:
                        paragraphs.append(txt)
            else:
                # fallback a lectura plana si la receta no devolvió estructura
                plain = _extract_with_pypdf2(pdf_path)
                paragraphs = _paragraphs_from_text(plain)

            full_text = "\n\n".join(paragraphs)
            hits = _hits_from_text(full_text, patterns)
            return [
                {
                    "paragraph": h.paragraph,
                    "snippet": h.snippet,
                    "start": h.start_char,
                    "end": h.end_char,
                }
                for h in hits[:max_hits]
            ]
        except Exception:
            # cae al fallback
            pass

    # 2) Fallback: PyPDF2 + regex
    plain = _extract_with_pypdf2(pdf_path)
    hits = _hits_from_text(plain, patterns)
    return [
        {
            "paragraph": h.paragraph,
            "snippet": h.snippet,
            "start": h.start_char,
            "end": h.end_char,
        }
        for h in hits[:max_hits]
    ]

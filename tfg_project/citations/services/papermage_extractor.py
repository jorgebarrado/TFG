from __future__ import annotations

from typing import List, Optional, Dict
import re

# Intentar usar PaperMage; si no, caemos a pdfplumber
try:
    # PaperMage no tiene una API única estable; este import es “no-op” para forzar la presencia.
    import papermage  # noqa: F401
    PM_AVAILABLE = True
except Exception:
    PM_AVAILABLE = False

# Respaldo: pdfplumber para extraer texto por páginas
try:
    import pdfplumber  # type: ignore
except Exception:
    pdfplumber = None


# ----------------------------
# Utilidades comunes
# ----------------------------

def _load_paragraphs_with_pdfplumber(pdf_path: str) -> List[str]:
    """Respaldo robusto: páginas -> texto -> párrafos (por saltos de línea en blanco)."""
    if pdfplumber is None:
        return []
    paragraphs: List[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            chunks: List[str] = []
            for page in pdf.pages:
                txt = page.extract_text() or ""
                chunks.append(txt)
            full = "\n".join(chunks)
        # Separar párrafos por líneas en blanco
        for block in re.split(r"\n\s*\n", full):
            p = block.strip()
            if len(p) > 40:  # filtrar ruido muy corto
                paragraphs.append(p)
    except Exception:
        return []
    return paragraphs


def pm_extract_paragraphs(pdf_path: str) -> List[str]:
    """
    Adaptador "sin target": devuelve párrafos. Si PaperMage está OK, aquí
    podrías invocar su pipeline real; por ahora usamos pdfplumber como respaldo estable.
    """
    # TODO: integrar pipeline real de PaperMage para segmentación de párrafos.
    return _load_paragraphs_with_pdfplumber(pdf_path)


# ----------------------------
# Extractor "con target" (para View context)
# ----------------------------

def extract_contexts_from_pdf(
    pdf_path: str,
    target_title: Optional[str] = None,
    target_first_author: Optional[str] = None,
    target_year: Optional[str] = None,
    target_doi: Optional[str] = None,
) -> List[Dict]:
    """
    Devuelve una lista de contextos (diccionarios) que “parecen” citar al artículo objetivo.
    Estrategia simple:
      - Buscar párrafos que contengan DOI del objetivo, o
      - 'ApellidoAutor' y el año, o
      - palabras significativas del título (muy básicas).
    El formato devuelto es compatible con tu modal de 'View context'.
    """
    paragraphs = pm_extract_paragraphs(pdf_path)
    if not paragraphs:
        return []

    goal = (target_title or "") + " " + (target_first_author or "") + " " + (target_year or "") + " " + (target_doi or "")
    if not goal.strip():
        # Si no hay “objetivo”, no podemos filtrar. Devolvemos vacío.
        return []

    hits: List[Dict] = []

    # Preparar patrones
    doi_pat = (re.escape(target_doi.strip().lower()) if target_doi else None)
    author_pat = (re.escape((target_first_author or "").split()[-1]) if target_first_author else None)  # último apellido
    year_pat = (re.escape(target_year) if target_year else None)

    # Palabras “clave” del título (muy simple): >= 5 letras
    title_keys = []
    if target_title:
        for w in re.findall(r"[A-Za-z]{5,}", target_title.lower()):
            title_keys.append(w)

    for p in paragraphs:
        pl = p.lower()
        score = 0

        # DOI directo
        if doi_pat and doi_pat in pl:
            score += 3

        # Autor + año (e.g., "Smith (2019)" o "[Smith, 2019]")
        if author_pat and year_pat:
            if re.search(rf"{author_pat}[^0-9]{{0,20}}{year_pat}", pl):
                score += 2

        # Título: si aparecen ≥2 claves del título, sube puntos
        if title_keys:
            count = sum(1 for w in title_keys if w in pl)
            if count >= 2:
                score += 1

        if score > 0:
            # Construir contexto mínimo esperado por el frontend
            hits.append(
                {
                    "paragraph": p,
                    "snippet": _shorten(p),
                    "start": 0,
                    "end": min(len(p), 400),
                }
            )

    return hits


def _shorten(s: str, width: int = 300) -> str:
    s = " ".join(s.split())
    return s if len(s) <= width else s[: width - 1] + "…"

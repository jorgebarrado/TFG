from __future__ import annotations
from typing import Any, List
import re

try:
    from .papermage_extractor import pm_extract_paragraphs
except Exception:
    pm_extract_paragraphs = None
# ====== Imports de extractores específicos (opcionales) ======
# PaperMage (si tu módulo actual está orientado a "target matching", NO lo uses aquí)
try:
    from .papermage_extractor import extract_contexts_from_pdf as pm_ctx  # puede requerir params extra
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
AUTHOR_YEAR  = re.compile(
    r"\b([A-Z][A-Za-z-]+(?:\s(?:and|&)\s[A-Z][A-Za-z-]+|(?:\s+et al\.)?)?)\s*\(((?:19|20)\d{2})\)"
)

def _extract_text_from_pdf_generic(path: str) -> str:
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

def _split_paragraphs(text: str) -> list[str]:
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
    out: list[dict] = []
    # [n]
    for m in NUMERIC_CITE.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s-80): min(len(p), e+80)]
        out.append({
            "ref": int(m.group(1)),
            "snippet": snippet,
            "paragraph": p,
            "start": s, "end": e,
            "pattern": "numeric"
        })
    # Autor (Año)
    for m in AUTHOR_YEAR.finditer(p):
        s, e = m.span()
        snippet = p[max(0, s-80): min(len(p), e+80)]
        out.append({
            "ref": 0,
            "snippet": snippet,
            "paragraph": p,
            "start": s, "end": e,
            "pattern": "author-year",
            "author": m.group(1),
            "year": m.group(2),
        })
    return out

def _generic_extract_contexts(path: str) -> list[dict]:
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

def process_manuscript(path: str, *, engine: str = "auto", debug: bool = False) -> dict[str, Any]:
    """
    Salida:
    {
      ok: bool,
      engine_used: "papermage"|"papercraft"|"generic"|None,
      count: int,
      contexts: [ { paragraph, snippet, start, end, ... }, ... ],
      error?: str,
      trace?: [{step,status,detail}]
    }
    """
    trace: list[dict] = []
    def add(step: str, status: str = "ok", detail: str = ""):
        trace.append({"step": step, "status": status, "detail": detail})

    engine = (engine or "auto").lower().strip()
    contexts: list[dict] = []
    engine_used: str | None = None

    # Selección explícita
    if engine == "papercraft":
        if pc_extract is None:
            add("papercraft.start", "error", "not installed/implemented")
            out = {"ok": False, "error": "PaperCraft extractor not installed", "engine_used": None, "count": 0, "contexts": []}
            if debug: out["trace"] = trace
            return out
        add("papercraft.start")
        try:
            contexts = pc_extract(path) or []
        except Exception as e:
            add("papercraft.error", "error", str(e))
            out = {"ok": False, "error": "PaperCraft failed", "engine_used": None, "count": 0, "contexts": []}
            if debug: out["trace"] = trace
            return out
        engine_used = "papercraft"
        add("papercraft.done", detail=f"hits={len(contexts)}")

    elif engine == "papermage":
        # Si tu pm requiere deps/argumentos, avisamos si está indisponible
        if pm_ctx is None:
            add("papermage.start", "error", "not available")
            out = {"ok": False, "error": "PaperMage extractor not available", "engine_used": None, "count": 0, "contexts": []}
            if debug: out["trace"] = trace
            return out
        add("papermage.start")
        contexts = _pm_loose_extract(path)  # intenta usar tu impl; si no sirve, devuelve []
        engine_used = "papermage"
        add("papermage.done", detail=f"hits={len(contexts)}")

        # Si no hubo hits, caemos al genérico para no dejarte sin resultados
        if not contexts:
            add("fallback.generic.start")
            contexts = _generic_extract_contexts(path)
            engine_used = "generic"
            add("fallback.generic.done", detail=f"hits={len(contexts)}")

    else:
        # AUTO → intenta papermage y, si no, genérico; luego (si existe) papercraft
        add("auto.papermage.start")
        pm_hits = _pm_loose_extract(path)
        if pm_hits:
            contexts = pm_hits
            engine_used = "papermage"
            add("auto.papermage.done", detail=f"hits={len(contexts)}")
        else:
            add("auto.generic.start")
            contexts = _generic_extract_contexts(path)
            engine_used = "generic"
            add("auto.generic.done", detail=f"hits={len(contexts)}")
            # Si aún quisieras probar papercraft al final:
            # if not contexts and pc_extract is not None:
            #     add("auto.papercraft.start")
            #     contexts = pc_extract(path) or []
            #     engine_used = "papercraft" if contexts else engine_used
            #     add("auto.papercraft.done", detail=f"hits={len(contexts)}")

    out = {"ok": True, "engine_used": engine_used, "count": len(contexts), "contexts": contexts}
    if debug: out["trace"] = trace
    return out

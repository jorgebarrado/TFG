# Motor de extracción de referencias y citas mediante LLM (Claude, OpenAI, Gemini).
# Usa pdfplumber para extraer texto del PDF y un LLM para estructurar referencias y contextos.
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

import pdfplumber

AI_ENGINES = {"ai_claude", "ai_openai", "ai_gemini"}

_REFS_PROMPT_HEADER = """\
Eres un experto en bibliografía científica.

Extrae TODAS las entradas de la lista de referencias del siguiente texto (sección de bibliografía).

Devuelve ÚNICAMENTE un JSON válido con esta estructura (sin texto adicional):
{
  "references": [
    {
      "index": 1,
      "text": "Texto completo de la referencia tal como aparece",
      "title": "Título del artículo o libro",
      "authors": ["Apellido, N.", "Apellido2, N2."],
      "year": "2020",
      "doi": "10.xxx/xxx",
      "venue": "Revista o conferencia"
    }
  ]
}

Notas:
- Si no hay DOI, usa null.
- Extrae TODAS las referencias, no solo algunas.

TEXTO DE LA SECCIÓN DE REFERENCIAS:

"""

_CONTEXTS_PROMPT_HEADER = """\
Eres un experto en citas académicas.

Identifica TODAS las citas en el texto del artículo. Una cita es cualquier referencia a otra obra, ya sea numérica ([1], [2,3]), autor-año (Smith, 2020) o similar.

Devuelve ÚNICAMENTE un JSON válido con esta estructura (sin texto adicional):
{
  "citation_contexts": [
    {
      "ref_indices": [1, 2],
      "page": 3,
      "snippet": "...fragmento corto con la cita...",
      "paragraph": "Párrafo completo donde aparece"
    }
  ]
}

Notas:
- ref_indices: lista de índices enteros de las referencias citadas.
- Incluye citas implícitas (autor-año) y explícitas ([N]).

TEXTO DEL ARTÍCULO (cuerpo, sin bibliografía):

"""

# Límite de caracteres enviados al LLM para mantenerse dentro del tier gratuito.
# ~4.000 chars ≈ ~1.000 tokens; ajustado para no superar el límite de tokens/min.
_MAX_REFS_CHARS = 12_000   # bibliografía raramente supera esto
_MAX_BODY_CHARS = 20_000   # cuerpo truncado para caber en el límite gratuito

_BIB_MARKERS = re.compile(
    r"^\s*(references|bibliography|bibliograf[ií]a|obras citadas|literatur)",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_pdf_pages(pdf_path: str) -> List[Dict[str, Any]]:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append({"page": i + 1, "text": text})
    return pages


def _split_body_and_refs(pages: List[Dict[str, Any]]) -> tuple[str, str]:
    """Separa el texto en cuerpo y sección de referencias."""
    full_text = "\n\n".join(
        f"[Página {p['page']}]\n{p['text']}" for p in pages if p["text"].strip()
    )
    match = _BIB_MARKERS.search(full_text)
    if match:
        split = match.start()
        return full_text[:split], full_text[split:]
    # Sin marcador: últimas 3 páginas como bibliografía aproximada
    if len(pages) >= 3:
        body_pages = pages[:-3]
        ref_pages = pages[-3:]
    else:
        body_pages = []
        ref_pages = pages
    body = "\n\n".join(
        f"[Página {p['page']}]\n{p['text']}" for p in body_pages if p["text"].strip()
    )
    refs = "\n\n".join(
        f"[Página {p['page']}]\n{p['text']}" for p in ref_pages if p["text"].strip()
    )
    return body, refs


def _build_refs_prompt(refs_text: str) -> str:
    return _REFS_PROMPT_HEADER + refs_text[:_MAX_REFS_CHARS]


def _build_contexts_prompt(body_text: str) -> str:
    return _CONTEXTS_PROMPT_HEADER + body_text[:_MAX_BODY_CHARS]


def _parse_json_response(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError(f"Respuesta IA con formato JSON inválido: {text[:300]}")


def _call_claude(prompt: str) -> Dict[str, Any]:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError(
            "Falta la dependencia 'anthropic'. Instala con: pip install 'anthropic>=0.50'"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno ANTHROPIC_API_KEY.")

    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json_response(message.content[0].text)


def _call_openai(prompt: str) -> Dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "Falta la dependencia 'openai'. Instala con: pip install 'openai>=1.0'"
        ) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno OPENAI_API_KEY.")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return _parse_json_response(response.choices[0].message.content)


def _call_gemini(prompt: str) -> Dict[str, Any]:
    import time

    import requests

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Falta la variable de entorno GOOGLE_API_KEY.")

    model = "gemini-3.5-flash"
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0},
    }

    # Reintentos con backoff para errores transitorios (503 sobrecarga, 429 cuota temporal).
    # El usuario prefiere esperar a que falle, así que esperamos hasta 5 minutos entre reintentos.
    retry_delays = [15, 30, 60, 120]
    last_error = ""
    for attempt, delay in enumerate([0] + retry_delays):
        if delay:
            time.sleep(delay)
        resp = requests.post(url, json=payload, timeout=300)
        if resp.ok:
            break
        last_error = f"Error de la API de Gemini ({resp.status_code}): {resp.text[:300]}"
        if resp.status_code in (429, 503) and attempt < len(retry_delays):
            continue
        raise RuntimeError(last_error)
    else:
        raise RuntimeError(last_error)
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_response(text)


_PROVIDERS: Dict[str, Any] = {
    "ai_claude": _call_claude,
    "ai_openai": _call_openai,
    "ai_gemini": _call_gemini,
}


def _normalize_references(raw_refs: List[Any]) -> List[Dict[str, Any]]:
    normalized = []
    for i, ref in enumerate(raw_refs or []):
        if not isinstance(ref, dict):
            continue
        idx = ref.get("index") or (i + 1)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = i + 1
        doi = ref.get("doi")
        if doi and str(doi).lower() in ("null", "none", ""):
            doi = None
        normalized.append(
            {
                "index": idx,
                "text": str(ref.get("text") or ""),
                "title": str(ref.get("title") or ""),
                "authors": ref.get("authors") or [],
                "year": str(ref.get("year") or ""),
                "doi": doi,
                "venue": str(ref.get("venue") or ""),
                "source": "ai_extracted",
            }
        )
    return normalized


def _normalize_citation_contexts(raw_contexts: List[Any]) -> List[Dict[str, Any]]:
    results = []
    for ctx in raw_contexts or []:
        if not isinstance(ctx, dict):
            continue
        ref_indices = ctx.get("ref_indices") or []
        if not isinstance(ref_indices, list):
            ref_indices = [ref_indices]
        for ref_idx in ref_indices:
            try:
                ref_idx = int(ref_idx)
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "ref": ref_idx,
                    "idx": ref_idx,
                    "page": ctx.get("page"),
                    "snippet": str(ctx.get("snippet") or ""),
                    "paragraph": str(ctx.get("paragraph") or ""),
                    "type": "ai_detected",
                    "confidence": 1.0,
                    "pattern": "ai_extracted",
                    "source": "ai_extracted",
                    "start": 0,
                    "end": 0,
                }
            )
    return results


def _detect_citation_style(references: List[Dict[str, Any]]) -> Tuple[str, bool, int]:
    """Returns (citation_style, references_numbered, max_reference_index)."""
    if not references:
        return "non_numeric", False, 0
    indices = [r.get("index") for r in references if isinstance(r.get("index"), int)]
    if indices and min(indices) >= 1 and max(indices) == len(references):
        return "numeric", True, max(indices)
    return "non_numeric", False, len(references)


def extract_with_ai(engine: str, pdf_path: str) -> Dict[str, Any]:
    """
    Extrae referencias y contextos de cita de un PDF usando un LLM.

    Envía dos prompts separados (referencias + contextos) para minimizar el uso
    de tokens por petición y mantenerse dentro del tier gratuito de Gemini.
    """
    call_fn = _PROVIDERS.get(engine)
    if not call_fn:
        raise ValueError(f"Motor IA desconocido: {engine}")

    pages = _extract_pdf_pages(pdf_path)
    non_empty = [p for p in pages if p["text"].strip()]
    if not non_empty:
        raise RuntimeError(
            "No se pudo extraer texto del PDF. "
            "El documento puede estar basado en imágenes escaneadas."
        )

    body_text, refs_text = _split_body_and_refs(pages)

    # Primera llamada: solo la sección de referencias (pequeña)
    refs_data = call_fn(_build_refs_prompt(refs_text))
    references = _normalize_references(refs_data.get("references", []))

    # Segunda llamada: cuerpo del artículo truncado (contextos de cita)
    try:
        ctx_data = call_fn(_build_contexts_prompt(body_text))
        results = _normalize_citation_contexts(ctx_data.get("citation_contexts", []))
    except Exception:
        # Si la segunda llamada falla (cuota), devolvemos las referencias sin contextos
        results = []
    citation_style, references_numbered, max_ref_idx = _detect_citation_style(references)

    return {
        "ok": True,
        "engine_used": engine,
        "references": references,
        "results": results,
        "pages_total": len(pages),
        "citation_style": citation_style,
        "references_numbered": references_numbered,
        "max_reference_index": max_ref_idx,
    }

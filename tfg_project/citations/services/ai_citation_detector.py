import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from citations.models import IncorrectCitation
from .papermage_extractor import pm_extract_paragraphs_with_positions


@dataclass
class AiDetectionResult:
    """
    Representa el resultado de una detección de cita por IA.
    """

    page: int
    paragraph_index: int
    confidence: float
    reason: str
    text: str


def build_ai_prompt_for_detection(
    metadata_original: dict, paragraphs: List[Dict[str, Any]]
) -> str:
    """Construye el prompt para el modelo IA a partir de metadatos y párrafos.

    Args:
        metadata_original (dict): Metadatos del artículo citado (A).
        paragraphs (List[Dict[str, Any]]): Lista de párrafos del artículo citante (B).

    Returns:
        str: El prompt formateado para enviar al modelo de IA.
    """
    title_field = metadata_original.get("title")
    title = title_field[0] if isinstance(title_field, list) else title_field or ""

    authors = metadata_original.get("author", [])
    year = (
        metadata_original.get("published-print", {})
        .get("date-parts", [[None]])[0][0]
        or metadata_original.get("published-online", {})
        .get("date-parts", [[None]])[0][0]
        or metadata_original.get("issued", {})
        .get("date-parts", [[None]])[0][0]
    )

    authors_str = ", ".join(
        f"{a.get('given', '')} {a.get('family', '')}".strip() for a in authors
    ) or "N/A"

    header = (
        "Eres un asistente experto en citas académicas.\n\n"
        "Tu tarea es identificar en qué párrafos del artículo B se cita o se hace referencia\n"
        "al artículo A, incluso si la cita es abreviada o solo por autores/año.\n\n"
        "Artículo A (objetivo):\n"
        f"- Título: {title}\n"
        f"- Autores: {authors_str}\n"
        f"- Año aproximado: {year}\n\n"
        "Se te proporcionan párrafos del artículo B con página e índice.\n"
        "Devuelve SOLO un JSON con una única clave 'matches', que es una lista.\n"
        "Cada elemento debe tener este formato:\n"
        "{\n"
        '  \"page\": <numero>,\n'
        '  \"paragraph_index\": <indice>,\n'
        '  \"confidence\": <numero entre 0 y 1>,\n'
        '  \"reason\": \"<explicacion corta>\",\n'
        '  \"text\": \"<texto literal del parrafo o fragmento relevante>\"\n'
        "}\n\n"
        "No incluyas texto adicional fuera del JSON.\n\n"
    )

    paragraphs_str = ""
    for p in paragraphs:
        paragraphs_str += f"[PAGE {p['page']} | INDEX {p['index']}]\n{p['text']}\n\n"

    return header + "Párrafos del artículo B:\n\n" + paragraphs_str


def call_llm_for_detection(prompt: str) -> Dict[str, Any]:
    """Realiza la llamada al modelo LLM (Gemini) para detectar citas.

    Args:
        prompt (str): El prompt a enviar al modelo.

    Returns:
        Dict[str, Any]: La respuesta del modelo parseada como JSON.

    Raises:
        RuntimeError: Si la configuración de IA falta o la respuesta es inválida.
    """
    missing_config_msg = (
        "La detección automática con IA no está configurada en este servidor "
        "(falta la dependencia google-generativeai o la variable GOOGLE_API_KEY)."
    )
    try:
        from google.generativeai import GenerativeModel, configure
    except ImportError as exc:
        raise RuntimeError(missing_config_msg) from exc

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(missing_config_msg)

    configure(api_key=api_key)
    model = GenerativeModel("gemini-1.5-flash")

    response = model.generate_content(prompt, generation_config={"temperature": 0})
    text = (response.text or "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise RuntimeError(f"Respuesta IA con formato inválido: {text}")


def ai_detect_citations_for_report(citation: IncorrectCitation) -> List[Dict[str, Any]]:
    """Detecta citas usando IA para un reporte dado.

    Extrae párrafos del PDF del artículo citante, consulta al modelo de IA
    y devuelve los contextos encontrados en un formato compatible.

    Args:
        citation (IncorrectCitation): El objeto del reporte.

    Returns:
        List[Dict[str, Any]]: Lista de contextos detectados por la IA.

    Raises:
        RuntimeError: Si no hay PDF subido para el artículo citante.
    """
    citation_pdf = getattr(citation, "citing_pdf_uploaded", None)
    if not citation_pdf:
        raise RuntimeError(
            "Este reporte todavía no tiene asociado el PDF del artículo que cita (B). "
            "Cuando añadamos ese campo en el modelo o usemos CitationReport, "
            "podremos activar la detección automática."
        )

    pdf_path = citation_pdf.path
    paragraphs_for_ai = pm_extract_paragraphs_with_positions(pdf_path)

    prompt = build_ai_prompt_for_detection(
        citation.metadata_original or {},
        paragraphs_for_ai,
    )

    ai_raw = call_llm_for_detection(prompt)
    matches = ai_raw.get("matches", [])

    contexts: List[Dict[str, Any]] = []
    for m in matches:
        contexts.append(
            {
                "page": m.get("page"),
                "paragraph_index": m.get("paragraph_index"),
                "paragraph": m.get("text", ""),
                "snippet": (m.get("text", "") or "")[:300],
                "confidence": m.get("confidence", 0.0),
                "pattern": "ai_detected",
            }
        )

    return contexts

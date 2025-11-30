import json
import os
from typing import Any, Dict, List

from citations.models import IncorrectCitation


def _extract_basic(meta: dict) -> tuple[str, str, Any]:
    title_field = meta.get("title")
    title = title_field[0] if isinstance(title_field, list) else title_field or ""

    authors = meta.get("author", [])
    year = (
        meta.get("published-print", {})
        .get("date-parts", [[None]])[0][0]
        or meta.get("published-online", {})
        .get("date-parts", [[None]])[0][0]
        or meta.get("issued", {})
        .get("date-parts", [[None]])[0][0]
    )
    authors_str = ", ".join(
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in authors
    ) or "N/A"
    return title, authors_str, year


def _build_report_prompt(citation: IncorrectCitation) -> str:
    meta_a = citation.metadata_original or {}
    meta_b = citation.metadata_incorrect or {}
    contexts: List[Dict[str, Any]] = citation.citation_contexts or []

    title_a, authors_a, year_a = _extract_basic(meta_a)
    title_b, authors_b, year_b = _extract_basic(meta_b)

    user_type = citation.citation_type
    user_reason = citation.incorrect_reason

    header = (
        "Eres un experto en citas académicas y revisión de literatura científica.\n\n"
        "Debes analizar si la cita del artículo A dentro del artículo B está bien utilizada,\n"
        "probablemente correcta, incierta, probablemente incorrecta o incorrecta.\n\n"
        "Devuelve SOLO un JSON con este formato (sin texto adicional):\n"
        "{\n"
        '  \"evaluation\": \"correct | probably_correct | unclear | probably_incorrect | incorrect\",\n'
        '  \"confidence\": 0.0,\n'
        '  \"suggested_error_type\": \"not said | misinterpretation | contextual misattribution | other\",\n'
        '  \"matches_user_type\": true,\n'
        '  \"reasoning\": \"<explicacion breve>\",\n'
        '  \"notes_for_author\": \"<sugerencias de mejora para el autor del articulo B>\"\n'
        "}\n\n"
        "Artículo A (original):\n"
        f"- DOI: {citation.doi_original}\n"
        f"- Título: {title_a}\n"
        f"- Autores: {authors_a}\n"
        f"- Año: {year_a}\n\n"
        "Artículo B (que cita):\n"
        f"- DOI: {citation.doi_incorrect}\n"
        f"- Título: {title_b}\n"
        f"- Autores: {authors_b}\n"
        f"- Año: {year_b}\n\n"
        "Tipo de error marcado por el usuario:\n"
        f"- {user_type}\n\n"
        "Explicación del usuario:\n"
        f"{user_reason}\n\n"
    )

    context_str = "Fragmentos de B donde, según el sistema o el usuario, aparece la cita:\n\n"
    if not contexts:
        context_str += "(No hay fragmentos específicos; responde con menor confianza y justifica la incertidumbre.)\n"
    else:
        for i, ctx in enumerate(contexts, start=1):
            context_str += (
                f"[Fragmento {i} | Página {ctx.get('page')}]\n"
                f"{ctx.get('paragraph', '')}\n\n"
            )

    return header + context_str


def analyze_report_with_ai(citation: IncorrectCitation) -> Dict[str, Any]:
    """
    Llama a OpenAI para evaluar el reporte y guarda el resultado en ai_assessment.
    """
    missing_config_msg = (
        "La evaluación automática con IA no está configurada en este servidor "
        "(falta la dependencia openai o la variable OPENAI_API_KEY)."
    )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(missing_config_msg) from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(missing_config_msg)

    client = OpenAI(api_key=api_key)
    prompt = _build_report_prompt(citation)

    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )

    text = completion.choices[0].message.content
    data = json.loads(text)

    citation.ai_assessment = data
    citation.save(update_fields=["ai_assessment"])

    return data

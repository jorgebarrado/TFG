# citations/views_api.py
from __future__ import annotations

import os
import time
import tempfile
from typing import Optional

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services.citation_extractor import process_manuscript
from .services.engines import ALLOWED_ENGINES, list_extractor_engines
from .services.reader_data import (
    build_mentions,
    build_references,
    build_snippets_from_mentions,
    build_snippets_from_results,
    extract_pdf_references,
    extract_pdf_references_from_url,
    resolve_pdf_url,
)
from .services.pdf_citation_analyzer import (
    PDFDownloadError,
    analyze_pdf_citations_from_url,
)
from .services.semantic_citation_pipeline import analyze_citations_for_original_doi
from .services.semantic_scholar_client import SemanticScholarError
from .services.papermage_extractor import ContextHit
from .models import IncorrectCitation

# --- PaperMage "context" (targeted) import, tolerante si no existe aún
try:
    from .services.papermage_extractor import extract_contexts_from_pdf
except Exception:

    def extract_contexts_from_pdf(*args, **kwargs):
        # Fallback vacío para no romper el arranque; la vista seguirá viva.
        return []


from .services.semanticscholar import get_openaccess_pdf_url, download_pdf_to_temp
import logging
import json
from django.views.decorators.http import require_http_methods
from .trace import Trace

logger = logging.getLogger("citations.context")
INCLUDE_TRACE_FLAG = os.getenv("INCLUDE_TRACE_IN_RESPONSE", "0") == "1"


@csrf_exempt
@require_http_methods(["GET", "POST"])
def get_citation_context(request: HttpRequest) -> JsonResponse:
    """Busca y extrae el contexto de una citación desde un artículo científico.

    Esta vista localiza un artículo (citador) a través de su DOI, descarga
    la versión de acceso abierto si está disponible en Semantic Scholar, y
    busca dentro del PDF las menciones a otro artículo (citado).

    La vista acepta parámetros tanto vía GET como con un cuerpo JSON en POST.

    Args:
        request: El objeto HttpRequest de Django.
            Puede contener en el querystring o en el cuerpo JSON los
            siguientes parámetros:
            - citing_doi (str): El DOI del artículo que contiene la cita.
              Es obligatorio.
            - target_title (str, optional): Título del artículo citado.
            - target_first_author (str, optional): Primer autor del
              artículo citado.
            - target_year (str, optional): Año de publicación del artículo
              citado.
            - target_doi (str, optional): DOI del artículo citado.

    Returns:
        JsonResponse: Un objeto JSON que contiene:
            - ok (bool): True si la operación fue exitosa.
            - contexts (list): Una lista de fragmentos de texto donde se
              encontró la cita.
            - count (int): El número de contextos encontrados.
            - error (str, optional): Un mensaje de error si `ok` es False.
            - trace (dict, optional): Información de depuración si se
              solicita con `?debug=1`.
    """
    # Compat: GET querystring o POST JSON
    if request.method == "POST":
        try:
            payload = json.loads(request.body or "{}")
        except Exception:
            payload = {}
    else:
        payload = request.GET.dict()

    citing_doi = (payload.get("citing_doi") or "").strip()  # paper B
    target_title = (payload.get("target_title") or "").strip() or None
    target_first_author = (payload.get("target_first_author") or "").strip() or None
    target_year = (payload.get("target_year") or "").strip() or None
    target_doi = (payload.get("target_doi") or "").strip() or None

    trace = Trace(
        citing_doi=citing_doi,
        target={
            "doi": target_doi,
            "title": target_title,
            "first_author": target_first_author,
            "year": target_year,
        },
    )
    trace.add("payload", "ok", f"method={request.method}; keys={list(payload.keys())}")

    if not citing_doi:
        trace.add("params", "error", "missing citing_doi")
        logger.info(trace.as_log_line())
        resp = {"ok": False, "error": "Missing 'citing_doi'"}
        if INCLUDE_TRACE_FLAG or request.GET.get("debug") == "1":
            resp["trace"] = trace.as_public_trace()
        return JsonResponse(resp, status=400)

    trace.add(
        "params", "ok", f"citing_doi={citing_doi}; target_doi={target_doi or '-'}"
    )

    # 1) OpenAccess PDF (Semantic Scholar)
    pdf_url = None
    try:
        pdf_url = get_openaccess_pdf_url(citing_doi)
    except Exception as e:
        trace.add("openaccess", "error", str(e))
        trace.error = str(e)
        logger.info(trace.as_log_line("ERROR"))
        resp = {"ok": False, "error": "Semantic Scholar error"}
        if INCLUDE_TRACE_FLAG or request.GET.get("debug") == "1":
            resp["trace"] = trace.as_public_trace()
        return JsonResponse(resp, status=502)

    if not pdf_url:
        trace.add("openaccess", "miss", "no openAccessPdf")
        logger.info(trace.as_log_line())
        resp = {"ok": False, "error": "No openAccessPdf for citing DOI"}
        if INCLUDE_TRACE_FLAG or request.GET.get("debug") == "1":
            resp["trace"] = trace.as_public_trace()
        return JsonResponse(resp, status=404)
    else:
        trace.pdf_url = pdf_url
        trace.add("openaccess", "ok", pdf_url)

    # 2) Descarga
    tmp_path: Optional[str] = download_pdf_to_temp(pdf_url)
    if not tmp_path:
        trace.add("download", "error", "failed to download")
        logger.info(trace.as_log_line("ERROR"))
        resp = {"ok": False, "error": "Failed to download PDF"}
        if INCLUDE_TRACE_FLAG or request.GET.get("debug") == "1":
            resp["trace"] = trace.as_public_trace()
        return JsonResponse(resp, status=502)

    try:
        # 3) Extracción / matching
        contexts = extract_contexts_from_pdf(
            tmp_path,
            target_title=target_title,
            target_first_author=target_first_author,
            target_year=target_year,
            target_doi=target_doi,
        )
        trace.hit_count = len(contexts)
        try:
            trace.pdf_size = os.path.getsize(tmp_path)
        except Exception:
            pass
        trace.add("download", "ok", f"{trace.pdf_size or 0} bytes")
        trace.add("extract", "ok", f"hits={len(contexts)}")

        resp = {
            "ok": True,
            "source": "semanticscholar",
            "pdf": "openAccess",
            "count": len(contexts),
            "contexts": contexts,
        }
        if INCLUDE_TRACE_FLAG or request.GET.get("debug") == "1":
            resp["trace"] = trace.as_public_trace()
        logger.info(trace.as_log_line())
        return JsonResponse(resp, status=200)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ========= TU endpoint existente para subir manuscritos =========
@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
    """Extrae referencias bibliográficas de un manuscrito en formato PDF o TXT.

    Esta API procesa un archivo subido por el usuario (`manuscript`),
    extrae las referencias que contiene utilizando diferentes motores de
    procesamiento y las devuelve en un formato estructurado.

    Args:
        request: El objeto HttpRequest de Django. Debe ser una solicitud
            POST que incluya un archivo en el campo 'manuscript'.
            También puede contener los siguientes campos en el cuerpo de
            la solicitud:
            - engine (str, optional): El motor de extracción a utilizar
              ('auto', 'science-parse', etc.). Por defecto es 'auto'.
            - debug (bool, optional): Si se activa, incluye información
              adicional de depuración en la respuesta.

    Returns:
        JsonResponse: Un objeto JSON que contiene los datos extraídos del
            manuscrito. Si la operación falla, devuelve un mensaje de
            error.
    """
    f: UploadedFile | None = request.FILES.get("manuscript")
    if not f:
        return JsonResponse({"ok": False, "error": "No file uploaded"}, status=400)

    engine = (request.POST.get("engine") or "").lower().strip()
    if not engine:
        return JsonResponse(
            {"ok": False, "error": "Debes seleccionar una herramienta de extraccion."},
            status=400,
        )
    if engine not in ALLOWED_ENGINES:
        return JsonResponse(
            {"ok": False, "error": "Herramienta no valida."},
            status=400,
        )
    debug = request.POST.get("debug") in ("1", "true", "True", "yes", "on")

    suffix = ".pdf" if f.name.lower().endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    start_time = time.time()
    try:
        data = process_manuscript(temp_path, engine=engine, debug=debug)
        elapsed_ms = int((time.time() - start_time) * 1000)
        data["time_ms"] = elapsed_ms

        if suffix == ".pdf" and data.get("ok", False):
            references, ref_stats = extract_pdf_references(temp_path)
            snippets = build_snippets_from_results(data.get("results"))
            data["references"] = references
            data["snippets"] = snippets
            data["stats"] = {
                "pages_total": ref_stats.get("pages_total", 0),
                "snippets_total": len(snippets),
                "references_total": ref_stats.get("references_total", len(references)),
                "dois_total": ref_stats.get("dois_total", 0),
                "engine_used": data.get("engine_used") or "",
                "time_ms": elapsed_ms,
                "references_numbered": ref_stats.get("references_numbered", False),
            }

        status = 200 if data.get("ok", False) else 422
        return JsonResponse(data, status=status, safe=True)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass


@require_GET
def api_extractor_engines(request: HttpRequest) -> JsonResponse:
    """Devuelve la lista de motores de extracción disponibles.

    Args:
        request: El objeto HttpRequest de Django.

    Returns:
        JsonResponse: Un objeto JSON con la lista de motores y su disponibilidad.
    """
    return JsonResponse({"engines": list_extractor_engines()}, status=200)


@require_GET
def api_reader_data(request: HttpRequest, report_id: int) -> JsonResponse:
    """Obtiene los datos necesarios para visualizar el lector de PDFs/reportes.

    Esta vista recopila información sobre un reporte de cita incorrecta,
    incluyendo la URL del PDF, fragmentos de texto relevantes (snippets),
    referencias extraídas y estadísticas.

    Args:
        request: El objeto HttpRequest de Django.
        report_id (int): El ID del reporte (IncorrectCitation).

    Returns:
        JsonResponse: Un objeto JSON con los datos del lector.
    """
    citation = get_object_or_404(IncorrectCitation, pk=report_id)
    pdf_url = resolve_pdf_url(citation.metadata_incorrect, citation.doi_incorrect)
    mentions = build_mentions(citation.citation_contexts)
    snippets = build_snippets_from_mentions(mentions)
    references, ref_stats = extract_pdf_references_from_url(pdf_url)
    if not references:
        references = build_references(citation.metadata_original, citation.doi_original)
        ref_stats = {
            "pages_total": 0,
            "references_total": len(references),
            "dois_total": sum(1 for ref in references if ref.get("doi")),
            "references_numbered": False,
        }
    return JsonResponse(
        {
            "pdf_url": pdf_url or "",
            "snippets": snippets,
            "references": references,
            "mentions": mentions,
            "stats": {
                "pages_total": ref_stats.get("pages_total", 0),
                "snippets_total": len(snippets),
                "references_total": ref_stats.get("references_total", len(references)),
                "dois_total": ref_stats.get("dois_total", 0),
                "engine_used": "",
                "time_ms": None,
                "references_numbered": ref_stats.get("references_numbered", False),
            },
        },
        status=200,
    )


@require_GET
def api_pdf_citation_contexts(request: HttpRequest) -> JsonResponse:
    """Busca contextos de citación en un PDF dado por URL.

    Args:
        request: El objeto HttpRequest de Django.
            Parámetros GET esperados:
            - pdf_url (str): URL del PDF a analizar (obligatorio).
            - pattern (list[str], optional): Lista de patrones regex personalizados
              para buscar citas. Se puede repetir el parámetro `pattern`.

    Returns:
        JsonResponse: Un objeto JSON con los contextos encontrados y su cantidad,
            o un mensaje de error si falla la descarga o procesamiento.
    """
    pdf_url = request.GET.get("pdf_url")
    if not pdf_url:
        return JsonResponse(
            {"error": "Falta el parámetro obligatorio 'pdf_url'."},
            status=400,
        )

    patterns = request.GET.getlist("pattern") or None

    try:
        contexts = analyze_pdf_citations_from_url(pdf_url, patterns)
    except PDFDownloadError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except FileNotFoundError:
        return JsonResponse(
            {"error": "No se pudo leer el PDF descargado."},
            status=500,
        )
    except RuntimeError as exc:
        return JsonResponse(
            {"error": f"Error al procesar el PDF con PaperMage: {exc}"},
            status=500,
        )

    return JsonResponse(
        {
            "count": len(contexts),
            "contexts": contexts,
        }
    )


@require_POST
def api_pdf_citation_contexts_upload(request: HttpRequest) -> JsonResponse:
    """Busca contextos de citación en un PDF subido por el usuario.

    Args:
        request: El objeto HttpRequest de Django. Debe ser POST e incluir
            un archivo en el campo 'pdf_file'.

    Returns:
        JsonResponse: Un objeto JSON con los contextos encontrados y su cantidad,
            o un mensaje de error si no se recibe el archivo o falla el procesamiento.
    """
    uploaded_file = request.FILES.get("pdf_file")
    if not uploaded_file:
        return JsonResponse(
            {"error": "No se ha recibido ningún archivo PDF ('pdf_file')."},
            status=400,
        )

    patterns = [
        r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]",  # [4], [4, 7], [4-7], [4–7]
        r"\b[A-Z][a-z]+ et al\., \d{4}\b",
        r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+",
    ]

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        contexts: list[ContextHit] = extract_contexts_from_pdf(tmp_path, patterns)
        return JsonResponse(
            {
                "count": len(contexts),
                "contexts": contexts,
            }
        )
    except Exception as exc:
        return JsonResponse(
            {"error": f"Error al procesar el PDF: {exc}"},
            status=500,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@require_GET
def api_semantic_citation_analysis(request: HttpRequest) -> JsonResponse:
    """Analiza citas semánticas dado un DOI original.

    Utiliza Semantic Scholar para encontrar quién cita el DOI dado y
    PaperMage para localizar los contextos exactos de la cita dentro
    de los PDFs de acceso abierto disponibles.

    Args:
        request: El objeto HttpRequest de Django.
            Parámetros GET esperados:
            - doi (str): El DOI del artículo original (citado).
            - max_citing (int, optional): Número máximo de artículos citantes
              a analizar. Por defecto es 5.

    Returns:
        JsonResponse: Un objeto JSON con los resultados del análisis.
    """
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse(
            {"error": "Falta el parámetro obligatorio 'doi'."},
            status=400,
        )

    try:
        max_citing = int(request.GET.get("max_citing", "5"))
    except ValueError:
        return JsonResponse(
            {"error": "El parámetro 'max_citing' debe ser un entero."},
            status=400,
        )

    analysis_result = analyze_citations_for_original_doi(
        original_doi=doi,
        max_citing_papers=max_citing,
    )

    return JsonResponse(analysis_result, safe=False)

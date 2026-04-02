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
from .services.papermage_extractor import ContextHit, extract_pdf_data
from .services.references_data import build_references_data
from .services.doi_enrichment_service import enrich_extraction_with_doi
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
from citations.logging_utils import get_logger, log_event, log_phase

logger = get_logger("citations.api")
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

    trace_data = {
        "citing_doi": citing_doi,
        "target_doi": target_doi,
        "target_title": target_title,
        "target_first_author": target_first_author,
        "target_year": target_year,
    }

    log_event(
        logger,
        logging.DEBUG,
        "api_get_citation_context_started",
        message=f"Petición de contextos de cita iniciada. citing_doi: {citing_doi}",
        **trace_data,
    )

    if not citing_doi:
        log_event(
            logger,
            logging.WARNING,
            "api_validation_failed",
            message="Falta 'citing_doi' en get_citation_context",
            error="missing_citing_doi",
        )
        return JsonResponse({"ok": False, "error": "Missing 'citing_doi'"}, status=400)

    # 1) OpenAccess PDF (Semantic Scholar)
    pdf_url = None
    with log_phase(logger, "semantic_scholar_openaccess_fetch", citing_doi=citing_doi):
        try:
            pdf_url = get_openaccess_pdf_url(citing_doi)
        except Exception as e:
            log_event(
                logger,
                logging.ERROR,
                "semantic_scholar_error",
                message=f"Error obteniendo OpenAccess PDF de Semantic Scholar: {e}",
                exc_info=True,
                error=str(e),
                citing_doi=citing_doi,
            )
            return JsonResponse(
                {"ok": False, "error": "Semantic Scholar error"}, status=502
            )

    if not pdf_url:
        log_event(
            logger,
            logging.INFO,
            "openaccess_pdf_not_found",
            message=f"No se encontró OpenAccess PDF para el DOI: {citing_doi}",
            citing_doi=citing_doi,
        )
        return JsonResponse(
            {"ok": False, "error": "No openAccessPdf for citing DOI"}, status=404
        )

    log_event(
        logger,
        logging.DEBUG,
        "openaccess_pdf_found",
        message=f"OpenAccess PDF encontrado: {pdf_url}",
        pdf_url=pdf_url,
        citing_doi=citing_doi,
    )

    # 2) Descarga
    tmp_path: Optional[str] = None
    with log_phase(logger, "pdf_download", pdf_url=pdf_url):
        tmp_path = download_pdf_to_temp(pdf_url)

    if not tmp_path:
        log_event(
            logger,
            logging.ERROR,
            "pdf_download_failed",
            message="Fallo al descargar el PDF",
            pdf_url=pdf_url,
        )
        return JsonResponse(
            {"ok": False, "error": "Failed to download PDF"}, status=502
        )

    try:
        pdf_size = os.path.getsize(tmp_path)
        log_event(
            logger,
            logging.DEBUG,
            "pdf_downloaded",
            message=f"PDF descargado correctamente. Tamaño: {pdf_size} bytes",
            pdf_url=pdf_url,
            size_bytes=pdf_size,
        )

        # 3) Extracción / matching
        with log_phase(logger, "extract_contexts_from_pdf", target_doi=target_doi):
            contexts = extract_contexts_from_pdf(
                tmp_path,
                target_title=target_title,
                target_first_author=target_first_author,
                target_year=target_year,
                target_doi=target_doi,
            )

        log_event(
            logger,
            logging.INFO,
            "api_get_citation_context_completed",
            message=f"Éxito: extraídos {len(contexts)} contextos",
            hit_count=len(contexts),
            citing_doi=citing_doi,
        )

        resp = {
            "ok": True,
            "source": "semanticscholar",
            "pdf": "openAccess",
            "count": len(contexts),
            "contexts": contexts,
        }
        return JsonResponse(resp, status=200)
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            "api_get_citation_context_failed",
            message=f"Error inesperado procesando la petición: {e}",
            exc_info=True,
            error=str(e),
            citing_doi=citing_doi,
        )
        return JsonResponse({"ok": False, "error": "Internal server error"}, status=500)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as e:
            log_event(
                logger,
                logging.WARNING,
                "cleanup_failed",
                message=f"Error borrando archivo temporal: {tmp_path} - {e}",
                error=str(e),
            )


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

    # Flujo unificado del reader preview: por defecto usamos PaperMage.
    engine = (request.POST.get("engine") or "papermage").lower().strip()
    if engine not in ALLOWED_ENGINES:
        return JsonResponse(
            {"ok": False, "error": "Herramienta no valida."},
            status=400,
        )
    debug = request.POST.get("debug") in ("1", "true", "True", "yes", "on")
    article_doi = (
        request.POST.get("article_doi") or request.POST.get("doi") or ""
    ).strip()

    log_event(
        logger,
        logging.INFO,
        "api_extract_citations_started",
        message=f"Petición de extracción de citas iniciada. engine={engine}",
        engine=engine,
        filename=f.name,
        article_doi=article_doi,
    )

    suffix = ".pdf" if f.name.lower().endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    start_time = time.time()
    try:
        references = []
        ref_stats = {
            "pages_total": 0,
            "references_total": 0,
            "dois_total": 0,
            "references_numbered": False,
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
        }
        if suffix == ".pdf":
            references, ref_stats = extract_pdf_references(temp_path)

        citation_style = (
            str(
                ref_stats.get("citation_style")
                or (
                    "numeric" if ref_stats.get("references_numbered") else "non_numeric"
                )
            )
            .strip()
            .lower()
        )
        try:
            max_reference_index = int(
                ref_stats.get("max_reference_index")
                or ref_stats.get("references_total")
                or len(references)
                or 0
            )
        except (TypeError, ValueError):
            max_reference_index = int(
                ref_stats.get("references_total") or len(references) or 0
            )
        total_references_for_validation = (
            max_reference_index if citation_style == "numeric" else len(references)
        )
        data = process_manuscript(
            temp_path,
            engine=engine,
            debug=debug,
            references=references,
            citation_style=citation_style,
            total_references=total_references_for_validation,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)
        data["time_ms"] = elapsed_ms

        if suffix == ".pdf" and data.get("ok", False):
            snippets = build_snippets_from_results(data.get("results"))
            stats_payload = {
                "pages_total": ref_stats.get("pages_total", 0),
                "snippets_total": len(snippets),
                "references_total": ref_stats.get("references_total", len(references)),
                "dois_total": ref_stats.get("dois_total", 0),
                "engine_used": data.get("engine_used") or "",
                "time_ms": elapsed_ms,
                "references_numbered": ref_stats.get("references_numbered", False),
                "citation_style": citation_style,
                "max_reference_index": max_reference_index,
                "bibliography_start_page": ref_stats.get("bibliography_start_page"),
            }
            data["references"] = references
            data["snippets"] = snippets
            data["stats"] = stats_payload
            data["citation_style"] = citation_style
            data["max_reference_index"] = max_reference_index
            data["bibliography_start_page"] = ref_stats.get("bibliography_start_page")
            # Datos de capas (pages/layers) para la pestaña "Capas".
            # Para el flujo unificado del preview, si falla PaperMage aquí
            # devolvemos error para que no quede una extracción a medias.
            try:
                reader_data = extract_pdf_data(temp_path)
            except Exception as exc:
                if engine == "papermage" or data.get("engine_used") == "papermage":
                    return JsonResponse(
                        {
                            "ok": False,
                            "error": f"No se pudieron preparar las capas del reader: {exc}",
                        },
                        status=500,
                    )
                reader_data = {"pages": [], "layers": {}}

            data["pages"] = (
                reader_data.get("pages", []) if isinstance(reader_data, dict) else []
            )
            data["layers"] = (
                reader_data.get("layers", {}) if isinstance(reader_data, dict) else {}
            )
            data["references_data"] = build_references_data(
                references=references,
                snippets=snippets,
                layers=data.get("layers", {}),
                references_numbered=bool(stats_payload.get("references_numbered")),
            )
            references_data_payload = data.get("references_data")
            if isinstance(references_data_payload, dict):
                data["citation_style"] = (
                    str(references_data_payload.get("citation_style") or citation_style)
                    .strip()
                    .lower()
                )
                try:
                    data["max_reference_index"] = int(
                        references_data_payload.get("max_reference_index")
                        or max_reference_index
                        or 0
                    )
                except (TypeError, ValueError):
                    data["max_reference_index"] = int(max_reference_index or 0)
                data["bibliography_start_page"] = references_data_payload.get(
                    "bibliography_start_page"
                )
                data["stats"]["citation_style"] = data["citation_style"]
                data["stats"]["max_reference_index"] = data["max_reference_index"]
                data["stats"]["bibliography_start_page"] = data[
                    "bibliography_start_page"
                ]

            try:
                enrichment_result = enrich_extraction_with_doi(
                    doi_input=article_doi,
                    local_references=data.get("references", []),
                    references_data_references=(
                        references_data_payload.get("references", [])
                        if isinstance(references_data_payload, dict)
                        else []
                    ),
                )
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "doi enrichment failed doi=%s error=%s", article_doi, exc
                )
                enrichment_result = {
                    "local_references": data.get("references", []),
                    "references_data_references": (
                        references_data_payload.get("references", [])
                        if isinstance(references_data_payload, dict)
                        else []
                    ),
                    "cited_by": [],
                    "enrichment": {
                        "doi_provided": bool(article_doi),
                        "doi_normalized": "",
                        "paper_resolved": False,
                        "references_enriched": 0,
                        "cited_by_count": 0,
                        "sources_used": [],
                        "warning": "enrichment_exception",
                    },
                }

            if isinstance(enrichment_result.get("local_references"), list):
                data["references"] = enrichment_result["local_references"]
            if isinstance(references_data_payload, dict) and isinstance(
                enrichment_result.get("references_data_references"), list
            ):
                references_data_payload["references"] = enrichment_result[
                    "references_data_references"
                ]
            data["cited_by"] = (
                enrichment_result.get("cited_by")
                if isinstance(enrichment_result.get("cited_by"), list)
                else []
            )
            data["enrichment"] = (
                enrichment_result.get("enrichment")
                if isinstance(enrichment_result.get("enrichment"), dict)
                else {
                    "doi_provided": bool(article_doi),
                    "doi_normalized": "",
                    "paper_resolved": False,
                    "references_enriched": 0,
                    "cited_by_count": 0,
                    "sources_used": [],
                }
            )
            if isinstance(data.get("stats"), dict):
                data["stats"]["dois_total"] = sum(
                    1
                    for ref in (data.get("references") or [])
                    if isinstance(ref, dict) and ref.get("doi")
                )
        else:
            data["cited_by"] = []
            data["enrichment"] = {
                "doi_provided": bool(article_doi),
                "doi_normalized": "",
                "paper_resolved": False,
                "references_enriched": 0,
                "cited_by_count": 0,
                "sources_used": [],
            }

        status = 200 if data.get("ok", False) else 422
        log_event(
            logger,
            logging.INFO,
            "api_extract_citations_completed",
            message=f"Extracción completada. status={status}",
            status=status,
            engine_used=data.get("engine_used"),
            duration_ms=int((time.time() - start_time) * 1000),
        )
        return JsonResponse(data, status=status, safe=True)
    except Exception as e:
        log_event(
            logger,
            logging.ERROR,
            "api_extract_citations_failed",
            message=f"Excepción en el procesamiento de api_extract_citations: {e}",
            exc_info=True,
            error=str(e),
        )
        return JsonResponse(
            {"ok": False, "error": "Error interno del servidor."}, status=500
        )
    finally:
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            log_event(
                logger,
                logging.WARNING,
                "cleanup_failed",
                message=f"Error borrando archivo temporal: {temp_path} - {e}",
                error=str(e),
            )


@require_GET
def api_extractor_engines(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"engines": list_extractor_engines()}, status=200)


@require_GET
def api_reader_data(request: HttpRequest, report_id: int) -> JsonResponse:
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
            "citation_style": "non_numeric",
            "max_reference_index": 0,
            "bibliography_start_page": None,
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
                "citation_style": ref_stats.get("citation_style", "non_numeric"),
                "max_reference_index": ref_stats.get("max_reference_index", 0),
                "bibliography_start_page": ref_stats.get("bibliography_start_page"),
            },
        },
        status=200,
    )


@require_GET
def api_pdf_citation_contexts(request: HttpRequest) -> JsonResponse:
    """
    API que recibe una URL de PDF y devuelve los contextos de cita detectados.

    Parámetros GET:
        - pdf_url: URL del PDF a analizar (obligatorio).
        - pattern: puede repetirse varias veces para pasar patrones personalizados (opcional).

    Respuesta:
        200 OK:
            {
              "count": <número de contextos>,
              "contexts": [ { ...ContextHit... }, ... ]
            }
        4xx / 5xx:
            { "error": "mensaje de error" }
    """
    pdf_url = request.GET.get("pdf_url")
    if not pdf_url:
        log_event(
            logger,
            logging.WARNING,
            "api_validation_failed",
            message="api_pdf_citation_contexts llamado sin pdf_url",
            error="missing_pdf_url",
        )
        return JsonResponse(
            {"error": "Falta el parámetro obligatorio 'pdf_url'."},
            status=400,
        )

    patterns = request.GET.getlist("pattern") or None
    log_event(
        logger,
        logging.INFO,
        "api_pdf_citation_contexts_started",
        message=f"Petición api_pdf_citation_contexts para: {pdf_url}",
        pdf_url=pdf_url,
    )

    with log_phase(logger, "analyze_pdf_citations", pdf_url=pdf_url):
        try:
            contexts = analyze_pdf_citations_from_url(pdf_url, patterns)
        except PDFDownloadError as exc:
            log_event(
                logger,
                logging.ERROR,
                "pdf_download_failed",
                message=f"Error descargando PDF en api_pdf_citation_contexts para {pdf_url}: {exc}",
                error=str(exc),
            )
            return JsonResponse({"error": str(exc)}, status=502)
        except ValueError as exc:
            log_event(
                logger,
                logging.ERROR,
                "api_validation_failed",
                message=f"Error de valor en api_pdf_citation_contexts para {pdf_url}: {exc}",
                error=str(exc),
            )
            return JsonResponse({"error": str(exc)}, status=400)
        except FileNotFoundError:
            log_event(
                logger,
                logging.ERROR,
                "pdf_not_found",
                message=f"PDF no encontrado tras descargar en api_pdf_citation_contexts para {pdf_url}",
                error="file_not_found",
            )
            return JsonResponse(
                {"error": "No se pudo leer el PDF descargado."},
                status=500,
            )
        except RuntimeError as exc:
            log_event(
                logger,
                logging.ERROR,
                "extraction_engine_failed",
                message=f"Error procesando PDF en api_pdf_citation_contexts para {pdf_url}: {exc}",
                exc_info=True,
                error=str(exc),
            )
            return JsonResponse(
                {"error": f"Error al procesar el PDF con PaperMage: {exc}"},
                status=500,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "api_pdf_citation_contexts_failed",
                message=f"Excepción inesperada en api_pdf_citation_contexts para {pdf_url}: {exc}",
                exc_info=True,
                error=str(exc),
            )
            return JsonResponse(
                {"error": "Error interno al procesar el PDF."},
                status=500,
            )

    log_event(
        logger,
        logging.INFO,
        "api_pdf_citation_contexts_completed",
        message=f"Éxito: devueltos {len(contexts)} contextos",
        count=len(contexts),
        pdf_url=pdf_url,
    )
    return JsonResponse(
        {
            "count": len(contexts),
            "contexts": contexts,
        }
    )


@require_POST
def api_pdf_citation_contexts_upload(request: HttpRequest) -> JsonResponse:
    """
    API que recibe un PDF subido por el usuario y devuelve los contextos de cita detectados.
    """
    uploaded_file = request.FILES.get("pdf_file")
    if not uploaded_file:
        log_event(
            logger,
            logging.WARNING,
            "api_validation_failed",
            message="api_pdf_citation_contexts_upload llamado sin pdf_file",
            error="missing_pdf_file",
        )
        return JsonResponse(
            {"error": "No se ha recibido ningún archivo PDF ('pdf_file')."},
            status=400,
        )

    log_event(
        logger,
        logging.INFO,
        "api_pdf_citation_contexts_upload_started",
        message=f"Petición api_pdf_citation_contexts_upload para archivo: {uploaded_file.name}",
        filename=uploaded_file.name,
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

        log_event(
            logger,
            logging.DEBUG,
            "temp_file_saved",
            message=f"Guardado temporalmente en {tmp_path}",
            path=tmp_path,
        )

        with log_phase(logger, "extract_contexts_from_pdf_upload"):
            contexts: list[ContextHit] = extract_contexts_from_pdf(tmp_path, patterns)

        log_event(
            logger,
            logging.INFO,
            "api_pdf_citation_contexts_upload_completed",
            message=f"Éxito: extraídos {len(contexts)} contextos del archivo subido",
            count=len(contexts),
        )
        return JsonResponse(
            {
                "count": len(contexts),
                "contexts": contexts,
            }
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "api_pdf_citation_contexts_upload_failed",
            message=f"Error procesando el PDF subido: {exc}",
            exc_info=True,
            error=str(exc),
        )
        return JsonResponse(
            {"error": f"Error al procesar el PDF: {exc}"},
            status=500,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as e:
                log_event(
                    logger,
                    logging.WARNING,
                    "cleanup_failed",
                    message=f"No se pudo eliminar archivo temporal en upload_contexts: {tmp_path} - {e}",
                    error=str(e),
                )
                pass


@csrf_exempt
@require_POST
def api_pdf_reader_v2_upload(request: HttpRequest) -> JsonResponse:
    """
    API que recibe un PDF subido por el usuario y devuelve los datos
    (pages + layers) para el overlay visual del reader V2.
    """
    uploaded_file = request.FILES.get("pdf_file") or request.FILES.get("manuscript")
    if not uploaded_file:
        return JsonResponse(
            {
                "ok": False,
                "error": "No se ha recibido ningun archivo PDF ('pdf_file').",
            },
            status=400,
        )

    tmp_path = None
    started_at = time.time()
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        reader_data = extract_pdf_data(tmp_path)
        elapsed_ms = int((time.time() - started_at) * 1000)
        return JsonResponse(
            {
                "ok": True,
                "pages": reader_data.get("pages", []),
                "layers": reader_data.get("layers", {}),
                "time_ms": elapsed_ms,
            },
            status=200,
        )
    except FileNotFoundError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RuntimeError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": f"Error al procesar el PDF: {exc}"},
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
    """
    API que dado un DOI original, usa Semantic Scholar para buscar quién lo cita
    y PaperMage para localizar contextos de cita en los PDFs open access.
    """
    doi = request.GET.get("doi")
    if not doi:
        log_event(
            logger,
            logging.WARNING,
            "api_validation_failed",
            message="api_semantic_citation_analysis llamado sin DOI",
            error="missing_doi",
        )
        return JsonResponse(
            {"error": "Falta el parámetro obligatorio 'doi'."},
            status=400,
        )

    try:
        max_citing = int(request.GET.get("max_citing", "5"))
    except ValueError:
        log_event(
            logger,
            logging.WARNING,
            "api_validation_failed",
            message=f"max_citing inválido ({request.GET.get('max_citing')})",
            error="invalid_max_citing",
        )
        return JsonResponse(
            {"error": "El parámetro 'max_citing' debe ser un entero."},
            status=400,
        )

    log_event(
        logger,
        logging.INFO,
        "api_semantic_citation_analysis_started",
        message=f"Petición api_semantic_citation_analysis para DOI: {doi} (max_citing={max_citing})",
        doi=doi,
        max_citing=max_citing,
    )

    try:
        with log_phase(
            logger, "analyze_citations_for_original_doi", doi=doi, max_citing=max_citing
        ):
            analysis_result = analyze_citations_for_original_doi(
                original_doi=doi,
                max_citing_papers=max_citing,
            )
        return JsonResponse(analysis_result, safe=False)
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "api_semantic_citation_analysis_failed",
            message=f"Error no controlado en api_semantic_citation_analysis para {doi}: {exc}",
            exc_info=True,
            error=str(exc),
        )
        return JsonResponse({"error": "Error interno durante el análisis."}, status=500)

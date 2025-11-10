# citations/views_api.py
from __future__ import annotations

import os
import tempfile
from typing import Optional

import requests
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services.papermage_extractor import extract_contexts_from_pdf
from .services.semanticscholar import get_openaccess_pdf_url, download_pdf_to_temp
from .trace_logger import TraceLogger


def get_citation_context(request: HttpRequest, trace_logger_instance=None) -> JsonResponse:
    """
    Extrae y devuelve los contextos de una cita de un artículo en formato PDF.

    Args:
        request (HttpRequest): La solicitud HTTP. Debe contener los siguientes parámetros GET:
            'citing_doi' (str): El DOI del artículo que contiene la cita.
            'target_title' (str): El título del artículo citado.
            'target_first_author' (str): El primer autor del artículo citado.
            'target_year' (str): El año de publicación del artículo citado.
            'target_doi' (str, opcional): El DOI del artículo citado.
        trace_logger_instance (TraceLogger, optional): Una instancia de TraceLogger para usar en las pruebas. Defaults to None.

    Returns:
        JsonResponse: Un objeto JSON con los contextos de la cita o un mensaje de error.
    """
    trace = trace_logger_instance or TraceLogger(request)
    debug_mode = request.GET.get("debug") == "1" or request.headers.get("X-Debug") == "1"
    tmp_path = None

    try:
        citing_doi = request.GET.get("citing_doi")
        target_title = request.GET.get("target_title")
        target_first_author = request.GET.get("target_first_author")
        target_year = request.GET.get("target_year")
        target_doi = request.GET.get("target_doi")

        trace.trace_data["citing_doi"] = citing_doi
        trace.trace_data["target"] = {
            "title": target_title,
            "first_author": target_first_author,
            "year": target_year,
            "doi": target_doi,
        }

        if not citing_doi:
            trace.add_step("params", "error", "Missing 'citing_doi'")
            return JsonResponse({"ok": False, "error": "Missing 'citing_doi'"}, status=400)
        trace.add_step("params", "ok")

        pdf_url = get_openaccess_pdf_url(citing_doi)
        if not pdf_url:
            trace.add_step("openaccess", "miss", "No openAccessPdf for citing DOI")
            return JsonResponse({"ok": False, "error": "No openAccessPdf for citing DOI"}, status=404)
        trace.add_step("openaccess", "ok", pdf_url)
        trace.trace_data["pdf_url"] = pdf_url

        tmp_path: Optional[str] = download_pdf_to_temp(pdf_url)
        if not tmp_path:
            trace.add_step("download", "error", "Failed to download PDF")
            return JsonResponse({"ok": False, "error": "Failed to download PDF"}, status=502)
        trace.add_step("download", "ok", f"{os.path.getsize(tmp_path)} bytes")
        trace.trace_data["pdf_size"] = os.path.getsize(tmp_path)

        contexts = extract_contexts_from_pdf(
            tmp_path,
            target_title=target_title,
            target_first_author=target_first_author,
            target_year=target_year,
            target_doi=target_doi,
        )
        trace.add_step("extract", "ok", f"{len(contexts)} hits")
        trace.trace_data["hit_count"] = len(contexts)

        response_data = {
            "ok": True,
            "source": "semanticscholar",
            "pdf": "openAccess",
            "count": len(contexts),
            "contexts": contexts,
        }
        if debug_mode:
            response_data["trace"] = trace.get_trace()
        return JsonResponse(response_data, status=200)

    except Exception as e:
        trace.add_step("error", "error", str(e))
        response_data = {"ok": False, "error": str(e)}
        if debug_mode:
            response_data["trace"] = trace.get_trace()
        return JsonResponse(response_data, status=500)

    finally:
        trace.log()
        if "tmp_path" in locals() and tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ========= TU endpoint existente para subir manuscritos =========
@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
    """
    Extrae las citas de un manuscrito subido (PDF o TXT).

    Args:
        request (HttpRequest): La solicitud HTTP. Debe contener un archivo adjunto con la clave 'manuscript'.

    Returns:
        JsonResponse: Un objeto JSON con las citas extraídas o un mensaje de error.
    """
    from .services.citation_extractor import process_manuscript  # keep your current flow

    f: UploadedFile | None = request.FILES.get("manuscript")
    if not f:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    suffix = ".pdf" if f.name.lower().endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        data = process_manuscript(temp_path)
        return JsonResponse(data, status=200, safe=True)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

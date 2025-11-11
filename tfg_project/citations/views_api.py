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

# --- PaperMage "context" (targeted) import, tolerante si no existe aún
try:
    from .services.papermage_extractor import extract_contexts_from_pdf
except Exception:
    def extract_contexts_from_pdf(*args, **kwargs):
        # Fallback vacío para no romper el arranque; la vista seguirá viva.
        return []
from .services.semanticscholar import get_openaccess_pdf_url, download_pdf_to_temp
from .trace_logger import TraceLogger
import logging, os, json
from django.views.decorators.http import require_http_methods
from .trace import Trace

logger = logging.getLogger("citations.context")
INCLUDE_TRACE_FLAG = os.getenv("INCLUDE_TRACE_IN_RESPONSE", "0") == "1"

@csrf_exempt
@require_http_methods(["GET", "POST"])
def get_citation_context(request: HttpRequest) -> JsonResponse:
    """
    /citations/api/get-citation-context/
    GET o POST(JSON) con:
      - citing_doi (paper B) [OBLIGATORIO]
      - target_title / target_first_author / target_year / target_doi (paper A) [opcionales]
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

    trace.add("params", "ok", f"citing_doi={citing_doi}; target_doi={target_doi or '-'}")

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
    from .services.citation_extractor import process_manuscript
    f = request.FILES.get("manuscript")
    if not f:
        return JsonResponse({"error": "No file uploaded"}, status=400)

    engine = (request.POST.get("engine") or "auto").lower().strip()
    debug  = (request.POST.get("debug") == "1")

    suffix = ".pdf" if f.name.lower().endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        data = process_manuscript(temp_path, engine=engine, debug=debug)
        return JsonResponse(data, status=200, safe=True)
    finally:
        try: os.remove(temp_path)
        except Exception: pass
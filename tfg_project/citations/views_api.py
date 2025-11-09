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


def get_citation_context(request: HttpRequest) -> JsonResponse:
    """
    /citations/api/get-citation-context/?citing_doi=...&target_title=...&target_first_author=...&target_year=...&target_doi=...

    Devuelve:
    {
      "ok": true,
      "source": "semanticscholar",
      "pdf": "openAccess",
      "contexts": [ { paragraph, snippet, start, end }, ... ]
    }
    """
    citing_doi = request.GET.get("citing_doi")  # paper B
    target_title = request.GET.get("target_title")  # paper A
    target_first_author = request.GET.get("target_first_author")
    target_year = request.GET.get("target_year")
    target_doi = request.GET.get("target_doi")  # opcional: DOI de A (mejora matching)

    if not citing_doi:
        return JsonResponse({"ok": False, "error": "Missing 'citing_doi'"}, status=400)

    pdf_url = get_openaccess_pdf_url(citing_doi)
    if not pdf_url:
        return JsonResponse({"ok": False, "error": "No openAccessPdf for citing DOI"}, status=404)

    tmp_path: Optional[str] = download_pdf_to_temp(pdf_url)
    if not tmp_path:
        return JsonResponse({"ok": False, "error": "Failed to download PDF"}, status=502)

    try:
        contexts = extract_contexts_from_pdf(
            tmp_path,
            target_title=target_title,
            target_first_author=target_first_author,
            target_year=target_year,
            target_doi=target_doi,
        )
        return JsonResponse(
            {
                "ok": True,
                "source": "semanticscholar",
                "pdf_url": pdf_url,
                "count": len(contexts),
                "contexts": contexts,
            },
            status=200,
        )
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ========= TU endpoint existente para subir manuscritos =========
@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
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

"""
EN/ES: API endpoint to extract citation snippets from an uploaded manuscript.
Place this file as `citations/views_api.py` or merge the view into your `views.py`.
"""

from __future__ import annotations

import os
import tempfile

import requests
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# Adjust import to your project structure:
from .services.citation_extractor import process_manuscript  # type: ignore


def get_citation_context(request):
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "DOI is required"}, status=400)

    try:
        url = f"https://api.semanticscholar.org/v1/paper/{doi}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        contexts = data.get("contexts", [])
        return JsonResponse({"contexts": contexts})
    except requests.exceptions.RequestException as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
    """
    EN: Accepts a file upload ('manuscript') and returns JSON with citation snippets.
    ES: Acepta un archivo ('manuscript') y devuelve JSON con fragmentos de citación.
    """
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

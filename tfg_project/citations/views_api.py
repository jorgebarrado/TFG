"""
EN/ES: API endpoint to extract citation snippets from an uploaded manuscript.
Place this file as `citations/views_api.py` or merge the view into your `views.py`.
"""

from __future__ import annotations

import os
import tempfile

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# Adjust import to your project structure:
from .utils import extract_augmented_snippets_with_papermage


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
        data = extract_augmented_snippets_with_papermage(temp_path)
        return JsonResponse(data, status=200, safe=False)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

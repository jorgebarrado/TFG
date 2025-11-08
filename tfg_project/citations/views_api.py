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
from .services.citation_extractor import process_manuscript  # type: ignore


@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
    """
    Handles manuscript uploads to extract citation snippets.

    This API endpoint accepts a POST request with a file upload (PDF or TXT)
    named 'manuscript'. It processes the file to identify and extract
    citation contexts and returns them in a JSON format.

    Args:
        request: The HttpRequest object, expected to contain the uploaded
                 file in `request.FILES['manuscript']`.

    Returns:
        A JsonResponse containing the extracted citation data, which includes
        the citation marker, the surrounding context, and section titles.
        If no file is uploaded, it returns a 400 error.
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

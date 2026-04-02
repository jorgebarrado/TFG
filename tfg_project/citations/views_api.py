"""
EN/ES: API endpoint to extract citation snippets from an uploaded manuscript.
Place this file as `citations/views_api.py` or merge the view into your `views.py`.
"""

from __future__ import annotations

import os
import tempfile
import time

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .logging_utils import get_logger, log_phase
from .utils import extract_augmented_snippets_with_papermage

logger = get_logger(__name__)


@csrf_exempt
@require_POST
def api_extract_citations(request: HttpRequest) -> JsonResponse:
    """
    EN: Accepts a file upload ('manuscript') and returns JSON with citation snippets.
    ES: Acepta un archivo ('manuscript') y devuelve JSON con fragmentos de citación.
    """
    start_time = time.time()

    f: UploadedFile | None = request.FILES.get("manuscript")
    if not f:
        logger.warning(
            "api_extract_citations_failed", extra={"reason": "No file uploaded"}
        )
        return JsonResponse({"error": "No file uploaded"}, status=400)

    suffix = ".pdf" if f.name.lower().endswith(".pdf") else ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        with log_phase(logger, "reference_extraction", {"engine": "papermage"}):
            data = extract_augmented_snippets_with_papermage(temp_path)

        # Summary final por request
        total_time_ms = round((time.time() - start_time) * 1000, 2)
        references_total = (
            len(data) if isinstance(data, list) else len(data.get("references", []))
        )

        # Assuming `data` list contains dicts with citation elements, but adapting generically
        logger.info(
            "extraction_summary",
            extra={
                "references_total": references_total,
                "elapsed_ms": total_time_ms,
                "filename": f.name,
            },
        )

        return JsonResponse(data, status=200, safe=False)
    except Exception as e:
        logger.exception("api_extract_citations_error", extra={"error": str(e)})
        return JsonResponse({"error": "Error processing manuscript"}, status=500)
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass

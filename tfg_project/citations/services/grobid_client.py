"""
Cliente HTTP para GROBID (integración EXPERIMENTAL).

Llama a endpoints TEI de una instancia local de GROBID
(`/api/processFulltextDocument` y `/api/processReferences`)
y devuelve el TEI XML crudo como string.

Configuración (settings.py o .env):
  GROBID_BASE_URL  — URL base de GROBID, por defecto http://localhost:8070
  GROBID_TIMEOUT   — timeout en segundos, por defecto 120

Este módulo no forma parte del flujo principal del proyecto.
No modifica ni reemplaza ningún extractor existente.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger("citations.grobid")

# ---------------------------------------------------------------------------
# Excepciones del cliente
# ---------------------------------------------------------------------------


class GrobidError(Exception):
    """Error genérico del cliente GROBID."""


class GrobidUnavailableError(GrobidError):
    """GROBID no está arriba o no se puede conectar."""


class GrobidHTTPError(GrobidError):
    """GROBID devolvió un código HTTP de error."""


class GrobidServiceNotReadyError(GrobidError):
    """GROBID responde pero no está listo para procesar."""


class GrobidInvalidResponseError(GrobidError):
    """
    La respuesta HTTP fue 200 pero su contenido no es TEI XML de GROBID.
    Ejemplos: landing page HTML, página de error de proxy, timeout page.

    Atributos extra para diagnóstico:
        url          — endpoint al que se llamó
        content_type — valor del header Content-Type recibido
        body_preview — primeros 300 chars del body recibido
    """

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        content_type: str = "",
        body: str = "",
        body_preview: str = "",  # mantenido por compatibilidad; se deriva de body si se pasa body
    ) -> None:
        super().__init__(message)
        self.url = url
        self.content_type = content_type
        # body almacena el body completo; body_preview los primeros 300 chars para display
        self.body = body or body_preview
        self.body_preview = (self.body[:300].strip()) if self.body else body_preview


# ---------------------------------------------------------------------------
# Lectura de configuración (Django settings con fallback a env)
# ---------------------------------------------------------------------------


def _get_setting(name: str, default: str) -> str:
    """Lee un setting de Django con fallback a variable de entorno."""
    try:
        from django.conf import settings as django_settings

        val = getattr(django_settings, name, None)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(name, default)


def get_base_url() -> str:
    return _get_setting("GROBID_BASE_URL", "http://localhost:8070").rstrip("/")


def get_timeout() -> int:
    return int(_get_setting("GROBID_TIMEOUT", "120"))


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------


def process_fulltext_document(
    pdf_path: str | Path,
    *,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Envía un PDF a /api/processFulltextDocument y devuelve TEI XML.
    """
    return _process_pdf_endpoint(
        pdf_path,
        endpoint_path="/api/processFulltextDocument",
        base_url=base_url,
        timeout=timeout,
    )


def process_references(
    pdf_path: str | Path,
    *,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Envía un PDF a /api/processReferences y devuelve TEI XML.
    """
    return _process_pdf_endpoint(
        pdf_path,
        endpoint_path="/api/processReferences",
        base_url=base_url,
        timeout=timeout,
    )


def process_header_document(
    pdf_path: str | Path,
    *,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Envía un PDF a /api/processHeaderDocument y devuelve TEI XML.
    """
    return _process_pdf_endpoint(
        pdf_path,
        endpoint_path="/api/processHeaderDocument",
        base_url=base_url,
        timeout=timeout,
    )


def _process_pdf_endpoint(
    pdf_path: str | Path,
    *,
    endpoint_path: str,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """
    Envía un PDF a GROBID y devuelve el TEI XML crudo como string.

    Args:
        pdf_path: Ruta al fichero PDF (debe existir).
        base_url: Override de URL base de GROBID (ignora settings/env si se pasa).
        timeout: Override de timeout en segundos.

    Returns:
        El TEI XML como string UTF-8.

    Raises:
        GrobidError: Si el PDF no existe o la respuesta es vacía/malformada.
        GrobidUnavailableError: Si no hay conexión con GROBID.
        GrobidHTTPError: Si GROBID responde con un código HTTP de error.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise GrobidError(f"PDF no encontrado: {pdf_path}")

    base_url = (base_url or get_base_url()).rstrip("/")
    timeout = timeout if timeout is not None else get_timeout()
    endpoint = f"{base_url}{endpoint_path}"

    logger.debug("Enviando PDF a GROBID: %s -> %s", pdf_path.name, endpoint)

    try:
        with pdf_path.open("rb") as fh:
            response = requests.post(
                endpoint,
                files={"input": (pdf_path.name, fh, "application/pdf")},
                timeout=timeout,
            )
    except requests.exceptions.ConnectionError as exc:
        raise GrobidUnavailableError(
            f"No se puede conectar a GROBID en {base_url}. "
            "¿Está GROBID levantado? Consulta docs/grobid_experiment.md"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise GrobidUnavailableError(
            f"Timeout al llamar a GROBID (>{timeout}s). "
            "El PDF puede ser demasiado grande o el servicio está sobrecargado."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise GrobidUnavailableError(f"Error de red al llamar a GROBID: {exc}") from exc

    if not response.ok:
        raise GrobidHTTPError(
            f"GROBID devolvió HTTP {response.status_code}: {response.text[:300]}"
        )

    tei = response.text
    if not tei or not tei.strip():
        raise GrobidError("GROBID devolvió una respuesta vacía.")

    _validate_tei_response(tei, endpoint=endpoint, response=response)

    logger.debug("TEI recibido de GROBID: %d bytes", len(tei.encode("utf-8")))
    return tei


def _validate_tei_response(
    body: str, *, endpoint: str, response: "requests.Response"
) -> None:
    """
    Valida que el body de la respuesta sea realmente TEI XML de GROBID.

    Raises:
        GrobidInvalidResponseError si el body es HTML, está vacío o no contiene <TEI.
    """
    content_type = response.headers.get("Content-Type", "")
    preview = body[:300].strip()

    # Detectar HTML explícito (landing pages, error pages, wake-up pages)
    head = body[:500].lower()
    if "<!doctype html" in head or head.lstrip().startswith("<html"):
        raise GrobidInvalidResponseError(
            f"La URL respondió con HTML, no con TEI XML de GROBID "
            f"[Content-Type: {content_type!r}, preview: {preview!r}]",
            url=endpoint,
            content_type=content_type,
            body=body,
        )

    # El body debe contener la raíz <TEI en las primeras 1000 chars
    if "<TEI" not in body[:1000]:
        raise GrobidInvalidResponseError(
            f"La respuesta no contiene <TEI> (no parece TEI XML de GROBID) "
            f"[Content-Type: {content_type!r}, preview: {preview!r}]",
            url=endpoint,
            content_type=content_type,
            body=body,
        )

    # Debe ser XML bien formado
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise GrobidInvalidResponseError(
            f"La respuesta parece TEI pero no es XML válido: {exc}",
            url=endpoint,
            content_type=content_type,
            body=body,
        ) from exc

    if "TEI" not in str(root.tag):
        raise GrobidInvalidResponseError(
            f"El XML recibido no tiene raíz TEI (root={root.tag!r}).",
            url=endpoint,
            content_type=content_type,
            body=body,
        )


def check_service_ready(
    base_url: Optional[str] = None,
    *,
    timeout: int = 5,
    check_health: bool = False,
) -> tuple[bool, str]:
    """
    Comprueba disponibilidad simple de GROBID.

    - /api/isalive debe responder con body que contenga "true"
    - Opcionalmente /api/health debe responder HTTP 200
    """
    base_url = (base_url or get_base_url()).rstrip("/")
    isalive_url = f"{base_url}/api/isalive"
    try:
        resp = requests.get(isalive_url, timeout=timeout)
    except requests.exceptions.ConnectionError:
        return False, f"Sin conexión con {base_url} (connection refused / host inalcanzable)"
    except requests.exceptions.Timeout:
        return False, f"Timeout al comprobar {isalive_url} (>{timeout}s)"
    except requests.exceptions.RequestException as exc:
        return False, f"Error de red en {isalive_url}: {exc}"

    if not resp.ok:
        return False, f"HTTP {resp.status_code} en {isalive_url}"

    body = (resp.text or "").strip()
    body_lower = body.lower()
    if "true" not in body_lower:
        preview = body[:120].replace("\n", " ")
        return False, f"/api/isalive no devolvió 'true': {preview!r}"

    if not check_health:
        return True, "OK (/api/isalive=true)"

    health_url = f"{base_url}/api/health"
    try:
        health_resp = requests.get(health_url, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        return False, f"Error comprobando {health_url}: {exc}"

    if not health_resp.ok:
        return False, f"/api/health devolvió HTTP {health_resp.status_code}"

    return True, "OK (/api/isalive=true, /api/health=200)"


def check_grobid_alive(
    base_url: Optional[str] = None,
    timeout: int = 5,
) -> tuple[bool, str]:
    """
    Comprueba si GROBID está disponible llamando a su endpoint /api/isalive.

    Returns:
        (ok: bool, detail: str)
        ok=True  solo si GROBID responde con body que contiene "true" y sin HTML.
        detail   explica brevemente el resultado para mostrarlo al usuario.
    """
    base_url = (base_url or get_base_url()).rstrip("/")
    url = f"{base_url}/api/isalive"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.exceptions.ConnectionError:
        return False, f"Sin conexión con {base_url} (connection refused / host inalcanzable)"
    except requests.exceptions.Timeout:
        return False, f"Timeout al comprobar {url} (>{timeout}s)"
    except requests.exceptions.RequestException as exc:
        return False, f"Error de red: {exc}"

    if not resp.ok:
        return False, f"HTTP {resp.status_code} en {url}"

    body = resp.text.strip()
    body_lower = body.lower()

    # Landing page HTML → servicio dormido o URL incorrecta
    if "<!doctype html" in body_lower or body_lower.lstrip().startswith("<html"):
        preview = body[:120].replace("\n", " ")
        return False, (
            f"La URL devolvió HTML, no 'true'. "
            f"El Space probablemente está dormido o la URL no apunta a la API. "
            f"Preview: {preview!r}"
        )

    # GROBID devuelve "true" (plain text); aceptamos también variantes menores
    if "true" in body_lower:
        return True, f"OK ({url} => {body!r})"

    preview = body[:80]
    return False, f"Respuesta inesperada de {url}: {preview!r}"

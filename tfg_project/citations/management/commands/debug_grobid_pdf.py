# Comando de gestión experimental: envía un PDF a GROBID y vuelca el XML TEI resultante para inspección.
"""
Management command: debug_grobid_pdf
====================================
Prueba experimental mínima de GROBID sobre un PDF local.

Objetivo:
- enviar un PDF a un endpoint de GROBID,
- recibir el XML,
- parsearlo,
- guardar artefactos simples.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.core.management.base import BaseCommand, CommandError

from citations.services.grobid_client import (
    GrobidError,
    GrobidHTTPError,
    GrobidInvalidResponseError,
    GrobidServiceNotReadyError,
    GrobidUnavailableError,
    check_service_ready,
    get_base_url,
    process_fulltext_document,
    process_header_document,
    process_references,
)
from citations.services.grobid_parser import (
    GrobidParseError,
    parse_fulltext_tei,
    parse_header_tei,
    parse_references_tei,
)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[4] / "tmp" / "grobid_pdf_debug"

_MODE_TO_ENDPOINT = {
    "header": "processHeaderDocument",
    "references": "processReferences",
    "fulltext": "processFulltextDocument",
}


class Command(BaseCommand):
    help = (
        "[EXPERIMENTAL] Envía un PDF a GROBID (header|references|fulltext), "
        "parsea la respuesta y guarda artefactos simples."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf",
            type=Path,
            required=True,
            metavar="PATH",
            help="Ruta al PDF a procesar.",
        )
        parser.add_argument(
            "--mode",
            default="fulltext",
            choices=["header", "references", "fulltext"],
            metavar="MODE",
            help="Modo/endpoint a probar (default: fulltext).",
        )
        parser.add_argument(
            "--grobid-url",
            default=None,
            metavar="URL",
            help="Override de URL base de GROBID (default: settings.GROBID_BASE_URL).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=120,
            metavar="N",
            help="Timeout en segundos para llamadas HTTP (default: 120).",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=None,
            metavar="DIR",
            help=f"Directorio de salida (default: {DEFAULT_OUTPUT_DIR}).",
        )
        parser.add_argument(
            "--check-health",
            action="store_true",
            default=False,
            help="Comprueba también /api/health además de /api/isalive.",
        )

    def handle(self, *args, **options):
        pdf_path: Path = options["pdf"].resolve()
        mode: str = options["mode"]
        grobid_url: Optional[str] = options["grobid_url"]
        timeout: int = options["timeout"]
        output_dir: Optional[Path] = options["output_dir"]
        check_health: bool = options["check_health"]

        if not pdf_path.is_file():
            raise CommandError(f"El fichero PDF no existe: {pdf_path}")
        if timeout <= 0:
            raise CommandError("--timeout debe ser > 0")

        base_url = (grobid_url or get_base_url()).rstrip("/")
        endpoint = _MODE_TO_ENDPOINT[mode]
        run_dir = self._build_run_dir(pdf_path, mode=mode, output_dir=output_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n[EXPERIMENTAL] GROBID PDF Debug\n"
                f"  PDF       : {pdf_path}\n"
                f"  URL       : {base_url}\n"
                f"  Modo      : {mode}\n"
                f"  Endpoint  : /api/{endpoint}\n"
            )
        )

        ok, detail = check_service_ready(
            base_url=base_url,
            timeout=min(timeout, 10),
            check_health=check_health,
        )
        if not ok:
            message = f"GROBID no está disponible: {detail}"
            self._save_error(
                run_dir=run_dir,
                error_type="service_not_ready",
                error=message,
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ: {message}"))
            self.stdout.write(f"  Detalles: {run_dir / 'error.json'}")
            sys.exit(1)

        self.stdout.write(self.style.SUCCESS(f"  Servicio OK: {detail}\n"))

        try:
            xml_body = self._run_endpoint(
                mode=mode,
                pdf_path=pdf_path,
                base_url=base_url,
                timeout=timeout,
            )
            parsed = self._parse_response(mode=mode, xml_body=xml_body)
        except GrobidInvalidResponseError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="invalid_response",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
                response_body=exc.body or exc.body_preview or None,
                extra={
                    "content_type": exc.content_type,
                    "url": exc.url,
                    "body_preview": exc.body_preview,
                },
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [invalid_response]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)
        except GrobidServiceNotReadyError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="service_not_ready",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [service_not_ready]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)
        except GrobidUnavailableError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="connection",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [connection]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)
        except GrobidHTTPError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="http",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [http]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)
        except GrobidParseError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="parse_error",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [parse_error]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)
        except GrobidError as exc:
            error_path = self._save_error(
                run_dir=run_dir,
                error_type="error",
                error=str(exc),
                mode=mode,
                endpoint=endpoint,
                pdf_path=pdf_path,
                base_url=base_url,
            )
            self.stdout.write(self.style.ERROR(f"  FALLÓ [error]: {exc}"))
            self.stdout.write(f"  Detalles: {error_path}")
            sys.exit(1)

        response_path = run_dir / "response.xml"
        response_path.write_text(xml_body, encoding="utf-8")

        parsed_path = run_dir / "parsed.json"
        parsed_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = self._build_summary(mode=mode, parsed=parsed)
        summary_path = run_dir / "summary.txt"
        summary_path.write_text(summary, encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS("  OK: respuesta procesada correctamente.\n")
        )
        self.stdout.write(summary)
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- Artefactos guardados ---"))
        self.stdout.write(f"  response.xml  {response_path}")
        self.stdout.write(f"  parsed.json   {parsed_path}")
        self.stdout.write(f"  summary.txt   {summary_path}")

    def _run_endpoint(
        self,
        *,
        mode: str,
        pdf_path: Path,
        base_url: str,
        timeout: int,
    ) -> str:
        if mode == "header":
            return process_header_document(pdf_path, base_url=base_url, timeout=timeout)
        if mode == "references":
            return process_references(pdf_path, base_url=base_url, timeout=timeout)
        return process_fulltext_document(pdf_path, base_url=base_url, timeout=timeout)

    def _parse_response(self, *, mode: str, xml_body: str) -> Dict[str, Any]:
        if mode == "header":
            return parse_header_tei(xml_body)
        if mode == "references":
            return parse_references_tei(xml_body, include_raw_citation=True)
        return parse_fulltext_tei(xml_body)

    def _build_summary(self, *, mode: str, parsed: Dict[str, Any]) -> str:
        lines: List[str] = []
        warnings = parsed.get("_warnings") or []

        lines.append("Resumen extracción GROBID:")
        lines.append(f"  mode: {mode}")

        if mode == "header":
            title = parsed.get("title") or "(sin título)"
            authors = ", ".join(parsed.get("authors") or []) or "(sin autores)"
            abstract = (parsed.get("abstract") or "").strip()
            if len(abstract) > 280:
                abstract = abstract[:280] + "..."
            doi = parsed.get("doi") or "(sin DOI)"
            lines += [
                f"  title: {title}",
                f"  authors: {authors}",
                f"  doi: {doi}",
                f"  abstract: {abstract or '(vacío)'}",
            ]
        elif mode == "references":
            refs = parsed.get("references") or []
            lines.append(
                f"  references_count: {parsed.get('reference_count', len(refs))}"
            )
            lines.append("  primeras_5_referencias:")
            for idx, ref in enumerate(refs[:5], 1):
                title = ref.get("title") or "(sin título)"
                doi = ref.get("doi") or ""
                year = ref.get("year") or ""
                bits = " | ".join([b for b in [str(year) if year else "", doi] if b])
                if bits:
                    lines.append(f"    [{idx}] {title} ({bits})")
                else:
                    lines.append(f"    [{idx}] {title}")
        else:
            metadata = parsed.get("metadata") or {}
            lines += [
                f"  title: {metadata.get('title') or '(sin título)'}",
                f"  authors: {', '.join(metadata.get('authors') or []) or '(sin autores)'}",
                f"  sections_count: {len(parsed.get('sections') or [])}",
                f"  references_count: {parsed.get('reference_count', 0)}",
                f"  inline_citations_count: {parsed.get('inline_citation_count', 0)}",
            ]

        if warnings:
            lines.append("  warnings:")
            for warning in warnings:
                lines.append(f"    - {warning}")

        return "\n".join(lines)

    def _build_run_dir(
        self, pdf_path: Path, *, mode: str, output_dir: Optional[Path]
    ) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_name = f"{ts}_{pdf_path.stem}_{mode}"
        return (output_dir or DEFAULT_OUTPUT_DIR) / run_name

    def _save_error(
        self,
        *,
        run_dir: Path,
        error_type: str,
        error: str,
        mode: str,
        endpoint: str,
        pdf_path: Path,
        base_url: str,
        response_body: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Path:
        payload: Dict[str, Any] = {
            "error_type": error_type,
            "error": error,
            "mode": mode,
            "endpoint": endpoint,
            "pdf": str(pdf_path),
            "base_url": base_url,
        }
        if extra:
            payload.update(extra)

        if response_body:
            body_path = run_dir / "response_body.txt"
            body_path.write_text(response_body, encoding="utf-8")
            payload["response_body"] = str(body_path)

        error_path = run_dir / "error.json"
        error_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return error_path

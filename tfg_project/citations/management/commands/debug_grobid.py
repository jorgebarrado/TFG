# Comando de gestión experimental: prueba GROBID sobre un PDF local y compara con el extractor actual.
"""
Management command: debug_grobid
================================
Prueba EXPERIMENTAL de GROBID sobre un PDF local.

Ejecuta GROBID, guarda los artefactos y opcionalmente compara
con el extractor actual del proyecto.

Uso básico:
    python manage.py debug_grobid --pdf /ruta/al/paper.pdf

Con comparación:
    python manage.py debug_grobid --pdf /ruta/al/paper.pdf --compare-current

Opciones completas:
    --pdf PATH              Ruta al PDF (obligatorio)
    --compare-current       Ejecuta el extractor actual y guarda comparación
    --engine ENGINE         Motor para el extractor actual: auto|papermage|papercraft|generic
    --output-dir DIR        Directorio de salida (default: tmp/grobid_debug/)
    --grobid-url URL        Override de la URL base de GROBID
    --timeout N             Override del timeout en segundos
    --mode MODE            fulltext|references|both (default: fulltext)
    --warmup-retries N      Reintentos /api/isalive para HF Space dormido (default: 6)
    --warmup-wait N         Espera entre reintentos en segundos (default: 10)
    --no-warmup-retry       Desactiva el warmup-retry automático para HF Space

Artefactos generados en tmp/grobid_debug/<timestamp>_<pdf>/:
    tei.xml         TEI XML crudo de GROBID
    parsed.json     JSON estructurado del TEI
    current.json    Resultado del extractor actual (solo con --compare-current)
    comparison.json Comparación numérica básica (solo con --compare-current)
    summary.txt     Resumen legible

Consulta docs/grobid_experiment.md para instrucciones de puesta en marcha.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.core.management.base import BaseCommand, CommandError

from citations.services.grobid_client import check_grobid_alive, get_base_url
from citations.services.grobid_extractor import (
    DEFAULT_OUTPUT_DIR,
    run_grobid_extraction,
)

_MODE_ENDPOINT = {
    "fulltext": "processFulltextDocument",
    "references": "processReferences",
}


# Descripciones cortas para consola (el detalle largo va a summary.txt / error.json)
_SHORT_ERROR_DESC: dict = {
    "connection": "GROBID no alcanzable (connection refused / timeout)",
    "http": "GROBID devolvió un código HTTP de error",
    "huggingface_space_warming_up": "HuggingFace Space dormido — devolvió HTML en lugar de TEI XML",
    "huggingface_space_warming_up_timeout": "El Space no salió del estado warming-up tras los reintentos",
    "non_tei_html_response": "URL devolvió HTML (proxy, landing page u otro servicio)",
    "non_tei_response": "Respuesta no-HTML pero sin <TEI> (endpoint incorrecto?)",
    "invalid_response": "Respuesta no es TEI XML de GROBID",
    "parse_error": "XML recibido no es TEI válido",
    "error": "Error genérico",
}

_ERROR_LABELS: dict = {
    "connection": "Error de conexión",
    "http": "Error HTTP de GROBID",
    "huggingface_space_warming_up": "HuggingFace Space dormido (devolvió HTML)",
    "huggingface_space_warming_up_timeout": "HuggingFace Space no salió de warming-up a tiempo",
    "non_tei_html_response": "URL devolvió HTML — no es el endpoint GROBID",
    "non_tei_response": "Respuesta sin <TEI> (endpoint incorrecto?)",
    "invalid_response": "Respuesta inválida — no es TEI XML de GROBID",
    "parse_error": "Error de parseo del XML recibido",
    "error": "Error genérico",
}


class Command(BaseCommand):
    help = (
        "[EXPERIMENTAL] Prueba GROBID sobre un PDF local. "
        "No afecta al flujo principal del proyecto."
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
            "--compare-current",
            action="store_true",
            default=False,
            help="Ejecuta también el extractor actual del proyecto y guarda una comparación.",
        )
        parser.add_argument(
            "--engine",
            default="auto",
            choices=["auto", "papermage", "papercraft", "generic"],
            metavar="ENGINE",
            help="Motor para el extractor actual en la comparación (default: auto).",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=None,
            metavar="DIR",
            help=f"Directorio de salida (default: {DEFAULT_OUTPUT_DIR}).",
        )
        parser.add_argument(
            "--grobid-url",
            default=None,
            metavar="URL",
            help="Override de la URL base de GROBID (default: settings.GROBID_BASE_URL).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=None,
            metavar="N",
            help="Timeout en segundos para la llamada a GROBID.",
        )
        parser.add_argument(
            "--mode",
            default="fulltext",
            choices=["fulltext", "references", "both"],
            metavar="MODE",
            help="Endpoint a probar: fulltext | references | both (default: fulltext).",
        )
        parser.add_argument(
            "--skip-alive-check",
            action="store_true",
            default=False,
            help="Omite la comprobación de /api/isalive y va directo al endpoint de extracción.",
        )
        parser.add_argument(
            "--warmup-retries",
            type=int,
            default=6,
            metavar="N",
            help="Reintentos de /api/isalive para HF Space dormido (default: 6).",
        )
        parser.add_argument(
            "--warmup-wait",
            type=int,
            default=10,
            metavar="N",
            help="Espera en segundos entre reintentos warmup (default: 10).",
        )
        parser.add_argument(
            "--no-warmup-retry",
            action="store_true",
            default=False,
            help="Desactiva el retry automático de warming-up para HF Space.",
        )

    # -----------------------------------------------------------------------
    # Punto de entrada
    # -----------------------------------------------------------------------

    def handle(self, *args, **options):
        pdf_path: Path = options["pdf"].resolve()
        compare_current: bool = options["compare_current"]
        engine: str = options["engine"]
        output_dir: Optional[Path] = options["output_dir"]
        grobid_url: Optional[str] = options["grobid_url"]
        timeout: Optional[int] = options["timeout"]
        mode: str = options["mode"]
        skip_alive_check: bool = options["skip_alive_check"]
        warmup_retries: int = options["warmup_retries"]
        warmup_wait: int = options["warmup_wait"]
        no_warmup_retry: bool = options["no_warmup_retry"]

        if not pdf_path.is_file():
            raise CommandError(f"El fichero PDF no existe: {pdf_path}")
        if warmup_retries < 0:
            raise CommandError("--warmup-retries debe ser >= 0")
        if warmup_wait < 0:
            raise CommandError("--warmup-wait debe ser >= 0")

        effective_grobid_url = (grobid_url or get_base_url()).rstrip("/")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n[EXPERIMENTAL] GROBID Debug\n"
                f"  PDF        : {pdf_path}\n"
                f"  GROBID URL : {effective_grobid_url}\n"
                f"  Modo       : {mode}\n"
            )
        )

        # Comprobación de disponibilidad de GROBID.
        # Para HF Space + HTML en /api/isalive puede activar warmup-retry bloqueante.
        alive: Optional[bool] = None
        alive_detail: str = ""
        warmup_retry: Dict[str, Any] = {
            "enabled": not no_warmup_retry,
            "eligible": False,
            "configured_retries": warmup_retries,
            "wait_seconds": warmup_wait,
            "attempts_performed": 0,
            "total_wait_seconds": 0,
            "ready_after_attempt": None,
            "result": "not_applicable",
            "initial_detail": "",
            "final_detail": "",
        }
        skip_grobid_extraction = False
        if skip_alive_check:
            self.stdout.write("  /api/isalive omitido (--skip-alive-check).\n")
            warmup_retry["result"] = "skipped_alive_check"
        else:
            self.stdout.write("  Comprobando /api/isalive...")
            alive, alive_detail = check_grobid_alive(base_url=effective_grobid_url)
            warmup_retry["initial_detail"] = alive_detail
            warmup_retry["final_detail"] = alive_detail
            if alive:
                self.stdout.write(self.style.SUCCESS(f"  OK — {alive_detail}\n"))
                warmup_retry["result"] = "not_needed"
            else:
                is_hf_warmup = self._is_hf_warming_up_signal(
                    effective_grobid_url,
                    alive_detail,
                )
                warmup_retry["eligible"] = is_hf_warmup
                if is_hf_warmup and not no_warmup_retry:
                    self.stdout.write(
                        self.style.WARNING(
                            "  /api/isalive devolvió HTML; el Space parece estar arrancando.\n"
                        )
                    )
                    alive, alive_detail, warmup_retry = self._retry_hf_space_warmup(
                        base_url=effective_grobid_url,
                        current_detail=alive_detail,
                        warmup_retry=warmup_retry,
                    )
                    if alive:
                        self.stdout.write(
                            self.style.SUCCESS(
                                "  GROBID listo; continuando con la extracción.\n"
                            )
                        )
                    else:
                        attempts_done = warmup_retry.get("attempts_performed", 0)
                        result_code = warmup_retry.get("result")
                        if result_code == "timeout":
                            msg = (
                                "  El Space no salió del estado warming-up tras "
                                f"{attempts_done} intentos."
                            )
                        else:
                            msg = (
                                "  /api/isalive no llegó a 'true' durante el warmup-retry "
                                f"(resultado: {result_code}, intentos: {attempts_done})."
                            )
                        self.stdout.write(
                            self.style.ERROR(
                                f"{msg}\n  Último detalle: {alive_detail}\n"
                            )
                        )
                        skip_grobid_extraction = True
                elif is_hf_warmup and no_warmup_retry:
                    self.stdout.write(
                        self.style.WARNING(
                            "  Aviso: el Space de HuggingFace parece dormido, pero "
                            "el warmup-retry está desactivado (--no-warmup-retry).\n"
                            "  Se intenta la llamada de extracción de todos modos...\n"
                        )
                    )
                    warmup_retry["result"] = "disabled"
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Aviso: {alive_detail}\n"
                            "  Se intenta la llamada de extracción de todos modos...\n"
                        )
                    )
                    warmup_retry["result"] = "not_eligible"

        # ------------------------------------------------------------------
        # 1. Extracción GROBID
        # ------------------------------------------------------------------
        selected_modes = ["fulltext", "references"] if mode == "both" else [mode]
        run_dir = self._build_run_dir(pdf_path, output_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        grobid_results: Dict[str, Dict[str, Any]] = {}

        if skip_grobid_extraction:
            for selected_mode in selected_modes:
                prefix = f"{selected_mode}_" if mode == "both" else ""
                grobid_results[selected_mode] = self._build_warmup_timeout_result(
                    pdf_path=pdf_path,
                    run_dir=run_dir,
                    mode=selected_mode,
                    artifact_prefix=prefix,
                    base_url=effective_grobid_url,
                    alive_detail=alive_detail,
                    warmup_retry=warmup_retry,
                )
        else:
            for selected_mode in selected_modes:
                endpoint_name = _MODE_ENDPOINT[selected_mode]
                prefix = f"{selected_mode}_" if mode == "both" else ""
                self.stdout.write(
                    f"Extracción GROBID [{selected_mode}] "
                    f"(endpoint=/api/{endpoint_name})..."
                )
                mode_result = run_grobid_extraction(
                    pdf_path,
                    save_artifacts=True,
                    base_url=effective_grobid_url,
                    timeout=timeout,
                    mode=selected_mode,
                    run_dir=run_dir,
                    artifact_prefix=prefix,
                )
                mode_result["warmup_retry"] = warmup_retry
                grobid_results[selected_mode] = mode_result

                if mode_result["ok"]:
                    parsed = mode_result["parsed"] or {}
                    if selected_mode == "fulltext":
                        msg = (
                            f"  OK — {parsed.get('reference_count', 0)} referencias, "
                            f"{parsed.get('inline_citation_count', 0)} citas inline.\n"
                        )
                    else:
                        msg = (
                            f"  OK — {parsed.get('reference_count', 0)} referencias.\n"
                        )
                    self.stdout.write(self.style.SUCCESS(msg))
                else:
                    error_type = mode_result.get("error_type", "error")
                    short_desc = _SHORT_ERROR_DESC.get(error_type, "error inesperado")
                    artifacts = mode_result.get("artifacts") or {}
                    error_file = artifacts.get("error_json", "error.json")
                    self.stdout.write(
                        self.style.ERROR(
                            f"  FALLÓ [{error_type}]: {short_desc}\n"
                            f"  Detalles en: {error_file}\n"
                        )
                    )

        # ------------------------------------------------------------------
        # 2. Extractor actual (opcional, solo si GROBID OK o se pide igualmente)
        # ------------------------------------------------------------------
        artifact_map: Dict[str, str] = {}
        for selected_mode, mode_result in grobid_results.items():
            for key, path in (mode_result.get("artifacts") or {}).items():
                label = f"{selected_mode}_{key}" if mode == "both" else key
                artifact_map[label] = path

        current_result: Optional[Dict[str, Any]] = None
        if compare_current:
            self.stdout.write(f"\nExtractor actual (engine={engine})...")
            current_result = self._run_current_extractor(pdf_path, engine)

            if current_result.get("ok"):
                run_dir.mkdir(parents=True, exist_ok=True)
                current_path = run_dir / "current.json"
                current_path.write_text(
                    json.dumps(current_result["data"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                artifact_map["current_json"] = str(current_path)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  OK — {current_result['ref_count']} referencias.\n"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  No disponible: {current_result.get('error')}\n"
                    )
                )

        # ------------------------------------------------------------------
        # 3. Summary y comparación (siempre, incluso si GROBID falló)
        # ------------------------------------------------------------------
        run_dir.mkdir(parents=True, exist_ok=True)

        # Guardar resultado del check de disponibilidad como artefacto
        if alive is not None:
            availability = {
                "checked": True,
                "ok": alive,
                "detail": alive_detail,
                "url": f"{effective_grobid_url}/api/isalive",
                "mode": mode,
                "selected_modes": selected_modes,
                "warmup_retry": warmup_retry,
            }
        else:
            availability = {
                "checked": False,
                "reason": "--skip-alive-check",
                "mode": mode,
                "selected_modes": selected_modes,
            }
        availability_path = run_dir / "availability_check.json"
        availability_path.write_text(
            json.dumps(availability, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifact_map["availability_check"] = str(availability_path)

        if mode == "both":
            summary = self._build_summary_both(grobid_results, current_result)
        else:
            summary = self._build_summary(
                grobid_results[selected_modes[0]], current_result
            )
        summary_path = run_dir / "summary.txt"
        summary_path.write_text(summary, encoding="utf-8")
        artifact_map["summary"] = str(summary_path)

        if current_result and current_result.get("ok"):
            for selected_mode, mode_result in grobid_results.items():
                if not mode_result.get("ok"):
                    continue
                comparison = self._build_comparison(
                    mode_result["parsed"], current_result
                )
                comparison_name = (
                    f"comparison_{selected_mode}.json"
                    if mode == "both"
                    else "comparison.json"
                )
                comparison_path = run_dir / comparison_name
                comparison_path.write_text(
                    json.dumps(comparison, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                key = (
                    f"comparison_{selected_mode}.json"
                    if mode == "both"
                    else "comparison_json"
                )
                artifact_map[key] = str(comparison_path)
                mode_result.setdefault("artifacts", {})["comparison_json"] = str(
                    comparison_path
                )

        # ------------------------------------------------------------------
        # 4. Salida en consola — solo artefactos; el detalle está en summary.txt
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- Artefactos guardados ---"))
        for key, path in artifact_map.items():
            self.stdout.write(f"  {key:25s}  {path}")
        self.stdout.write(f"\n  Resumen completo: {summary_path}\n")

        any_grobid_error = any(not r.get("ok") for r in grobid_results.values())
        if any_grobid_error:
            sys.exit(1)

    # -----------------------------------------------------------------------
    # Extractor actual del proyecto
    # -----------------------------------------------------------------------

    def _is_hf_warming_up_signal(self, base_url: str, detail: str) -> bool:
        """
        True solo para el caso acotado de HF Space + respuesta HTML en /api/isalive.
        """
        base_lower = (base_url or "").lower()
        detail_lower = (detail or "").lower()
        is_hf = "hf.space" in base_lower or "huggingface" in base_lower
        looks_like_html = (
            " html" in f" {detail_lower}"
            or "<!doctype html" in detail_lower
            or detail_lower.lstrip().startswith("<html")
        )
        return is_hf and looks_like_html

    def _retry_hf_space_warmup(
        self,
        *,
        base_url: str,
        current_detail: str,
        warmup_retry: Dict[str, Any],
    ) -> tuple[bool, str, Dict[str, Any]]:
        retries = int(warmup_retry.get("configured_retries", 0))
        wait_seconds = int(warmup_retry.get("wait_seconds", 0))
        last_detail = current_detail

        for attempt in range(1, retries + 1):
            self.stdout.write(
                f"  Esperando {wait_seconds}s antes del reintento {attempt}/{retries}..."
            )
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            self.stdout.write("  Reintentando /api/isalive...")
            alive, detail = check_grobid_alive(base_url=base_url)

            warmup_retry["attempts_performed"] = attempt
            warmup_retry["total_wait_seconds"] = attempt * wait_seconds
            warmup_retry["final_detail"] = detail
            last_detail = detail

            if alive:
                warmup_retry["result"] = "recovered"
                warmup_retry["ready_after_attempt"] = attempt
                return True, detail, warmup_retry

            if not self._is_hf_warming_up_signal(base_url, detail):
                warmup_retry["result"] = "ended_with_non_ready_response"
                return False, detail, warmup_retry

        warmup_retry["result"] = "timeout"
        return False, last_detail, warmup_retry

    def _build_run_dir(self, pdf_path: Path, output_dir: Optional[Path]) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_name = f"{ts}_{pdf_path.stem}"
        return (output_dir or DEFAULT_OUTPUT_DIR) / run_name

    def _build_warmup_timeout_result(
        self,
        *,
        pdf_path: Path,
        run_dir: Path,
        mode: str,
        artifact_prefix: str,
        base_url: str,
        alive_detail: str,
        warmup_retry: Dict[str, Any],
    ) -> Dict[str, Any]:
        error_type = "huggingface_space_warming_up_timeout"
        attempts_done = int(warmup_retry.get("attempts_performed", 0))
        waited_total = int(warmup_retry.get("total_wait_seconds", 0))
        error_payload = {
            "error_type": error_type,
            "error": (
                "El Space de HuggingFace no llegó a un estado API listo "
                f"tras {attempts_done} reintentos (espera acumulada: {waited_total}s)."
            ),
            "pdf": str(pdf_path),
            "mode": mode,
            "endpoint": _MODE_ENDPOINT.get(mode, ""),
            "base_url": base_url,
            "alive_detail": alive_detail,
            "warmup_retry": warmup_retry,
        }
        error_name = f"{artifact_prefix}error.json" if artifact_prefix else "error.json"
        error_path = run_dir / error_name
        error_path.write_text(
            json.dumps(error_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "ok": False,
            "error": error_payload["error"],
            "error_type": error_type,
            "mode": mode,
            "endpoint": _MODE_ENDPOINT.get(mode, ""),
            "pdf": str(pdf_path),
            "tei_xml": None,
            "parsed": None,
            "artifacts": {"error_json": str(error_path)},
            "run_dir": str(run_dir),
            "warmup_retry": warmup_retry,
        }

    def _run_current_extractor(self, pdf_path: Path, engine: str) -> Dict[str, Any]:
        """Ejecuta el extractor actual (reader_data + references_data) sobre el PDF."""
        try:
            from citations.services.reader_data import extract_pdf_references
            from citations.services.references_data import build_references_data
        except ImportError as exc:
            return {
                "ok": False,
                "error": f"No se pudo importar el extractor actual: {exc}",
            }

        try:
            references, stats = extract_pdf_references(str(pdf_path))
        except Exception as exc:
            return {
                "ok": False,
                "error": f"extract_pdf_references falló: {type(exc).__name__}: {exc}",
            }

        # Intentar obtener layers de papermage (no es fatal si falla)
        layers: Dict[str, Any] = {}
        try:
            from citations.services.papermage_extractor import extract_pdf_data

            reader = extract_pdf_data(str(pdf_path))
            layers = reader.get("layers", {})
        except Exception:
            pass

        try:
            references_data = build_references_data(
                references=references,
                snippets=[],
                layers=layers,
                references_numbered=bool(stats.get("references_numbered")),
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": f"build_references_data falló: {type(exc).__name__}: {exc}",
            }

        entries = list((references_data or {}).get("references") or [])
        return {
            "ok": True,
            "ref_count": len(entries),
            "data": {
                "stats": stats,
                "raw_references": references,
                "references_data": references_data,
            },
        }

    # -----------------------------------------------------------------------
    # Summary legible
    # -----------------------------------------------------------------------

    def _build_summary(
        self,
        grobid_result: Dict[str, Any],
        current_result: Optional[Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        parsed = grobid_result.get("parsed") or {}
        meta = parsed.get("metadata") or {}
        artifacts = grobid_result.get("artifacts") or {}
        warmup_retry = grobid_result.get("warmup_retry") or {}
        mode_name = grobid_result.get("mode") or "fulltext"
        endpoint_name = grobid_result.get("endpoint") or _MODE_ENDPOINT.get(
            mode_name, ""
        )

        lines += [
            "=== Resumen GROBID Experimental ===",
            f"Fecha       : {ts}",
            f"PDF         : {grobid_result['pdf']}",
            f"Modo        : {mode_name}",
            (
                f"Endpoint    : /api/{endpoint_name}"
                if endpoint_name
                else "Endpoint    : (no informado)"
            ),
            "",
        ]

        if warmup_retry:
            lines += [
                "--- Warmup retry HF Space ---",
                f"Activado    : {'sí' if warmup_retry.get('enabled') else 'no'}",
                f"Elegible    : {'sí' if warmup_retry.get('eligible') else 'no'}",
                f"Intentos cfg: {warmup_retry.get('configured_retries', 0)}",
                f"Espera cfg  : {warmup_retry.get('wait_seconds', 0)} s",
                f"Reintentos  : {warmup_retry.get('attempts_performed', 0)}",
                f"Espera total: {warmup_retry.get('total_wait_seconds', 0)} s",
                f"Resultado   : {warmup_retry.get('result')}",
            ]
            if warmup_retry.get("initial_detail"):
                lines.append(f"Detalle ini.: {warmup_retry.get('initial_detail')}")
            if warmup_retry.get("final_detail"):
                lines.append(f"Detalle fin.: {warmup_retry.get('final_detail')}")
            lines.append("")

        # ---- GROBID ----
        if not grobid_result["ok"]:
            error_type = grobid_result.get("error_type") or "error"
            label = _ERROR_LABELS.get(error_type, error_type)
            lines += [
                "--- GROBID: FALLÓ ---",
                f"Estado      : ERROR [{error_type}]",
                f"Tipo        : {label}",
            ]

            # Diagnóstico específico por tipo
            if error_type == "huggingface_space_warming_up":
                lines += [
                    "",
                    "Diagnóstico:",
                    "  El HuggingFace Space devolvió una página HTML en lugar de TEI XML.",
                    "  Causa más probable: el Space está dormido (inactivo por falta de uso).",
                    "  Solución: abre el Space en el navegador, espera que arranque y reintenta.",
                    "  O usa una instancia local de GROBID con Docker (ver docs/grobid_experiment.md).",
                ]
            elif error_type == "huggingface_space_warming_up_timeout":
                lines += [
                    "",
                    "Diagnóstico:",
                    "  Se detectó warming-up en un HF Space y se aplicó warmup-retry automático.",
                    "  El endpoint /api/isalive nunca devolvió 'true' dentro del límite configurado.",
                    "  No se ejecutó el endpoint de extracción para evitar un POST prematuro.",
                ]
            elif error_type in (
                "non_tei_html_response",
                "invalid_response",
                "non_tei_response",
            ):
                lines += [
                    "",
                    "Diagnóstico:",
                    "  La URL no devolvió TEI XML de GROBID.",
                    "  Causas habituales:",
                    "    - URL incorrecta o endpoint equivocado",
                    "    - Proxy intermedio devolvió su propia página de error",
                    "    - Servicio dormido o con otro software en ese puerto",
                    "  Una respuesta válida de GROBID empieza por: <?xml ... <TEI ...",
                ]
            elif error_type == "connection":
                lines += [
                    "",
                    "Diagnóstico:",
                    "  No se pudo conectar al servidor GROBID.",
                    "  Comprueba que GROBID está corriendo y que la URL es correcta.",
                    "  Para uso local: docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.1",
                ]

            lines += [
                "",
                "Artefactos de diagnóstico:",
            ]
            if artifacts.get("error_json"):
                lines.append(f"  error.json          : {artifacts['error_json']}")
            if artifacts.get("response_body"):
                lines.append(f"  response_body.txt   : {artifacts['response_body']}")
            if artifacts.get("availability_check"):
                lines.append(
                    f"  availability_check  : {artifacts['availability_check']}"
                )
        else:
            lines += [
                "--- GROBID: OK ---",
                "Estado      : OK",
                f"Referencias : {parsed.get('reference_count', 0)}",
            ]
            if mode_name == "fulltext":
                lines += [
                    f"Título      : {meta.get('title') or '(no detectado)'}",
                    f"Autores     : {', '.join(meta.get('authors') or []) or '(ninguno)'}",
                    f"Citas inline: {parsed.get('inline_citation_count', 0)}",
                ]

            refs = parsed.get("references") or []
            if refs:
                lines += ["", "Primeras 5 referencias (GROBID):"]
                for i, ref in enumerate(refs[:5]):
                    auth = ", ".join(ref.get("authors") or [])[:70]
                    tit = (ref.get("title") or "(sin título)")[:90]
                    yr = ref.get("year") or ""
                    doi = ref.get("doi") or ""
                    lines.append(f"  [{i + 1}] {tit}")
                    if auth:
                        lines.append(f"       Autores: {auth}")
                    details = " | ".join(filter(None, [str(yr) if yr else "", doi]))
                    if details:
                        lines.append(f"       {details}")

            warnings = parsed.get("_warnings") or []
            if warnings:
                lines += ["", "Advertencias del parser TEI:"]
                for w in warnings:
                    lines.append(f"  ! {w}")

        # ---- Extractor actual ----
        if current_result is not None:
            lines += ["", "--- Extractor actual ---"]
            if not current_result.get("ok"):
                lines.append("Estado      : ERROR")
                lines.append(f"Detalle     : {current_result.get('error')}")
            else:
                lines += [
                    "Estado      : OK",
                    f"Referencias : {current_result.get('ref_count', 0)}",
                ]
                current_data = current_result.get("data") or {}
                current_refs = list(
                    (current_data.get("references_data") or {}).get("references") or []
                )
                if current_refs:
                    lines += ["", "Primeras 5 referencias (extractor actual):"]
                    for i, ref in enumerate(current_refs[:5]):
                        text = str(ref.get("text") or "")[:100]
                        doi = ref.get("doi") or ""
                        src = ref.get("structure_source") or ""
                        lines.append(f"  [{i + 1}] {text}")
                        details = " | ".join(
                            filter(None, [doi, f"src={src}" if src else ""])
                        )
                        if details:
                            lines.append(f"       {details}")

            # ---- Comparación rápida ----
            lines += ["", "--- Comparación rápida ---"]
            if grobid_result["ok"] and current_result.get("ok"):
                gp = grobid_result.get("parsed") or {}
                g = gp.get("reference_count", 0)
                c = current_result.get("ref_count", 0)
                lines.append(
                    f"Referencias — GROBID: {g} | Actual: {c} | Diferencia: {g - c:+d}"
                )
                g_inline = gp.get("inline_citation_count", 0)
                lines.append(
                    f"Citas inline — GROBID: {g_inline} | Actual: (no medido aquí)"
                )
                g_with_doi = sum(
                    1 for r in (gp.get("references") or []) if r.get("doi")
                )
                lines.append(f"Refs con DOI (GROBID): {g_with_doi} de {g}")
                if artifacts.get("comparison_json"):
                    lines.append("Ver comparison.json para detalle DOI-a-DOI.")
            elif not grobid_result["ok"]:
                lines.append(
                    f"(Comparación no ejecutada: GROBID falló [{grobid_result.get('error_type')}].)"
                )
                lines.append(
                    f"  El extractor actual encontró {current_result.get('ref_count', '?')} "
                    f"referencias (funcionó correctamente)."
                )
            else:
                lines.append(
                    "(Comparación no disponible: el extractor actual devolvió error.)"
                )

        return "\n".join(lines)

    def _build_summary_both(
        self,
        grobid_results: Dict[str, Dict[str, Any]],
        current_result: Optional[Dict[str, Any]],
    ) -> str:
        lines: List[str] = []
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        first_result = (
            grobid_results.get("fulltext") or grobid_results.get("references") or {}
        )
        pdf_path = first_result.get("pdf", "(desconocido)")
        warmup_retry = first_result.get("warmup_retry") or {}

        lines += [
            "=== Resumen GROBID Experimental (mode=both) ===",
            f"Fecha       : {ts}",
            f"PDF         : {pdf_path}",
            "",
        ]

        if warmup_retry:
            lines += [
                "--- Warmup retry HF Space ---",
                f"Reintentos  : {warmup_retry.get('attempts_performed', 0)}",
                f"Espera total: {warmup_retry.get('total_wait_seconds', 0)} s",
                f"Resultado   : {warmup_retry.get('result')}",
                "",
            ]

        lines += ["--- Resultados por endpoint ---"]
        for mode_name in ["fulltext", "references"]:
            result = grobid_results.get(mode_name)
            if not result:
                continue
            endpoint = result.get("endpoint") or _MODE_ENDPOINT.get(mode_name, "")
            if result.get("ok"):
                parsed = result.get("parsed") or {}
                ref_count = parsed.get("reference_count", 0)
                line = (
                    f"{mode_name:10s} /api/{endpoint} -> OK | referencias: {ref_count}"
                )
                if mode_name == "fulltext":
                    line += f" | citas inline: {parsed.get('inline_citation_count', 0)}"
                lines.append(line)
            else:
                err_type = result.get("error_type", "error")
                err_label = _SHORT_ERROR_DESC.get(err_type, "error")
                lines.append(
                    f"{mode_name:10s} /api/{endpoint} -> ERROR [{err_type}] {err_label}"
                )

        lines += ["", "--- Extractor actual ---"]
        if current_result is None:
            lines.append("No ejecutado (--compare-current no activo).")
        elif not current_result.get("ok"):
            lines.append(f"Estado: ERROR | Detalle: {current_result.get('error')}")
        else:
            current_count = int(current_result.get("ref_count", 0))
            lines.append(f"Estado: OK | referencias: {current_count}")

        lines += ["", "--- Comparación rápida para bibliografía ---"]
        if not (current_result and current_result.get("ok")):
            lines.append("No disponible (falta baseline del extractor actual).")
            return "\n".join(lines)

        current_count = int(current_result.get("ref_count", 0))
        mode_counts: Dict[str, int] = {}
        for mode_name in ["fulltext", "references"]:
            result = grobid_results.get(mode_name) or {}
            if result.get("ok"):
                parsed = result.get("parsed") or {}
                mode_counts[mode_name] = int(parsed.get("reference_count", 0))

        if not mode_counts:
            lines.append("Ningún endpoint GROBID devolvió resultado válido.")
            return "\n".join(lines)

        for mode_name, count in mode_counts.items():
            lines.append(
                f"{mode_name:10s}: {count} refs | diferencia vs actual: {count - current_count:+d}"
            )

        best_mode = min(mode_counts, key=lambda m: abs(mode_counts[m] - current_count))
        best_diff = abs(mode_counts[best_mode] - current_count)
        ties = [
            m for m, c in mode_counts.items() if abs(c - current_count) == best_diff
        ]
        if len(ties) > 1:
            lines.append(
                "Conclusión: ambos endpoints quedan igual de cerca del baseline actual."
            )
        else:
            lines.append(
                f"Conclusión: {best_mode} es el endpoint más cercano al baseline actual "
                "para conteo de bibliografía."
            )
        if mode_counts.get("references", 0) > mode_counts.get("fulltext", 0):
            lines.append(
                "Nota: processReferences detectó más referencias que processFulltextDocument."
            )
        elif mode_counts.get("references", 0) < mode_counts.get("fulltext", 0):
            lines.append(
                "Nota: processFulltextDocument detectó más referencias que processReferences."
            )
        else:
            lines.append(
                "Nota: ambos endpoints detectaron el mismo número de referencias."
            )

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Comparación JSON estructurada
    # -----------------------------------------------------------------------

    def _build_comparison(
        self,
        grobid_parsed: Dict[str, Any],
        current_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Genera un JSON de comparación numérica básica entre GROBID y el extractor actual."""
        grobid_refs = grobid_parsed.get("references") or []
        current_data = current_result.get("data") or {}
        current_refs = list(
            (current_data.get("references_data") or {}).get("references") or []
        )

        grobid_dois = {r["doi"].strip().lower() for r in grobid_refs if r.get("doi")}
        current_dois = {
            str(r.get("doi") or "").strip().lower()
            for r in current_refs
            if r.get("doi")
        }

        common_dois = grobid_dois & current_dois
        only_grobid = sorted(grobid_dois - current_dois)
        only_current = sorted(current_dois - grobid_dois)

        return {
            "grobid_ref_count": len(grobid_refs),
            "current_ref_count": len(current_refs),
            "grobid_inline_citation_count": grobid_parsed.get(
                "inline_citation_count", 0
            ),
            "grobid_refs_with_doi": len(grobid_dois),
            "current_refs_with_doi": len(current_dois),
            "dois_in_common": len(common_dois),
            "dois_only_in_grobid": only_grobid,
            "dois_only_in_current": only_current,
            "grobid_first5": [
                {
                    "id": r.get("id", ""),
                    "title": r.get("title", ""),
                    "authors": r.get("authors", []),
                    "doi": r.get("doi") or "",
                    "year": r.get("year"),
                    "venue": r.get("venue", ""),
                }
                for r in grobid_refs[:5]
            ],
            "current_first5": [
                {
                    "text": str(r.get("text") or "")[:150],
                    "doi": r.get("doi") or "",
                    "structure_source": r.get("structure_source", ""),
                    "accepted": (r.get("reference_validation") or {}).get("accepted"),
                }
                for r in current_refs[:5]
            ],
        }

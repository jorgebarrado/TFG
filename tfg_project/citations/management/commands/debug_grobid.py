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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.core.management.base import BaseCommand, CommandError

from citations.services.grobid_client import check_grobid_alive, get_base_url
from citations.services.grobid_extractor import DEFAULT_OUTPUT_DIR, run_grobid_extraction


# Descripciones cortas para consola (el detalle largo va a summary.txt / error.json)
_SHORT_ERROR_DESC: dict = {
    "connection":                   "GROBID no alcanzable (connection refused / timeout)",
    "http":                         "GROBID devolvió un código HTTP de error",
    "huggingface_space_warming_up": "HuggingFace Space dormido — devolvió HTML en lugar de TEI XML",
    "non_tei_html_response":        "URL devolvió HTML (proxy, landing page u otro servicio)",
    "non_tei_response":             "Respuesta no-HTML pero sin <TEI> (endpoint incorrecto?)",
    "invalid_response":             "Respuesta no es TEI XML de GROBID",
    "parse_error":                  "XML recibido no es TEI válido",
    "error":                        "Error genérico",
}

_ERROR_LABELS: dict = {
    "connection":                   "Error de conexión",
    "http":                         "Error HTTP de GROBID",
    "huggingface_space_warming_up": "HuggingFace Space dormido (devolvió HTML)",
    "non_tei_html_response":        "URL devolvió HTML — no es el endpoint GROBID",
    "non_tei_response":             "Respuesta sin <TEI> (endpoint incorrecto?)",
    "invalid_response":             "Respuesta inválida — no es TEI XML de GROBID",
    "parse_error":                  "Error de parseo del XML recibido",
    "error":                        "Error genérico",
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
            "--skip-alive-check",
            action="store_true",
            default=False,
            help="Omite la comprobación de /api/isalive y va directo al endpoint de extracción.",
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
        skip_alive_check: bool = options["skip_alive_check"]

        if not pdf_path.is_file():
            raise CommandError(f"El fichero PDF no existe: {pdf_path}")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n[EXPERIMENTAL] GROBID Debug\n"
            f"  PDF        : {pdf_path}\n"
            f"  GROBID URL : {grobid_url or get_base_url()}\n"
        ))

        # Comprobación de disponibilidad de GROBID (informativa, no bloqueante)
        alive: Optional[bool] = None
        alive_detail: str = ""
        if skip_alive_check:
            self.stdout.write("  /api/isalive omitido (--skip-alive-check).\n")
        else:
            self.stdout.write("  Comprobando /api/isalive...")
            alive, alive_detail = check_grobid_alive(base_url=grobid_url)
            if alive:
                self.stdout.write(self.style.SUCCESS(f"  OK — {alive_detail}\n"))
            else:
                # Detectar si el Space de HF devolvió HTML (está dormido)
                detail_lower = alive_detail.lower()
                is_hf_html = "html" in detail_lower and (
                    "huggingface" in (grobid_url or "").lower()
                    or "hf.space" in (grobid_url or "").lower()
                    or "preview" in detail_lower
                )
                if is_hf_html:
                    self.stdout.write(self.style.WARNING(
                        "  Aviso: el Space de HuggingFace parece estar dormido "
                        "(devolvió HTML en /api/isalive).\n"
                        "  Se intenta la llamada de extracción de todos modos "
                        "(puede tardar mientras el Space arranca)...\n"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"  Aviso: {alive_detail}\n"
                        "  Se intenta la llamada de extracción de todos modos...\n"
                    ))

        # ------------------------------------------------------------------
        # 1. Extracción GROBID
        # ------------------------------------------------------------------
        self.stdout.write("Extracción GROBID (puede tardar varios segundos)...")
        grobid_result = run_grobid_extraction(
            pdf_path,
            save_artifacts=True,
            output_dir=output_dir,
            base_url=grobid_url,
            timeout=timeout,
        )
        run_dir = Path(grobid_result["run_dir"])

        grobid_ok = grobid_result["ok"]
        if grobid_ok:
            parsed = grobid_result["parsed"]
            self.stdout.write(self.style.SUCCESS(
                f"  OK — {parsed['reference_count']} referencias, "
                f"{parsed['inline_citation_count']} citas inline.\n"
            ))
        else:
            error_type = grobid_result.get("error_type", "error")
            # Mensaje corto en consola; el detalle completo va a error.json / summary.txt
            short_desc = _SHORT_ERROR_DESC.get(error_type, "error inesperado")
            artifacts = grobid_result.get("artifacts") or {}
            error_file = artifacts.get("error_json", "error.json")
            self.stdout.write(self.style.ERROR(
                f"  FALLÓ [{error_type}]: {short_desc}\n"
                f"  Detalles en: {error_file}\n"
            ))

        # ------------------------------------------------------------------
        # 2. Extractor actual (opcional, solo si GROBID OK o se pide igualmente)
        # ------------------------------------------------------------------
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
                grobid_result["artifacts"]["current_json"] = str(current_path)
                self.stdout.write(self.style.SUCCESS(
                    f"  OK — {current_result['ref_count']} referencias.\n"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  No disponible: {current_result.get('error')}\n"
                ))

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
                "url": f"{grobid_url or get_base_url()}/api/isalive",
            }
        else:
            availability = {"checked": False, "reason": "--skip-alive-check"}
        availability_path = run_dir / "availability_check.json"
        availability_path.write_text(
            json.dumps(availability, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        grobid_result["artifacts"]["availability_check"] = str(availability_path)

        summary = self._build_summary(grobid_result, current_result)
        summary_path = run_dir / "summary.txt"
        summary_path.write_text(summary, encoding="utf-8")
        grobid_result["artifacts"]["summary"] = str(summary_path)

        if grobid_ok and current_result and current_result.get("ok"):
            comparison = self._build_comparison(grobid_result["parsed"], current_result)
            comparison_path = run_dir / "comparison.json"
            comparison_path.write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            grobid_result["artifacts"]["comparison_json"] = str(comparison_path)

        # ------------------------------------------------------------------
        # 4. Salida en consola — solo artefactos; el detalle está en summary.txt
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("\n--- Artefactos guardados ---"))
        for key, path in grobid_result["artifacts"].items():
            self.stdout.write(f"  {key:25s}  {path}")
        self.stdout.write(f"\n  Resumen completo: {summary_path}\n")

        if not grobid_ok:
            sys.exit(1)

    # -----------------------------------------------------------------------
    # Extractor actual del proyecto
    # -----------------------------------------------------------------------

    def _run_current_extractor(self, pdf_path: Path, engine: str) -> Dict[str, Any]:
        """Ejecuta el extractor actual (reader_data + references_data) sobre el PDF."""
        try:
            from citations.services.reader_data import extract_pdf_references
            from citations.services.references_data import build_references_data
        except ImportError as exc:
            return {"ok": False, "error": f"No se pudo importar el extractor actual: {exc}"}

        try:
            references, stats = extract_pdf_references(str(pdf_path))
        except Exception as exc:
            return {"ok": False, "error": f"extract_pdf_references falló: {type(exc).__name__}: {exc}"}

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

        lines += [
            "=== Resumen GROBID Experimental ===",
            f"Fecha       : {ts}",
            f"PDF         : {grobid_result['pdf']}",
            "",
        ]

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
            elif error_type in ("non_tei_html_response", "invalid_response", "non_tei_response"):
                lines += [
                    "",
                    "Diagnóstico:",
                    "  La URL no devolvió TEI XML de GROBID.",
                    "  Causas habituales:",
                    "    - URL incorrecta (no apunta a /api/processFulltextDocument)",
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
                lines.append(f"  availability_check  : {artifacts['availability_check']}")
        else:
            lines += [
                "--- GROBID: OK ---",
                f"Estado      : OK",
                f"Título      : {meta.get('title') or '(no detectado)'}",
                f"Autores     : {', '.join(meta.get('authors') or []) or '(ninguno)'}",
                f"Referencias : {parsed.get('reference_count', 0)}",
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
                lines.append(f"Estado      : ERROR")
                lines.append(f"Detalle     : {current_result.get('error')}")
            else:
                lines += [
                    f"Estado      : OK",
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
                        details = " | ".join(filter(None, [doi, f"src={src}" if src else ""]))
                        if details:
                            lines.append(f"       {details}")

            # ---- Comparación rápida ----
            lines += ["", "--- Comparación rápida ---"]
            if grobid_result["ok"] and current_result.get("ok"):
                gp = grobid_result.get("parsed") or {}
                g = gp.get("reference_count", 0)
                c = current_result.get("ref_count", 0)
                lines.append(f"Referencias — GROBID: {g} | Actual: {c} | Diferencia: {g - c:+d}")
                g_inline = gp.get("inline_citation_count", 0)
                lines.append(f"Citas inline — GROBID: {g_inline} | Actual: (no medido aquí)")
                g_with_doi = sum(
                    1 for r in (gp.get("references") or []) if r.get("doi")
                )
                lines.append(f"Refs con DOI (GROBID): {g_with_doi} de {g}")
                if artifacts.get("comparison_json"):
                    lines.append(f"Ver comparison.json para detalle DOI-a-DOI.")
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
            "grobid_inline_citation_count": grobid_parsed.get("inline_citation_count", 0),
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

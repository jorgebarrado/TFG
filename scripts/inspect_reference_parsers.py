from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import requests

from citations.services.grobid_client import (  # noqa: E402
    check_service_ready,
    get_base_url,
    get_timeout,
    process_fulltext_document,
    process_references,
)
from citations.services.grobid_parser import (  # noqa: E402
    GrobidParseError,
    parse_fulltext_tei,
    parse_references_tei,
)
from citations.services.reference_parsing_experiments.input_common import (  # noqa: E402
    build_common_input,
)
from citations.services.reference_parsing_experiments.runners import (  # noqa: E402
    run_refextract_parser,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str((ROOT / "tfg_project").resolve()))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _error_payload(
    exc: Exception, *, context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    return {
        "status": "error",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "context": context or {},
        "traceback": traceback.format_exc(),
    }


def _collect_grobid_health(base_url: str, timeout: int) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    checks: Dict[str, Any] = {}
    for endpoint in ("/api/version", "/api/isalive", "/api/health"):
        url = f"{base}{endpoint}"
        payload: Dict[str, Any] = {
            "url": url,
            "ok": False,
            "status_code": None,
            "body_preview": "",
            "error": "",
        }
        try:
            resp = requests.get(url, timeout=timeout)
            body = resp.text or ""
            payload["ok"] = bool(resp.ok)
            payload["status_code"] = resp.status_code
            payload["body_preview"] = body[:300]
            if endpoint == "/api/isalive":
                payload["isalive_true"] = "true" in body.lower()
        except requests.RequestException as exc:
            payload["error"] = str(exc)
        checks[endpoint] = payload

    ready, ready_detail = check_service_ready(
        base_url=base,
        timeout=min(timeout, 10),
        check_health=True,
    )
    return {
        "base_url": base,
        "timeout_seconds": timeout,
        "created_at": datetime.now().isoformat(),
        "checks": checks,
        "summary": {
            "ready": bool(ready),
            "ready_detail": ready_detail,
            "isalive_true": bool(checks.get("/api/isalive", {}).get("isalive_true")),
            "all_http_ok": all(bool(item.get("ok")) for item in checks.values()),
        },
    }


def _call_process_citation_list(
    raw_references: Sequence[Dict[str, Any]],
    *,
    base_url: str,
    timeout: int,
) -> Tuple[str, Dict[str, Any]]:
    citations = [
        (item.get("raw_input") or "").strip()
        for item in raw_references
        if (item.get("raw_input") or "").strip()
    ]
    if not citations:
        raise ValueError("No raw references available for /api/processCitationList")

    payload = [("citations", citation) for citation in citations]
    url = f"{base_url.rstrip('/')}/api/processCitationList"
    response = requests.post(
        url,
        data=payload,
        headers={"Accept": "application/xml"},
        timeout=timeout,
    )
    response.raise_for_status()

    tei_xml = response.text or ""
    if "<TEI" not in tei_xml[:1200]:
        preview = tei_xml[:300]
        raise GrobidParseError(
            f"/api/processCitationList did not return TEI XML. Preview: {preview!r}"
        )

    parsed = parse_references_tei(tei_xml, include_raw_citation=True)
    parsed_refs = parsed.get("references") or []
    notes: List[str] = []
    if len(parsed_refs) != len(citations):
        notes.append(
            f"processCitationList returned {len(parsed_refs)} parsed references for {len(citations)} inputs."
        )

    return tei_xml, {
        "input_reference_count": len(citations),
        "parsed_reference_count": len(parsed_refs),
        "notes": notes,
        "parsed": parsed,
    }


def _save_skipped_grobid_errors(output_dir: Path, reason: str, detail: str) -> None:
    payload = {
        "status": "skipped",
        "error_type": "grobid_unavailable",
        "error": reason,
        "detail": detail,
    }
    _write_json(output_dir / "grobid_processReferences_error.json", payload)
    _write_json(output_dir / "grobid_processFulltextDocument_error.json", payload)
    _write_json(output_dir / "grobid_processCitationList_error.json", payload)


def _list_output_files(output_dir: Path) -> List[str]:
    files = [
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    ]
    return sorted(files)


def run_inspection(
    *,
    pdf_path: Path,
    out_root: Path,
    grobid_base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    output_dir = (out_root / pdf_path.stem).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    statuses: Dict[str, str] = {}

    health = _collect_grobid_health(grobid_base_url, timeout)
    _write_json(output_dir / "health.json", health)
    grobid_ready = bool(health.get("summary", {}).get("ready"))

    common_input: Dict[str, Any] | None = None
    raw_reference_count = 0
    try:
        common_input = build_common_input(pdf_path)
        raw_references = common_input.get("raw_references") or []
        raw_reference_count = len(raw_references)
        _write_json(output_dir / "common_input.json", common_input)
        _write_json(output_dir / "extractor_raw_references.json", raw_references)
        _write_json(
            output_dir / "extractor_warnings.json", common_input.get("warnings") or []
        )
        _write_json(
            output_dir / "extractor_stats.json",
            common_input.get("extractor_stats") or {},
        )
        statuses["common_input"] = "ok"
    except Exception as exc:
        _write_json(
            output_dir / "common_input_error.json",
            _error_payload(exc, context={"pdf_path": str(pdf_path.resolve())}),
        )
        statuses["common_input"] = "error"

    if grobid_ready:
        try:
            tei = process_references(
                pdf_path, base_url=grobid_base_url, timeout=timeout
            )
            parsed = parse_references_tei(tei, include_raw_citation=True)
            _write_text(output_dir / "grobid_processReferences.xml", tei)
            _write_json(output_dir / "grobid_processReferences_parsed.json", parsed)
            statuses["grobid_processReferences"] = "ok"
        except Exception as exc:
            _write_json(
                output_dir / "grobid_processReferences_error.json",
                _error_payload(exc, context={"endpoint": "/api/processReferences"}),
            )
            statuses["grobid_processReferences"] = "error"

        try:
            tei = process_fulltext_document(
                pdf_path, base_url=grobid_base_url, timeout=timeout
            )
            parsed = parse_fulltext_tei(tei)
            _write_text(output_dir / "grobid_processFulltextDocument.xml", tei)
            _write_json(
                output_dir / "grobid_processFulltextDocument_parsed.json", parsed
            )
            statuses["grobid_processFulltextDocument"] = "ok"
        except Exception as exc:
            _write_json(
                output_dir / "grobid_processFulltextDocument_error.json",
                _error_payload(
                    exc, context={"endpoint": "/api/processFulltextDocument"}
                ),
            )
            statuses["grobid_processFulltextDocument"] = "error"

        try:
            if not common_input:
                raise RuntimeError(
                    "common_input unavailable; cannot run /api/processCitationList"
                )
            tei, parsed_payload = _call_process_citation_list(
                common_input.get("raw_references") or [],
                base_url=grobid_base_url,
                timeout=timeout,
            )
            _write_text(output_dir / "grobid_processCitationList.xml", tei)
            _write_json(
                output_dir / "grobid_processCitationList_parsed.json", parsed_payload
            )
            statuses["grobid_processCitationList"] = "ok"
        except Exception as exc:
            _write_json(
                output_dir / "grobid_processCitationList_error.json",
                _error_payload(exc, context={"endpoint": "/api/processCitationList"}),
            )
            statuses["grobid_processCitationList"] = "error"
    else:
        detail = str(
            health.get("summary", {}).get("ready_detail") or "GROBID is not ready"
        )
        _save_skipped_grobid_errors(
            output_dir=output_dir,
            reason="grobid_not_ready",
            detail=detail,
        )
        statuses["grobid_processReferences"] = "skipped"
        statuses["grobid_processFulltextDocument"] = "skipped"
        statuses["grobid_processCitationList"] = "skipped"

    try:
        if not common_input:
            raise RuntimeError("common_input unavailable; cannot run refextract")
        refextract_output = run_refextract_parser(common_input)
        _write_json(output_dir / "refextract_raw.json", refextract_output)
        _write_json(
            output_dir / "refextract_entries.json",
            refextract_output.get("entries") or [],
        )
        _write_json(
            output_dir / "refextract_notes.json",
            {
                "status": refextract_output.get("status"),
                "availability": refextract_output.get("availability") or {},
                "notes": refextract_output.get("notes") or [],
            },
        )
        if refextract_output.get("status") != "ok":
            _write_json(
                output_dir / "refextract_error.json",
                {
                    "status": "error",
                    "error_type": "refextract_not_ok",
                    "error": "run_refextract_parser returned non-ok status",
                    "result_status": refextract_output.get("status"),
                    "notes": refextract_output.get("notes") or [],
                    "availability": refextract_output.get("availability") or {},
                },
            )
            statuses["refextract"] = "error"
        else:
            statuses["refextract"] = "ok"
    except Exception as exc:
        _write_json(output_dir / "refextract_raw.json", {})
        _write_json(output_dir / "refextract_entries.json", [])
        _write_json(
            output_dir / "refextract_notes.json",
            {"status": "error", "notes": ["refextract execution failed"]},
        )
        _write_json(
            output_dir / "refextract_error.json",
            _error_payload(exc),
        )
        statuses["refextract"] = "error"

    files_generated = _list_output_files(output_dir)
    summary = {
        "created_at": datetime.now().isoformat(),
        "pdf_path": str(pdf_path.resolve()),
        "pdf_name": pdf_path.name,
        "output_dir": str(output_dir),
        "grobid_base_url": grobid_base_url.rstrip("/"),
        "timeout_seconds": timeout,
        "raw_reference_count": raw_reference_count,
        "grobid_ready": grobid_ready,
        "statuses": statuses,
        "files_generated": files_generated,
    }
    _write_json(output_dir / "summary.json", summary)

    summary["files_generated"] = _list_output_files(output_dir)
    _write_json(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect extractor + GROBID + refextract outputs for a single PDF."
    )
    parser.add_argument(
        "pdf_path",
        help="Absolute or relative path to a single PDF file.",
    )
    parser.add_argument(
        "--out",
        default="tmp/parser_inspection",
        help="Output root directory. Result is written under <out>/<pdf_stem>/",
    )
    parser.add_argument(
        "--grobid-base-url",
        default=get_base_url(),
        help="GROBID base URL.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=get_timeout(),
        help="Timeout in seconds for GROBID HTTP requests.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).expanduser()
    if not pdf_path.is_file():
        parser.error(f"PDF not found: {pdf_path}")

    summary = run_inspection(
        pdf_path=pdf_path,
        out_root=Path(args.out),
        grobid_base_url=args.grobid_base_url,
        timeout=args.timeout,
    )

    print(f"PDF: {summary['pdf_path']}")
    print(f"Output: {summary['output_dir']}")
    print(f"Raw references: {summary['raw_reference_count']}")
    print("Generated files:")
    for path in summary["files_generated"]:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

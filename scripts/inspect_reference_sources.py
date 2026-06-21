# Inspecciona y compara todas las fuentes de referencias para un PDF:
# extractor propio, GROBID, refextract, Crossref y Semantic Scholar.
# Salida en tmp/reference_source_inspection/<pdf_stem>/ con un JSON unificado por fuente.
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import requests

from citations.services.doi_enrichment_service import (  # noqa: E402
    is_valid_doi,
    normalize_doi,
)
from citations.services.grobid_client import (  # noqa: E402
    check_service_ready,
    get_base_url,
    get_timeout,
    process_header_document,
    process_references,
)
from citations.services.grobid_parser import (  # noqa: E402
    parse_header_tei,
    parse_references_tei,
)
from citations.services.papermage_extractor import extract_pdf_data  # noqa: E402
from citations.services.reference_parsing_experiments.input_common import (  # noqa: E402
    build_common_input,
)
from citations.services.reference_parsing_experiments.runners import (  # noqa: E402
    run_refextract_parser,
)
from citations.services.references_data import (  # noqa: E402
    _detect_article_doi_from_rows,
)
from citations.services.semantic_scholar_client import (  # noqa: E402
    SEMANTIC_SCHOLAR_API_URL,
    SemanticScholarError,
    get_paper_by_doi,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str((ROOT / "tfg_project").resolve()))


CROSSREF_API_BASE = "https://api.crossref.org"
SOURCE_ORDER = [
    "extractor",
    "grobid_processReferences",
    "refextract",
    "crossref",
    "semantic_scholar",
]
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value).strip()
        return normalized or None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized or None


def coerce_year(value: Any) -> Optional[int]:
    if isinstance(value, int) and 1500 <= value <= 2100:
        return value
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            year = coerce_year(item)
            if year is not None:
                return year
        return None
    match = YEAR_RE.search(str(value))
    if not match:
        return None
    try:
        year = int(match.group(0))
    except ValueError:
        return None
    return year if 1500 <= year <= 2100 else None


def first_text(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = clean_text(item)
                if text:
                    return text
            continue
        text = clean_text(value)
        if text:
            return text
    return None


def normalize_author_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    authors: List[str] = []
    for item in values:
        if isinstance(item, dict):
            name = clean_text(item.get("name"))
            if not name:
                given = clean_text(item.get("given"))
                family = clean_text(item.get("family"))
                literal = clean_text(item.get("literal"))
                name = (
                    clean_text(" ".join(part for part in [given, family] if part))
                    or literal
                )
        else:
            name = clean_text(item)
        if name:
            authors.append(name)
    return authors


def normalize_doi_or_none(value: Any) -> Optional[str]:
    normalized = normalize_doi(value)
    if not normalized:
        return None
    if not is_valid_doi(normalized):
        return None
    return normalized


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _error_payload(
    exc: Exception, *, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "status": "error",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "context": context or {},
        "traceback": traceback.format_exc(),
    }


def _http_error_payload(
    response: requests.Response,
    *,
    url: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    preview = (response.text or "")[:500]
    return {
        "status": "error",
        "error_type": "http_error",
        "error": f"HTTP {response.status_code}",
        "context": {
            "url": url,
            "status_code": response.status_code,
            "body_preview": preview,
            **(context or {}),
        },
    }


def build_external_api_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def build_semantic_scholar_fields() -> str:
    return (
        "title,year,venue,externalIds,url,"
        "references.title,references.year,references.externalIds,references.authors,"
        "references.venue,references.url"
    )


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


def _list_output_files(output_dir: Path) -> List[str]:
    return sorted(
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    )


def _extractor_bibliography_start_page(
    common_input: Optional[Dict[str, Any]],
) -> Optional[int]:
    extractor_stats = (
        ((common_input or {}).get("extractor_stats") or {})
        if isinstance(common_input, dict)
        else {}
    )
    raw_page = extractor_stats.get("bibliography_start_page")
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return None
    if page <= 0:
        return None
    return page - 1


def collect_extractor_paper_candidate(
    pdf_path: Path,
    common_input: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    warnings: List[str] = []
    if not common_input:
        warnings.append(
            "Extractor metadata unavailable because common_input could not be built."
        )
        return {
            "paper_title": None,
            "paper_doi": None,
            "doi_source": None,
            "warnings": warnings,
        }

    try:
        reader_data = extract_pdf_data(str(pdf_path))
        layers = reader_data.get("layers", {}) if isinstance(reader_data, dict) else {}
        row_items = layers.get("rows", []) if isinstance(layers, dict) else []
        bibliography_start_page = _extractor_bibliography_start_page(common_input)
        detected_doi = _detect_article_doi_from_rows(
            row_items if isinstance(row_items, list) else [],
            bibliography_start_page,
        )
        normalized_doi = normalize_doi_or_none(detected_doi)
        if detected_doi and not normalized_doi:
            warnings.append(
                f"Extractor produced an invalid DOI candidate: {detected_doi}"
            )
        return {
            "paper_title": None,
            "paper_doi": normalized_doi,
            "doi_source": "extractor_row_detection" if normalized_doi else None,
            "warnings": warnings,
        }
    except Exception as exc:
        warnings.append(f"Extractor DOI detection failed: {exc}")
        return {
            "paper_title": None,
            "paper_doi": None,
            "doi_source": None,
            "warnings": warnings,
        }


def collect_grobid_paper_candidate(
    pdf_path: Path,
    *,
    grobid_ready: bool,
    grobid_base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    warnings: List[str] = []
    if not grobid_ready:
        warnings.append("GROBID header metadata skipped because GROBID is not ready.")
        return {
            "paper_title": None,
            "paper_doi": None,
            "doi_source": None,
            "warnings": warnings,
        }

    try:
        tei_xml = process_header_document(
            pdf_path,
            base_url=grobid_base_url,
            timeout=timeout,
        )
        parsed = parse_header_tei(tei_xml)
        raw_doi = parsed.get("doi")
        normalized_doi = normalize_doi_or_none(raw_doi)
        if raw_doi and not normalized_doi:
            warnings.append(
                f"GROBID header produced an invalid DOI candidate: {raw_doi}"
            )
        warnings.extend(
            clean_text(item)
            for item in (parsed.get("_warnings") or [])
            if clean_text(item)
        )
        return {
            "paper_title": clean_text(parsed.get("title")),
            "paper_doi": normalized_doi,
            "doi_source": "grobid_header" if normalized_doi else None,
            "warnings": warnings,
        }
    except Exception as exc:
        warnings.append(f"GROBID header metadata failed: {exc}")
        return {
            "paper_title": None,
            "paper_doi": None,
            "doi_source": None,
            "warnings": warnings,
        }


def resolve_paper_identity(
    *,
    pdf_name: str,
    extractor_candidate: Optional[Dict[str, Any]],
    grobid_candidate: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    extractor_candidate = extractor_candidate or {}
    grobid_candidate = grobid_candidate or {}

    extractor_doi = normalize_doi_or_none(extractor_candidate.get("paper_doi"))
    grobid_doi = normalize_doi_or_none(grobid_candidate.get("paper_doi"))
    extractor_title = clean_text(extractor_candidate.get("paper_title"))
    grobid_title = clean_text(grobid_candidate.get("paper_title"))

    warnings: List[str] = []
    warnings.extend(
        clean_text(item)
        for item in extractor_candidate.get("warnings", [])
        if clean_text(item)
    )
    warnings.extend(
        clean_text(item)
        for item in grobid_candidate.get("warnings", [])
        if clean_text(item)
    )

    paper_doi: Optional[str] = None
    doi_source: Optional[str] = None
    if extractor_doi:
        paper_doi = extractor_doi
        doi_source = (
            clean_text(extractor_candidate.get("doi_source"))
            or "extractor_row_detection"
        )
        if grobid_doi and grobid_doi != extractor_doi:
            warnings.append(
                f"DOI conflict between extractor ({extractor_doi}) and GROBID ({grobid_doi}); extractor DOI kept by priority."
            )
    elif grobid_doi:
        paper_doi = grobid_doi
        doi_source = clean_text(grobid_candidate.get("doi_source")) or "grobid_header"
    else:
        warnings.append(
            "No reliable paper DOI detected from extractor metadata or GROBID header."
        )

    paper_title = extractor_title or grobid_title
    return {
        "pdf_name": pdf_name,
        "paper_title": paper_title,
        "paper_doi": paper_doi,
        "doi_source": doi_source,
        "warnings": warnings,
        "candidates": {
            "extractor": extractor_candidate,
            "grobid": grobid_candidate,
        },
    }


def normalize_extractor_reference(
    reference: Dict[str, Any], *, index: int
) -> Dict[str, Any]:
    return {
        "source": "extractor",
        "index": index + 1,
        "raw": clean_text(reference.get("raw_input") or reference.get("raw")),
        "title": None,
        "authors": [],
        "year": None,
        "doi": normalize_doi_or_none(
            reference.get("extractor_doi") or reference.get("doi")
        ),
        "venue": None,
        "pages": None,
        "extra": {
            "source_index": reference.get("source_index"),
            "numbered": bool(reference.get("numbered")),
            "warnings": [
                clean_text(item)
                for item in (reference.get("warnings") or [])
                if clean_text(item)
            ],
            "extractor_confidence": reference.get("extractor_confidence"),
        },
    }


def normalize_grobid_reference(
    reference: Dict[str, Any], *, index: int
) -> Dict[str, Any]:
    return {
        "source": "grobid_processReferences",
        "index": index + 1,
        "raw": clean_text(reference.get("raw_citation")),
        "title": clean_text(reference.get("title")),
        "authors": normalize_author_list(reference.get("authors")),
        "year": coerce_year(reference.get("year")),
        "doi": normalize_doi_or_none(reference.get("doi")),
        "venue": clean_text(reference.get("venue")),
        "pages": clean_text(reference.get("pages")),
        "extra": {
            "id": clean_text(reference.get("id")),
            "identifiers": reference.get("identifiers") or {},
        },
    }


def normalize_refextract_reference(
    reference: Dict[str, Any], *, index: int
) -> Dict[str, Any]:
    return {
        "source": "refextract",
        "index": index + 1,
        "raw": clean_text(reference.get("raw_input")),
        "title": clean_text(reference.get("title")),
        "authors": normalize_author_list(reference.get("authors")),
        "year": coerce_year(reference.get("year")),
        "doi": normalize_doi_or_none(reference.get("doi")),
        "venue": clean_text(reference.get("venue")),
        "pages": clean_text(reference.get("pages")),
        "extra": {
            "type": clean_text(reference.get("type")),
            "identifiers": reference.get("identifiers") or {},
            "warnings": [
                clean_text(item)
                for item in (reference.get("warnings") or [])
                if clean_text(item)
            ],
            "confidence": reference.get("confidence"),
        },
    }


def normalize_crossref_reference(
    reference: Dict[str, Any], *, index: int
) -> Dict[str, Any]:
    raw = clean_text(reference.get("unstructured"))
    title = first_text(
        reference.get("article-title"),
        reference.get("volume-title"),
        reference.get("series-title"),
    )
    author = clean_text(reference.get("author"))
    return {
        "source": "crossref",
        "index": index + 1,
        "raw": raw,
        "title": title,
        "authors": [author] if author else [],
        "year": coerce_year(reference.get("year")),
        "doi": normalize_doi_or_none(reference.get("DOI") or reference.get("doi")),
        "venue": first_text(
            reference.get("journal-title"), reference.get("series-title")
        ),
        "pages": first_text(reference.get("first-page"), reference.get("page")),
        "extra": {
            "volume": clean_text(reference.get("volume")),
            "issue": clean_text(reference.get("issue")),
            "key": clean_text(reference.get("key")),
        },
    }


def normalize_semantic_scholar_reference(
    reference: Dict[str, Any], *, index: int
) -> Dict[str, Any]:
    external_ids = reference.get("externalIds") or {}
    return {
        "source": "semantic_scholar",
        "index": index + 1,
        "raw": None,
        "title": clean_text(reference.get("title")),
        "authors": normalize_author_list(reference.get("authors")),
        "year": coerce_year(reference.get("year")),
        "doi": normalize_doi_or_none(external_ids.get("DOI")),
        "venue": clean_text(reference.get("venue")),
        "pages": None,
        "extra": {
            "externalIds": external_ids,
            "url": clean_text(reference.get("url")),
        },
    }


def build_unified_counts(
    *,
    paper_identity: Dict[str, Any],
    source_payloads: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    doi_available = bool(paper_identity.get("paper_doi"))
    counts: List[Dict[str, Any]] = []
    for source in SOURCE_ORDER:
        payload = source_payloads.get(source) or {}
        references = payload.get("references") or []
        notes = [
            clean_text(item)
            for item in (payload.get("notes") or [])
            if clean_text(item)
        ]
        counts.append(
            {
                "source": source,
                "status": clean_text(payload.get("status")) or "skipped",
                "total_references": len(references),
                "notes": notes,
                "doi_available": doi_available,
                "paper_doi": paper_identity.get("paper_doi"),
                "doi_source": paper_identity.get("doi_source"),
            }
        )
    return counts


def _fetch_crossref_artifacts(
    doi: Optional[str],
    *,
    timeout: int,
    output_dir: Path,
) -> Dict[str, Any]:
    session = build_external_api_session()
    notes: List[str] = []
    work_payload: Dict[str, Any] = {}
    raw_references: List[Dict[str, Any]] = []
    normalized_references: List[Dict[str, Any]] = []

    if not doi:
        notes.append("Skipped: no paper DOI available.")
        _write_json(output_dir / "crossref_work.json", work_payload)
        _write_json(output_dir / "crossref_references.json", raw_references)
        _write_json(
            output_dir / "crossref_notes.json",
            {"status": "skipped", "doi": None, "reference_count": 0, "notes": notes},
        )
        return {
            "status": "skipped",
            "references": normalized_references,
            "notes": notes,
        }

    url = f"{CROSSREF_API_BASE}/works/{quote(doi, safe='')}"
    try:
        response = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        _write_json(output_dir / "crossref_work.json", work_payload)
        _write_json(output_dir / "crossref_references.json", raw_references)
        _write_json(
            output_dir / "crossref_error.json",
            _error_payload(exc, context={"url": url, "doi": doi}),
        )
        notes.append(f"Crossref request failed: {exc}")
        _write_json(
            output_dir / "crossref_notes.json",
            {"status": "error", "doi": doi, "reference_count": 0, "notes": notes},
        )
        return {"status": "error", "references": normalized_references, "notes": notes}

    if response.status_code != 200:
        _write_json(output_dir / "crossref_work.json", work_payload)
        _write_json(output_dir / "crossref_references.json", raw_references)
        _write_json(
            output_dir / "crossref_error.json",
            _http_error_payload(response, url=url, context={"doi": doi}),
        )
        notes.append(f"Crossref returned HTTP {response.status_code}.")
        _write_json(
            output_dir / "crossref_notes.json",
            {"status": "error", "doi": doi, "reference_count": 0, "notes": notes},
        )
        return {"status": "error", "references": normalized_references, "notes": notes}

    payload = response.json() if response.content else {}
    message = payload.get("message") if isinstance(payload, dict) else {}
    work_payload = message if isinstance(message, dict) else {}
    raw_references = [
        item for item in (work_payload.get("reference") or []) if isinstance(item, dict)
    ]
    normalized_references = [
        normalize_crossref_reference(item, index=index)
        for index, item in enumerate(raw_references)
    ]
    if not raw_references:
        notes.append("Crossref resolved the DOI but did not return a reference list.")
    else:
        notes.append(
            "Crossref references come from the work record and may omit fields for individual entries."
        )

    _write_json(output_dir / "crossref_work.json", work_payload)
    _write_json(output_dir / "crossref_references.json", raw_references)
    _write_json(
        output_dir / "crossref_notes.json",
        {
            "status": "ok",
            "doi": doi,
            "reference_count": len(raw_references),
            "notes": notes,
        },
    )
    return {
        "status": "ok",
        "references": normalized_references,
        "notes": notes,
        "work": work_payload,
    }


def _fetch_semantic_scholar_artifacts(
    doi: Optional[str],
    *,
    timeout: int,
    output_dir: Path,
) -> Dict[str, Any]:
    notes: List[str] = []
    paper_payload: Dict[str, Any] = {}
    raw_references: List[Dict[str, Any]] = []
    normalized_references: List[Dict[str, Any]] = []

    if not doi:
        notes.append("Skipped: no paper DOI available.")
        _write_json(output_dir / "semantic_scholar_paper.json", paper_payload)
        _write_json(output_dir / "semantic_scholar_references.json", raw_references)
        _write_json(
            output_dir / "semantic_scholar_notes.json",
            {"status": "skipped", "doi": None, "reference_count": 0, "notes": notes},
        )
        return {
            "status": "skipped",
            "references": normalized_references,
            "notes": notes,
        }

    url = f"{SEMANTIC_SCHOLAR_API_URL}/paper/DOI:{quote(doi, safe='')}"
    try:
        payload = get_paper_by_doi(doi, fields=build_semantic_scholar_fields())
    except SemanticScholarError as exc:
        _write_json(output_dir / "semantic_scholar_paper.json", paper_payload)
        _write_json(output_dir / "semantic_scholar_references.json", raw_references)
        _write_json(
            output_dir / "semantic_scholar_error.json",
            _error_payload(exc, context={"url": url, "doi": doi}),
        )
        notes.append(f"Semantic Scholar request failed: {exc}")
        _write_json(
            output_dir / "semantic_scholar_notes.json",
            {"status": "error", "doi": doi, "reference_count": 0, "notes": notes},
        )
        return {"status": "error", "references": normalized_references, "notes": notes}

    if not isinstance(payload, dict):
        _write_json(output_dir / "semantic_scholar_paper.json", paper_payload)
        _write_json(output_dir / "semantic_scholar_references.json", raw_references)
        _write_json(
            output_dir / "semantic_scholar_error.json",
            {
                "status": "error",
                "error_type": "invalid_response",
                "error": "Semantic Scholar did not return a JSON object.",
                "context": {"url": url, "doi": doi},
            },
        )
        notes.append("Semantic Scholar returned an invalid response.")
        _write_json(
            output_dir / "semantic_scholar_notes.json",
            {"status": "error", "doi": doi, "reference_count": 0, "notes": notes},
        )
        return {"status": "error", "references": normalized_references, "notes": notes}

    paper_payload = payload if isinstance(payload, dict) else {}
    raw_references = [
        item
        for item in (paper_payload.get("references") or [])
        if isinstance(item, dict)
    ]
    normalized_references = [
        normalize_semantic_scholar_reference(item, index=index)
        for index, item in enumerate(raw_references)
    ]
    if not raw_references:
        notes.append("Semantic Scholar resolved the DOI but did not return references.")
    else:
        notes.append(
            "Semantic Scholar references come from the Graph paper record, not citing papers."
        )

    _write_json(output_dir / "semantic_scholar_paper.json", paper_payload)
    _write_json(output_dir / "semantic_scholar_references.json", raw_references)
    _write_json(
        output_dir / "semantic_scholar_notes.json",
        {
            "status": "ok",
            "doi": doi,
            "reference_count": len(raw_references),
            "notes": notes,
        },
    )
    return {
        "status": "ok",
        "references": normalized_references,
        "notes": notes,
        "paper": paper_payload,
    }


def _empty_source_payload(*, status: str, notes: Iterable[str]) -> Dict[str, Any]:
    return {
        "status": status,
        "references": [],
        "notes": [clean_text(item) for item in notes if clean_text(item)],
    }


def run_inspection(
    *,
    pdf_path: Path,
    out_root: Path,
    grobid_base_url: str,
    timeout: int,
) -> Dict[str, Any]:
    output_dir = (out_root / pdf_path.stem).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_payloads: Dict[str, Dict[str, Any]] = {}

    health = _collect_grobid_health(grobid_base_url, timeout)
    _write_json(output_dir / "health.json", health)
    grobid_ready = bool(health.get("summary", {}).get("ready"))

    common_input: Optional[Dict[str, Any]] = None
    try:
        common_input = build_common_input(pdf_path)
        raw_references = common_input.get("raw_references") or []
        _write_json(output_dir / "common_input.json", common_input)
        _write_json(output_dir / "extractor_raw_references.json", raw_references)
        _write_json(
            output_dir / "extractor_stats.json",
            common_input.get("extractor_stats") or {},
        )
        _write_json(
            output_dir / "extractor_warnings.json", common_input.get("warnings") or []
        )
        source_payloads["extractor"] = {
            "status": "ok",
            "references": [
                normalize_extractor_reference(item, index=index)
                for index, item in enumerate(raw_references)
                if isinstance(item, dict)
            ],
            "notes": [
                clean_text(item)
                for item in (common_input.get("warnings") or [])
                if clean_text(item)
            ],
        }
    except Exception as exc:
        _write_json(
            output_dir / "common_input_error.json",
            _error_payload(exc, context={"pdf_path": str(pdf_path.resolve())}),
        )
        source_payloads["extractor"] = _empty_source_payload(
            status="error",
            notes=[f"common_input failed: {exc}"],
        )

    extractor_candidate = collect_extractor_paper_candidate(pdf_path, common_input)

    if grobid_ready:
        try:
            tei_xml = process_references(
                pdf_path,
                base_url=grobid_base_url,
                timeout=timeout,
            )
            parsed = parse_references_tei(tei_xml, include_raw_citation=True)
            _write_text(output_dir / "grobid_processReferences.xml", tei_xml)
            _write_json(output_dir / "grobid_processReferences_parsed.json", parsed)
            source_payloads["grobid_processReferences"] = {
                "status": "ok",
                "references": [
                    normalize_grobid_reference(item, index=index)
                    for index, item in enumerate(parsed.get("references") or [])
                    if isinstance(item, dict)
                ],
                "notes": [
                    clean_text(item)
                    for item in (parsed.get("_warnings") or [])
                    if clean_text(item)
                ],
            }
        except Exception as exc:
            _write_json(
                output_dir / "grobid_processReferences_error.json",
                _error_payload(exc, context={"endpoint": "/api/processReferences"}),
            )
            source_payloads["grobid_processReferences"] = _empty_source_payload(
                status="error",
                notes=[f"GROBID processReferences failed: {exc}"],
            )
    else:
        reason = str(
            health.get("summary", {}).get("ready_detail") or "GROBID is not ready"
        )
        _write_json(
            output_dir / "grobid_processReferences_error.json",
            {
                "status": "skipped",
                "error_type": "grobid_unavailable",
                "error": "grobid_not_ready",
                "detail": reason,
            },
        )
        source_payloads["grobid_processReferences"] = _empty_source_payload(
            status="skipped",
            notes=[f"GROBID skipped: {reason}"],
        )

    grobid_candidate = collect_grobid_paper_candidate(
        pdf_path,
        grobid_ready=grobid_ready,
        grobid_base_url=grobid_base_url,
        timeout=timeout,
    )
    paper_identity = resolve_paper_identity(
        pdf_name=pdf_path.name,
        extractor_candidate=extractor_candidate,
        grobid_candidate=grobid_candidate,
    )
    _write_json(output_dir / "paper_identity.json", paper_identity)

    if common_input:
        try:
            refextract_output = run_refextract_parser(common_input)
            entries = [
                item
                for item in (refextract_output.get("entries") or [])
                if isinstance(item, dict)
            ]
            refextract_notes = [
                clean_text(item)
                for item in (refextract_output.get("notes") or [])
                if clean_text(item)
            ]
            _write_json(output_dir / "refextract_raw.json", refextract_output)
            _write_json(output_dir / "refextract_entries.json", entries)
            _write_json(
                output_dir / "refextract_notes.json",
                {
                    "status": clean_text(refextract_output.get("status")) or "unknown",
                    "availability": refextract_output.get("availability") or {},
                    "notes": refextract_notes,
                },
            )
            status = "ok" if refextract_output.get("status") == "ok" else "error"
            if status != "ok":
                _write_json(
                    output_dir / "refextract_error.json",
                    {
                        "status": "error",
                        "error_type": "refextract_not_ok",
                        "error": "run_refextract_parser returned non-ok status",
                        "result_status": refextract_output.get("status"),
                        "availability": refextract_output.get("availability") or {},
                        "notes": refextract_notes,
                    },
                )
            source_payloads["refextract"] = {
                "status": status,
                "references": [
                    normalize_refextract_reference(item, index=index)
                    for index, item in enumerate(entries)
                ],
                "notes": refextract_notes,
            }
        except Exception as exc:
            _write_json(output_dir / "refextract_raw.json", {})
            _write_json(output_dir / "refextract_entries.json", [])
            _write_json(
                output_dir / "refextract_notes.json",
                {"status": "error", "notes": ["Refextract execution failed."]},
            )
            _write_json(output_dir / "refextract_error.json", _error_payload(exc))
            source_payloads["refextract"] = _empty_source_payload(
                status="error",
                notes=[f"Refextract failed: {exc}"],
            )
    else:
        _write_json(output_dir / "refextract_raw.json", {})
        _write_json(output_dir / "refextract_entries.json", [])
        _write_json(
            output_dir / "refextract_notes.json",
            {
                "status": "error",
                "notes": ["Refextract skipped because common_input is unavailable."],
            },
        )
        _write_json(
            output_dir / "refextract_error.json",
            {
                "status": "error",
                "error_type": "missing_common_input",
                "error": "common_input unavailable; cannot run refextract",
            },
        )
        source_payloads["refextract"] = _empty_source_payload(
            status="error",
            notes=["Refextract skipped because common_input is unavailable."],
        )

    paper_doi = paper_identity.get("paper_doi")
    crossref_payload = _fetch_crossref_artifacts(
        paper_doi,
        timeout=timeout,
        output_dir=output_dir,
    )
    source_payloads["crossref"] = {
        "status": clean_text(crossref_payload.get("status")) or "skipped",
        "references": crossref_payload.get("references") or [],
        "notes": crossref_payload.get("notes") or [],
    }

    semantic_payload = _fetch_semantic_scholar_artifacts(
        paper_doi,
        timeout=timeout,
        output_dir=output_dir,
    )
    source_payloads["semantic_scholar"] = {
        "status": clean_text(semantic_payload.get("status")) or "skipped",
        "references": semantic_payload.get("references") or [],
        "notes": semantic_payload.get("notes") or [],
    }

    unified_references: List[Dict[str, Any]] = []
    for source in SOURCE_ORDER:
        unified_references.extend(
            source_payloads.get(source, {}).get("references") or []
        )
    _write_json(output_dir / "unified_references.json", unified_references)

    unified_counts = build_unified_counts(
        paper_identity=paper_identity,
        source_payloads=source_payloads,
    )
    _write_json(output_dir / "unified_counts.json", unified_counts)

    summary = {
        "created_at": datetime.now().isoformat(),
        "pdf_path": str(pdf_path.resolve()),
        "pdf_name": pdf_path.name,
        "output_dir": str(output_dir),
        "grobid_base_url": grobid_base_url.rstrip("/"),
        "timeout_seconds": timeout,
        "paper_title": paper_identity.get("paper_title"),
        "paper_doi": paper_identity.get("paper_doi"),
        "doi_source": paper_identity.get("doi_source"),
        "source_statuses": {
            source: (source_payloads.get(source) or {}).get("status")
            for source in SOURCE_ORDER
        },
        "reference_counts": {
            source: len((source_payloads.get(source) or {}).get("references") or [])
            for source in SOURCE_ORDER
        },
        "files_generated": _list_output_files(output_dir),
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and compare reference sources for a single PDF."
    )
    parser.add_argument(
        "pdf_path",
        help="Absolute or relative path to a single PDF file.",
    )
    parser.add_argument(
        "--out",
        default="tmp/reference_source_inspection",
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
        help="Timeout in seconds for HTTP requests.",
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
    if summary.get("paper_title"):
        print(f"Title: {summary['paper_title']}")
    print(f"DOI for external APIs: {summary.get('paper_doi') or 'None'}")
    for source in SOURCE_ORDER:
        status = summary["source_statuses"].get(source)
        count = summary["reference_counts"].get(source, 0)
        print(f"{source}: {count} references ({status})")
    print(f"Output: {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# Compares PDF citation/reference extraction engines and exports graph-ready CSVs.
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
DEFAULT_OUTPUT_ROOT = ROOT / "tmp" / "pdf_model_comparison"


def _load_env_file(env_path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(dotenv_path=env_path, override=False)


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_load_env_file(PROJECT_ROOT / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / ".cache" / "transformers"))

import django  # noqa: E402
from django.apps import apps  # noqa: E402

if not apps.ready:
    django.setup()

from citations.services.ai_extractor import AI_ENGINES, extract_with_ai  # noqa: E402
from citations.services.citation_extractor import process_manuscript  # noqa: E402
from citations.services.engines import (  # noqa: E402
    ALLOWED_ENGINES,
    list_extractor_engines,
)
from citations.services.reader_data import extract_pdf_references  # noqa: E402
from citations.services.semantic_scholar_client import (  # noqa: E402
    SemanticScholarError,
    get_work_by_doi,
)


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")
MANIFEST_PDF_KEYS = ("pdf", "path", "pdf_path", "file", "filename")
MANIFEST_DOI_KEYS = ("doi", "article_doi", "paper_doi")
MANIFEST_ID_KEYS = ("id", "paper_id", "name", "key")
ENGINE_METRIC_FIELDS = [
    "paper_id",
    "pdf",
    "doi",
    "engine",
    "engine_effective",
    "ok",
    "error",
    "time_ms",
    "references_total",
    "contexts_total",
    "dois_total",
    "extracted_reference_dois_total",
    "semantic_references_total",
    "semantic_reference_dois_total",
    "matched_reference_dois",
    "extra_semantic_reference_dois",
    "references_delta_vs_semantic",
    "semantic_reference_doi_coverage_pct",
    "extracted_reference_doi_coverage_pct",
]
PAIRWISE_FIELDS = [
    "paper_id",
    "pdf",
    "doi",
    "engine_a",
    "engine_b",
    "engine_a_ok",
    "engine_b_ok",
    "engine_a_references_total",
    "engine_b_references_total",
    "references_total_delta",
    "engine_a_contexts_total",
    "engine_b_contexts_total",
    "contexts_total_delta",
    "engine_a_reference_dois_total",
    "engine_b_reference_dois_total",
    "matched_reference_dois",
    "reference_doi_union_total",
    "reference_doi_jaccard_pct",
]
REFERENCE_FIELDS = [
    "paper_id",
    "pdf",
    "article_doi",
    "source",
    "engine",
    "reference_index",
    "reference_doi",
    "title",
    "year",
    "venue",
    "text",
]


@dataclass(frozen=True)
class PaperInput:
    paper_id: str
    pdf_path: Path
    doi: str = ""


def _safe_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _round_pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((float(part) / float(total)) * 100.0, 2)


def normalize_doi(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^doi:\s*", "", raw, flags=re.IGNORECASE)
    match = DOI_RE.search(raw)
    candidate = match.group(0) if match else raw
    if not candidate.lower().startswith("10."):
        return ""
    return candidate.strip().rstrip(".,;)").lower()


def _safe_id(value: Any, fallback: str = "paper") -> str:
    cleaned = SAFE_ID_RE.sub("_", str(value or "").strip()).strip("._-")
    return cleaned or fallback


def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _entry_value(entry: Dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""


def _unique_paper_inputs(papers: Iterable[PaperInput]) -> List[PaperInput]:
    seen: Dict[str, int] = {}
    unique: List[PaperInput] = []
    for paper in papers:
        base_id = _safe_id(paper.paper_id, paper.pdf_path.stem)
        count = seen.get(base_id, 0) + 1
        seen[base_id] = count
        paper_id = base_id if count == 1 else f"{base_id}_{count}"
        unique.append(PaperInput(paper_id=paper_id, pdf_path=paper.pdf_path, doi=paper.doi))
    return unique


def _resolve_manifest_pdf(value: str, base_dir: Path) -> Path:
    if not value:
        raise ValueError("Manifest row without pdf/path column.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Manifest entry is not a PDF: {path}")
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    return path


def _paper_from_manifest_entry(entry: Dict[str, Any], base_dir: Path) -> PaperInput:
    pdf_path = _resolve_manifest_pdf(_entry_value(entry, MANIFEST_PDF_KEYS), base_dir)
    paper_id = _entry_value(entry, MANIFEST_ID_KEYS) or pdf_path.stem
    doi = normalize_doi(_entry_value(entry, MANIFEST_DOI_KEYS))
    return PaperInput(paper_id=_safe_id(paper_id, pdf_path.stem), pdf_path=pdf_path, doi=doi)


def _load_csv_manifest(path: Path) -> List[PaperInput]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV manifest has no header: {path}")
        entries = [dict(row) for row in reader]
    return [_paper_from_manifest_entry(entry, path.parent) for entry in entries]


def _load_json_manifest(path: Path) -> List[PaperInput]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        entries = payload.get("papers") or payload.get("items") or payload.get("documents")
    else:
        entries = payload
    if not isinstance(entries, list):
        raise ValueError("JSON manifest must be a list or contain papers/items/documents.")
    return [
        _paper_from_manifest_entry(entry, path.parent)
        for entry in entries
        if isinstance(entry, dict)
    ]


def _load_text_manifest(path: Path) -> List[PaperInput]:
    papers: List[PaperInput] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        for index, row in enumerate(reader, start=1):
            if not row:
                continue
            pdf_path = _resolve_manifest_pdf(str(row[0] or "").strip(), path.parent)
            doi = normalize_doi(row[1] if len(row) > 1 else "")
            paper_id = _safe_id(row[2] if len(row) > 2 else pdf_path.stem, pdf_path.stem)
            papers.append(PaperInput(paper_id=paper_id, pdf_path=pdf_path, doi=doi))
    return papers


def collect_paper_inputs(input_source: Path | str) -> List[PaperInput]:
    source = Path(input_source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Input source not found: {source}")

    if source.is_dir():
        papers = [
            PaperInput(paper_id=_safe_id(path.stem), pdf_path=path.resolve(), doi="")
            for path in sorted(source.rglob("*.pdf"), key=lambda item: str(item).lower())
        ]
        return _unique_paper_inputs(papers)

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return [PaperInput(paper_id=_safe_id(source.stem), pdf_path=source, doi="")]
    if suffix == ".csv":
        return _unique_paper_inputs(_load_csv_manifest(source))
    if suffix == ".json":
        return _unique_paper_inputs(_load_json_manifest(source))
    if suffix in {".txt", ".list"}:
        return _unique_paper_inputs(_load_text_manifest(source))
    raise ValueError("Input must be a PDF, directory, or CSV/JSON/TXT manifest.")


def resolve_engines(raw_engines: str | Sequence[str] | None = None) -> List[str]:
    if raw_engines is None or raw_engines == "auto":
        available = [
            str(item.get("key"))
            for item in list_extractor_engines()
            if item.get("available") and item.get("key") in ALLOWED_ENGINES
        ]
        return available or ["papermage"]

    if isinstance(raw_engines, str):
        if raw_engines.strip().lower() == "all":
            candidates = sorted(ALLOWED_ENGINES)
        else:
            candidates = [
                item.strip()
                for chunk in raw_engines.split()
                for item in chunk.split(",")
                if item.strip()
            ]
    else:
        candidates = [str(item).strip() for item in raw_engines if str(item).strip()]

    engines: List[str] = []
    seen: set[str] = set()
    for engine in candidates:
        if engine not in ALLOWED_ENGINES:
            raise ValueError(
                f"Unsupported engine '{engine}'. Valid engines: {', '.join(sorted(ALLOWED_ENGINES))}"
            )
        if engine not in seen:
            engines.append(engine)
            seen.add(engine)
    if not engines:
        raise ValueError("At least one engine is required.")
    return engines


def _resolve_reference_context(
    references: Sequence[Dict[str, Any]],
    ref_stats: Dict[str, Any],
) -> Dict[str, Any]:
    citation_style = (
        str(
            ref_stats.get("citation_style")
            or ("numeric" if ref_stats.get("references_numbered") else "non_numeric")
        )
        .strip()
        .lower()
    )
    if citation_style == "non-numeric":
        citation_style = "non_numeric"
    if citation_style not in {"numeric", "non_numeric"}:
        citation_style = "numeric" if ref_stats.get("references_numbered") else "non_numeric"

    max_reference_index = _safe_int(ref_stats.get("max_reference_index"))
    if max_reference_index is None or max_reference_index <= 0:
        max_reference_index = _safe_int(ref_stats.get("references_total")) or len(references)

    total_references_for_validation = (
        max_reference_index if citation_style == "numeric" else len(references)
    )
    return {
        "citation_style": citation_style,
        "max_reference_index": max_reference_index,
        "total_references_for_validation": total_references_for_validation,
    }


def _build_ai_reference_stats(
    ai_result: Dict[str, Any],
    references: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    references_numbered = bool(ai_result.get("references_numbered"))
    citation_style = (
        str(
            ai_result.get("citation_style")
            or ("numeric" if references_numbered else "non_numeric")
        )
        .strip()
        .lower()
    )
    if citation_style == "non-numeric":
        citation_style = "non_numeric"
    if citation_style not in {"numeric", "non_numeric"}:
        citation_style = "numeric" if references_numbered else "non_numeric"

    max_reference_index = _safe_int(ai_result.get("max_reference_index"))
    if max_reference_index is None or max_reference_index <= 0:
        max_reference_index = max(
            (_safe_int(item.get("index")) or 0 for item in references),
            default=0,
        )
    if max_reference_index <= 0:
        max_reference_index = len(references)

    return {
        "pages_total": _safe_int(ai_result.get("pages_total")) or 0,
        "references_total": len(references),
        "dois_total": sum(1 for item in references if normalize_doi(item.get("doi"))),
        "references_numbered": references_numbered,
        "citation_style": citation_style,
        "max_reference_index": max_reference_index,
        "bibliography_start_page": None,
        "reference_source": "ai_extractor",
    }


def run_extraction_engine(pdf_path: Path, engine: str) -> Dict[str, Any]:
    started_at = time.perf_counter()
    try:
        if engine in AI_ENGINES:
            ai_result = extract_with_ai(engine, str(pdf_path))
            if not ai_result.get("ok", False):
                raise RuntimeError(str(ai_result.get("error") or "AI extraction failed"))
            references = _coerce_dict_list(ai_result.get("references"))
            contexts = _coerce_dict_list(ai_result.get("results") or ai_result.get("citation_contexts"))
            reference_stats = _build_ai_reference_stats(ai_result, references)
            engine_effective = str(ai_result.get("engine_used") or engine)
        else:
            references, reference_stats = extract_pdf_references(str(pdf_path))
            references = _coerce_dict_list(references)
            reference_context = _resolve_reference_context(references, reference_stats)
            manuscript_data = process_manuscript(
                str(pdf_path),
                engine=engine,
                debug=False,
                references=references,
                citation_style=reference_context["citation_style"],
                total_references=reference_context["total_references_for_validation"],
            )
            if not manuscript_data.get("ok", False):
                raise RuntimeError(str(manuscript_data.get("error") or "extraction failed"))
            contexts = _coerce_dict_list(manuscript_data.get("results"))
            engine_effective = str(manuscript_data.get("engine_used") or engine)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "ok": True,
            "error": "",
            "engine_requested": engine,
            "engine_effective": engine_effective,
            "time_ms": elapsed_ms,
            "references": references,
            "contexts": contexts,
            "reference_stats": reference_stats,
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "engine_requested": engine,
            "engine_effective": "",
            "time_ms": elapsed_ms,
            "references": [],
            "contexts": [],
            "reference_stats": {},
        }


def fetch_semantic_scholar_work(doi: str, timeout: int = 20) -> Dict[str, Any]:
    normalized = normalize_doi(doi)
    if not normalized:
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_doi",
            "references_total": 0,
            "citations_total": 0,
            "work": None,
        }
    try:
        work = get_work_by_doi(normalized, timeout=timeout)
    except SemanticScholarError as exc:
        return {
            "ok": False,
            "skipped": False,
            "error": str(exc),
            "references_total": 0,
            "citations_total": 0,
            "work": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "error": f"{type(exc).__name__}: {exc}",
            "references_total": 0,
            "citations_total": 0,
            "work": None,
        }

    if not isinstance(work, dict):
        return {
            "ok": False,
            "skipped": False,
            "found": False,
            "reason": "not_found",
            "references_total": 0,
            "citations_total": 0,
            "work": None,
        }

    references = _coerce_dict_list(work.get("references"))
    citations = _coerce_dict_list(work.get("citations"))
    return {
        "ok": True,
        "skipped": False,
        "found": True,
        "references_total": len(references),
        "citations_total": len(citations),
        "work": work,
    }


def _reference_text(reference: Dict[str, Any]) -> str:
    for key in ("raw", "text", "label", "title"):
        value = str(reference.get(key) or "").strip()
        if value:
            return re.sub(r"\s+", " ", value)
    return ""


def _reference_title(reference: Dict[str, Any]) -> str:
    title = str(reference.get("title") or "").strip()
    if title:
        return re.sub(r"\s+", " ", title)
    return ""


def _reference_index(reference: Dict[str, Any]) -> str:
    for key in ("index", "ref_index", "number"):
        parsed = _safe_int(reference.get(key))
        if parsed is not None and parsed > 0:
            return str(parsed)
    return ""


def _reference_dois(references: Sequence[Dict[str, Any]]) -> List[str]:
    dois: List[str] = []
    for reference in references:
        doi = normalize_doi(reference.get("doi"))
        if not doi:
            doi = normalize_doi(_reference_text(reference))
        if doi:
            dois.append(doi)
    return dois


def build_engine_metrics(
    *,
    paper_id: str,
    pdf_name: str,
    doi: str,
    engine: str,
    engine_result: Dict[str, Any],
    semantic_work: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    references = _coerce_dict_list(engine_result.get("references"))
    contexts = _coerce_dict_list(engine_result.get("contexts"))
    reference_dois = _reference_dois(references)
    reference_doi_set = set(reference_dois)

    semantic_references = (
        _coerce_dict_list(semantic_work.get("references")) if isinstance(semantic_work, dict) else []
    )
    semantic_doi_set = set(_reference_dois(semantic_references))
    matched_dois = reference_doi_set & semantic_doi_set

    references_total = len(references)
    semantic_references_total = len(semantic_references)
    return {
        "paper_id": paper_id,
        "pdf": pdf_name,
        "doi": normalize_doi(doi),
        "engine": engine,
        "engine_effective": str(engine_result.get("engine_effective") or ""),
        "ok": bool(engine_result.get("ok")),
        "error": str(engine_result.get("error") or ""),
        "time_ms": int(engine_result.get("time_ms") or 0),
        "references_total": references_total,
        "contexts_total": len(contexts),
        "dois_total": sum(1 for item in reference_dois if item),
        "extracted_reference_dois_total": len(reference_doi_set),
        "semantic_references_total": semantic_references_total,
        "semantic_reference_dois_total": len(semantic_doi_set),
        "matched_reference_dois": len(matched_dois),
        "extra_semantic_reference_dois": len(semantic_doi_set - reference_doi_set),
        "references_delta_vs_semantic": references_total - semantic_references_total,
        "semantic_reference_doi_coverage_pct": _round_pct(
            len(matched_dois),
            len(semantic_doi_set),
        ),
        "extracted_reference_doi_coverage_pct": _round_pct(
            len(matched_dois),
            len(reference_doi_set),
        ),
    }


def _build_pairwise_rows(paper: Dict[str, Any], engines: Sequence[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    engine_payloads = paper.get("engines") if isinstance(paper.get("engines"), dict) else {}
    for left_index, engine_a in enumerate(engines):
        result_a = engine_payloads.get(engine_a) or {}
        refs_a = _coerce_dict_list(result_a.get("references"))
        contexts_a = _coerce_dict_list(result_a.get("contexts"))
        dois_a = set(_reference_dois(refs_a))
        for engine_b in engines[left_index + 1 :]:
            result_b = engine_payloads.get(engine_b) or {}
            refs_b = _coerce_dict_list(result_b.get("references"))
            contexts_b = _coerce_dict_list(result_b.get("contexts"))
            dois_b = set(_reference_dois(refs_b))
            union = dois_a | dois_b
            matched = dois_a & dois_b
            rows.append(
                {
                    "paper_id": paper.get("paper_id") or "",
                    "pdf": paper.get("pdf") or "",
                    "doi": normalize_doi(paper.get("doi")),
                    "engine_a": engine_a,
                    "engine_b": engine_b,
                    "engine_a_ok": bool(result_a.get("ok")),
                    "engine_b_ok": bool(result_b.get("ok")),
                    "engine_a_references_total": len(refs_a),
                    "engine_b_references_total": len(refs_b),
                    "references_total_delta": len(refs_a) - len(refs_b),
                    "engine_a_contexts_total": len(contexts_a),
                    "engine_b_contexts_total": len(contexts_b),
                    "contexts_total_delta": len(contexts_a) - len(contexts_b),
                    "engine_a_reference_dois_total": len(dois_a),
                    "engine_b_reference_dois_total": len(dois_b),
                    "matched_reference_dois": len(matched),
                    "reference_doi_union_total": len(union),
                    "reference_doi_jaccard_pct": _round_pct(len(matched), len(union)),
                }
            )
    return rows


def _reference_rows_for_source(
    *,
    paper: Dict[str, Any],
    source: str,
    engine: str,
    references: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for reference in references:
        rows.append(
            {
                "paper_id": paper.get("paper_id") or "",
                "pdf": paper.get("pdf") or "",
                "article_doi": normalize_doi(paper.get("doi")),
                "source": source,
                "engine": engine,
                "reference_index": _reference_index(reference),
                "reference_doi": normalize_doi(reference.get("doi")) or normalize_doi(_reference_text(reference)),
                "title": _reference_title(reference),
                "year": str(reference.get("year") or "").strip(),
                "venue": str(reference.get("venue") or "").strip(),
                "text": _reference_text(reference),
            }
        )
    return rows


def _build_reference_rows(papers: Sequence[Dict[str, Any]], engines: Sequence[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for paper in papers:
        engine_payloads = paper.get("engines") if isinstance(paper.get("engines"), dict) else {}
        for engine in engines:
            result = engine_payloads.get(engine) or {}
            rows.extend(
                _reference_rows_for_source(
                    paper=paper,
                    source="extracted",
                    engine=engine,
                    references=_coerce_dict_list(result.get("references")),
                )
            )
        semantic_payload = paper.get("semantic_scholar")
        semantic_work = (
            semantic_payload.get("work")
            if isinstance(semantic_payload, dict) and isinstance(semantic_payload.get("work"), dict)
            else None
        )
        if semantic_work:
            rows.extend(
                _reference_rows_for_source(
                    paper=paper,
                    source="semantic_scholar",
                    engine="semantic_scholar",
                    references=_coerce_dict_list(semantic_work.get("references")),
                )
            )
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _compact_engine_summary(engine_result: Dict[str, Any]) -> Dict[str, Any]:
    references = _coerce_dict_list(engine_result.get("references"))
    contexts = _coerce_dict_list(engine_result.get("contexts"))
    return {
        "ok": bool(engine_result.get("ok")),
        "error": str(engine_result.get("error") or ""),
        "engine_effective": str(engine_result.get("engine_effective") or ""),
        "time_ms": int(engine_result.get("time_ms") or 0),
        "references_total": len(references),
        "contexts_total": len(contexts),
        "reference_dois_total": len(set(_reference_dois(references))),
    }


def _compact_semantic_summary(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"ok": False, "skipped": True, "references_total": 0, "citations_total": 0}
    summary = {
        "ok": bool(payload.get("ok")),
        "skipped": bool(payload.get("skipped")),
        "found": bool(payload.get("found")),
        "references_total": int(payload.get("references_total") or 0),
        "citations_total": int(payload.get("citations_total") or 0),
    }
    if payload.get("error"):
        summary["error"] = str(payload.get("error"))
    if payload.get("reason"):
        summary["reason"] = str(payload.get("reason"))
    return summary


def write_outputs(
    *,
    output_dir: Path,
    papers: Sequence[Dict[str, Any]],
    engines: Sequence[str],
    input_source: str,
) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    metric_rows: List[Dict[str, Any]] = []
    pairwise_rows: List[Dict[str, Any]] = []
    for paper in papers:
        semantic_payload = paper.get("semantic_scholar")
        semantic_work = (
            semantic_payload.get("work")
            if isinstance(semantic_payload, dict) and isinstance(semantic_payload.get("work"), dict)
            else None
        )
        engine_payloads = paper.get("engines") if isinstance(paper.get("engines"), dict) else {}
        for engine in engines:
            metric_rows.append(
                build_engine_metrics(
                    paper_id=str(paper.get("paper_id") or ""),
                    pdf_name=str(paper.get("pdf") or ""),
                    doi=str(paper.get("doi") or ""),
                    engine=engine,
                    engine_result=engine_payloads.get(engine) or {},
                    semantic_work=semantic_work,
                )
            )
        pairwise_rows.extend(_build_pairwise_rows(paper, engines))

    reference_rows = _build_reference_rows(papers, engines)
    engine_runs_ok = sum(1 for row in metric_rows if bool(row.get("ok")))
    summary = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_source": input_source,
            "engines": list(engines),
        },
        "aggregate": {
            "papers_total": len(papers),
            "engine_runs_total": len(metric_rows),
            "engine_runs_ok": engine_runs_ok,
            "engine_runs_failed": len(metric_rows) - engine_runs_ok,
            "semantic_scholar_queries_ok": sum(
                1
                for paper in papers
                if isinstance(paper.get("semantic_scholar"), dict)
                and bool(paper["semantic_scholar"].get("ok"))
            ),
            "semantic_scholar_references_total": sum(
                int((paper.get("semantic_scholar") or {}).get("references_total") or 0)
                for paper in papers
                if isinstance(paper.get("semantic_scholar"), dict)
            ),
        },
        "papers": [
            {
                "paper_id": paper.get("paper_id") or "",
                "pdf": paper.get("pdf") or "",
                "doi": normalize_doi(paper.get("doi")),
                "semantic_scholar": _compact_semantic_summary(paper.get("semantic_scholar")),
                "engines": {
                    engine: _compact_engine_summary((paper.get("engines") or {}).get(engine) or {})
                    for engine in engines
                },
            }
            for paper in papers
        ],
        "artifacts": {
            "engine_metrics_csv": "engine_metrics.csv",
            "engine_pair_metrics_csv": "engine_pair_metrics.csv",
            "references_by_engine_csv": "references_by_engine.csv",
            "raw_results_json": "raw_results.json",
        },
    }

    summary_path = output_dir / "summary.json"
    raw_path = output_dir / "raw_results.json"
    engine_metrics_path = output_dir / "engine_metrics.csv"
    pairwise_path = output_dir / "engine_pair_metrics.csv"
    references_path = output_dir / "references_by_engine.csv"

    _write_json(summary_path, summary)
    _write_json(raw_path, {"papers": papers})
    _write_csv(engine_metrics_path, metric_rows, ENGINE_METRIC_FIELDS)
    _write_csv(pairwise_path, pairwise_rows, PAIRWISE_FIELDS)
    _write_csv(references_path, reference_rows, REFERENCE_FIELDS)

    return {
        "summary_json": str(summary_path),
        "raw_results_json": str(raw_path),
        "engine_metrics_csv": str(engine_metrics_path),
        "engine_pair_metrics_csv": str(pairwise_path),
        "references_by_engine_csv": str(references_path),
    }


def run_comparison(
    *,
    input_source: Path,
    output_dir: Path,
    engines: Sequence[str],
    use_semantic_scholar: bool = True,
    limit: Optional[int] = None,
    semantic_timeout: int = 20,
) -> Dict[str, Any]:
    paper_inputs = collect_paper_inputs(input_source)
    if limit is not None and limit >= 0:
        paper_inputs = paper_inputs[:limit]

    papers: List[Dict[str, Any]] = []
    for paper in paper_inputs:
        print(f"[paper] {paper.paper_id} ({paper.pdf_path.name})")
        paper_payload: Dict[str, Any] = {
            "paper_id": paper.paper_id,
            "pdf": paper.pdf_path.name,
            "pdf_path": str(paper.pdf_path),
            "doi": paper.doi,
            "semantic_scholar": {
                "ok": False,
                "skipped": True,
                "reason": "disabled" if not use_semantic_scholar else "missing_doi",
                "references_total": 0,
                "citations_total": 0,
                "work": None,
            },
            "engines": {},
        }
        if use_semantic_scholar and paper.doi:
            print(f"  [semantic_scholar] DOI {paper.doi}")
            paper_payload["semantic_scholar"] = fetch_semantic_scholar_work(
                paper.doi,
                timeout=semantic_timeout,
            )

        for engine in engines:
            print(f"  [engine] {engine}")
            paper_payload["engines"][engine] = run_extraction_engine(paper.pdf_path, engine)

        papers.append(paper_payload)

    artifacts = write_outputs(
        output_dir=output_dir,
        papers=papers,
        engines=engines,
        input_source=str(input_source),
    )
    summary = json.loads(Path(artifacts["summary_json"]).read_text(encoding="utf-8"))
    return {"summary": summary, "artifacts": artifacts}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compara motores de extraccion sobre PDFs y cruza referencias con "
            "Semantic Scholar cuando el manifest incluye DOI."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="PDF, carpeta de PDFs o manifest CSV/JSON/TXT con columnas pdf/path, doi e id.",
    )
    parser.add_argument(
        "--engines",
        default="auto",
        help=(
            "Motores a ejecutar: auto, all o lista separada por comas. "
            f"Disponibles: {', '.join(sorted(ALLOWED_ENGINES))}."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directorio de salida. Por defecto usa tmp/pdf_model_comparison/<timestamp>.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita el numero de PDFs procesados.",
    )
    parser.add_argument(
        "--semantic-timeout",
        type=int,
        default=20,
        help="Timeout en segundos para cada consulta a Semantic Scholar.",
    )
    semantic_group = parser.add_mutually_exclusive_group()
    semantic_group.add_argument(
        "--semantic-scholar",
        dest="semantic_scholar",
        action="store_true",
        default=True,
        help="Consulta Semantic Scholar cuando haya DOI (por defecto).",
    )
    semantic_group.add_argument(
        "--skip-semantic-scholar",
        dest="semantic_scholar",
        action="store_false",
        help="No consulta Semantic Scholar aunque haya DOI.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        engines = resolve_engines(args.engines)
    except ValueError as exc:
        parser.error(str(exc))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)
    result = run_comparison(
        input_source=args.input,
        output_dir=output_dir,
        engines=engines,
        use_semantic_scholar=bool(args.semantic_scholar),
        limit=args.limit,
        semantic_timeout=args.semantic_timeout,
    )
    aggregate = result["summary"]["aggregate"]
    print("")
    print(f"Summary JSON: {result['artifacts']['summary_json']}")
    print(f"Engine metrics CSV: {result['artifacts']['engine_metrics_csv']}")
    print(f"Pairwise metrics CSV: {result['artifacts']['engine_pair_metrics_csv']}")
    print(f"References CSV: {result['artifacts']['references_by_engine_csv']}")
    print(
        "Runs: {ok}/{total} OK across {papers} papers".format(
            ok=aggregate.get("engine_runs_ok"),
            total=aggregate.get("engine_runs_total"),
            papers=aggregate.get("papers_total"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

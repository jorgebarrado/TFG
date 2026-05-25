#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

import django  # noqa: E402

from citations.services.papermage_extractor import extract_pdf_data  # noqa: E402
from citations.services.reader_data import extract_pdf_references  # noqa: E402
from citations.services.references_data import (  # noqa: E402
    REFERENCE_NOISE_RE,
    build_references_data,
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tfg_project.settings")
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / ".cache" / "transformers"))


django.setup()


DEFAULT_PDF = (
    ROOT
    / "tfg_project/citations/static/citations/PDFs-Reales/2017-CT-development-computational-thinking_RG.pdf"
)
NOISE_LABELS = {
    "view publication stats": "view_publication_stats",
    "wipsce": "conference_header",
    "nijmegen": "conference_header",
    "brackmann, román-gonzález, robles, moreno-león, casali and barone": "author_header",
    "researchgate": "researchgate_noise",
}
NESTED_ANCHOR_RE = re.compile(r"\[\s*(\d+)\s*\]")


def detect_alerts(entry: Dict[str, Any]) -> List[str]:
    text = str(entry.get("text") or "")
    alerts: List[str] = []
    lowered = text.lower()
    for needle, label in NOISE_LABELS.items():
        if needle in lowered:
            alerts.append(label)
    if REFERENCE_NOISE_RE.search(text):
        alerts.append("noise_regex")
    entry_index = entry.get("index")
    anchor_values = {
        int(match.group(1))
        for match in NESTED_ANCHOR_RE.finditer(text)
        if match.group(1).isdigit()
    }
    foreign = sorted(
        value
        for value in anchor_values
        if entry_index is None or value != int(entry_index)
    )
    if foreign:
        alerts.append(f"nested_anchors={foreign}")
    if not text.strip():
        alerts.append("empty_text")
    return sorted(set(alerts))


def print_reference_block(entry: Dict[str, Any]) -> None:
    validation = entry.get("reference_validation") or {}
    alerts = detect_alerts(entry)
    print(f"[{entry.get('index')}]")
    print(
        "  source="
        f"{entry.get('structure_source') or '-'} "
        f"accepted={validation.get('accepted')} "
        f"reason={validation.get('reason') or '-'} "
        f"doi={entry.get('doi') or '-'}"
    )
    print(f"  alerts={alerts or ['-']}")
    print(f"  text={str(entry.get('text') or '').strip()}")


def build_payload(pdf_path: Path) -> Dict[str, Any]:
    references, stats = extract_pdf_references(str(pdf_path))
    reader = extract_pdf_data(str(pdf_path))
    references_data = build_references_data(
        references=references,
        snippets=[],
        layers=reader.get("layers", {}),
        references_numbered=bool(stats.get("references_numbered")),
    )
    return {
        "pdf_path": str(pdf_path),
        "stats": stats,
        "references": references,
        "references_data": references_data,
    }


def summarize_sources(entries: Iterable[Dict[str, Any]]) -> Counter:
    counter: Counter = Counter()
    for entry in entries:
        counter[str(entry.get("structure_source") or "unknown")] += 1
    return counter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--write-json", type=Path, default=None)
    args = parser.parse_args()

    payload = build_payload(args.pdf)
    entries = list(payload["references_data"].get("references") or [])
    source_counts = summarize_sources(entries)
    fallback_count = sum(
        1 for entry in entries if "fallback" in str(entry.get("structure_source") or "")
    )

    print(f"PDF: {args.pdf}")
    print(f"Total referencias base: {len(payload['references'])}")
    print(f"Total referencias finales: {len(entries)}")
    print(f"Fuentes: {dict(source_counts)}")
    print(f"Fallbacks: {fallback_count}")
    print()

    for entry in entries:
        print_reference_block(entry)
        print()

    if args.write_json:
        args.write_json.parent.mkdir(parents=True, exist_ok=True)
        args.write_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON escrito en: {args.write_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

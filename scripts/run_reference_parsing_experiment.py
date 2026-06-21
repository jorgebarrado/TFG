# Lanza experimentos de parsing de referencias sobre PDFs ya segmentados,
# comparando múltiples parsers (refextract, GROBID citation list, LLM…).
# Salida en tmp/reference_parser_experiments/<run-id>/.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from citations.experimental.reference_parsing_experiments import (  # noqa: E402
    DEFAULT_PDFS,
    discover_all_pdf_paths,
    run_reference_parsing_experiment,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str((ROOT / "tfg_project").resolve()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated reference parsing experiments over already segmented references."
    )
    parser.add_argument(
        "--pdf",
        action="append",
        dest="pdfs",
        help="PDF filename from tfg_project/citations/static/citations/PDFs-Reales or an absolute path. Repeat for multiple PDFs.",
    )
    parser.add_argument(
        "--all-pdfs",
        action="store_true",
        help="Run the experiment over all PDFs discovered under tfg_project/citations/static/citations/PDFs-Reales.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional run id. Defaults to a timestamp.",
    )
    parser.add_argument(
        "--output-root",
        default="tmp/reference_parser_experiments",
        help="Root directory for experiment artifacts.",
    )
    parser.add_argument(
        "--comparison-limit",
        type=int,
        default=8,
        help="How many references per paper to include in the side-by-side comparison artifact.",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4.1-mini",
        help="Model name to use when the LLM runner is executable.",
    )
    parser.add_argument(
        "--list-default-pdfs",
        action="store_true",
        help="Print the curated default PDF sample and exit.",
    )
    parser.add_argument(
        "--list-all-pdfs",
        action="store_true",
        help="Print all discovered PDFs under the fixture directory and exit.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_default_pdfs:
        print(json.dumps(DEFAULT_PDFS, indent=2, ensure_ascii=False))
        return 0

    if args.list_all_pdfs:
        print(
            json.dumps(
                [path.name for path in discover_all_pdf_paths()],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if args.all_pdfs and args.pdfs:
        parser.error("Use either --all-pdfs or --pdf, not both.")

    summary = run_reference_parsing_experiment(
        pdf_names=args.pdfs,
        all_pdfs=bool(args.all_pdfs),
        output_root=args.output_root,
        run_id=args.run_id,
        comparison_limit=args.comparison_limit,
        llm_model=args.llm_model,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Compara el detector de citas viejo vs nuevo sobre PDFs reales o texto.

Uso:
    cd tfg_project_root

    # Por defecto: corre sobre todos los PDFs en PDFs-Reales/
    python scripts/compare_citation_detectors.py

    # Sobre un PDF concreto
    python scripts/compare_citation_detectors.py path/al/paper.pdf

    # Sobre varios PDFs / .txt
    python scripts/compare_citation_detectors.py paper1.pdf paper2.pdf

    # Modo verboso: lista cada cita ganada/perdida (no solo totales)
    python scripts/compare_citation_detectors.py -v

    # Ejecuta los samples sinteticos en lugar de PDFs
    python scripts/compare_citation_detectors.py --samples

Reproduce los regex viejos inline para que la comparacion sea fiable aunque
el codigo actual ya este refactorizado. No carga Django.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

from citations.services.citation_patterns import find_citation_matches  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tfg_project"))

DEFAULT_PDF_DIR = (
    ROOT / "tfg_project" / "citations" / "static" / "citations" / "PDFs-Reales"
)


# ---- Regex viejos (copiados de la version pre-refactor) ----
OLD_NUMERIC = re.compile(r"\[\s*\d+(?:\s*(?:[,;]\s*\d+|\s*[-–—]\s*\d+))*\s*\]")
OLD_AUTHOR_YEAR_NARROW = re.compile(r"\b([A-Z][A-Za-z\-]+)\s*\(\s*(19|20)\d{2}\s*\)")
OLD_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def detect_old(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in OLD_NUMERIC.finditer(text):
        out.append(("numeric", m.group(0)))
    for m in OLD_AUTHOR_YEAR_NARROW.finditer(text):
        out.append(("authoryear", m.group(0)))
    for m in OLD_DOI.finditer(text):
        out.append(("doi", m.group(0)))
    return out


def detect_new(text: str) -> list[tuple[str, str]]:
    return [(h["type"], h["match"]) for h in find_citation_matches(text)]


def extract_pdf_text(pdf_path: Path) -> str:
    """Vuelca el texto de un PDF. Usa PyMuPDF si esta, si no pdftotext."""
    try:
        import fitz  # type: ignore[import-not-found]

        with fitz.open(str(pdf_path)) as doc:
            return "\n\n".join(page.get_text() for page in doc)
    except ImportError:
        pass

    import shutil
    import subprocess

    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    raise RuntimeError(
        "Necesito PyMuPDF (`pip install pymupdf`) o `pdftotext` instalado "
        "para volcar el texto de los PDFs."
    )


SAMPLES = [
    "We rely on Smith et al. (2020) and (Jones, 2021) and [1, 2-3].",
    "(Smith and Jones, 2020; Doe et al., 2021) extended this work.",
    "(Garcia et al., 2020a) reviewed the field; see also (Brown 2019).",
    "Multi-author: (Smith, Jones, & Doe, 2020).",
    "Diacriticos: Muller (2020) and (O'Brien, 2021) discuss it.",
    "DOI con punto: 10.1109/MC.2020.123456.",
    "DOI entre parens: (10.1109/MC.2020.123456).",
    "Falso positivo: See Section 3 (2020 dataset) and Figure 4 (2020).",
    "Mix: As [3, 5-7] and Smith (2020) showed; cf. (Doe, 2021).",
    "Anios apilados: Smith (2020a, 2021b) extended this.",
]


def render_hits(label: str, hits: list[tuple[str, str]]) -> str:
    if not hits:
        return f"  {label}: -"
    inside = ", ".join(f"{kind}={match!r}" for kind, match in hits)
    return f"  {label}: {inside}"


def report_text(label: str, text: str, *, verbose: bool) -> tuple[int, int]:
    old = detect_old(text)
    new = detect_new(text)
    gained = [h for h in new if h not in old]
    lost = [h for h in old if h not in new]

    print("-" * 78)
    print(label)
    if verbose:
        snippet = text.strip().replace("\n", " ")
        print(f"  texto: {snippet[:140]}{'...' if len(snippet) > 140 else ''}")
        print(render_hits("VIEJO", old))
        print(render_hits("NUEVO", new))
        if gained:
            print(render_hits("+ NUEVOS DETECTADOS", gained))
        if lost:
            print(render_hits("- DEJA DE DETECTAR", lost))
    else:
        print(
            f"  viejo={len(old):4d}  nuevo={len(new):4d}  "
            f"+{len(gained):3d} nuevos  -{len(lost):3d} perdidos"
        )
    return len(old), len(new)


def collect_targets(args: argparse.Namespace) -> list[Path]:
    if args.samples:
        return []
    if not args.paths:
        if not DEFAULT_PDF_DIR.is_dir():
            raise SystemExit(
                f"No encuentro el directorio por defecto: {DEFAULT_PDF_DIR}"
            )
        return sorted(DEFAULT_PDF_DIR.glob("*.pdf"))

    out: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.glob("*.pdf")))
        elif path.is_file():
            out.append(path)
        else:
            print(f"warn: no existe {path}, lo salto", file=sys.stderr)
    return out


def iter_texts(targets: list[Path], use_samples: bool) -> Iterable[tuple[str, str]]:
    if use_samples:
        for idx, sample in enumerate(SAMPLES, start=1):
            yield f"sample #{idx}", sample
        return
    for target in targets:
        suffix = target.suffix.lower()
        if suffix == ".pdf":
            try:
                text = extract_pdf_text(target)
            except Exception as exc:
                print(f"  ! error volcando {target.name}: {exc}", file=sys.stderr)
                continue
        else:
            text = target.read_text(encoding="utf-8", errors="replace")
        yield target.name, text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "paths",
        nargs="*",
        help="PDFs/.txt/directorios a analizar (def: PDFs-Reales/).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Lista cada cita ganada o perdida, no solo totales.",
    )
    parser.add_argument(
        "--samples",
        action="store_true",
        help="Ejecuta los textos sinteticos en lugar de PDFs.",
    )
    args = parser.parse_args()

    targets = collect_targets(args)
    if not args.samples and not targets:
        raise SystemExit("No hay PDFs ni ficheros para analizar.")

    total_old = total_new = 0
    for label, text in iter_texts(targets, args.samples):
        old_n, new_n = report_text(label, text, verbose=args.verbose)
        total_old += old_n
        total_new += new_n

    print("=" * 78)
    delta = total_new - total_old
    pct = (delta / total_old * 100) if total_old else float("inf")
    print(
        f"TOTAL  viejo={total_old}  nuevo={total_new}  " f"delta=+{delta} ({pct:+.1f}%)"
    )


if __name__ == "__main__":
    main()

"""Compara el detector de citas viejo vs nuevo sobre texto sintetico y real.

Uso:
    cd tfg_project
    python ../scripts/compare_citation_detectors.py
    # o pasando un fichero .txt:
    python ../scripts/compare_citation_detectors.py path/al/parrafo.txt

No carga Django: usa solo `citation_patterns` y reproduce los regex viejos
inline para que la comparacion sea reproducible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Asegura que tfg_project este en sys.path para importar `citations.*`.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tfg_project"))

from citations.services.citation_patterns import find_citation_matches  # noqa: E402

# ---- Regex viejos (copiados de la version pre-refactor) ----
OLD_NUMERIC = re.compile(
    r"\[\s*\d+(?:\s*(?:[,;]\s*\d+|\s*[-–—]\s*\d+))*\s*\]"
)
OLD_AUTHOR_YEAR_NARROW = re.compile(
    r"\b([A-Z][A-Za-z\-]+)\s*\(\s*(19|20)\d{2}\s*\)"
)
OLD_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")


def detect_old(text: str) -> list[tuple[str, str]]:
    out = []
    for m in OLD_NUMERIC.finditer(text):
        out.append(("numeric", m.group(0)))
    for m in OLD_AUTHOR_YEAR_NARROW.finditer(text):
        out.append(("authoryear", m.group(0)))
    for m in OLD_DOI.finditer(text):
        out.append(("doi", m.group(0)))
    return out


def detect_new(text: str) -> list[tuple[str, str]]:
    return [(h["type"], h["match"]) for h in find_citation_matches(text)]


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


def render(label: str, hits: list[tuple[str, str]]) -> str:
    if not hits:
        return f"  {label}: -"
    inside = ", ".join(f"{kind}={match!r}" for kind, match in hits)
    return f"  {label}: {inside}"


def main() -> None:
    if len(sys.argv) > 1:
        texts = [Path(p).read_text(encoding="utf-8") for p in sys.argv[1:]]
    else:
        texts = SAMPLES

    total_old = total_new = 0
    for text in texts:
        old = detect_old(text)
        new = detect_new(text)
        total_old += len(old)
        total_new += len(new)
        gained = [h for h in new if h not in old]
        lost = [h for h in old if h not in new]
        print("-" * 78)
        print(text[:200] + ("..." if len(text) > 200 else ""))
        print(render("VIEJO", old))
        print(render("NUEVO", new))
        if gained:
            print(render("+ NUEVOS DETECTADOS", gained))
        if lost:
            print(render("- DEJA DE DETECTAR (revisar si era valido)", lost))

    print("=" * 78)
    print(f"Total citas detectadas  viejo={total_old}  nuevo={total_new}")


if __name__ == "__main__":
    main()

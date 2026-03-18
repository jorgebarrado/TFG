from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tfg_project"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from citations.services.papermage_extractor import extract_pdf_data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python scripts/test_papermage_reader_json.py ruta/al/archivo.pdf")

    pdf_path = sys.argv[1]
    data = extract_pdf_data(pdf_path)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:5000])
    print(f"\nPáginas: {len(data['pages'])}")
    print(f"Items: {len(data['items'])}")

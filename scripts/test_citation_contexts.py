from __future__ import annotations

import sys
from pathlib import Path

# Ahora podemos importar usando tfg_project.citations...
from tfg_project.citations.services.papermage_extractor import (
    extract_contexts_from_pdf,
)

# --- Ajustar sys.path para poder importar tfg_project ---
BASE_DIR = Path(__file__).resolve().parent.parent
# BASE_DIR = C:\Users\jbarr\Documents\TFG
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# --- Ruta al PDF de prueba ---
PDF_PATH = Path(
    r"C:\Users\jbarr\Downloads\2017-CT-development-computational-thinking_RG (1).pdf"
)

if not PDF_PATH.is_file():
    print(f"[ERROR] No se encontró el PDF en: {PDF_PATH}")
    sys.exit(1)

# --- Patrones de cita a buscar ---
patterns = [
    r"\[(\d+)\]",  # citas tipo [12]
    r"\b[A-Z][a-z]+ et al\., \d{4}\b",  # citas estilo "Smith et al., 2017"
    r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+",  # DOI en el texto
]

print(f"Analizando PDF: {PDF_PATH}")
contexts = extract_contexts_from_pdf(str(PDF_PATH), patterns)

print(f"\nContextos encontrados: {len(contexts)}")

for ctx in contexts[:10]:
    print("\n--- CONTEXTO ---")
    print(f"Página    : {ctx['page']}")
    print(f"Patrón    : {ctx['pattern']}")
    print(f"Posición  : {ctx['start']} - {ctx['end']}")
    print(f"Fragmento : {ctx['snippet']}")

from __future__ import annotations
from typing import List

# Marca indisponible (lo integrarás más adelante)
PC_AVAILABLE = False

def pc_extract_paragraphs(pdf_path: str) -> List[str]:
    if not PC_AVAILABLE:
        raise RuntimeError("PaperCraft no está disponible en este entorno.")
    raise NotImplementedError("PaperCraft aún no integrado.")

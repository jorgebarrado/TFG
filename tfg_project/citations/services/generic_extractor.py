from __future__ import annotations
from typing import List
import re

try:
    import pdfplumber  # más fiable en Windows para texto
except Exception:
    pdfplumber = None

def _split_paragraphs(text: str) -> List[str]:
    parts = re.split(r"\n\s*\n", text)
    out = []
    for p in parts:
        p = re.sub(r"[ \t]*\n[ \t]*", " ", p.strip())
        if p:
            out.append(p)
    return out

def generic_extract_paragraphs(pdf_path: str) -> List[str]:
    if pdfplumber is None:
        return []
    chunks: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            chunks.append(txt)
    return _split_paragraphs("\n".join(chunks))

from __future__ import annotations

from papermage.parsers.pdfplumber_parser import PDFPlumberParser
from papermage.magelib import Document

PDF_PATH = (
    r"C:\Users\jbarr\Downloads\2017-CT-development-computational-thinking_RG (1).pdf"
)

parser = PDFPlumberParser()

print("Cargando PDF...")
doc: Document = parser.parse(input_pdf_path=PDF_PATH)

print("\n=== INFO DEL DOCUMENTO ===")
print("Páginas:", len(doc.pages))
print("Número de símbolos:", len(doc.symbols))

print("\n=== SPANS DE LA PRIMERA PÁGINA ===")
first_page = doc.pages[0]
for i, span in enumerate(first_page.spans[:20]):  # solo primeros 20
    print(
        f"Span {i}: start={span.start} end={span.end} text='{doc.symbols[span.start : span.end]}'"
    )

print("\n=== TEXTO COMPLETO DE LA PRIMERA PÁGINA ===")
page_text = ""
for span in first_page.spans:
    start = max(int(span.start), 0)
    end = min(int(span.end), len(doc.symbols))
    page_text += doc.symbols[start:end]

print(page_text[:2000])  # primeros 2000 chars

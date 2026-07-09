# Tests unitarios de reader_data: deteccion robusta de bibliografia y fallback seguro.
from unittest.mock import patch

from django.test import SimpleTestCase

from citations.services.reader_data import _is_reference_header, extract_pdf_references


class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self):
        return self._text


class _FakeDoc:
    def __init__(self, page_texts):
        self._pages = [_FakePage(text) for text in page_texts]
        self.page_count = len(self._pages)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        return iter(self._pages)


class _FakeFitz:
    def __init__(self, page_texts):
        self._page_texts = page_texts

    def open(self, _pdf_path):
        return _FakeDoc(self._page_texts)


class ReaderDataReferenceDetectionTests(SimpleTestCase):
    def test_reference_header_accepts_latex_and_unicode_spanish_variants(self):
        accepted = [
            "Bibliograf´ıa",
            "BIBLIOGRAF´IA",
            "Bibliografıa",
            "Bibliografía",
            "Bibliografia",
            "Referencias",
            "Referencias bibliográficas",
            "Bibliografía y referencias",
            "References",
            "Bibliography",
            "Works cited",
            "7. Bibliografía",
            "Capítulo 7: Bibliografía",
        ]

        for line in accepted:
            with self.subTest(line=line):
                self.assertTrue(_is_reference_header(line))

    def test_reference_header_rejects_long_body_mentions(self):
        self.assertFalse(
            _is_reference_header(
                "Bibliografía y citas: LATEX herramientas para crear documentos "
                "cientificos con ejemplos, plantillas y recomendaciones de uso."
            )
        )

    def test_extract_pdf_references_uses_spanish_latex_heading_and_numbered_refs(self):
        page_texts = [
            "Capitulo 1\nTexto del cuerpo con citas [1] y [2].",
            (
                "BIBLIOGRAF´IA\n"
                "[1] Ada Lovelace. Notes on the analytical engine. 1843.\n"
                "[2] Donald Knuth. The TeXbook. Addison-Wesley. 1984.\n"
                "Continuacion de la segunda referencia.\n"
                "[3] Leslie Lamport. LaTeX: A Document Preparation System. 1994."
            ),
        ]

        with patch("citations.services.reader_data.fitz", _FakeFitz(page_texts)):
            references, stats = extract_pdf_references("fake.pdf")

        self.assertEqual(len(references), 3)
        self.assertEqual([reference["index"] for reference in references], [1, 2, 3])
        self.assertTrue(stats["references_header_found"])
        self.assertEqual(stats["bibliography_start_page"], 2)
        self.assertFalse(stats["fallback_used"])
        self.assertEqual(stats["fallback_reason"], "")
        self.assertIn("BIBLIOGRAF´IA", stats["reference_heading_candidates"])
        self.assertIn("bibliografia", stats["normalized_heading_candidates"])

    def test_extract_pdf_references_ignores_table_of_contents_heading_entry(self):
        page_texts = [
            (
                "´Indice general\n"
                "1. Introduccion . . . . . . . . . . . . . . . . . 1\n"
                "Bibliograf´ıa\n"
                "55\n"
                "IX"
            ),
            "Capitulo 1\nTexto del cuerpo con citas [1] y [2].",
            (
                "Bibliograf´ıa\n"
                "[1] Ada Lovelace. Notes on the analytical engine. 1843.\n"
                "[2] Donald Knuth. The TeXbook. Addison-Wesley. 1984.\n"
                "[3] Leslie Lamport. LaTeX: A Document Preparation System. 1994."
            ),
        ]

        with patch("citations.services.reader_data.fitz", _FakeFitz(page_texts)):
            references, stats = extract_pdf_references("fake.pdf")

        self.assertEqual(len(references), 3)
        self.assertEqual(stats["bibliography_start_page"], 3)
        self.assertTrue(stats["references_header_found"])
        self.assertFalse(stats["fallback_used"])

    def test_long_document_without_heading_or_sequence_returns_empty_references(self):
        page_texts = [
            (
                f"Capitulo {page_number}\n"
                "Texto del cuerpo con menciones a bibliografia y citas, pero sin "
                "una seccion final de referencias ni entradas numeradas."
            )
            for page_number in range(1, 36)
        ]

        with patch("citations.services.reader_data.fitz", _FakeFitz(page_texts)):
            references, stats = extract_pdf_references("fake.pdf")

        self.assertEqual(references, [])
        self.assertFalse(stats["references_header_found"])
        self.assertIsNone(stats["bibliography_start_page"])
        self.assertFalse(stats["fallback_used"])
        self.assertEqual(
            stats["fallback_reason"],
            "missing_header_no_coherent_numbered_sequence",
        )

    def test_long_document_without_heading_uses_numbered_sequence_fallback(self):
        page_texts = [
            f"Capitulo {page_number}\nTexto del cuerpo sin heading de referencias."
            for page_number in range(1, 35)
        ]
        page_texts.append(
            "[1] Ada Lovelace. Notes on the analytical engine. 1843.\n"
            "[2] Donald Knuth. The TeXbook. Addison-Wesley. 1984.\n"
            "[3] Leslie Lamport. LaTeX: A Document Preparation System. 1994."
        )

        with patch("citations.services.reader_data.fitz", _FakeFitz(page_texts)):
            references, stats = extract_pdf_references("fake.pdf")

        self.assertEqual(len(references), 3)
        self.assertFalse(stats["references_header_found"])
        self.assertEqual(stats["bibliography_start_page"], 35)
        self.assertTrue(stats["fallback_used"])
        self.assertEqual(stats["fallback_reason"], "missing_header_numbered_sequence")

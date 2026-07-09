from unittest.mock import patch

from django.test import SimpleTestCase

from citations.services.papermage_extractor import (
    _infer_rows_from_tokens,
    _is_bibliography_header_text,
    extract_pdf_data,
)
from citations.services.references_data import (
    _is_reference_heading_text,
    _looks_like_reference_section_snippet,
)


class _FakeBox:
    def __init__(self, page, left=10.0, top=20.0, width=100.0, height=10.0):
        self.page = page
        self.left = left
        self.top = top
        self.width = width
        self.height = height


class _FakeEntity:
    def __init__(self, text, page):
        self.text = text
        self.boxes = [_FakeBox(page)]


class _FakeDocument:
    pages = [object()]
    rows = [_FakeEntity("stale PaperMage row", 0)]
    paragraphs = []
    sections = []
    bibliographies = []


class PaperMageExtractorVisualLayerTests(SimpleTestCase):
    def test_bibliography_heading_helpers_accept_latex_artifacts(self):
        self.assertTrue(_is_bibliography_header_text("Bibliograf´ıa"))
        self.assertTrue(_is_bibliography_header_text("BIBLIOGRAF´IA"))
        self.assertTrue(_is_bibliography_header_text("Bibliografıa"))
        self.assertTrue(_is_reference_heading_text("Bibliograf´ıa"))
        self.assertTrue(_is_reference_heading_text("Capítulo 7: Bibliografía"))
        self.assertFalse(
            _is_reference_heading_text("Bibliografía y citas: LATEX herramientas")
        )

    def test_reference_section_snippet_filter_rejects_bibliography_fragments(self):
        self.assertTrue(
            _looks_like_reference_section_snippet(
                "Bibliograf´ıa [1] J. Astigarraga and V. Cruz-Alonso. "
                "Ecosistemas, 31(1):2332-2332, 2022. [2] T. Bray. "
                "The javascript object notation format. Technical report, 2014."
            )
        )
        self.assertTrue(
            _looks_like_reference_section_snippet(
                "...Ecosistemas, 31(1):2332-2332, 2022. [2] T. Bray. "
                "The javascript object notation format. Technical report, 2014."
            )
        )
        self.assertTrue(
            _looks_like_reference_section_snippet(
                "...windows subsystem for linux on windows 11. [7] J. A. "
                "Mora-Castillo. Serialización de objetos. [8] J. V. Neto. "
                "Boxplot: um recurso gráfico, 2017."
            )
        )
        self.assertTrue(
            _looks_like_reference_section_snippet(
                "...Revista Tecnología en Marcha, 29(1):118-125, 2016. [8] J. V. "
                "Mora-Castillo. Serialización de objetos. Revista Tecnología, 2016."
            )
        )
        self.assertTrue(
            _looks_like_reference_section_snippet(
                "...Odontológica do Brasil Central, 26(76), 2017. [9] J. R. M. "
                "R´ıos, N. M. L. Mora, and E. L. L. Sojos. Evaluación de frameworks."
            )
        )
        self.assertFalse(
            _looks_like_reference_section_snippet(
                "La función principal de GitHub [1] es que los usuarios puedan "
                "trabajar juntos en un proyecto."
            )
        )

    def test_infer_rows_from_fitz_tokens_groups_words_by_visual_line(self):
        tokens = [
            {
                "id": "token_2_0_1_1_w1",
                "token_id": "token_2_0_1_1",
                "text": "Reference",
                "page": 2,
                "box": [0.16, 0.20, 0.20, 0.02],
                "type": "token",
            },
            {
                "id": "token_2_0_1_0_w0",
                "token_id": "token_2_0_1_0",
                "text": "[1]",
                "page": 2,
                "box": [0.10, 0.20, 0.04, 0.02],
                "type": "token",
            },
        ]

        rows = _infer_rows_from_tokens(tokens)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["page"], 2)
        self.assertEqual(rows[0]["text"], "[1] Reference")
        self.assertEqual(rows[0]["source"], "fitz")
        for actual, expected in zip(rows[0]["box"], [0.1, 0.2, 0.26, 0.02]):
            self.assertAlmostEqual(actual, expected)

    def test_extract_pdf_data_rebuilds_rows_from_fitz_when_pagemaps_disagree(self):
        fitz_tokens = [
            {
                "id": "token_1_0_0_0_w0",
                "token_id": "token_1_0_0_0",
                "text": "[1]",
                "page": 1,
                "box": [0.10, 0.25, 0.04, 0.02],
                "type": "token",
            },
            {
                "id": "token_1_0_0_1_w1",
                "token_id": "token_1_0_0_1",
                "text": "Correct",
                "page": 1,
                "box": [0.16, 0.25, 0.12, 0.02],
                "type": "token",
            },
        ]

        with patch(
            "citations.services.papermage_extractor._load_reader_document",
            return_value=_FakeDocument(),
        ), patch(
            "citations.services.papermage_extractor._extract_real_pdf_page_dimensions",
            return_value=[(595.0, 842.0), (595.0, 842.0)],
        ), patch(
            "citations.services.papermage_extractor._extract_visual_words_with_fitz",
            return_value=fitz_tokens,
        ):
            payload = extract_pdf_data("dummy.pdf")

        self.assertEqual(len(payload["pages"]), 2)
        rows = payload["layers"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["page"], 1)
        self.assertEqual(rows[0]["text"], "[1] Correct")
        self.assertEqual(rows[0]["source"], "fitz")

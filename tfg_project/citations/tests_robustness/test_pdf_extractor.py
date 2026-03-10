import pytest
import os
import shutil
from unittest.mock import patch, MagicMock
from pathlib import Path
from citations.services.papermage_extractor import PM_AVAILABLE, extract_contexts_from_pdf, _iter_paragraphs, pm_extract_paragraphs

@pytest.fixture
def mock_pdf_files(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()

    # Generate fake pdf files
    native_pdf = pdf_dir / "native.pdf"
    native_pdf.write_text("fake pdf with text layer")

    scanned_pdf = pdf_dir / "scanned.pdf"
    scanned_pdf.write_text("fake scanned pdf")

    protected_pdf = pdf_dir / "protected.pdf"
    protected_pdf.write_text("fake encrypted pdf")

    double_col_pdf = pdf_dir / "double_col.pdf"
    double_col_pdf.write_text("fake double column pdf")

    return {
        "native": native_pdf,
        "scanned": scanned_pdf,
        "protected": protected_pdf,
        "double_col": double_col_pdf
    }

@pytest.mark.skipif(not PM_AVAILABLE, reason="PaperMage not available")
class TestPaperMageExtractor:

    @patch('citations.services.papermage_extractor.PDFPlumberParser')
    @pytest.mark.parametrize("run", range(75))
    def test_native_pdf(self, mock_parser, mock_pdf_files, run):
        mock_doc = MagicMock()
        mock_doc.symbols = "This is a cited paragraph [1]"

        mock_page = MagicMock()
        span = MagicMock()
        span.start = 0
        span.end = len(mock_doc.symbols)
        mock_page.spans = [span]

        mock_doc.pages = [mock_page]

        mock_parser.return_value.parse.return_value = mock_doc

        contexts = extract_contexts_from_pdf(str(mock_pdf_files["native"]), ["cited"])
        assert len(contexts) == 1
        assert contexts[0]["snippet"] == "This is a cited paragraph [1]"

    @patch('citations.services.papermage_extractor.PDFPlumberParser')
    @pytest.mark.parametrize("run", range(75))
    def test_scanned_pdf(self, mock_parser, mock_pdf_files, run):
        mock_doc = MagicMock()
        mock_doc.symbols = "" # No OCR, empty text layer

        mock_parser.return_value.parse.return_value = mock_doc

        with pytest.raises(RuntimeError) as excinfo:
            extract_contexts_from_pdf(str(mock_pdf_files["scanned"]), ["cited"])

        assert "No se pudo extraer texto del PDF" in str(excinfo.value)

    @patch('citations.services.papermage_extractor.PDFPlumberParser')
    @pytest.mark.parametrize("run", range(75))
    def test_protected_pdf(self, mock_parser, mock_pdf_files, run):
        # mock pdfplumber raising an exception because of protection
        mock_parser.return_value.parse.side_effect = Exception("PDF is encrypted")

        with pytest.raises(RuntimeError) as excinfo:
             extract_contexts_from_pdf(str(mock_pdf_files["protected"]), ["cited"])

        assert "No se pudo leer el PDF con PaperMage" in str(excinfo.value)

    @patch('citations.services.papermage_extractor.PDFPlumberParser')
    @pytest.mark.parametrize("run", range(75))
    def test_double_col_pdf(self, mock_parser, mock_pdf_files, run):
        mock_doc = MagicMock()
        # Mocking a layout where right col is read after left col properly or badly depending on spans.
        mock_doc.symbols = "Left col. \n\nRight col cited text."
        mock_page = MagicMock()
        span1 = MagicMock()
        span1.start = 0
        span1.end = 11
        span2 = MagicMock()
        span2.start = 12
        span2.end = 34
        mock_page.spans = [span1, span2]

        mock_doc.pages = [mock_page]
        mock_parser.return_value.parse.return_value = mock_doc

        contexts = extract_contexts_from_pdf(str(mock_pdf_files["double_col"]), ["cited"])

        assert len(contexts) == 1
        assert "cited text" in contexts[0]["snippet"]

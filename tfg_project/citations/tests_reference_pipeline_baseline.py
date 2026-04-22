from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from citations.services.citation_extractor import process_manuscript
from citations.services.papermage_extractor import extract_pdf_data
from citations.services.reader_data import (
    build_snippets_from_results,
    extract_pdf_references,
)
from citations.services.references_data import build_references_data


PDF_FIXTURE_DIR = (
    Path(__file__).resolve().parent / "static" / "citations" / "PDFs-Reales"
)


def _raise_crossref_failure(*args, **kwargs):
    raise RuntimeError("forced Crossref failure for reference baseline tests")


class ReferencePipelineBaselineTests(SimpleTestCase):
    maxDiff = None

    def _run_current_pipeline(self, pdf_name):
        pdf_path = PDF_FIXTURE_DIR / pdf_name
        self.assertTrue(pdf_path.exists(), f"Missing baseline PDF: {pdf_path}")

        references, ref_stats = extract_pdf_references(str(pdf_path))
        references_numbered = bool(ref_stats.get("references_numbered"))
        citation_style = ref_stats.get("citation_style") or (
            "numeric" if references_numbered else "non_numeric"
        )
        max_reference_index = int(
            ref_stats.get("max_reference_index")
            or ref_stats.get("references_total")
            or len(references)
            or 0
        )
        total_references_for_validation = (
            max_reference_index if references_numbered else len(references)
        )

        manuscript_payload = process_manuscript(
            str(pdf_path),
            engine="papermage",
            references=references,
            citation_style=citation_style,
            total_references=total_references_for_validation,
        )
        snippets = build_snippets_from_results(manuscript_payload.get("results") or [])
        reader_payload = extract_pdf_data(str(pdf_path))

        with patch(
            "citations.services.references_data.crossref_fetch_work_by_doi",
            _raise_crossref_failure,
        ):
            references_data = build_references_data(
                references=references,
                snippets=snippets,
                layers=reader_payload.get("layers") or {},
                references_numbered=references_numbered,
                article_doi="",
                source_filename=pdf_name,
                engine_used=manuscript_payload.get("engine_used") or "papermage",
                debug_reference_detection=True,
            )

        return {
            "references": references,
            "ref_stats": ref_stats,
            "manuscript": manuscript_payload,
            "snippets": snippets,
            "reader": reader_payload,
            "references_data": references_data,
        }

    def _assert_common_baseline(
        self,
        result,
        *,
        min_pages,
        min_rows,
        min_paragraphs,
        min_bibliographies,
        min_structured_references,
    ):
        manuscript = result["manuscript"]
        self.assertTrue(manuscript.get("ok"), manuscript)
        self.assertEqual(manuscript.get("engine_used"), "papermage")
        self.assertGreater(len(manuscript.get("results") or []), 0)
        self.assertGreater(len(result["snippets"]), 0)

        reader = result["reader"]
        pages = reader.get("pages") or []
        layers = reader.get("layers") or {}
        self.assertGreaterEqual(len(pages), min_pages)
        self.assertGreaterEqual(len(layers.get("rows") or []), min_rows)
        self.assertGreaterEqual(len(layers.get("paragraphs") or []), min_paragraphs)
        self.assertGreaterEqual(
            len(layers.get("bibliographies") or []),
            min_bibliographies,
        )

        references_data = result["references_data"]
        structured_references = references_data.get("references") or []
        self.assertGreaterEqual(
            len(structured_references),
            min_structured_references,
        )
        self.assertIn(
            references_data.get("citation_style"),
            {"numeric", "non_numeric"},
        )
        self.assertIsInstance(references_data.get("max_reference_index"), int)
        self.assertGreater(references_data.get("max_reference_index"), 0)

        debug_payload = references_data.get("debug_payload") or {}
        expected_debug_keys = {
            "metadata",
            "phases",
            "document_diagnostics",
            "phase_diagnostics",
            "references",
            "row_rejection_audit",
            "reference_failure_audit",
            "start_page_column_decision",
        }
        self.assertTrue(expected_debug_keys.issubset(debug_payload.keys()))

        if references_data.get("citation_style") == "numeric":
            self.assertTrue(
                {
                    "numeric_coverage_summary",
                    "numeric_reference_pipeline_v2",
                    "numeric_reference_pipeline_v3",
                }.issubset(debug_payload.keys())
            )

        crossref_phase = (debug_payload.get("phases") or {}).get("crossref") or {}
        self.assertTrue(crossref_phase.get("queried"))
        self.assertFalse(crossref_phase.get("crossref_available"))

    def _structure_source_counts(self, references_data):
        counts = {}
        for reference in references_data.get("references") or []:
            source = reference.get("structure_source") or "missing"
            counts[source] = counts.get(source, 0) + 1
        return counts

    def _fallback_count(self, references_data):
        return sum(
            1
            for reference in references_data.get("references") or []
            if "fallback" in str(reference.get("structure_source") or "")
        )

    def test_ct_pdf_current_reference_pipeline_baseline(self):
        result = self._run_current_pipeline(
            "2017-CT-development-computational-thinking_RG.pdf"
        )

        self._assert_common_baseline(
            result,
            min_pages=8,
            min_rows=500,
            min_paragraphs=100,
            min_bibliographies=10,
            min_structured_references=30,
        )

        references_data = result["references_data"]
        self.assertEqual(
            self._fallback_count(references_data),
            0,
            self._structure_source_counts(references_data),
        )

    def test_jscientometres_pdf_current_reference_pipeline_baseline(self):
        result = self._run_current_pipeline("JScientometRes-14-3-838.pdf")

        self._assert_common_baseline(
            result,
            min_pages=12,
            min_rows=1000,
            min_paragraphs=300,
            min_bibliographies=20,
            min_structured_references=50,
        )

        references_data = result["references_data"]
        structured_references = references_data.get("references") or []
        self.assertLessEqual(
            self._fallback_count(references_data),
            max(10, len(structured_references) // 10),
            self._structure_source_counts(references_data),
        )

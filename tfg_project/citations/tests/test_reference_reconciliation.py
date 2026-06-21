# Tests de reconciliación de fuentes de referencias: contrasta la salida del pipeline con la fuente base.
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from citations.services.citation_extractor import process_manuscript
from citations.services.papermage_extractor import extract_pdf_data
from citations.services.reader_data import (
    build_snippets_from_results,
    extract_pdf_references,
)
from citations.services.reference_reconciliation import reconcile_reference_sources
from citations.services.references_data import build_references_data

PDF_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "static" / "citations" / "PDFs-Reales"
)


def _raise_crossref_failure(*args, **kwargs):
    raise RuntimeError("forced Crossref failure for reconciliation tests")


class ReferenceReconciliationTests(SimpleTestCase):
    maxDiff = None

    def _build_real_payloads(self, pdf_name):
        pdf_path = PDF_FIXTURE_DIR / pdf_name
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
            structured_payload = build_references_data(
                references=references,
                snippets=snippets,
                layers=reader_payload.get("layers") or {},
                references_numbered=references_numbered,
                article_doi="",
                source_filename=pdf_name,
                engine_used=manuscript_payload.get("engine_used") or "papermage",
                debug_reference_detection=True,
            )
        return references, ref_stats, structured_payload

    def test_healthy_structured_output_filters_fallbacks_and_deduplicates_indices(self):
        base_references = [
            {"index": 1, "raw": "[1] Base one. 2020."},
            {
                "index": 2,
                "raw": "[2] Base two. Journal of Examples. 2021; 3(2): 10-20.",
            },
            {"index": 3, "raw": "[3] Base three. 2022."},
        ]
        structured_payload = {
            "references": [
                {
                    "index": 1,
                    "text": "[1] Structured one. 2020.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 1,
                    "text": "[1] Duplicate weaker. 2020.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 2,
                    "text": "[2] Dudoso fallback. 2021.",
                    "structure_source": "raw_reference_fallback",
                    "reference_validation": {"accepted": False},
                },
                {
                    "index": 3,
                    "text": "[3] Structured three. 2022.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
            ],
            "citation_style": "numeric",
            "max_reference_index": 3,
            "bibliography_start_page": 7,
        }

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats={
                "citation_style": "numeric",
                "max_reference_index": 3,
                "bibliography_start_page": 7,
                "references_numbered": True,
            },
            structured_references_data=structured_payload,
        )

        summary = result["reconciliation_summary"]
        self.assertEqual(summary["source_selected"], "structured")
        self.assertEqual(summary["structured_fallback_count"], 1)
        self.assertEqual(summary["structured_duplicate_indices"], [1])
        self.assertEqual(summary["final_duplicate_indices"], [])
        self.assertTrue(summary["rescue_attempted"])
        self.assertEqual(summary["rescued_indices"], [2])
        self.assertEqual(result["final_references_total"], 3)
        self.assertEqual(result["final_max_reference_index"], 3)
        self.assertEqual(
            [ref["index"] for ref in result["final_references"]], [1, 2, 3]
        )
        self.assertFalse(
            any(
                "fallback" in str(ref.get("structure_source") or "")
                for ref in result["final_references"]
            )
        )

    def test_rescue_skips_ambiguous_base_candidates_for_missing_index(self):
        base_references = [
            {"index": 1, "raw": "[1] Base one. 2020."},
            {"index": 2, "raw": "[2] First plausible candidate. 2021. Journal."},
            {"index": 2, "raw": "[2] Second plausible candidate. 2021. Journal."},
            {"index": 3, "raw": "[3] Base three. 2022."},
        ]
        structured_payload = {
            "references": [
                {
                    "index": 1,
                    "text": "[1] Structured one. 2020.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 3,
                    "text": "[3] Structured three. 2022.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
            ],
            "citation_style": "numeric",
            "max_reference_index": 3,
        }

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats={
                "citation_style": "numeric",
                "max_reference_index": 3,
                "references_numbered": True,
            },
            structured_references_data=structured_payload,
        )

        summary = result["reconciliation_summary"]
        self.assertTrue(summary["rescue_attempted"])
        self.assertEqual(summary["rescued_indices"], [])
        self.assertEqual(summary["final_missing_indices"], [2])
        self.assertEqual(result["final_references_total"], 2)
        self.assertIn(
            {
                "index": 2,
                "source": "base",
                "action": "skipped",
                "reason": "ambiguous_candidates",
            },
            summary["rescue_reasons"],
        )

    def test_rescue_skips_fallback_when_no_clean_candidate_exists(self):
        base_references = [
            {"index": 1, "raw": "[1] Base one. 2020."},
            {"index": 3, "raw": "[3] Base three. 2022."},
            {"index": 4, "raw": "[4] Base four. 2023."},
        ]
        structured_payload = {
            "references": [
                {
                    "index": 1,
                    "text": "[1] Structured one. 2020.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 2,
                    "text": "[2] Fallback two. 2021. Journal.",
                    "structure_source": "raw_reference_fallback",
                    "reference_validation": {"accepted": False},
                },
                {
                    "index": 3,
                    "text": "[3] Structured three. 2022.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 4,
                    "text": "[4] Structured four. 2023.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
            ],
            "citation_style": "numeric",
            "max_reference_index": 4,
        }

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats={
                "citation_style": "numeric",
                "max_reference_index": 4,
                "references_numbered": True,
            },
            structured_references_data=structured_payload,
        )

        summary = result["reconciliation_summary"]
        self.assertTrue(summary["rescue_attempted"])
        self.assertEqual(summary["rescued_indices"], [])
        self.assertEqual(summary["final_missing_indices"], [2])
        self.assertIn(
            {
                "index": 2,
                "source": "structured_discarded",
                "action": "skipped",
                "reason": "no_reasonable_candidate",
            },
            summary["rescue_reasons"],
        )

    def test_weak_structured_output_falls_back_to_base_contract(self):
        base_references = [
            {"index": 1, "raw": "[1] Base one. 2020."},
            {"index": 2, "raw": "[2] Base two. 2021."},
        ]
        structured_payload = {
            "references": [
                {
                    "index": 1,
                    "text": "",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": False},
                },
                {
                    "index": 2,
                    "text": "[2] Fallback two. 2021.",
                    "structure_source": "raw_reference_fallback",
                    "reference_validation": {"accepted": False},
                },
            ],
            "citation_style": "numeric",
            "max_reference_index": 2,
        }

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats={
                "citation_style": "numeric",
                "max_reference_index": 2,
                "references_numbered": True,
            },
            structured_references_data=structured_payload,
        )

        self.assertEqual(result["reconciliation_summary"]["source_selected"], "base")
        self.assertEqual(result["final_references_total"], 2)
        self.assertEqual(result["final_max_reference_index"], 2)
        self.assertEqual(
            [ref["raw"] for ref in result["final_references"]],
            [ref["raw"] for ref in base_references],
        )

    def test_ct_pdf_remains_stable_after_reconciliation(self):
        base_references, base_stats, structured_payload = self._build_real_payloads(
            "2017-CT-development-computational-thinking_RG.pdf"
        )

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats=base_stats,
            structured_references_data=structured_payload,
        )

        summary = result["reconciliation_summary"]
        self.assertEqual(summary["source_selected"], "structured")
        self.assertEqual(result["final_references_total"], 37)
        self.assertEqual(result["final_max_reference_index"], 37)
        self.assertEqual(summary["structured_fallback_count"], 0)
        self.assertFalse(summary["rescue_attempted"])
        self.assertEqual(summary["rescued_indices"], [])
        self.assertEqual(summary["final_duplicate_indices"], [])
        self.assertFalse(
            any(
                "fallback" in str(ref.get("structure_source") or "")
                for ref in result["final_references"]
            )
        )

    def test_jscientometres_pdf_uses_structured_rows_without_fallback_noise(self):
        base_references, base_stats, structured_payload = self._build_real_payloads(
            "JScientometRes-14-3-838.pdf"
        )

        result = reconcile_reference_sources(
            base_references=base_references,
            base_stats=base_stats,
            structured_references_data=structured_payload,
        )

        summary = result["reconciliation_summary"]
        self.assertEqual(summary["source_selected"], "structured")
        self.assertEqual(summary["structured_fallback_count"], 3)
        self.assertEqual(summary["structured_duplicate_indices"], [1, 2, 3, 10])
        self.assertEqual(summary["structured_missing_indices"], [66])
        self.assertEqual(summary["final_duplicate_indices"], [])
        self.assertTrue(summary["rescue_attempted"])
        self.assertEqual(summary["rescued_indices"], [11, 33, 45])
        self.assertEqual(summary["final_missing_indices"], [66])
        self.assertLess(result["final_references_total"], summary["structured_total"])
        self.assertGreaterEqual(result["final_references_total"], 70)
        self.assertEqual(result["final_max_reference_index"], 72)
        self.assertFalse(
            any(
                not str(ref.get("raw") or "").strip()
                or "fallback" in str(ref.get("structure_source") or "")
                for ref in result["final_references"]
            )
        )

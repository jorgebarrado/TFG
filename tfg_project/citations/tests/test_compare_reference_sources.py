# Tests del script compare_reference_sources: comparación y resumen entre la fuente base y la estructurada de referencias.
# isort: skip_file
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from django.test import SimpleTestCase  # noqa: E402

from scripts.compare_reference_sources import (  # noqa: E402
    compare_reference_sources,
    resolve_pdf_paths,
    summarize_base_source,
    summarize_structured_source,
)


class CompareReferenceSourcesTests(SimpleTestCase):
    def test_base_summary_tracks_indices_dois_and_suspicious_entries(self):
        references = [
            {"index": 1, "raw": "[1] Smith, J. 2020. A useful paper. doi:10.1000/a"},
            {"index": 1, "raw": "[1] Smith duplicate. 2020."},
            {"index": 3, "raw": "View publication stats"},
            {"raw": "Tiny"},
        ]
        stats = {
            "citation_style": "numeric",
            "max_reference_index": 3,
            "bibliography_start_page": 8,
            "references_numbered": True,
        }

        summary = summarize_base_source(references, stats)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["doi_count"], 1)
        self.assertEqual(summary["citation_style"], "numeric")
        self.assertEqual(summary["max_reference_index"], 3)
        self.assertEqual(summary["bibliography_start_page"], 8)
        self.assertTrue(summary["references_numbered"])
        self.assertEqual(summary["index_summary"]["duplicate_indices"], [1])
        self.assertEqual(summary["index_summary"]["missing_indices"], [2])
        self.assertEqual(summary["index_summary"]["unlabeled_count"], 1)

        suspicious_reasons = {
            reason
            for item in summary["suspicious_entries"]
            for reason in item["reasons"]
        }
        self.assertIn("non_bibliographic_phrase", suspicious_reasons)
        self.assertIn("very_short", suspicious_reasons)

    def test_structured_summary_counts_sources_validation_and_fallbacks(self):
        references = [
            {
                "id": "ref-1",
                "index": 1,
                "text": "[1] Smith, J. 2020. A useful paper.",
                "doi": "10.1000/a",
                "structure_source": "rows_raw",
                "reference_validation": {"accepted": True},
            },
            {
                "id": "ref-2",
                "index": 2,
                "text": "[2] View publication stats",
                "structure_source": "raw_reference_fallback",
                "reference_validation": {"accepted": False},
            },
        ]
        payload = {
            "references": references,
            "citation_style": "numeric",
            "max_reference_index": 2,
            "bibliography_start_page": 8,
        }

        summary = summarize_structured_source(payload)

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["doi_count"], 1)
        self.assertEqual(
            summary["source_counts"], {"rows_raw": 1, "raw_reference_fallback": 1}
        )
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["accepted_count"], 1)
        self.assertEqual(summary["rejected_count"], 1)
        self.assertEqual(summary["index_summary"]["duplicate_indices"], [])
        self.assertEqual(summary["index_summary"]["missing_indices"], [])
        self.assertEqual(
            summary["suspicious_entries"][0]["reasons"],
            ["non_bibliographic_phrase", "structure_fallback"],
        )

    def test_compare_reference_sources_reports_diffs_overlap_and_contamination_classification(
        self,
    ):
        base_references = [
            {"index": 1, "raw": "[1] Smith, J. 2020. A useful paper."},
            {"index": 2, "raw": "[2] Doe, A. 2021. Another useful paper."},
        ]
        base_stats = {
            "citation_style": "numeric",
            "max_reference_index": 2,
            "references_numbered": True,
            "bibliography_start_page": 5,
        }
        structured_payload = {
            "references": [
                {
                    "index": 1,
                    "text": "[1] Smith, J. 2020. A useful paper.",
                    "structure_source": "rows_raw",
                    "reference_validation": {"accepted": True},
                },
                {
                    "index": 3,
                    "text": "[3] View publication stats",
                    "structure_source": "raw_reference_fallback",
                    "reference_validation": {"accepted": False},
                },
            ],
            "citation_style": "numeric",
            "max_reference_index": 3,
            "bibliography_start_page": 5,
        }

        comparison = compare_reference_sources(
            pdf_path=Path("sample.pdf"),
            base_references=base_references,
            base_stats=base_stats,
            structured_payload=structured_payload,
        )

        direct = comparison["comparison"]
        self.assertEqual(direct["references_total_delta"], 0)
        self.assertEqual(direct["max_reference_index_delta"], 1)
        self.assertTrue(direct["citation_style_match"])
        self.assertEqual(direct["indices_base_only"], [2])
        self.assertEqual(direct["indices_structured_only"], [3])
        self.assertEqual(direct["overlap"]["matched_count"], 1)
        self.assertEqual(comparison["classification"], "contaminated_structured_output")
        self.assertIn("index_sets_differ", comparison["classification_reasons"])

    def test_resolve_pdf_paths_uses_default_dir_and_glob(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "b.txt").write_text("not a pdf", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "c.pdf").write_bytes(b"%PDF-1.4\n")

            paths = resolve_pdf_paths(
                pdfs=[],
                directory=root,
                glob_pattern="*.pdf",
                default_dir=root,
            )

        self.assertEqual([path.name for path in paths], ["a.pdf"])

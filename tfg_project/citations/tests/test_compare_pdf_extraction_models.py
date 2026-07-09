# Tests del script compare_pdf_extraction_models: entradas, metricas y artefactos.
import csv
import json
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import compare_pdf_extraction_models as runner  # noqa: E402


class ComparePdfExtractionModelsTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = None

    @property
    def tmpdir(self):
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory()
        return self._tmp.name

    def tearDown(self):
        try:
            if self._tmp is not None:
                self._tmp.cleanup()
        finally:
            super().tearDown()

    def test_collect_papers_from_directory_manifest_and_single_pdf(self):
        root = Path(self.tmpdir)
        pdf_a = root / "a.pdf"
        pdf_b = root / "nested" / "b.pdf"
        pdf_b.parent.mkdir()
        pdf_a.write_bytes(b"%PDF-1.4\n")
        pdf_b.write_bytes(b"%PDF-1.4\n")
        (root / "ignored.txt").write_text("not a pdf", encoding="utf-8")

        directory_papers = runner.collect_paper_inputs(root)

        self.assertEqual([paper.paper_id for paper in directory_papers], ["a", "b"])
        self.assertEqual(
            [paper.pdf_path.name for paper in directory_papers],
            ["a.pdf", "b.pdf"],
        )
        self.assertEqual(directory_papers[0].doi, "")

        manifest = root / "manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "pdf", "doi"])
            writer.writeheader()
            writer.writerow({"id": "paper-a", "pdf": "a.pdf", "doi": "https://doi.org/10.1000/ABC"})

        manifest_papers = runner.collect_paper_inputs(manifest)

        self.assertEqual(len(manifest_papers), 1)
        self.assertEqual(manifest_papers[0].paper_id, "paper-a")
        self.assertEqual(manifest_papers[0].pdf_path, pdf_a.resolve())
        self.assertEqual(manifest_papers[0].doi, "10.1000/abc")

        single_pdf = runner.collect_paper_inputs(pdf_a)
        self.assertEqual(len(single_pdf), 1)
        self.assertEqual(single_pdf[0].paper_id, "a")

    def test_semantic_reference_comparison_uses_doi_overlap(self):
        engine_result = {
            "ok": True,
            "references": [
                {"index": 1, "doi": "10.1000/A", "title": "A"},
                {"index": 2, "doi": "10.1000/B", "title": "B"},
                {"index": 3, "title": "No DOI"},
            ],
            "contexts": [{"ref": 1}, {"ref": 2}],
            "time_ms": 123,
        }
        semantic_work = {
            "references": [
                {"doi": "10.1000/a", "title": "A"},
                {"doi": "10.1000/c", "title": "C"},
                {"title": "No DOI in Semantic Scholar"},
            ]
        }

        metrics = runner.build_engine_metrics(
            paper_id="paper-a",
            pdf_name="a.pdf",
            doi="10.2000/article",
            engine="ai_openai",
            engine_result=engine_result,
            semantic_work=semantic_work,
        )

        self.assertEqual(metrics["references_total"], 3)
        self.assertEqual(metrics["contexts_total"], 2)
        self.assertEqual(metrics["dois_total"], 2)
        self.assertEqual(metrics["semantic_references_total"], 3)
        self.assertEqual(metrics["semantic_reference_dois_total"], 2)
        self.assertEqual(metrics["matched_reference_dois"], 1)
        self.assertEqual(metrics["semantic_reference_doi_coverage_pct"], 50.0)
        self.assertEqual(metrics["extracted_reference_doi_coverage_pct"], 50.0)
        self.assertEqual(metrics["extra_semantic_reference_dois"], 1)

    def test_write_outputs_creates_graph_ready_csvs_and_summary(self):
        root = Path(self.tmpdir)
        output_dir = root / "out"
        papers = [
            {
                "paper_id": "paper-a",
                "pdf": "a.pdf",
                "doi": "10.2000/article",
                "semantic_scholar": {
                    "ok": True,
                    "references_total": 1,
                    "citations_total": 0,
                    "work": {"references": [{"doi": "10.1000/a"}]},
                },
                "engines": {
                    "papermage": {
                        "ok": True,
                        "time_ms": 10,
                        "references": [{"index": 1, "doi": "10.1000/a", "title": "A"}],
                        "contexts": [{"ref": 1}],
                    },
                    "ai_openai": {
                        "ok": False,
                        "time_ms": 5,
                        "error": "missing key",
                        "references": [],
                        "contexts": [],
                    },
                },
            }
        ]

        artifacts = runner.write_outputs(
            output_dir=output_dir,
            papers=papers,
            engines=["papermage", "ai_openai"],
            input_source=str(root),
        )

        self.assertTrue((output_dir / "summary.json").exists())
        self.assertTrue((output_dir / "engine_metrics.csv").exists())
        self.assertTrue((output_dir / "references_by_engine.csv").exists())
        self.assertEqual(artifacts["summary_json"], str(output_dir / "summary.json"))

        summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["aggregate"]["papers_total"], 1)
        self.assertEqual(summary["aggregate"]["engine_runs_total"], 2)
        self.assertEqual(summary["aggregate"]["engine_runs_ok"], 1)

        with (output_dir / "engine_metrics.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["paper_id"], "paper-a")
        self.assertEqual(rows[0]["engine"], "papermage")
        self.assertEqual(rows[0]["semantic_reference_doi_coverage_pct"], "100.0")

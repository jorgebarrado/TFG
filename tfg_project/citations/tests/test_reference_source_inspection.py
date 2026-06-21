# Tests del script inspect_reference_sources: helpers de inspección de fuentes de referencia.
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "inspect_reference_sources.py"
)


def _load_script_module():
    spec = spec_from_file_location("inspect_reference_sources", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load script module from {SCRIPT_PATH}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceSourceInspectionHelperTests(SimpleTestCase):
    def test_semantic_scholar_fields_use_supported_reference_authors_field(self):
        module = _load_script_module()

        fields = module.build_semantic_scholar_fields()

        self.assertIn("references.authors", fields)
        self.assertNotIn("references.authors.name", fields)

    def test_external_api_session_ignores_env_proxy_by_default(self):
        module = _load_script_module()

        session = module.build_external_api_session()

        self.assertFalse(session.trust_env)

    def test_resolve_paper_identity_prefers_extractor_doi_and_warns_on_conflict(self):
        module = _load_script_module()

        identity = module.resolve_paper_identity(
            pdf_name="paper.pdf",
            extractor_candidate={
                "paper_title": None,
                "paper_doi": "10.1000/extractor",
                "doi_source": "extractor_row_detection",
            },
            grobid_candidate={
                "paper_title": "Paper title from GROBID",
                "paper_doi": "10.2000/grobid",
                "doi_source": "grobid_header",
            },
        )

        self.assertEqual(identity["paper_doi"], "10.1000/extractor")
        self.assertEqual(identity["doi_source"], "extractor_row_detection")
        self.assertEqual(identity["paper_title"], "Paper title from GROBID")
        self.assertTrue(
            any("conflict" in warning.lower() for warning in identity["warnings"])
        )

    def test_normalize_crossref_reference_maps_message_reference_shape(self):
        module = _load_script_module()

        normalized = module.normalize_crossref_reference(
            {
                "unstructured": "Smith, J. Great Paper. 2020.",
                "DOI": "10.1000/ref-1",
                "article-title": "Great Paper",
                "author": "Smith, J.",
                "year": "2020",
                "journal-title": "Journal of Tests",
                "first-page": "10",
            },
            index=0,
        )

        self.assertEqual(normalized["source"], "crossref")
        self.assertEqual(normalized["index"], 1)
        self.assertEqual(normalized["raw"], "Smith, J. Great Paper. 2020.")
        self.assertEqual(normalized["title"], "Great Paper")
        self.assertEqual(normalized["authors"], ["Smith, J."])
        self.assertEqual(normalized["year"], 2020)
        self.assertEqual(normalized["doi"], "10.1000/ref-1")
        self.assertEqual(normalized["venue"], "Journal of Tests")
        self.assertEqual(normalized["pages"], "10")

    def test_normalize_semantic_scholar_reference_maps_graph_payload(self):
        module = _load_script_module()

        normalized = module.normalize_semantic_scholar_reference(
            {
                "title": "Graph Paper",
                "year": 2021,
                "venue": "S2 Venue",
                "externalIds": {"DOI": "10.1000/graph-1"},
                "authors": [{"name": "Ada Lovelace"}, {"name": "Grace Hopper"}],
                "url": "https://example.org/paper",
            },
            index=2,
        )

        self.assertEqual(normalized["source"], "semantic_scholar")
        self.assertEqual(normalized["index"], 3)
        self.assertIsNone(normalized["raw"])
        self.assertEqual(normalized["title"], "Graph Paper")
        self.assertEqual(normalized["authors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(normalized["year"], 2021)
        self.assertEqual(normalized["doi"], "10.1000/graph-1")
        self.assertEqual(normalized["venue"], "S2 Venue")
        self.assertIsNone(normalized["pages"])
        self.assertEqual(
            normalized["extra"]["url"],
            "https://example.org/paper",
        )

    def test_build_unified_counts_marks_external_sources_skipped_without_doi(self):
        module = _load_script_module()

        counts = module.build_unified_counts(
            paper_identity={
                "paper_doi": None,
                "doi_source": None,
            },
            source_payloads={
                "extractor": {
                    "status": "ok",
                    "references": [{"source": "extractor", "index": 1}],
                    "notes": [],
                },
                "grobid_processReferences": {
                    "status": "ok",
                    "references": [{"source": "grobid_processReferences", "index": 1}],
                    "notes": [],
                },
                "refextract": {
                    "status": "error",
                    "references": [],
                    "notes": ["refextract failed"],
                },
                "crossref": {
                    "status": "skipped",
                    "references": [],
                    "notes": ["Skipped: no paper DOI available."],
                },
                "semantic_scholar": {
                    "status": "skipped",
                    "references": [],
                    "notes": ["Skipped: no paper DOI available."],
                },
            },
        )

        by_source = {item["source"]: item for item in counts}

        self.assertEqual(by_source["extractor"]["total_references"], 1)
        self.assertEqual(by_source["grobid_processReferences"]["total_references"], 1)
        self.assertEqual(by_source["refextract"]["status"], "error")
        self.assertEqual(by_source["crossref"]["status"], "skipped")
        self.assertTrue(by_source["crossref"]["doi_available"] is False)
        self.assertEqual(by_source["semantic_scholar"]["status"], "skipped")

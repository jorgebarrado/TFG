from __future__ import annotations

from django.test import SimpleTestCase

from citations.services.reference_pipeline.author_year import (
    run_author_year_rich_pipeline,
)
from citations.services.reference_pipeline.common import build_bibliography_zone
from citations.services.reference_pipeline.numeric import run_numeric_rich_pipeline
from citations.services.reference_pipeline.router import (
    build_document_profile,
    route_reference_pipeline,
)
from citations.services.references_data import build_references_data


def make_row(
    *,
    row_id: str,
    text: str,
    page: int = 0,
    x: float = 0.1,
    y: float = 0.1,
    w: float = 0.8,
    h: float = 0.03,
    column_id: str = "left",
    flow_position: int = 0,
) -> dict:
    return {
        "id": row_id,
        "text": text,
        "page": page,
        "box": [x, y, w, h],
        "column_id": column_id,
        "x0": x,
        "y0": y,
        "x1": x + w,
        "y1": y + h,
        "width": w,
        "height": h,
        "flow_position": flow_position,
    }


def make_segment(page: int = 0) -> list[dict]:
    return [
        {
            "page": page,
            "column_id": "left",
            "box": [0.05, 0.05, 0.9, 0.9],
            "confidence": 0.9,
            "source": "test",
            "row_count": 10,
        }
    ]


class NumericPipelineTests(SimpleTestCase):
    def test_numeric_sequence_clear_and_coverage_high(self):
        stream_units = [
            make_row(
                row_id="n1",
                text="[1] Alpha, A. 2018. First Journal paper.",
                flow_position=0,
            ),
            make_row(
                row_id="n2",
                text="[2] Beta, B. 2019. Second Conference paper.",
                y=0.15,
                flow_position=1,
            ),
            make_row(
                row_id="n3",
                text="[3] Gamma, C. 2020. Third Review article.",
                y=0.2,
                flow_position=2,
            ),
        ]
        result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=[
                {"index": 1, "raw": "Alpha, A. 2018. First Journal paper."},
                {"index": 2, "raw": "Beta, B. 2019. Second Conference paper."},
                {"index": 3, "raw": "Gamma, C. 2020. Third Review article."},
            ],
            references_by_index={
                1: {"index": 1, "raw": "Alpha, A. 2018. First Journal paper."},
                2: {"index": 2, "raw": "Beta, B. 2019. Second Conference paper."},
                3: {"index": 3, "raw": "Gamma, C. 2020. Third Review article."},
            },
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        self.assertEqual(result["coverage_audit"]["expected_indices"], [1, 2, 3])
        self.assertEqual(result["coverage_audit"]["serialized_indices"], [1, 2, 3])
        self.assertEqual(result["coverage_audit"]["extraction_status"], "complete")
        self.assertTrue(
            all(candidate["status"] != "failed" for candidate in result["reference_candidates"])
        )

    def test_numeric_mixed_row_is_split_into_two_candidates(self):
        stream_units = [
            make_row(
                row_id="m1",
                text="[21] Alpha, A. 2018. First paper. [22] Beta, B. 2019. Second paper.",
                flow_position=0,
            )
        ]
        result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        candidate_21 = next(item for item in result["reference_candidates"] if item["index"] == 21)
        candidate_22 = next(item for item in result["reference_candidates"] if item["index"] == 22)
        self.assertNotIn("[22]", candidate_21["repaired_text"])
        self.assertTrue(candidate_22["repaired_text"].startswith("[22]"))

    def test_numeric_truncated_candidate_extends_with_continuation_row(self):
        stream_units = [
            make_row(
                row_id="t1",
                text="[5] Example, E. 2021. Computa-",
                flow_position=0,
            ),
            make_row(
                row_id="t2",
                text="tional Thinking Journal article.",
                y=0.14,
                flow_position=1,
            ),
            make_row(
                row_id="t3",
                text="[6] Next, N. 2022. Independent paper.",
                y=0.18,
                flow_position=2,
            ),
        ]
        result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        candidate_5 = next(item for item in result["reference_candidates"] if item["index"] == 5)
        self.assertIn("Thinking Journal", candidate_5["repaired_text"])
        self.assertGreaterEqual(
            len(candidate_5.get("repaired_rows") or candidate_5.get("raw_rows") or []),
            2,
        )

    def test_numeric_ambiguous_case_ends_failed(self):
        stream_units = [
            make_row(
                row_id="a1",
                text="[7] [8] [9] broken row with several anchors and no bibliographic body",
                flow_position=0,
            )
        ]
        result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        candidate_7 = next(item for item in result["reference_candidates"] if item["index"] == 7)
        self.assertEqual(candidate_7["status"], "failed")

    def test_numeric_low_coverage_is_inconsistent(self):
        stream_units = [
            make_row(
                row_id="c1",
                text="[1] First 2018 journal paper.",
                flow_position=0,
            ),
            make_row(
                row_id="c2",
                text="[4] Fourth 2021 review paper.",
                y=0.2,
                flow_position=1,
            ),
        ]
        result = run_numeric_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        self.assertEqual(result["coverage_audit"]["expected_indices"], [1, 2, 3, 4])
        self.assertEqual(result["coverage_audit"]["extraction_status"], "inconsistent")
        self.assertIn(2, result["coverage_audit"]["missing_indices"])


class AuthorYearPipelineTests(SimpleTestCase):
    def test_author_year_clean_entries_detected(self):
        stream_units = [
            make_row(
                row_id="ay1",
                text="Smith, J. (2020). Example study. Journal of Examples.",
                flow_position=0,
            ),
            make_row(
                row_id="ay2",
                text="Brown, A. (2021). Another study. Conference on Examples.",
                y=0.15,
                flow_position=1,
            ),
        ]
        result = run_author_year_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        self.assertEqual(len(result["reference_candidates"]), 2)
        self.assertTrue(
            all(candidate["status"] != "failed" for candidate in result["reference_candidates"])
        )

    def test_author_year_glued_entries_are_separated(self):
        stream_units = [
            make_row(
                row_id="ayg1",
                text="Smith, J. (2020). Example study. Brown, A. (2021). Another study.",
                flow_position=0,
            )
        ]
        result = run_author_year_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        self.assertEqual(len(result["reference_candidates"]), 2)
        self.assertTrue(
            result["reference_candidates"][0]["repaired_text"].startswith("Smith, J. (2020)")
        )
        self.assertTrue(
            result["reference_candidates"][1]["repaired_text"].startswith("Brown, A. (2021)")
        )

    def test_author_year_truncated_entry_extends(self):
        stream_units = [
            make_row(
                row_id="ayt1",
                text="Smith, J. (2020). Computational thinking in software",
                flow_position=0,
            ),
            make_row(
                row_id="ayt2",
                text="engineering. Journal of Practice.",
                y=0.14,
                flow_position=1,
            ),
            make_row(
                row_id="ayt3",
                text="Brown, A. (2021). Another study. Journal of Examples.",
                y=0.18,
                flow_position=2,
            ),
        ]
        result = run_author_year_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        first_candidate = result["reference_candidates"][0]
        self.assertIn("Journal of Practice", first_candidate["repaired_text"])
        self.assertGreaterEqual(
            len(first_candidate.get("repaired_rows") or first_candidate.get("raw_rows") or []),
            2,
        )

    def test_author_year_ambiguous_case_fails(self):
        stream_units = [
            make_row(
                row_id="aya1",
                text="Notes appendix data and additional comments without clear bibliographic structure",
                flow_position=0,
            )
        ]
        result = run_author_year_rich_pipeline(
            stream_units=stream_units,
            references=[],
            references_by_index={},
            bibliography_segments=make_segment(),
            tokens_by_page={},
            crossref_context={},
        )
        self.assertEqual(len(result["reference_candidates"]), 1)
        self.assertEqual(result["reference_candidates"][0]["status"], "failed")


class RouterTests(SimpleTestCase):
    def test_router_classifies_numeric_rich(self):
        rows = [
            make_row(row_id="r0", text="References", flow_position=0),
            make_row(row_id="r1", text="[1] Alpha 2018. Journal.", y=0.14, flow_position=1),
            make_row(row_id="r2", text="[2] Beta 2019. Journal.", y=0.18, flow_position=2),
            make_row(row_id="r3", text="[3] Gamma 2020. Journal.", y=0.22, flow_position=3),
        ]
        profile_payload = build_document_profile(
            row_items=rows,
            token_items=[{"id": f"t{i}"} for i in range(80)],
            section_items=[make_row(row_id="s0", text="References")],
            bibliography_items=[{"id": "b0", "page": 0, "box": [0.05, 0.05, 0.9, 0.9], "text": "References"}],
        )
        routed = route_reference_pipeline(
            profile_payload["document_profile"],
            routing_inputs=profile_payload["routing_inputs"],
        )
        self.assertEqual(routed["document_profile"]["document_mode"], "numeric_rich")

    def test_router_classifies_author_year_rich(self):
        rows = [
            make_row(row_id="r0", text="References", flow_position=0),
            make_row(
                row_id="r1",
                text="Smith, J. (2020). Example journal article.",
                y=0.14,
                flow_position=1,
            ),
            make_row(
                row_id="r2",
                text="Brown, A. (2021). Conference article.",
                y=0.18,
                flow_position=2,
            ),
        ]
        profile_payload = build_document_profile(
            row_items=rows,
            token_items=[{"id": f"t{i}"} for i in range(80)],
            section_items=[make_row(row_id="s0", text="References")],
            bibliography_items=[{"id": "b0", "page": 0, "box": [0.05, 0.05, 0.9, 0.9], "text": "References"}],
        )
        routed = route_reference_pipeline(
            profile_payload["document_profile"],
            routing_inputs=profile_payload["routing_inputs"],
        )
        self.assertEqual(routed["document_profile"]["document_mode"], "author_year_rich")

    def test_router_classifies_weak_or_unknown(self):
        rows = [
            make_row(row_id="r0", text="Appendix", flow_position=0),
            make_row(row_id="r1", text="Notes and comments", y=0.14, flow_position=1),
        ]
        profile_payload = build_document_profile(
            row_items=rows,
            token_items=[],
            section_items=[],
            bibliography_items=[],
        )
        routed = route_reference_pipeline(
            profile_payload["document_profile"],
            routing_inputs=profile_payload["routing_inputs"],
        )
        self.assertEqual(routed["document_profile"]["document_mode"], "weak_or_unknown")

    def test_router_prioritizes_heading_window_over_numeric_noise(self):
        rows = [
            make_row(row_id="b0", text="1. Introduction", page=0, flow_position=0),
            make_row(row_id="b1", text="2. Related work", page=1, flow_position=1),
            make_row(row_id="h0", text="References", page=9, y=0.08, flow_position=2),
            make_row(
                row_id="r1",
                text="Smith, J. (2020). Example journal article.",
                page=9,
                y=0.14,
                flow_position=3,
            ),
            make_row(
                row_id="r2",
                text="Brown, A. (2021). Conference article.",
                page=9,
                y=0.18,
                flow_position=4,
            ),
        ]
        profile_payload = build_document_profile(
            row_items=rows,
            token_items=[{"id": f"t{i}"} for i in range(160)],
            section_items=[make_row(row_id="s0", text="References", page=9)],
            bibliography_items=[{"id": "b0", "page": 9, "box": [0.05, 0.05, 0.9, 0.9], "text": "References"}],
        )
        routed = route_reference_pipeline(
            profile_payload["document_profile"],
            routing_inputs=profile_payload["routing_inputs"],
        )
        self.assertEqual(profile_payload["routing_inputs"]["profile_row_source"], "heading_window")
        self.assertEqual(routed["document_profile"]["document_mode"], "author_year_rich")


class BibliographyZoneTests(SimpleTestCase):
    def test_zone_fallback_builds_row_based_segments_per_column(self):
        rows = [
            make_row(
                row_id="ack1",
                text="Acknowledgements and project support details.",
                page=5,
                x=0.1,
                y=0.16,
                w=0.32,
                column_id="left",
            ),
            make_row(
                row_id="ack2",
                text="Additional notes without bibliographic structure.",
                page=5,
                x=0.1,
                y=0.21,
                w=0.32,
                column_id="left",
            ),
            make_row(
                row_id="ref1",
                text="Smith, J. (2020). Example journal article.",
                page=5,
                x=0.56,
                y=0.16,
                w=0.32,
                column_id="right",
            ),
            make_row(
                row_id="ref2",
                text="Brown, A. (2021). Conference on Examples.",
                page=5,
                x=0.56,
                y=0.21,
                w=0.32,
                column_id="right",
            ),
        ]
        zone_payload = build_bibliography_zone(
            row_items=rows,
            section_items=[],
            paragraph_items=[],
            bibliography_items=[
                {
                    "id": "bib0",
                    "page": 5,
                    "box": [0.08, 0.12, 0.84, 0.18],
                    "text": "References and bibliography area",
                }
            ],
        )
        self.assertTrue(zone_payload["bibliography_segments"])
        self.assertTrue(
            all(
                segment["source"] == "bibliography_layer_rows_fallback"
                for segment in zone_payload["bibliography_segments"]
            )
        )
        self.assertTrue(
            all(
                "Acknowledgements" not in str(segment.get("raw_text") or "")
                for segment in zone_payload["bibliography_segments"]
            )
        )


class PublicContractRegressionTests(SimpleTestCase):
    def test_build_references_data_preserves_clean_numeric_case(self):
        layers = {
            "rows": [
                {"id": "h0", "text": "References", "page": 0, "box": [0.1, 0.08, 0.8, 0.03]},
                {"id": "r1", "text": "[1] Alpha, A. 2018. First Journal paper.", "page": 0, "box": [0.1, 0.14, 0.8, 0.03]},
                {"id": "r2", "text": "[2] Beta, B. 2019. Second Conference paper.", "page": 0, "box": [0.1, 0.18, 0.8, 0.03]},
                {"id": "r3", "text": "[3] Gamma, C. 2020. Third Review article.", "page": 0, "box": [0.1, 0.22, 0.8, 0.03]},
                {"id": "body", "text": "We build on [2] for our method.", "page": 1, "box": [0.1, 0.2, 0.8, 0.03]},
            ],
            "sections": [
                {"id": "s0", "text": "References", "page": 0, "box": [0.1, 0.08, 0.8, 0.03]}
            ],
            "paragraphs": [
                {"id": "p0", "text": "We build on [2] for our method.", "page": 1, "box": [0.08, 0.18, 0.84, 0.06]}
            ],
            "bibliographies": [
                {"id": "b0", "text": "References", "page": 0, "box": [0.05, 0.05, 0.9, 0.3]}
            ],
            "tokens": [],
        }
        result = build_references_data(
            references=[
                {"index": 1, "raw": "Alpha, A. 2018. First Journal paper."},
                {"index": 2, "raw": "Beta, B. 2019. Second Conference paper."},
                {"index": 3, "raw": "Gamma, C. 2020. Third Review article."},
            ],
            snippets=[{"id": "sn1", "page": 1, "snippet": "We build on [2] for our method."}],
            layers=layers,
            references_numbered=True,
            debug_reference_detection=True,
        )
        self.assertEqual(result["document_mode"], "numeric_rich")
        self.assertEqual(result["coverage_audit"]["extraction_status"], "complete")
        self.assertEqual(len(result["references"]), 3)
        self.assertTrue(all(reference["status"] != "failed" for reference in result["references"]))

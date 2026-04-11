from django.test import SimpleTestCase

from citations.services.references_data import (
    _build_numeric_reference_comparison_v2,
    _build_reference_rows_between_anchors_v2,
    _detect_numeric_anchor_candidates_v2,
    _build_document_diagnostics,
    _match_reference_anchor_at_line_start,
    _split_reference_row_on_anchors,
    build_references_data,
    is_numbered_bibliography,
)


class ReferenceAnchorDetectionTests(SimpleTestCase):
    def test_existing_bracketed_and_dotted_styles_still_match(self):
        bracketed = _match_reference_anchor_at_line_start(
            "[1] Smith, J., 2017. Computational thinking in practice."
        )
        dotted = _match_reference_anchor_at_line_start(
            "1. Smith, J., 2017. Computational thinking in practice."
        )

        self.assertIsNotNone(bracketed)
        self.assertEqual(bracketed["anchor_style"], "bracketed")
        self.assertTrue(bracketed["accepted"])
        self.assertEqual(bracketed["index"], 1)

        self.assertIsNotNone(dotted)
        self.assertEqual(dotted["anchor_style"], "dotted")
        self.assertTrue(dotted["accepted"])
        self.assertEqual(dotted["index"], 1)

    def test_new_suffix_and_wrapped_paren_styles_match(self):
        suffix_paren = _match_reference_anchor_at_line_start(
            "1) Smith, J., 2017. Computational thinking in practice."
        )
        wrapped_paren = _match_reference_anchor_at_line_start(
            "(1) Smith, J., 2017. Computational thinking in practice."
        )

        self.assertIsNotNone(suffix_paren)
        self.assertEqual(suffix_paren["anchor_style"], "suffix_paren")
        self.assertTrue(suffix_paren["accepted"])
        self.assertEqual(suffix_paren["index"], 1)

        self.assertIsNotNone(wrapped_paren)
        self.assertEqual(wrapped_paren["anchor_style"], "wrapped_paren")
        self.assertTrue(wrapped_paren["accepted"])
        self.assertEqual(wrapped_paren["index"], 1)

    def test_new_paren_styles_reject_year_like_and_doi_like_candidates(self):
        year_like = _match_reference_anchor_at_line_start(
            "(2017) Smith, J., Doe, A., and Roe, P.",
            include_rejected=True,
        )
        doi_like = _match_reference_anchor_at_line_start(
            "1) doi 10.1145/1234567.1234568",
            include_rejected=True,
        )

        self.assertIsNotNone(year_like)
        self.assertEqual(year_like["anchor_style"], "wrapped_paren")
        self.assertFalse(year_like["accepted"])
        self.assertEqual(year_like["anchor_rejected_reason"], "year_like")

        self.assertIsNotNone(doi_like)
        self.assertEqual(doi_like["anchor_style"], "suffix_paren")
        self.assertFalse(doi_like["accepted"])
        self.assertEqual(doi_like["anchor_rejected_reason"], "doi_like")

    def test_new_paren_styles_reject_non_bibliographic_internal_numbering(self):
        internal_numbering = _match_reference_anchor_at_line_start(
            "1) Introduction",
            include_rejected=True,
        )

        self.assertIsNotNone(internal_numbering)
        self.assertEqual(internal_numbering["anchor_style"], "suffix_paren")
        self.assertFalse(internal_numbering["accepted"])
        self.assertEqual(
            internal_numbering["anchor_rejected_reason"],
            "weak_bibliographic_signal",
        )

    def test_split_reference_row_on_new_paren_styles(self):
        parts = _split_reference_row_on_anchors(
            {
                "id": "row-1",
                "text": (
                    "1) Smith, J., 2017. Computational thinking in practice. "
                    "2) Doe, A., 2018. Another bibliographic entry."
                ),
            }
        )

        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0]["text"].startswith("1)"))
        self.assertTrue(parts[1]["text"].startswith("2)"))

    def test_numbered_diagnostics_track_new_anchor_styles_and_dominant_style(self):
        bibliography_lines = [
            {"text": "1) Smith, J., 2017. Computational thinking in practice."},
            {"text": "2) Doe, A., 2018. Another bibliographic entry."},
            {"text": "3) Roe, P., 2019. Yet another bibliographic entry."},
            {"text": "4) Poe, Q., 2020. Final bibliographic entry."},
            {"text": "5) Moe, T., 2021. Additional bibliographic entry."},
            {"text": "6) Foe, R., 2022. Closing bibliographic entry."},
        ]
        bibliography_rows_debug = [
            {
                "page": 5,
                "included": True,
                "anchor_style": "suffix_paren",
                "anchor_candidate_style": "suffix_paren",
                "anchor_rejected_reason": None,
                "text": bibliography_lines[0]["text"],
            },
            {
                "page": 5,
                "included": True,
                "anchor_style": "suffix_paren",
                "anchor_candidate_style": "suffix_paren",
                "anchor_rejected_reason": None,
                "text": bibliography_lines[1]["text"],
            },
            {
                "page": 5,
                "included": True,
                "anchor_style": "suffix_paren",
                "anchor_candidate_style": "suffix_paren",
                "anchor_rejected_reason": None,
                "text": bibliography_lines[2]["text"],
            },
            {
                "page": 5,
                "included": True,
                "anchor_style": "wrapped_paren",
                "anchor_candidate_style": "wrapped_paren",
                "anchor_rejected_reason": None,
                "text": "(4) Poe, Q., 2020. Final bibliographic entry.",
            },
        ]

        diagnostics = _build_document_diagnostics(
            bibliography_rows_debug=bibliography_rows_debug,
            bibliography_lines=bibliography_lines,
            bibliography_segments=[{"page": 5}, {"page": 6}],
            selected_heading={"text": "References"},
            start_page=5,
        )

        self.assertTrue(is_numbered_bibliography(bibliography_lines))
        self.assertEqual(diagnostics["reference_style_detected"], "numeric")
        self.assertEqual(diagnostics["anchor_style_detected"], "suffix_paren")
        self.assertEqual(
            diagnostics["reference_style_signals"]["suffix_paren_anchor_rows"],
            3,
        )
        self.assertEqual(
            diagnostics["reference_style_signals"]["wrapped_paren_anchor_rows"],
            1,
        )
        self.assertEqual(
            diagnostics["reference_style_signals"]["bracketed_anchor_rows"],
            0,
        )
        self.assertEqual(
            diagnostics["reference_style_signals"]["dotted_anchor_rows"],
            0,
        )

    def test_v2_recovers_split_anchor_from_following_row(self):
        ordered_rows = [
            {
                "id": "row-1",
                "page": 5,
                "flow_position": 0,
                "text": "12.",
            },
            {
                "id": "row-2",
                "page": 5,
                "flow_position": 1,
                "text": "Smith, J., 2020. Robust reference extraction for PDFs.",
            },
        ]

        candidates = _detect_numeric_anchor_candidates_v2(ordered_rows)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["index"], 12)
        self.assertEqual(candidates[0]["strength"], "weak")
        self.assertTrue(candidates[0]["body_in_next_row"])

    def test_v2_reference_growth_allows_page_continuation(self):
        ordered_rows = [
            {
                "id": "row-1",
                "page": 7,
                "text": "[3] Smith, J., 2020. A long reference that",
                "box": [0.1, 0.72, 0.7, 0.03],
                "x0": 0.1,
                "x1": 0.8,
                "y0": 0.72,
                "y1": 0.75,
                "reading_unit_id": "unit-7-left",
                "flow_position": 0,
            },
            {
                "id": "row-2",
                "page": 7,
                "text": "continues on the next page without a new anchor.",
                "box": [0.13, 0.76, 0.67, 0.03],
                "x0": 0.13,
                "x1": 0.8,
                "y0": 0.76,
                "y1": 0.79,
                "reading_unit_id": "unit-7-left",
                "flow_position": 1,
            },
            {
                "id": "row-3",
                "page": 8,
                "text": "Journal of Testing, 10(2), 1-12.",
                "box": [0.1, 0.08, 0.7, 0.03],
                "x0": 0.1,
                "x1": 0.8,
                "y0": 0.08,
                "y1": 0.11,
                "reading_unit_id": "unit-8-left",
                "flow_position": 2,
            },
        ]

        block = _build_reference_rows_between_anchors_v2(
            ordered_rows=ordered_rows,
            current_anchor={"index": 3, "position": 0},
            next_anchor=None,
            anchor_candidates_by_position={},
            artifact_info={"repeated_text_keys": set()},
        )

        self.assertEqual(len(block["rows"]), 3)
        self.assertTrue(block["continuation_between_pages"])
        self.assertEqual(block["closure_reason"], "reading_flow_exhausted")

    def test_v2_comparison_marks_regression_when_accepted_reference_is_lost(self):
        current_entries = [
            {
                "index": 4,
                "structure_source": "rows_raw",
                "rows": [{"page": 2}, {"page": 3}],
                "final_decision": {"accepted": True, "reason": "rows_structure_consistent"},
                "reference_validation": {"has_nested_anchor": False},
                "text": "Current reference text.",
            }
        ]
        experimental_entries = [
            {
                "index": 4,
                "structure_source": "raw_reference_fallback",
                "rows": [{"page": 2}],
                "final_decision": {"accepted": False, "reason": "fallback_without_rows_structure"},
                "reference_validation": {"has_nested_anchor": False},
                "text": "Fallback text.",
            }
        ]

        comparison = _build_numeric_reference_comparison_v2(
            current_entries=current_entries,
            experimental_entries=experimental_entries,
            current_metrics={"pct_accepted": 100.0},
            experimental_metrics={"pct_accepted": 0.0},
        )

        self.assertEqual(comparison["status"], "regression_detected")
        regression_types = {item["type"] for item in comparison["regressions"]}
        self.assertIn("accepted_reference_lost", regression_types)
        self.assertIn("new_raw_fallback", regression_types)
        self.assertIn("page_continuation_lost", regression_types)

    def test_build_references_data_exposes_v2_without_replacing_current_output(self):
        references = [
            {"index": 1, "raw": "[1] Smith, J., 2020. First title. Journal of Testing 1(1), 1-10."},
            {"index": 2, "raw": "[2] Doe, A., 2021. Second title. Conference on Testing, 11-20."},
        ]
        layers = {
            "rows": [
                {"id": "h1", "page": 0, "text": "References", "box": [0.1, 0.12, 0.2, 0.03]},
                {"id": "r1", "page": 0, "text": "[1] Smith, J., 2020. First title.", "box": [0.1, 0.2, 0.75, 0.03]},
                {"id": "r2", "page": 0, "text": "Journal of Testing 1(1), 1-10.", "box": [0.13, 0.24, 0.72, 0.03]},
                {"id": "r3", "page": 1, "text": "[2] Doe, A., 2021. Second title.", "box": [0.1, 0.08, 0.75, 0.03]},
                {"id": "r4", "page": 1, "text": "Conference on Testing, 11-20.", "box": [0.13, 0.12, 0.72, 0.03]},
            ],
            "sections": [
                {"id": "s1", "page": 0, "text": "References", "box": [0.1, 0.12, 0.2, 0.03]},
            ],
            "bibliographies": [
                {"id": "b1", "page": 0, "text": "", "box": [0.08, 0.18, 0.8, 0.14]},
                {"id": "b2", "page": 1, "text": "", "box": [0.08, 0.06, 0.8, 0.12]},
            ],
            "tokens": [],
            "paragraphs": [],
        }

        payload = build_references_data(
            references=references,
            snippets=[],
            layers=layers,
            references_numbered=True,
            debug_reference_detection=True,
        )

        self.assertEqual(len(payload["references"]), 2)
        self.assertTrue(all(item["index"] in {1, 2} for item in payload["references"]))
        debug_payload = payload["debug_payload"]
        self.assertIn("numeric_pipeline_current_metrics", debug_payload)
        self.assertIn("numeric_reference_pipeline_v2", debug_payload)
        self.assertFalse(debug_payload["numeric_reference_pipeline_v2"]["selected_as_default"])

from django.test import SimpleTestCase

from citations.services.references_data import (
    _build_document_diagnostics,
    _match_reference_anchor_at_line_start,
    _split_reference_row_on_anchors,
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

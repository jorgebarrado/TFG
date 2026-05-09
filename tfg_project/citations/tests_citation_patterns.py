"""Tests de regresion para `citations.services.citation_patterns`.

El objetivo es cubrir todas las formas de cita in-text que un humano resaltaria
manualmente al leer un paper academico, asegurando que el detector las
encuentra y descartando falsos positivos clasicos (Section/Figure (year)).
"""

from __future__ import annotations

import unicodedata

from django.test import SimpleTestCase

from citations.services.citation_patterns import (
    expand_numeric_block,
    find_citation_matches,
    infer_numeric_style,
    is_valid_numeric_citation,
    max_reference_index,
)


def _types(text):
    return [hit["type"] for hit in find_citation_matches(text)]


def _matches(text):
    return [hit["match"] for hit in find_citation_matches(text)]


class NumericCitationDetectionTests(SimpleTestCase):
    def test_single_numeric(self):
        self.assertEqual(_matches("As shown in [12] this works."), ["[12]"])

    def test_comma_list(self):
        self.assertEqual(_matches("Multiple results [1, 2, 3] hold."), ["[1, 2, 3]"])

    def test_semicolon_list(self):
        self.assertEqual(_matches("See [1; 2; 3]."), ["[1; 2; 3]"])

    def test_range_with_hyphen(self):
        self.assertEqual(_matches("Cited in [1-3]."), ["[1-3]"])

    def test_range_with_en_dash(self):
        self.assertEqual(_matches("Cited in [1–3]."), ["[1–3]"])

    def test_range_with_em_dash(self):
        self.assertEqual(_matches("Cited in [1—3]."), ["[1—3]"])

    def test_mixed(self):
        hits = find_citation_matches("See [1, 3-5; 7].")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["citation_numbers"], [1, 3, 4, 5, 7])

    def test_filter_by_total_references(self):
        # Si el paper tiene 30 refs, [42] no debe aceptarse cuando style=numeric.
        text = "See [3] and [42]."
        accepted = [
            h["match"]
            for h in find_citation_matches(
                text, citation_style="numeric", total_references=30
            )
        ]
        self.assertEqual(accepted, ["[3]"])

    def test_no_filter_when_style_unknown(self):
        text = "See [3] and [42]."
        self.assertEqual(
            sorted(_matches(text)),
            sorted(["[3]", "[42]"]),
        )


class AuthorYearNarrativeTests(SimpleTestCase):
    def test_simple_narrative(self):
        self.assertEqual(_matches("Smith (2020) showed."), ["Smith (2020)"])

    def test_et_al_narrative(self):
        self.assertEqual(
            _matches("As Smith et al. (2020) demonstrated."),
            ["Smith et al. (2020)"],
        )

    def test_two_authors_and(self):
        self.assertEqual(
            _matches("Smith and Jones (2020) extended this."),
            ["Smith and Jones (2020)"],
        )

    def test_two_authors_ampersand(self):
        self.assertEqual(
            _matches("Smith & Jones (2020) extended this."),
            ["Smith & Jones (2020)"],
        )

    def test_multiple_years(self):
        self.assertEqual(
            _matches("Smith (2020, 2021) reviewed the topic."),
            ["Smith (2020, 2021)"],
        )

    def test_year_with_suffix(self):
        self.assertEqual(_matches("Smith (2020a) and Smith (2020b)."), [
            "Smith (2020a)",
            "Smith (2020b)",
        ])


class AuthorYearParentheticalTests(SimpleTestCase):
    def test_simple_paren(self):
        self.assertEqual(_matches("It was confirmed (Smith, 2020)."), ["(Smith, 2020)"])

    def test_paren_no_comma(self):
        # Algunos estilos omiten la coma: (Brown 2019).
        self.assertEqual(_matches("It was confirmed (Brown 2019)."), ["(Brown 2019)"])

    def test_et_al_paren(self):
        self.assertEqual(
            _matches("Confirmed (Smith et al., 2020)."),
            ["(Smith et al., 2020)"],
        )

    def test_two_authors_and(self):
        self.assertEqual(
            _matches("(Smith and Jones, 2020)"),
            ["(Smith and Jones, 2020)"],
        )

    def test_three_authors_enumerated(self):
        self.assertEqual(
            _matches("(Smith, Jones, & Doe, 2020)"),
            ["(Smith, Jones, & Doe, 2020)"],
        )

    def test_multi_citation_stack(self):
        self.assertEqual(
            _matches("(Smith, 2020; Jones, 2021; Doe et al., 2022)"),
            ["(Smith, 2020; Jones, 2021; Doe et al., 2022)"],
        )

    def test_year_suffixes(self):
        self.assertEqual(
            _matches("(Smith, 2020a; Smith, 2020b)"),
            ["(Smith, 2020a; Smith, 2020b)"],
        )

    def test_diacritics(self):
        self.assertEqual(
            _matches("(García et al., 2020)"),
            ["(García et al., 2020)"],
        )

    def test_apostrophe_in_name(self):
        self.assertEqual(_matches("(O'Brien, 2021)"), ["(O'Brien, 2021)"])

    def test_hyphenated_name(self):
        self.assertEqual(
            _matches("(Jiménez-García, 2020)"),
            ["(Jiménez-García, 2020)"],
        )

    def test_decomposed_diacritic(self):
        # NFKD descompone Garcia en Garc + i + combinante; el regex debe seguir
        # cazandolo (espejo exacto del comportamiento del frontend).
        decomposed = unicodedata.normalize("NFKD", "García et al. (2020)")
        hits = find_citation_matches(decomposed)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "authoryear")


class FalsePositiveSuppressionTests(SimpleTestCase):
    def test_section_year_dataset(self):
        # "Section 3 (2020 dataset)" no es una cita real.
        self.assertEqual(find_citation_matches("See Section 3 (2020 dataset)."), [])

    def test_figure_year(self):
        self.assertEqual(find_citation_matches("Cf. Figure 4 (2020)."), [])

    def test_table_year(self):
        self.assertEqual(find_citation_matches("Table 7 (2020) summarises."), [])

    def test_equation_year(self):
        self.assertEqual(find_citation_matches("Equation 12 (2020) yields."), [])

    def test_unrelated_parenthesis(self):
        # Texto sin nombre propio antes del parentesis no debe matchear.
        self.assertEqual(find_citation_matches("we report (the year 2020)"), [])


class DoiDetectionTests(SimpleTestCase):
    def test_simple_doi(self):
        hits = find_citation_matches("See doi:10.1145/abc.123 here.")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "doi")
        self.assertEqual(hits[0]["match"], "10.1145/abc.123")

    def test_doi_strips_trailing_period(self):
        hits = find_citation_matches("Reference 10.1109/MC.2020.123456.")
        self.assertEqual(hits[0]["match"], "10.1109/MC.2020.123456")

    def test_doi_strips_trailing_paren(self):
        hits = find_citation_matches("Reference (10.1109/MC.2020.123456).")
        self.assertEqual(hits[0]["match"], "10.1109/MC.2020.123456")

    def test_doi_with_complex_suffix(self):
        text = "DOI 10.1016/j.compedu.2017.05.014 was used."
        hits = find_citation_matches(text)
        self.assertEqual(hits[0]["match"], "10.1016/j.compedu.2017.05.014")


class MixedParagraphTests(SimpleTestCase):
    def test_numeric_and_authoryear_in_same_paragraph(self):
        text = (
            "Smith et al. (2020) and (Jones, 2021) reported similar results, "
            "see also [3, 5-7]. Earlier work (García, 2018) is consistent."
        )
        types = _types(text)
        self.assertIn("authoryear", types)
        self.assertIn("numeric", types)
        # Tres citas autor-anio + una numerica.
        self.assertEqual(types.count("authoryear"), 3)
        self.assertEqual(types.count("numeric"), 1)

    def test_no_overlap_between_authoryear_styles(self):
        # "Smith (2020)" detectado solo una vez aunque encaje narrativo y
        # parentetico no aplica aqui.
        hits = find_citation_matches("Result by Smith (2020) was confirmed.")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["match"], "Smith (2020)")

    def test_doi_and_authoryear_not_double_counted(self):
        # Si una cita contiene un DOI dentro, no se duplican.
        text = "See Smith (2020) [doi: 10.1145/abc.999]."
        hits = find_citation_matches(text)
        kinds = [h["type"] for h in hits]
        self.assertIn("authoryear", kinds)
        self.assertIn("doi", kinds)
        # No deben solaparse.
        for i, hit in enumerate(hits):
            for other in hits[i + 1 :]:
                self.assertFalse(
                    hit["start"] < other["end"] and hit["end"] > other["start"],
                    f"Hits overlap: {hit} vs {other}",
                )


class NumericExpansionTests(SimpleTestCase):
    def test_simple(self):
        self.assertEqual(expand_numeric_block("[1, 2, 3]"), [1, 2, 3])

    def test_range(self):
        self.assertEqual(expand_numeric_block("[1-4]"), [1, 2, 3, 4])

    def test_range_descending(self):
        self.assertEqual(expand_numeric_block("[4-1]"), [4, 3, 2, 1])

    def test_huge_range_is_capped(self):
        # Los rangos absurdos (errores de OCR) se acotan a 50 elementos.
        result = expand_numeric_block("[1-9999]", max_span=50)
        self.assertEqual(len(result), 50)

    def test_dedup(self):
        self.assertEqual(expand_numeric_block("[1, 2, 1, 3, 2]"), [1, 2, 3])

    def test_unicode_dashes(self):
        self.assertEqual(expand_numeric_block("[1–3]"), [1, 2, 3])
        self.assertEqual(expand_numeric_block("[1—3]"), [1, 2, 3])


class StyleInferenceTests(SimpleTestCase):
    def test_numeric_style_from_indices(self):
        refs = [{"index": 1}, {"index": 2}, {"index": 3}]
        self.assertTrue(infer_numeric_style(refs))

    def test_no_numeric_when_first_index_missing(self):
        refs = [{"index": 2}, {"index": 3}, {"index": 5}]
        self.assertFalse(infer_numeric_style(refs))

    def test_max_reference_index(self):
        refs = [{"index": 1}, {"index": 7}, {"index": 3}]
        self.assertEqual(max_reference_index(refs), 7)

    def test_is_valid_numeric_citation(self):
        self.assertTrue(is_valid_numeric_citation(5, 10))
        self.assertFalse(is_valid_numeric_citation(11, 10))
        self.assertFalse(is_valid_numeric_citation("abc", 10))
        self.assertFalse(is_valid_numeric_citation(0, 10))


class HitShapeContractTests(SimpleTestCase):
    def test_numeric_hit_shape(self):
        hits = find_citation_matches("See [3, 5-6].")
        self.assertEqual(len(hits), 1)
        h = hits[0]
        self.assertEqual(h["type"], "numeric")
        for key in ("match", "start", "end", "snippet", "confidence",
                    "citation_block", "citation_numbers"):
            self.assertIn(key, h)
        self.assertEqual(h["citation_numbers"], [3, 5, 6])

    def test_authoryear_hit_shape(self):
        hits = find_citation_matches("Smith et al. (2020) said so.")
        h = hits[0]
        self.assertEqual(h["type"], "authoryear")
        self.assertIn("authors", h)
        self.assertIn("years", h)
        self.assertEqual(h["years"], ["2020"])

    def test_doi_hit_shape(self):
        hits = find_citation_matches("doi: 10.1145/abc.123")
        h = hits[0]
        self.assertEqual(h["type"], "doi")
        self.assertEqual(h["doi"], "10.1145/abc.123")
        self.assertEqual(h["match"], "10.1145/abc.123")

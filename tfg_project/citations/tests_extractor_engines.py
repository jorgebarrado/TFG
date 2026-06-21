from django.test import SimpleTestCase

from citations.services.engines import (
    ALLOWED_ENGINES,
    list_extractor_engines,
    run_engine,
)


class ExtractorEngineContractTests(SimpleTestCase):
    def test_only_papermage_is_publicly_available(self):
        self.assertEqual(ALLOWED_ENGINES, {"papermage"})
        self.assertEqual(
            [engine["key"] for engine in list_extractor_engines()],
            ["papermage"],
        )

    def test_removed_engines_are_rejected_without_fallback(self):
        for removed_engine in ("generic", "papercraft", "auto"):
            engine_used, paragraphs, attempts, error, paragraphs_with_positions = (
                run_engine(removed_engine, "unused.pdf")
            )

            self.assertIsNone(engine_used)
            self.assertEqual(paragraphs, [])
            self.assertEqual(attempts, [])
            self.assertEqual(paragraphs_with_positions, [])
            self.assertIn("no soportado", error)

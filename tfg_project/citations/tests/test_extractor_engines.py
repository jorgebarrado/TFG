# Tests del contrato publico de extractor engines: motores listados y despacho no-IA.
from unittest import TestCase

from citations.services.ai_extractor import AI_ENGINES
from citations.management.commands.debug_grobid import Command as DebugGrobidCommand
from citations.services.engines import (
    ALLOWED_ENGINES,
    list_extractor_engines,
    run_engine,
)


class ExtractorEngineContractTests(TestCase):
    def test_public_engines_include_papermage_and_ai_options(self):
        self.assertEqual(ALLOWED_ENGINES, {"papermage", *AI_ENGINES})
        self.assertEqual(
            [engine["key"] for engine in list_extractor_engines()],
            ["papermage", "ai_claude", "ai_openai", "ai_gemini"],
        )

    def test_run_engine_rejects_removed_and_ai_engines_without_fallback(self):
        for removed_engine in ("generic", "papercraft", "auto", *AI_ENGINES):
            engine_used, paragraphs, attempts, error, paragraphs_with_positions = (
                run_engine(removed_engine, "unused.pdf")
            )

            self.assertIsNone(engine_used)
            self.assertEqual(paragraphs, [])
            self.assertEqual(attempts, [])
            self.assertEqual(paragraphs_with_positions, [])
            self.assertIn("no soportado", error)

    def test_debug_grobid_cli_does_not_offer_removed_engines(self):
        parser = DebugGrobidCommand().create_parser("manage.py", "debug_grobid")
        engine_action = next(
            action for action in parser._actions if "--engine" in action.option_strings
        )

        self.assertEqual(engine_action.choices, ["auto", "papermage"])

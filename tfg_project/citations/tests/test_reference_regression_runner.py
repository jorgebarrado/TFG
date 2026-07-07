# Tests del runner de regresion de referencias: arranque como script externo.
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "run_reference_regression.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_reference_regression as runner  # noqa: E402


def test_reference_regression_runner_help_bootstraps_from_repo_root():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("DJANGO_SETTINGS_MODULE", None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Runner de regresion" in result.stdout


def test_load_env_file_reads_explicit_file_without_overriding_existing_values(
    tmp_path,
    monkeypatch,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GOOGLE_API_KEY=test-gemini-key\nEXISTING_VALUE=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from-env")

    runner._load_env_file(env_path)

    assert os.environ["GOOGLE_API_KEY"] == "test-gemini-key"
    assert os.environ["EXISTING_VALUE"] == "from-env"


def test_run_single_extraction_uses_ai_extractor_for_ai_engines(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    ai_references = [
        {
            "index": 1,
            "text": "[1] Smith, J. A useful paper. 2020.",
            "source": "ai_extracted",
        }
    ]
    ai_results = [
        {
            "ref": 1,
            "idx": 1,
            "page": 1,
            "snippet": "Smith 2020",
            "paragraph": "Smith 2020 explains it.",
        }
    ]

    with (
        patch.object(
            runner,
            "extract_with_ai",
            return_value={
                "ok": True,
                "engine_used": "ai_gemini",
                "references": ai_references,
                "results": ai_results,
                "pages_total": 1,
                "citation_style": "numeric",
                "references_numbered": True,
                "max_reference_index": 1,
            },
            create=True,
        ) as extract_with_ai,
        patch.object(
            runner,
            "process_manuscript",
            side_effect=AssertionError("AI engines must not use process_manuscript"),
        ),
        patch.object(
            runner,
            "build_snippets_from_results",
            return_value=[{"ref": 1, "snippet": "Smith 2020"}],
        ),
        patch.object(
            runner,
            "extract_pdf_data",
            return_value={"pages": [{"page": 1}], "layers": {}},
        ),
        patch.object(
            runner,
            "build_references_data",
            return_value={
                "references": ai_references,
                "max_reference_index": 1,
                "debug_payload": {"metadata": {"document_mode": "ai"}},
            },
        ) as build_references_data,
    ):
        result = runner._run_single_extraction(
            pdf_path=pdf_path,
            paper_entry={"id": "paper-1", "dataset_type": "exploratory"},
            engine="ai_gemini",
        )

    extract_with_ai.assert_called_once_with("ai_gemini", str(pdf_path))
    build_references_data.assert_called_once()
    assert build_references_data.call_args.kwargs["references"] == ai_references
    extraction = result["extraction"]
    assert extraction["engine_effective"] == "ai_gemini"
    assert extraction["base_reference_count"] == 1
    assert extraction["base_reference_stats"]["references_numbered"] is True
    assert extraction["process_manuscript"]["results_total"] == 1

# Reference Parsing Experiment

This experiment is intentionally isolated from the application flow. It does not touch views, models, URLs, or frontend code.

## Goal

Compare three alternatives for parsing and enriching references that have already been segmented by the current extractor:

1. `refextract`
2. `anystyle`
3. `llm`

Primary path:

`PDF -> current extractor -> raw references -> alternative parser`

## Code layout

- `tfg_project/citations/services/reference_parsing_experiments/input_common.py`
  - Builds the shared input by calling `extract_pdf_references()` and writing `inputs/<paper>_raw_references.json`.
- `tfg_project/citations/services/reference_parsing_experiments/runners/refextract_runner.py`
  - Runs `refextract` in string mode over already segmented references.
- `tfg_project/citations/services/reference_parsing_experiments/runners/anystyle_runner.py`
  - Runs `anystyle parse` over one-reference-per-line text if the CLI is installed.
- `tfg_project/citations/services/reference_parsing_experiments/runners/llm_runner.py`
  - Builds a strict JSON prompt, validates the response, and stores prompt/raw response artifacts.
- `tfg_project/citations/services/reference_parsing_experiments/normalization.py`
  - Converts each parser output into a shared schema.
- `tfg_project/citations/services/reference_parsing_experiments/comparison.py`
  - Generates counts and side-by-side comparisons.
- `tfg_project/citations/services/reference_parsing_experiments/experiment.py`
  - Orchestrates the run and writes artifacts.
- `scripts/run_reference_parsing_experiment.py`
  - Standalone CLI entry point.

## Execution

From the repository root:

```powershell
.\.venv311\Scripts\python.exe scripts/run_reference_parsing_experiment.py
```

With explicit PDFs:

```powershell
.\.venv311\Scripts\python.exe scripts/run_reference_parsing_experiment.py `
  --pdf JScientometRes-14-3-838.pdf `
  --pdf 2023.emnlp-demo.45.pdf `
  --pdf Kelemen_Subramanian_19.09.2023.pdf
```

To inspect the curated default sample:

```powershell
.\.venv311\Scripts\python.exe scripts/run_reference_parsing_experiment.py --list-default-pdfs
```

## Artifacts

Each run is written to:

`tmp/reference_parser_experiments/<run_id>/`

Expected layout:

- `config.json`
- `summary.md`
- `summary.json`
- `inputs/<paper_slug>_raw_references.json`
- `refextract/<paper_slug>.json`
- `anystyle/<paper_slug>.json`
- `llm/<paper_slug>.json`
- `llm/<paper_slug>_prompt.txt`
- `llm/<paper_slug>_raw_response.txt`
- `comparisons/<paper_slug>.json`
- `comparisons/aggregate.json`

## Environment notes

- `refextract`
  - Validated in string mode over already segmented references.
  - In this Windows environment, the package imports `magic` even for string mode. The runner installs a local shim only for the experiment so the string API can execute. File-based `refextract` paths remain out of scope.
- `anystyle`
  - Not executable unless `anystyle` is installed and available on `PATH`.
  - The official CLI depends on Ruby/anystyle-cli.
- `llm`
  - Requires `OPENAI_API_KEY`.
  - The runner is compatible with both legacy and newer OpenAI Python SDK shapes, but it will not fabricate results when credentials are missing.

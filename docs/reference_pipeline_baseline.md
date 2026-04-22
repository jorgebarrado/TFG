# Reference Pipeline Baseline

Run the current end-to-end reference pipeline baseline with:

```powershell
.\.venv311\Scripts\python.exe tfg_project/manage.py test citations.tests_reference_pipeline_baseline
```

The baseline intentionally uses the current production flow:

1. `extract_pdf_references`
2. `process_manuscript`
3. `extract_pdf_data`
4. `build_references_data`

It covers two real PDFs already present in `tfg_project/citations/static/citations/PDFs-Reales`:

- `2017-CT-development-computational-thinking_RG.pdf`
- `JScientometRes-14-3-838.pdf`

The assertions use stable invariants: the pipeline completes, PaperMage layers exist, structured references are produced, citation style and max reference index are defined, debug payload keys are present, and a forced Crossref failure does not break the flow. The CT case also pins the current fallback count at zero.

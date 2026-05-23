# Reference Pipeline Baseline

La baseline del pipeline de referencias se ejecuta con:

```powershell
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
```

## Qué Cubre

El test usa el flujo de producción:

1. `extract_pdf_references`
2. `process_manuscript`
3. `extract_pdf_data`
4. `build_references_data`

PDFs cubiertos:

- `tfg_project/citations/static/citations/PDFs-Reales/2017-CT-development-computational-thinking_RG.pdf`
- `tfg_project/citations/static/citations/PDFs-Reales/JScientometRes-14-3-838.pdf`

## Invariantes

La prueba no intenta congelar toda la salida. Comprueba invariantes estables:

- el pipeline completa sin excepción;
- existen capas PaperMage;
- se producen referencias estructuradas;
- se define `citation_style`;
- se define `max_reference_index`;
- existen claves esperadas en `debug_payload`;
- un fallo forzado de Crossref no rompe el flujo;
- el caso CT conserva la cuenta de fallback actual.

## Cuándo Usarla

Ejecuta esta prueba al tocar:

- extracción de referencias;
- reconciliación;
- enriquecimiento DOI;
- capas del reader;
- motores;
- API de extracción del reader.

Para inspección más amplia usa también:

```powershell
python scripts/run_reference_regression.py --engine papermage --limit 1
```

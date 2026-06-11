# Tests y Verificación

Este documento resume la suite de tests de `tfg_project/citations/`, qué cubre cada módulo y qué conviene ejecutar según el tipo de cambio. Para estilo de código y pre-commit, consulta [STYLE.md](../STYLE.md).

## Ejecutar Tests

Suite completa de la app:

```powershell
python tfg_project/manage.py test citations
```

Un módulo concreto:

```powershell
python tfg_project/manage.py test citations.tests_citation_patterns
```

## Módulos de Test

| Módulo | Cubre |
| --- | --- |
| `tests.py` | Vistas básicas: home, listado, comentarios, guardados, votos y autenticación con allauth. |
| `tests_citation_patterns.py` | Detección de patrones de cita: numéricas (`[1]`, `[1,2]`, `[1-3]`), autor-año y variantes. |
| `tests_reference_pipeline_baseline.py` | Baseline del pipeline completo de referencias sobre PDFs reales. Ver [reference_pipeline_baseline.md](reference_pipeline_baseline.md). |
| `tests_reference_anchors.py` | Detección de anchors de referencia en bibliografías. |
| `tests_reference_reconciliation.py` | Reconciliación entre fuentes de referencias. |
| `tests_reference_source_inspection.py` | Inspección de fuentes de referencias. |
| `tests_compare_reference_sources.py` | Comparación de fuentes de referencias. |
| `tests_semantic_scholar_client.py` | Cliente Semantic Scholar, incluido manejo de API key. |
| `tests_dblp_client.py` | Cliente DBLP. |
| `tests_dblp_loading.py` | Carga de publicaciones DBLP en perfiles. |

## Qué Ejecutar Según el Cambio

| Cambio | Verificación mínima |
| --- | --- |
| Vistas HTML, plantillas, comunidad | `manage.py test citations` |
| Patrones de cita (`citation_patterns.py`, `citation_extractor.py`) | `tests_citation_patterns` + baseline |
| Pipeline de referencias (`references_data.py`, `reader_data.py`, `engines.py`) | Baseline + `scripts/run_reference_regression.py --engine papermage --limit 1` |
| Clientes externos (Semantic Scholar, DBLP, Crossref) | Test del cliente correspondiente |
| Reader React | `npm run build` en `frontend_reader/` y prueba manual del preview |

La baseline y el runner de regresión usan PDFs reales del repositorio y tardan más que un test unitario; ejecútalos al tocar extracción aunque la suite rápida pase.

## Scripts de Diagnóstico

En `scripts/` hay utilidades CLI que no son tests automáticos pero ayudan a investigar regresiones:

| Script | Uso |
| --- | --- |
| `run_reference_regression.py` | Regresión de referencias sobre PDFs reales. Ver [extractor_referencias_y_regresion.md](extractor_referencias_y_regresion.md). |
| `run_reference_parsing_experiment.py` | Comparativa refextract/AnyStyle/LLM. Ver [reference_parsing_experiment.md](reference_parsing_experiment.md). |
| `run_grobid_eval.py` | Evaluación experimental de GROBID. |
| `compare_citation_detectors.py` | Comparación de detectores de citas. |
| `compare_reference_sources.py` / `inspect_reference_sources.py` | Comparación e inspección de fuentes de referencias. |
| `inspect_reference_parsers.py` | Inspección de parsers de referencias. |
| `test_papermage_raw.py` / `test_papermage_reader_json.py` | Pruebas manuales de PaperMage y su salida para el reader. |
| `test_citation_contexts.py` | Pruebas manuales de extracción de contextos. |
| `debug_references_ct_pdf.py` | Debug puntual de referencias de un PDF concreto. |

Sus artefactos se escriben bajo `tmp/` y son diagnósticos, no fuente de verdad.

# Extractor de Referencias y Runner de Regresión

Esta página documenta dos piezas relacionadas:

- `tfg_project/citations/services/references_data.py`
- `scripts/run_reference_regression.py`

`references_data.py` construye la salida estructurada de referencias para el reader. El runner ejecuta el flujo real sobre PDFs del repositorio y guarda artefactos comparables.

## `references_data.py`

### Responsabilidad

Transforma:

- referencias base extraídas del PDF;
- snippets detectados en el manuscrito;
- capas geométricas del reader (`tokens`, `rows`, `paragraphs`, `bibliographies`, `sections`);

en:

- referencias finales;
- menciones/citations;
- contextos;
- metadatos de bibliografía;
- alertas;
- pasos de debug;
- payload diagnóstico opcional.

No descarga PDFs, no llama a PaperMage directamente y no decide qué motor ejecutar.

### API Pública

#### `build_references_data(...)`

Entrada principal:

```python
build_references_data(
    *,
    references,
    snippets,
    layers,
    references_numbered=False,
    article_doi="",
    source_filename="",
    engine_used="",
    debug_reference_detection=False,
)
```

Salida principal:

- `references`
- `citations`
- `contexts`
- `citation_style`
- `max_reference_index`
- `bibliography_start_page`
- `bibliography_segments`
- `crossref_available`
- `article_doi`
- `crossref_article_metadata`
- `crossref_reference_candidates`
- `crossref_reference_count`
- `global_alerts`
- `debug_payload`
- `reference_debug_steps`

#### `finalize_reference_detection_debug_payload(...)`

Ajusta el debug final al estado real de las referencias después de reconciliación o enriquecimiento.

```python
final_debug_payload = finalize_reference_detection_debug_payload(
    debug_payload,
    references=references_data_payload.get("references", []),
)
```

#### `write_reference_detection_debug_json(...)`

Escribe debug final en `tmp/reference_debug/<paper>/debug-<timestamp>.json` y devuelve la ruta.

### Fases Internas

1. Normaliza capas del reader.
2. Detecta segmentos de bibliografía.
3. Recorta rows dentro de zona bibliográfica.
4. Detecta anchors de referencia.
5. Reconstruye referencias por rows si el documento parece numerado.
6. Aplica fallbacks si la estructura no alcanza.
7. Construye `reference_entries`.
8. Vincula snippets, citations y contexts.
9. Construye alertas globales.
10. Construye debug y auditorías.

### Debug

Con `debug_reference_detection=True`, el módulo puede exponer:

- `metadata`;
- `phases`;
- `references`;
- `alerts`;
- `document_diagnostics`;
- `phase_diagnostics`;
- `row_rejection_audit`;
- `reference_failure_audit`;
- `numeric_coverage_summary`;
- `contamination_diagnostics`;
- `start_page_column_decision`.

Úsalo para explicar por qué faltan referencias, por qué se rechazaron rows o por qué una bibliografía fue interpretada como no numerada.

## `run_reference_regression.py`

### Responsabilidad

Runner CLI para ejecutar el pipeline real actual sobre PDFs en:

```text
tfg_project/citations/static/citations/PDFs-Reales
```

Por cada PDF:

1. descubre referencias base;
2. ejecuta `process_manuscript`;
3. genera snippets;
4. obtiene capas reales;
5. ejecuta `build_references_data`;
6. finaliza debug;
7. calcula métricas;
8. escribe artefactos.

### Comandos

Smoke test:

```powershell
python scripts/run_reference_regression.py --engine papermage --limit 1
```

Un paper concreto:

```powershell
python scripts/run_reference_regression.py --engine papermage --paper-id 2017_ct_development_computational_thinking_rg
```

Run manual persistente:

```powershell
python scripts/run_reference_regression.py --engine papermage --run-name baseline_refs --overwrite
```

Limpiar runs antiguos:

```powershell
python scripts/run_reference_regression.py --cleanup-keep-days 3
```

### Opciones

| Opción | Uso |
| --- | --- |
| `--dataset-type all|exploratory` | Filtra el subconjunto autodetectado. |
| `--paper-id <id>` | Puede repetirse para ejecutar varios PDFs concretos. |
| `--engine papermage|papercraft|generic|auto` | Motor usado por `process_manuscript`. |
| `--limit N` | Limita cantidad de PDFs tras filtros. |
| `--output-dir DIR` | Directorio de salida manual. |
| `--run-name NAME` | Nombre bajo `tmp/reference_regression/`. |
| `--overwrite` | Permite reemplazar una salida manual existente. |
| `--cleanup-all` | Borra todos los runs y termina. |
| `--cleanup-keep-days N` | Conserva solo runs recientes. |
| `--cleanup-keep-current-revision` | Conserva solo runs de la revisión git actual. |

### Artefactos

Por paper, dentro de `per_paper/<paper_id>/`:

- `extraction.json`
- `reference_debug.json`
- `metrics.json`

A nivel de run:

- `summary.json`
- `summary.md`

### Métricas Relevantes

- `references_total`
- `max_reference_index_detected`
- `coverage_ratio`
- `pct_structure_source_rows_raw`
- `pct_structure_source_raw_reference_fallback`
- `pct_references_inside_bibliography_zone`
- `pct_references_local_anchor_detected`
- `pct_accepted`
- `appendix_contamination_detected`
- `last_reference_tail_noise_detected`
- `status`
- `status_reasons`

## Cómo Revisar Una Regresión

1. Abre `summary.md`.
2. Mira `status` y `main_issues` por paper.
3. Abre `metrics.json` del PDF problemático.
4. Abre `reference_debug.json`.
5. Compara `reference_failure_audit`, `row_rejection_audit` y `global_alerts`.

## Cuándo Ejecutarlo

Ejecuta el runner antes y después de cambiar:

- `references_data.py`;
- `reader_data.py`;
- `citation_extractor.py`;
- `engines.py`;
- `views_api.api_extract_citations`;
- CSS/DOM del reader si afecta resaltados o capas.

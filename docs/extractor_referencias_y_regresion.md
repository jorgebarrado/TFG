# Extractor de Referencias y Runner de Regresión

Esta página documenta dos piezas muy relacionadas del sistema:

1. `tfg_project/citations/services/references_data.py`
2. `scripts/run_reference_regression.py`

La primera construye la salida estructurada de referencias a partir de referencias base, snippets y capas del reader. La segunda ejecuta ese flujo real sobre un conjunto de PDFs y guarda artefactos comparables.

## 1. `references_data.py`

### Responsabilidad

`references_data.py` es la capa que transforma:

- referencias base extraídas del PDF
- snippets de citas detectados en el manuscrito
- capas geométricas del reader (`tokens`, `rows`, `paragraphs`, `bibliographies`, `sections`)

en una salida final con:

- `references`
- `citations`
- `contexts`
- metadatos de bibliografía
- `reference_debug_steps`
- `debug_payload` opcional para diagnóstico profundo

No es el extractor inicial del PDF. Trabaja encima de datos ya extraídos por `reader_data.py`, `papermage_extractor.py` y `citation_extractor.py`.

### API pública

#### `build_references_data(...)`

Entrada principal del módulo.

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

Entradas:

- `references`: referencias base del PDF, normalmente desde `extract_pdf_references(...)`
- `snippets`: resultados de `build_snippets_from_results(...)`
- `layers`: capas del reader, normalmente desde `extract_pdf_data(...)`
- `references_numbered`: pista inicial sobre si el documento es numerado
- `article_doi`: DOI del paper fuente, usado para contexto Crossref
- `source_filename`: nombre del PDF para metadatos/debug
- `engine_used`: motor real que ejecutó `process_manuscript`
- `debug_reference_detection`: si `True`, construye `debug_payload`

Salida principal:

- `references`: referencias serializadas finales
- `citations`: menciones/citas enlazadas a referencias
- `contexts`: contextos enriquecidos
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

Normaliza el `debug_payload` al estado final de las referencias, especialmente útil después de enriquecimiento DOI o de cualquier ajuste posterior sobre `references_data["references"]`.

Uso típico:

```python
final_debug_payload = finalize_reference_detection_debug_payload(
    debug_payload,
    references=references_data_payload.get("references", []),
)
```

#### `write_reference_detection_debug_json(...)`

Escribe el debug final a `tmp/reference_debug/<paper>/debug-<timestamp>.json`.

Se usa cuando se quiere descarga o persistencia explícita del debug fuera del runner de regresión.

### Usos reales en el proyecto

#### 1. API de extracción

En `tfg_project/citations/views_api.py` se usa dentro del flujo real de extracción del preview:

1. `extract_pdf_references(...)`
2. `process_manuscript(...)`
3. `build_snippets_from_results(...)`
4. `extract_pdf_data(...)`
5. `build_references_data(...)`

Después:

- la vista reemplaza la lista visual de referencias por `references_data["references"]`
- propaga `citation_style`, `max_reference_index` y `bibliography_start_page`
- lanza enriquecimiento DOI
- si el modo debug está activo, finaliza y escribe el debug JSON

#### 2. Runner de regresión

`scripts/run_reference_regression.py` ejecuta exactamente ese flujo real por PDF y usa `build_references_data(...)` como paso central para generar:

- `extraction.json`
- `reference_debug.json`
- `metrics.json`

#### 3. Script de depuración puntual

`scripts/debug_references_ct_pdf.py` usa `build_references_data(...)` para inspección rápida de un PDF concreto, normalmente sin recorrer todo el flujo del preview.

### Fases internas relevantes

Sin entrar en cada helper privado, el módulo sigue este esquema:

1. Carga y normalización de capas: `bibliographies`, `tokens`, `rows`, `paragraphs`, `sections`
2. Detección de segmentos de bibliografía
3. Recorte de rows dentro de la zona de bibliografía
4. Detección de anchors de referencia
5. Reconstrucción de referencias por rows si el documento parece numerado
6. Fallbacks si no hay estructura suficiente
7. Construcción de `reference_entries`
8. Vinculación de snippets/citations/contexts
9. Construcción de `global_alerts`
10. Construcción de `reference_debug_steps`
11. Construcción opcional de `debug_payload`

### Debug y diagnóstico

Si `debug_reference_detection=True`, el módulo expone un `debug_payload` amplio.

Bloques principales:

- `metadata`
- `phases`
- `references`
- `alerts`
- `document_diagnostics`
- `phase_diagnostics`
- `row_rejection_audit`
- `reference_failure_audit`
- `numeric_coverage_summary`
- `contamination_diagnostics`
- `start_page_column_decision`

Objetivo de estos bloques:

- explicar si el PDF fue interpretado como numerado o no
- ver en qué fase empieza a degradarse
- auditar rows rechazadas
- auditar referencias fallidas o débiles
- resumir cobertura numérica
- detectar contaminación de apéndice o tail noise
- explicar la decisión de columnas en la `start_page`

### Cuándo tocar este módulo

Tócalo cuando quieras:

- cambiar cómo se serializan las referencias finales
- mejorar enlace entre snippets y referencias
- añadir o ajustar señales diagnósticas
- modificar geometría de bibliografía o heurísticas de segmentación
- cambiar trazas de debug del extractor de referencias

No es el sitio correcto para:

- cambiar descarga de PDFs
- cambiar el motor PaperMage
- cambiar selección de engine
- cambiar el pipeline semántico de citadores

## 2. `run_reference_regression.py`

### Responsabilidad

`scripts/run_reference_regression.py` es un runner CLI para ejecutar el flujo real actual del extractor sobre PDFs reales y guardar artefactos comparables por paper y por run.

No es un endpoint web y no lo llama ningún otro módulo. Se usa manualmente desde terminal.

### Qué hace

Por cada PDF seleccionado:

1. descubre referencias base con `extract_pdf_references(...)`
2. resuelve contexto de citación esperado
3. ejecuta `process_manuscript(...)`
4. genera snippets con `build_snippets_from_results(...)`
5. obtiene capas reales con `extract_pdf_data(...)`
6. ejecuta `build_references_data(...)`
7. finaliza el debug con `finalize_reference_detection_debug_payload(...)` si existe
8. calcula métricas de regresión
9. escribe artefactos por paper

Después:

- agrega métricas globales
- escribe `summary.json`
- escribe `summary.md`
- aplica la política de limpieza de runs

### Dataset y descubrimiento

El dataset actual se descubre automáticamente en:

`tfg_project/citations/static/citations/PDFs-Reales`

No usa manifest externo. El `paper_id` se deriva del nombre del PDF.

### Artefactos que genera

Por paper, dentro de `per_paper/<paper_id>/`:

- `extraction.json`
- `reference_debug.json`
- `metrics.json`

A nivel global:

- `summary.json`
- `summary.md`

### Salidas principales

#### `extraction.json`

Snapshot del flujo real de extracción. Incluye:

- contexto del paper
- engine pedido y engine efectivo
- stats base de referencias
- resumen de `process_manuscript`
- resumen de capas del reader
- `final_extraction`

#### `reference_debug.json`

Payload diagnóstico final. Si la rama tiene `finalize_reference_detection_debug_payload`, el runner lo usa. Si no existe, conserva el `debug_payload` crudo.

#### `metrics.json`

Resumen estable y comparable por PDF. Contiene métricas como:

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

#### `summary.json`

Índice compacto del run:

- `metadata`
- `aggregate_metrics`
- `papers`

Cada entrada en `papers` incluye:

- `paper_id`
- `pdf_file`
- `status`
- `document_mode`
- `references_total`
- `max_reference_index_detected`
- `coverage_ratio`
- `pct_rows_raw`
- `pct_raw_fallback`
- `pct_accepted`
- `main_issues`
- `artifacts`

#### `summary.md`

Tabla breve para revisión rápida del run.

### CLI disponible

Opciones actuales:

- `--dataset-type`
- `--paper-id`
- `--engine`
- `--limit`
- `--output-dir`
- `--run-name`
- `--overwrite`
- `--cleanup-all`
- `--cleanup-keep-days`
- `--cleanup-keep-current-revision`

### Ejemplos de uso

Smoke test:

```powershell
python scripts/run_reference_regression.py --engine papermage --limit 1
```

Un solo paper:

```powershell
python scripts/run_reference_regression.py --engine papermage --paper-id 2017_ct_development_computational_thinking_rg
```

Run manual persistente:

```powershell
python scripts/run_reference_regression.py --engine papermage --run-name baseline_refs --overwrite
```

Limpiar y terminar:

```powershell
python scripts/run_reference_regression.py --cleanup-keep-days 3
```

### Política de limpieza

#### Limpieza automática normal

Se aplica tras un run nuevo y es conservadora:

- borra runs `auto` con `git_revision` distinta
- borra runs `auto` con más de `RUN_RETENTION_DAYS`
- no borra runs `manual`

#### Limpieza explícita

Modos disponibles:

- `--cleanup-all`: borra todos los runs del runner
- `--cleanup-keep-days N`: borra todo excepto los últimos `N` días
- `--cleanup-keep-current-revision`: borra todo excepto runs de la revisión git actual

La decisión se basa preferentemente en `summary.json`:

- `run_kind`
- `git_revision`
- `timestamp`

Si falta `summary.json`, el runner usa heurísticas conservadoras con nombre de carpeta y timestamps de filesystem.

### Cuándo usar este script

Úsalo cuando quieras:

- comparar comportamiento del extractor entre cambios
- generar artefactos reproducibles por PDF
- revisar fallos de cobertura, fallback, contaminación o tail noise
- validar una rama antes de tocar lógica funcional

No es el sitio correcto para:

- cambiar el extractor
- cambiar scoring del pipeline
- servir datos al frontend
- persistir debug en el flujo web de usuario

## Resumen operativo

Relación entre ambas piezas:

- `references_data.py` construye la salida estructurada y diagnóstica por PDF
- `run_reference_regression.py` ejecuta ese flujo sobre un conjunto de PDFs y lo convierte en artefactos comparables de regresión

Si quieres depurar un PDF concreto, empieza por `reference_debug.json`.

Si quieres comparar una rama completa, usa el runner y revisa:

1. `summary.md`
2. `summary.json`
3. `metrics.json` del paper problemático
4. `reference_debug.json` para el detalle fino

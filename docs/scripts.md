# Scripts

Scripts de análisis, depuración y experimentación. Todos se ejecutan desde la raíz del repositorio con el entorno virtual activado.

Ninguno modifica datos de producción; escriben artefactos en `tmp/` o por stdout.

---

## `clean_tmp.py`

Limpia la carpeta `tmp/` del repositorio. Solo usa la biblioteca estándar y pide confirmación antes de borrar.

```powershell
# Borra todo tmp/
python scripts/clean_tmp.py

# Borra solo una subcarpeta concreta
python scripts/clean_tmp.py reference_regression

# Conserva los de los últimos 3 días
python scripts/clean_tmp.py --keep-days 3

# Conserva una subcarpeta específica (se puede repetir)
python scripts/clean_tmp.py --keep-folder grobid_eval
python scripts/clean_tmp.py --keep-folder grobid_eval --keep-folder reference_regression

# Sin confirmación interactiva (útil en scripts)
python scripts/clean_tmp.py -y
```

---

## `gen_metricas.py`

Recuento de magnitudes del proyecto para la memoria (líneas de código, modelos, migraciones, commits…). Solo usa la biblioteca estándar.

```powershell
python scripts/gen_metricas.py
```

---

## `compare_citation_detectors.py`

Compara el detector de citas antiguo (regex inline) con el nuevo (`find_citation_matches`) sobre PDFs reales o textos sintéticos. Muestra cuántas citas se ganan o pierden. No carga Django.

```powershell
# Todos los PDFs del corpus
python scripts/compare_citation_detectors.py

# Un PDF concreto, modo verbose
python scripts/compare_citation_detectors.py path/al/paper.pdf -v

# Textos sintéticos en lugar de PDFs
python scripts/compare_citation_detectors.py --samples
```

---

## `debug_papermage_reader_json.py`

Vuelca en JSON los primeros 5000 caracteres del resultado de `extract_pdf_data` (páginas y capas papermage) para un PDF. Útil para verificar qué ve el extractor antes de procesar referencias.

```powershell
python scripts/debug_papermage_reader_json.py ruta/al/paper.pdf
```

---

## `debug_references_ct_pdf.py`

Muestra por consola las referencias finales de un PDF tal como las construye `build_references_data`: fuente estructural, alertas, validación y DOI. Opcionalmente escribe el payload completo en JSON.

```powershell
# PDF por defecto (hardcodeado en el script)
python scripts/debug_references_ct_pdf.py

# PDF personalizado
python scripts/debug_references_ct_pdf.py --pdf ruta/al/paper.pdf

# También guarda el JSON
python scripts/debug_references_ct_pdf.py --pdf paper.pdf --write-json tmp/debug.json
```

Requiere Django (`DJANGO_SETTINGS_MODULE` configurado o `.env` en la raíz).

---

## `compare_reference_sources.py`

Compara las referencias que extrae `reader_data` (fuente base) con las de `references_data` (fuente estructurada) para cada PDF del corpus. Clasifica el resultado por PDF: `stable_match`, `base_better`, `structured_better`, `needs_manual_review`…

```powershell
# Todos los PDFs del corpus
python scripts/compare_reference_sources.py

# Un PDF concreto
python scripts/compare_reference_sources.py --pdf ruta/al/paper.pdf

# Varios PDFs o directorio
python scripts/compare_reference_sources.py --dir ruta/carpeta/

# Permitir consultas a Crossref durante la comparación
python scripts/compare_reference_sources.py --allow-crossref
```

Salida en `tmp/reference_source_compare/<run-id>/summary.json` y `summary.md`.

---

## `inspect_reference_parsers.py`

Inspecciona un único PDF con todos los parsers disponibles: extractor propio, GROBID (`processReferences`, `processFulltextDocument`, `processCitationList`) y refextract. Vuelca cada artefacto en JSON y XML.

```powershell
python scripts/inspect_reference_parsers.py ruta/al/paper.pdf

# Directorio de salida personalizado
python scripts/inspect_reference_parsers.py paper.pdf --out tmp/mi_debug

# URL de GROBID distinta
python scripts/inspect_reference_parsers.py paper.pdf --grobid-base-url http://localhost:8070
```

Salida en `tmp/parser_inspection/<pdf_stem>/`. GROBID debe estar corriendo; si no está disponible, los pasos de GROBID se marcan como `skipped`.

---

## `inspect_reference_sources.py`

Inspecciona y compara todas las fuentes de referencias para un único PDF: extractor propio, GROBID, refextract, Crossref y Semantic Scholar. Detecta el DOI del artículo y lo usa para consultar las APIs externas.

```powershell
python scripts/inspect_reference_sources.py ruta/al/paper.pdf

# Directorio de salida y timeout personalizados
python scripts/inspect_reference_sources.py paper.pdf --out tmp/inspeccion --timeout 60
```

Salida en `tmp/reference_source_inspection/<pdf_stem>/` con un JSON por fuente y un `unified_references.json`.

---

## `run_reference_parsing_experiment.py`

Lanza experimentos de parsing de referencias sobre PDFs ya segmentados, comparando múltiples parsers (refextract, GROBID `processCitationList`, LLM…). Genera artefactos de comparación lado a lado.

```powershell
# PDFs de muestra por defecto
python scripts/run_reference_parsing_experiment.py

# Un PDF concreto
python scripts/run_reference_parsing_experiment.py --pdf nombre_archivo.pdf

# Todos los PDFs del corpus
python scripts/run_reference_parsing_experiment.py --all-pdfs

# Ver la lista de PDFs de muestra por defecto
python scripts/run_reference_parsing_experiment.py --list-default-pdfs
```

Salida en `tmp/reference_parser_experiments/<run-id>/`.

---

## `run_grobid_eval.py`

Evalúa GROBID sobre PDFs problemáticos (buckets `low_alpha_or_short_noise`, `small_reference_set`, `header_not_found_fallback`) y PDFs de control limpios. Responde tres preguntas y emite una recomendación de integración.

Requiere GROBID corriendo en `http://localhost:8070` (o la URL que se pase con `--grobid-base-url`).

```powershell
# Selección automática desde el resumen de experimentos anterior
python scripts/run_grobid_eval.py

# PDFs explícitos
python scripts/run_grobid_eval.py --pdf nombre.pdf --pdf otro.pdf

# URL y timeout personalizados
python scripts/run_grobid_eval.py --grobid-base-url http://localhost:8070 --timeout 180
```

Salida en `tmp/grobid_eval/<run-id>/summary.json` y `summary.md`.

---

## `run_reference_regression.py`

Runner de regresión del pipeline completo de extracción de referencias sobre el corpus de PDFs reales. Procesa cada PDF, calcula métricas (cobertura, fallbacks, ruido…) y clasifica en `OK / WARN / FAIL`. Limpia automáticamente runs automáticos obsoletos.

```powershell
# Todos los PDFs del corpus
python scripts/run_reference_regression.py

# Un solo PDF por paper_id
python scripts/run_reference_regression.py --paper-id nombre_sin_extension

# Limitar a N PDFs
python scripts/run_reference_regression.py --limit 5

# Motor alternativo
python scripts/run_reference_regression.py --engine papermage

# Limpiar runs más antiguos de 3 días
python scripts/run_reference_regression.py --cleanup-keep-days 3
```

Salida en `tmp/reference_regression/<run-id>/summary.json` y `summary.md`.

---

## `scripts/legacy/`

Scripts antiguos conservados por referencia histórica. No se usan en el flujo actual.

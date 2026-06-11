# Servicios de Extracción y Procesamiento

Los servicios de `tfg_project/citations/services/` concentran la lógica pesada: lectura de PDFs, extracción de referencias, detección de menciones, enriquecimiento DOI, clientes externos y experimentos.

## Mapa de Servicios

| Archivo | Responsabilidad |
| --- | --- |
| `engines.py` | Declara motores disponibles y política de ejecución. |
| `papermage_extractor.py` | Extracción estructural con PaperMage. |
| `citation_extractor.py` | Procesamiento de manuscrito y detección de citas. |
| `citation_patterns.py` | Patrones y heurísticas de citas. |
| `pdf_citation_analyzer.py` | Descarga PDF por URL y aplica extracción de contextos. |
| `reader_data.py` | Referencias base, DOI/PDF metadata y snippets para reader. |
| `references_data.py` | Reconstrucción avanzada de referencias y debug. |
| `reference_reconciliation.py` | Decide referencias finales combinando fuentes. |
| `doi_enrichment_service.py` | Enriquecimiento con Crossref/Semantic Scholar. |
| `semantic_citation_pipeline.py` | Búsqueda inversa de citadores y análisis automático. |
| `semantic_scholar_client.py` / `semanticscholar.py` | Clientes Semantic Scholar. |
| `crossref_client.py` | Cliente Crossref. |
| `dblp_client.py` | Cliente DBLP. |
| `grobid_*` | Experimento GROBID aislado. |
| `ai_*` | Funciones IA experimentales. |

## Motores

`engines.py` expone:

- `papermage`: único motor disponible, extracción estructural rica.

`run_engine(engine_requested, pdf_path)` ejecuta siempre PaperMage (incluida la política `auto`); si falla o no está disponible devuelve error, sin fallback.

Nota: la API pública `api_extract_citations` valida `engine` contra `ALLOWED_ENGINES`, que contiene las claves declaradas en `ENGINE_LABELS` y no incluye `auto`.

## Flujo de Extracción del Reader

`POST /citations/api/extract-citations/` ejecuta una cadena de servicios:

1. `reader_data.extract_pdf_references()`
   - Usa PyMuPDF para localizar bibliografía y referencias base.
2. `citation_extractor.process_manuscript()`
   - Ejecuta el motor solicitado.
   - Devuelve resultados de menciones/snippets.
3. `reader_data.build_snippets_from_results()`
   - Normaliza snippets para el frontend.
4. `papermage_extractor.extract_pdf_data()` o equivalente
   - Prepara páginas y capas visuales.
5. `references_data.build_references_data()`
   - Reconstruye referencias finales con capas, bibliografía y citas.
6. `reference_reconciliation.reconcile_reference_sources()`
   - Combina referencias base y estructuradas.
7. `doi_enrichment_service.enrich_extraction_with_doi()`
   - Añade DOI, título, autores, año, venue y citadores cuando hay datos externos confiables.

## `references_data.py`

Es la pieza más crítica del pipeline de referencias. No descarga PDFs ni selecciona motor; trabaja con datos ya extraídos:

- referencias base;
- snippets;
- capas del reader: `tokens`, `rows`, `paragraphs`, `bibliographies`, `sections`.

Devuelve:

- `references`;
- `citations`;
- `contexts`;
- `citation_style`;
- `max_reference_index`;
- `bibliography_start_page`;
- `global_alerts`;
- `debug_payload` opcional;
- `reference_debug_steps`.

Tócalo cuando necesites mejorar:

- segmentación de bibliografía;
- detección de anchors;
- unión de rows;
- validación de referencias;
- diagnósticos de contaminación o ruido;
- enlace entre menciones y referencias.

No lo toques para cambios de descarga, selección de motor, UI o clientes externos.

## Enriquecimiento DOI

`doi_enrichment_service.py` resuelve el DOI del artículo fuente y usa Crossref/Semantic Scholar para:

- traer metadatos del paper;
- traer referencias externas;
- traer citadores;
- intentar enriquecer referencias locales.

El servicio valida coincidencias para evitar mezclar referencias. No debe asignar un DOI externo solo por parecido débil de texto.

## Pipeline Semántico

`semantic_citation_pipeline.py` implementa el flujo:

1. DOI original.
2. Semantic Scholar busca papers citadores.
3. Se filtran citadores con PDF open access.
4. Se descarga cada PDF temporalmente.
5. Se buscan contextos donde aparece la cita.
6. Se devuelve un resultado agregado.

Limitaciones:

- depende de Semantic Scholar;
- solo analiza PDFs open access;
- es síncrono y puede tardar;
- no sustituye la revisión humana.

## GROBID

Los servicios `grobid_client.py`, `grobid_parser.py` y `grobid_extractor.py` son experimentales. Sirven para comparar GROBID contra el extractor actual, no para el flujo principal.

Consulta:

- [grobid_experiment.md](grobid_experiment.md)
- [grobid_pdf_debug.md](grobid_pdf_debug.md)

## Pruebas y Regresión

Para validar cambios de extracción:

```powershell
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
python scripts/run_reference_regression.py --engine papermage --limit 1
```

Para cambios profundos en `references_data.py`, ejecuta una muestra mayor:

```powershell
python scripts/run_reference_regression.py --engine papermage --run-name refs_check --overwrite
```

Revisa `summary.md`, `summary.json`, `metrics.json` y `reference_debug.json` del paper problemático.

# Servicios de Extraccion y Procesamiento

Los servicios de `tfg_project/citations/services/` concentran la logica pesada:
lectura de PDFs, extraccion de referencias, deteccion de menciones,
enriquecimiento DOI, clientes externos y experimentos.

## Mapa de Servicios

| Archivo | Responsabilidad |
| --- | --- |
| `engines.py` | Declara PaperMage como unico motor disponible. |
| `papermage_extractor.py` | Extraccion estructural con PaperMage. |
| `citation_extractor.py` | Procesamiento de manuscrito y deteccion de citas. |
| `citation_patterns.py` | Patrones y heuristicas de citas. |
| `pdf_citation_analyzer.py` | Descarga PDF por URL y aplica extraccion de contextos. |
| `reader_data.py` | Referencias base, DOI/PDF metadata y snippets para reader. |
| `references_data.py` | Reconstruccion avanzada de referencias y debug. |
| `reference_reconciliation.py` | Decide referencias finales combinando fuentes. |
| `doi_enrichment_service.py` | Enriquecimiento con Crossref/Semantic Scholar. |
| `semantic_citation_pipeline.py` | Busqueda inversa de citadores y analisis automatico. |
| `semantic_scholar_client.py` / `semanticscholar.py` | Clientes Semantic Scholar. |
| `crossref_client.py` | Cliente Crossref. |
| `dblp_client.py` | Cliente DBLP. |
| `grobid_*` | Experimento GROBID aislado. |
| `ai_*` | Funciones IA experimentales. |

## Motor

`engines.py` expone solo `papermage`. `run_engine(engine_requested, pdf_path)`
rechaza cualquier otro valor y no aplica fallback a otros extractores.

## Flujo de Extraccion del Reader

`POST /citations/api/extract-citations/` ejecuta una cadena de servicios:

1. `reader_data.extract_pdf_references()`
   - Usa PyMuPDF para localizar bibliografia y referencias base.
2. `citation_extractor.process_manuscript()`
   - Ejecuta PaperMage.
   - Devuelve resultados de menciones/snippets.
3. `reader_data.build_snippets_from_results()`
   - Normaliza snippets para el frontend.
4. `papermage_extractor.extract_pdf_data()`
   - Prepara paginas y capas visuales.
5. `references_data.build_references_data()`
   - Reconstruye referencias finales con capas, bibliografia y citas.
6. `reference_reconciliation.reconcile_reference_sources()`
   - Combina referencias base y estructuradas.
7. `doi_enrichment_service.enrich_extraction_with_doi()`
   - Anade DOI, titulo, autores, ano, venue y citadores cuando hay datos
     externos confiables.

## `references_data.py`

Es la pieza mas critica del pipeline de referencias. No descarga PDFs ni
selecciona motor; trabaja con datos ya extraidos:

- referencias base;
- snippets;
- capas del reader: `tokens`, `rows`, `paragraphs`, `bibliographies`,
  `sections`.

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

Tocalo cuando necesites mejorar:

- segmentacion de bibliografia;
- deteccion de anchors;
- union de rows;
- validacion de referencias;
- diagnosticos de contaminacion o ruido;
- enlace entre menciones y referencias.

No lo toques para cambios de descarga, seleccion de motor, UI o clientes
externos.

## Enriquecimiento DOI

`doi_enrichment_service.py` resuelve el DOI del articulo fuente y usa
Crossref/Semantic Scholar para:

- traer metadatos del paper;
- traer referencias externas;
- traer citadores;
- intentar enriquecer referencias locales.

El servicio valida coincidencias para evitar mezclar referencias. No debe
asignar un DOI externo solo por parecido debil de texto.

## Pipeline Semantico

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
- es sincrono y puede tardar;
- no sustituye la revision humana.

## GROBID

Los servicios `grobid_client.py`, `grobid_parser.py` y `grobid_extractor.py`
son experimentales. Sirven para comparar GROBID contra el extractor actual, no
para el flujo principal.

Consulta:

- [grobid_experiment.md](grobid_experiment.md)
- [grobid_pdf_debug.md](grobid_pdf_debug.md)

## Pruebas y Regresion

Para validar cambios de extraccion:

```powershell
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
python scripts/run_reference_regression.py --engine papermage --limit 1
```

Para cambios profundos en `references_data.py`, ejecuta una muestra mayor:

```powershell
python scripts/run_reference_regression.py --engine papermage --run-name refs_check --overwrite
```

Revisa `summary.md`, `summary.json`, `metrics.json` y `reference_debug.json`
del paper problematico.

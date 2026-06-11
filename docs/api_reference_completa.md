# Referencia Completa de API

Base de la app: `/citations/`. Los endpoints JSON principales cuelgan de `/citations/api/`.

Esta referencia documenta los endpoints mantenidos en `citations/urls.py`, `views_api.py` y `views/ajax_views.py`.

## Resumen

| Endpoint | Método | Vista | Uso |
| --- | --- | --- | --- |
| `/citations/api/extract-citations/` | POST | `views_api.api_extract_citations` | Extrae referencias, snippets, capas y enriquecimiento desde un PDF/TXT subido. |
| `/citations/api/detect-article-doi/` | POST | `views_api.api_detect_article_doi` | Intenta detectar DOI del artículo a partir de un PDF. |
| `/citations/api/extractor-engines/` | GET | `views_api.api_extractor_engines` | Lista motores disponibles. |
| `/citations/api/reference-debug-download/` | GET | `views_api.api_reference_debug_download` | Descarga JSON de debug de referencias. |
| `/citations/api/reader-data/<report_id>/` | GET | `views_api.api_reader_data` | Inicializa el reader para un reporte existente. |
| `/citations/api/get-citation-context/` | GET/POST | `views_api.get_citation_context` | Busca contextos en un citador open access. |
| `/citations/api/pdf-contexts/` | GET | `views_api.api_pdf_citation_contexts` | Extrae contextos desde URL directa de PDF. |
| `/citations/api/pdf-contexts-upload/` | POST | `views_api.api_pdf_citation_contexts_upload` | Extrae contextos desde PDF subido. |
| `/citations/api/pdf-reader-v2-upload/` | POST | `views_api.api_pdf_reader_v2_upload` | Devuelve `pages` y `layers` para overlays del reader. |
| `/citations/api/get-semantic-citations/` | GET | `ajax_views.get_semantic_citations` | Consulta citadores para UI semántica. |
| `/citations/api/semantic-citation-analysis/` | GET | `views_api.api_semantic_citation_analysis` | Ejecuta análisis completo de citadores por DOI. |
| `/citations/api/doi/` | GET | `ajax_views.fetch_doi_metadata` | Obtiene metadatos para un DOI. |

Los endpoints AJAX no estrictamente REST (`ajax_submit/`, `vote/`, `citations/toggle_saved/`, etc.) se consumen desde plantillas y pueden devolver HTML parcial o JSON específico de UI.

## Motores de Extracción

`GET /citations/api/extractor-engines/`

Respuesta:

```json
{
  "engines": [
    { "key": "papermage", "label": "PaperMage", "available": true }
  ]
}
```

`api_extract_citations` acepta `engine` únicamente con el valor `papermage`. La API valida contra `ALLOWED_ENGINES`, que no incluye `auto`.

## Extraer Referencias de Manuscrito

`POST /citations/api/extract-citations/`

Content-Type: `multipart/form-data`

Campos:

| Campo | Tipo | Requerido | Descripción |
| --- | --- | --- | --- |
| `manuscript` | file | Sí | PDF o TXT a procesar. |
| `engine` | string | No | `papermage` (valor por defecto y único motor disponible). |
| `debug` | bool | No | Incluye datos de depuración del procesamiento base. |
| `debug_reference_detection` | bool | No | Genera debug detallado de referencias y URL de descarga. |
| `article_doi` / `doi` | string | No | DOI del artículo fuente para enriquecimiento Crossref/Semantic Scholar. |

Respuesta parcial:

```json
{
  "ok": true,
  "engine_used": "papermage",
  "references": [
    {
      "index": 1,
      "raw": "[1] Doe, J. ...",
      "doi": "10.1000/example",
      "confidence": 1.0,
      "numbered": true
    }
  ],
  "snippets": [
    {
      "id": "snippet-1",
      "page": 3,
      "snippet": "... [1] ...",
      "type": "numeric",
      "confidence": 0.8
    }
  ],
  "pages": [],
  "layers": {},
  "references_data": {},
  "stats": {
    "pages_total": 12,
    "snippets_total": 20,
    "references_total": 35,
    "dois_total": 18,
    "engine_used": "papermage",
    "time_ms": 1500,
    "citation_style": "numeric",
    "max_reference_index": 35,
    "bibliography_start_page": 10
  },
  "cited_by": [],
  "enrichment": {
    "doi_provided": true,
    "doi_normalized": "10.1000/example",
    "paper_resolved": true,
    "references_enriched": 4,
    "cited_by_count": 12,
    "sources_used": ["crossref", "semantic_scholar"]
  },
  "article_info": {}
}
```

Errores comunes:

- `400`: falta `manuscript` o motor inválido.
- `422`: procesamiento ejecutado pero `ok=false`.
- `500`: error interno o capas del reader no preparadas para `papermage`.

## Detectar DOI del Artículo

`POST /citations/api/detect-article-doi/`

Campo requerido: `manuscript` con PDF.

Respuesta:

```json
{
  "ok": true,
  "detected": true,
  "article_doi": "10.1000/example",
  "article_info": {},
  "crossref_available": true
}
```

## Datos Para Reader

`GET /citations/api/reader-data/<report_id>/`

Inicializa un reader para un `IncorrectCitation` existente.

Respuesta:

```json
{
  "pdf_url": "https://example.org/paper.pdf",
  "snippets": [],
  "references": [],
  "mentions": [],
  "stats": {
    "pages_total": 0,
    "snippets_total": 0,
    "references_total": 1,
    "dois_total": 1,
    "engine_used": "",
    "time_ms": null,
    "references_numbered": false,
    "citation_style": "non_numeric",
    "max_reference_index": 0,
    "bibliography_start_page": null
  }
}
```

## Capas del Reader V2

`POST /citations/api/pdf-reader-v2-upload/`

Campos: `pdf_file` o `manuscript`.

Respuesta:

```json
{
  "ok": true,
  "pages": [],
  "layers": {},
  "time_ms": 800
}
```

## Contextos de Cita

### DOI Citador

`GET|POST /citations/api/get-citation-context/`

Parámetros por querystring o JSON:

| Parámetro | Requerido | Descripción |
| --- | --- | --- |
| `citing_doi` | Sí | DOI del artículo que contiene la cita. |
| `target_doi` | No | DOI del artículo citado. |
| `target_title` | No | Título del citado. |
| `target_first_author` | No | Primer autor del citado. |
| `target_year` | No | Año del citado. |
| `debug` | No | `1` para incluir traza pública. |

Respuesta:

```json
{
  "ok": true,
  "source": "semanticscholar",
  "pdf": "openAccess",
  "count": 2,
  "contexts": [
    {
      "paragraph": "Texto completo...",
      "snippet": "... fragmento ...",
      "page": 3,
      "start": 25,
      "end": 45,
      "pattern": "author-year",
      "section": "body"
    }
  ]
}
```

Errores:

- `400`: falta `citing_doi`.
- `404`: no hay PDF open access.
- `502`: error de Semantic Scholar o descarga.

### PDF por URL

`GET /citations/api/pdf-contexts/?pdf_url=<url>&pattern=<regex>`

`pattern` puede repetirse. Si no se envía, se usan patrones por defecto del servicio.

Respuesta:

```json
{
  "count": 3,
  "contexts": []
}
```

### PDF Subido

`POST /citations/api/pdf-contexts-upload/`

Campo requerido: `pdf_file`.

Respuesta:

```json
{
  "count": 3,
  "contexts": []
}
```

## Análisis Semántico

`GET /citations/api/semantic-citation-analysis/?doi=<doi>&max_citing=5`

Ejecuta el pipeline de búsqueda inversa:

1. resuelve citadores en Semantic Scholar;
2. filtra PDFs open access;
3. analiza contextos con PaperMage/fallbacks;
4. devuelve estructura agregada del servicio.

Errores:

- `400`: falta `doi` o `max_citing` no es entero.
- `500`: error interno del pipeline.

## Debug de Referencias

`GET /citations/api/reference-debug-download/?file=<relative-path>`

Descarga un JSON generado por `debug_reference_detection=1`. La ruta se resuelve siempre dentro de `tmp/reference_debug/`; rutas fuera de ese directorio devuelven 404.

## Notas de Seguridad

- Algunos endpoints están marcados con `@csrf_exempt` para facilitar pruebas y uso desde el reader. No asumas que están listos para exposición pública sin revisar CSRF, auth y límites.
- Las APIs que descargan PDFs deben tratar URLs externas como entrada no confiable.
- Los errores no están estandarizados en todo el módulo; revisa cada consumidor antes de cambiar payloads.

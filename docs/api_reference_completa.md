# Referencia Completa de la API

Esta referencia documenta los endpoints REST expuestos por la aplicación `citations`. Estos endpoints están definidos en `citations/urls.py` y servidos principalmente por `citations/views_api.py`.

**Base URL:** `/citations/api/` (relativo a la raíz del sitio)

## Endpoints de Contexto y Extracción

### 1. Obtener Contexto de Citas (PaperMage + Semantic Scholar)

Busca un artículo por DOI, intenta descargar su PDF open access y extrae las frases donde se cita a un artículo "objetivo".

*   **Ruta:** `/citations/api/get-citation-context/`
*   **Vista:** `citations.views_api.get_citation_context`
*   **Métodos:** `GET`, `POST`
*   **Parámetros (QueryString o JSON Body):**

| Parámetro | Tipo | Obligatorio | Descripción |
| :--- | :--- | :--- | :--- |
| `citing_doi` | String | **Sí** | DOI del artículo que contiene la cita (el "citador"). |
| `target_doi` | String | No | DOI del artículo citado (para búsqueda exacta). |
| `target_title` | String | No | Título del artículo citado (ayuda al matcher). |
| `target_first_author` | String | No | Apellido del primer autor del citado. |
| `target_year` | String | No | Año de publicación del citado. |
| `debug` | Bool | No | Si `1`, incluye traza de ejecución en la respuesta. |

*   **Respuesta Exitosa (200 OK):**

```json
{
  "ok": true,
  "source": "semanticscholar",
  "pdf": "openAccess",
  "count": 2,
  "contexts": [
    {
      "paragraph": "Como se menciona en Smith et al. (2020) [12], el algoritmo falla...",
      "snippet": "...Smith et al. (2020) [12], el algoritmo...",
      "page": 3,
      "start": 25,
      "end": 45,
      "pattern": "author-year",
      "section": "body"
    }
  ]
}
```

---

### 2. Extracción de Manuscrito (Subida de PDF)

Procesa un archivo PDF subido por el usuario para extraer *todas* las referencias bibliográficas. Usado en el "Reader".

*   **Ruta:** `/citations/api/extract-citations/`
*   **Vista:** `citations.views_api.api_extract_citations`
*   **Métodos:** `POST`
*   **Content-Type:** `multipart/form-data`
*   **Parámetros:**

| Campo | Tipo | Descripción |
| :--- | :--- | :--- |
| `manuscript` | File | El archivo PDF a procesar. |
| `engine` | String | Motor de extracción (ver listado de motores). Default: `auto`. |
| `debug` | Bool | Opcional. |

*   **Respuesta Exitosa (200 OK):**

```json
{
  "ok": true,
  "references": [
    {
      "id": "ref-1",
      "index": 1,
      "raw": "[1] J. Doe, 'Title', 2020.",
      "doi": "10.1000/xyz",
      "confidence": 1.0,
      "numbered": true
    }
  ],
  "snippets": [...],
  "stats": {
    "pages_total": 12,
    "references_total": 40,
    "dois_total": 35,
    "time_ms": 1500,
    "engine_used": "papermage"
  }
}
```

---

### 3. Motores de Extracción Disponibles

Lista los motores de extracción soportados y detectados en el entorno (ver `citations/services/engines.py`).

*   **Ruta:** `/citations/api/extractor-engines/`
*   **Vista:** `citations.views_api.api_extractor_engines`
*   **Métodos:** `GET`

*   **Respuesta Típica:**

```json
{
  "engines": [
    { "key": "papermage", "label": "PaperMage", "available": true },
    { "key": "generic", "label": "Generico (rapido)", "available": true },
    { "key": "papercraft", "label": "PaperCraft", "available": false }
  ]
}
```

*   **Nota de Ingeniería:**
    *   `papermage`: Usa `papermage` library. Más lento, más preciso.
    *   `generic`: Usa regex simples sobre texto plano extraído (rápido, menos contexto).
    *   `papercraft`: Experimental.
    *   `auto`: Intenta `papermage` -> `papercraft` -> `generic`.

---

### 4. Análisis de Citas en PDF por URL (PaperMage Directo)

Descarga un PDF arbitrario de una URL y devuelve contextos de cita encontrados.

*   **Ruta:** `/citations/api/pdf-contexts/`
*   **Vista:** `citations.views_api.api_pdf_citation_contexts`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `pdf_url` (String, Obligatorio): URL directa al PDF.
    *   `pattern` (String, Opcional, Múltiple): Patrones regex personalizados.

---

### 5. Upload PDF para Contextos (PaperMage Directo)

Igual que el anterior, pero subiendo el binario del PDF.

*   **Ruta:** `/citations/api/pdf-contexts-upload/`
*   **Vista:** `citations.views_api.api_pdf_citation_contexts_upload`
*   **Métodos:** `POST` (`multipart/form-data`)
*   **Parámetros:**
    *   `pdf_file` (File, Obligatorio).

---

### 6. Cargar Datos para el Reader (Reporte Existente)

Carga los datos iniciales para el visor (Viewer) cuando se abre un reporte existente.

*   **Ruta:** `/citations/api/reader-data/<int:report_id>/`
*   **Vista:** `citations.views_api.api_reader_data`
*   **Métodos:** `GET`

---

### 7. Análisis de Citación Semántica (Pipeline Completo)

Ejecuta el pipeline de búsqueda inversa: Dado un DOI original, busca quién lo cita y analiza esos PDFs.

*   **Ruta:** `/citations/api/semantic-citation-analysis/`
*   **Vista:** `citations.views_api.api_semantic_citation_analysis`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `doi` (String, Obligatorio): DOI original.
    *   `max_citing` (Int, Default 5): Número máximo de artículos citadores a analizar.

---

## Notas de Implementación

*   **Autenticación:** La mayoría de estos endpoints están marcados con `@csrf_exempt` en `views_api.py` para facilitar pruebas desde herramientas externas (Postman), pero en producción deberían estar protegidos.
*   **Errores:** El formato de error estándar es `{"ok": false, "error": "Mensaje descriptivo"}` o `{"error": "Mensaje"}` dependiendo de la vista. Se recomienda estandarizar esto en el futuro.

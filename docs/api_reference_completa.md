# Referencia Completa de la API

Esta referencia documenta los endpoints REST expuestos por la aplicación `citations`. Estos endpoints son consumidos principalmente por el Frontend React (Reader) y, en menor medida, por las vistas AJAX de Django.

**Base URL:** `/citations/api/` (relativo a la raíz del sitio)

## Endpoints de Contexto y Extracción

### 1. Obtener Contexto de Citas (PaperMage + Semantic Scholar)

Busca un artículo por DOI, intenta descargar su PDF open access y extrae las frases donde se cita a un artículo "objetivo".

*   **Endpoint:** `/citations/get_citation_context/`
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
    },
    {
       "paragraph": "[12] Smith, J. ...",
       "snippet": "[12]",
       "page": 10,
       "section": "references"
    }
  ],
  "trace": { ... } // Solo si debug=1
}
```

*   **Errores Comunes:**
    *   `400 Bad Request`: Falta `citing_doi`.
    *   `404 Not Found`: No se encontró PDF open access para el DOI citador.
    *   `502 Bad Gateway`: Error de comunicación con Semantic Scholar o fallo en la descarga del PDF.

---

### 2. Extracción de Manuscrito (Subida de PDF)

Procesa un archivo PDF subido por el usuario para extraer *todas* las referencias bibliográficas. Usado en el "Reader".

*   **Endpoint:** `/citations/api/extract-citations/`
*   **Métodos:** `POST`
*   **Content-Type:** `multipart/form-data`
*   **Parámetros:**

| Campo | Tipo | Descripción |
| :--- | :--- | :--- |
| `manuscript` | File | El archivo PDF a procesar. |
| `engine` | String | Motor de extracción (`auto`, `grobid`, `regex`). |
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
  "snippets": [...], // Fragmentos detectados
  "stats": {
    "pages_total": 12,
    "references_total": 40,
    "dois_total": 35,
    "time_ms": 1500
  }
}
```

---

### 3. Análisis de Citas en PDF por URL

Descarga un PDF arbitrario de una URL y devuelve contextos de cita encontrados (sin target específico, busca patrones generales como `[1]`, `(Author, 2000)`).

*   **Endpoint:** `/citations/api/pdf-citation-contexts/`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `pdf_url` (String, Obligatorio): URL directa al PDF.
    *   `pattern` (String, Opcional, Múltiple): Patrones regex personalizados.

*   **Respuesta (200 OK):**

```json
{
  "count": 5,
  "contexts": [
    {
      "paragraph": "El método propuesto [3] mejora...",
      "page": 2,
      ...
    }
  ]
}
```

---

### 4. Cargar Datos para el Reader (Reporte Existente)

Carga los datos iniciales para el visor (Viewer) cuando se abre un reporte existente.

*   **Endpoint:** `/citations/api/reader-data/<int:report_id>/`
*   **Métodos:** `GET`
*   **Descripción:** Recupera el `IncorrectCitation`, obtiene el PDF url (del metadato incorrecto), y reconstruye los snippets y referencias guardados.

*   **Respuesta (200 OK):**

```json
{
  "pdf_url": "https://pdfs.semanticscholar.org/...",
  "snippets": [...],
  "references": [...],
  "mentions": [...],
  "stats": { ... }
}
```

---

### 5. Análisis de Citación Semántica (Pipeline Completo)

Ejecuta el pipeline de búsqueda inversa: Dado un DOI original, busca quién lo cita y analiza esos PDFs.

*   **Endpoint:** `/citations/api/semantic-citation-analysis/`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `doi` (String, Obligatorio): DOI original.
    *   `max_citing` (Int, Default 5): Número máximo de artículos citadores a analizar.

*   **Respuesta (200 OK):**

```json
{
  "original_doi": "10.1038/nature123",
  "citing_count": 3,
  "analyzed": [
    {
      "citing_title": "A follow up study...",
      "citing_doi": "10.1093/bio/456",
      "pdf_url": "https://...",
      "contexts": [ ... ] // Hits encontrados en este PDF
    }
  ],
  "errors": []
}
```

---

### 6. Motores Disponibles

Lista los motores de extracción soportados por el backend.

*   **Endpoint:** `/citations/api/extractor-engines/`
*   **Métodos:** `GET`
*   **Respuesta:** `{"engines": [{"key": "auto", "label": "Automático", ...}]}`

---

## Notas de Implementación

*   **Autenticación:** La mayoría de estos endpoints están marcados con `@csrf_exempt` en `views_api.py` para facilitar pruebas, pero en producción deberían estar protegidos o usar tokens CSRF/Session.
*   **Errores:** El formato de error estándar es `{"ok": false, "error": "Mensaje descriptivo"}` o `{"error": "Mensaje"}` dependiendo de la vista. Se recomienda estandarizar esto en el futuro.

# API REST

CiteCheck expone una API REST para permitir la integración con herramientas externas y alimentar su propio frontend interactivo.

## Endpoints de Contexto

### `GET /api/get-citation-context/`
Extrae el contexto de una cita específica dentro de un artículo citante.

*   **Parámetros (Query String):**
    *   `citing_doi` (Requerido): DOI del artículo que contiene la cita.
    *   `target_title`: Título del artículo citado (ayuda a la búsqueda).
    *   `target_doi`: DOI del artículo citado.
    *   `target_first_author`: Primer autor del citado.
    *   `target_year`: Año del citado.
    *   `debug`: `1` para incluir traza de ejecución.
*   **Respuesta (JSON):**
    *   `ok`: Booleano.
    *   `contexts`: Lista de fragmentos de texto encontrados.
    *   `source`: Fuente del PDF (ej. "semanticscholar").

### `GET /api/pdf-contexts/`
Analiza un PDF accesible vía URL pública.

*   **Parámetros:**
    *   `pdf_url` (Requerido).
    *   `pattern` (Opcional, múltiple): Patrones regex personalizados para buscar referencias.
*   **Respuesta:**
    *   `count`: Número de hallazgos.
    *   `contexts`: Lista de contextos.

### `POST /api/pdf-contexts-upload/`
Analiza un archivo PDF subido directamente.

*   **Body (Multipart):**
    *   `pdf_file`: El archivo PDF.
*   **Respuesta:** Similar a `/api/pdf-contexts/`.

## Endpoints de Extracción General

### `POST /api/extract-citations/`
Sube un manuscrito para extraer todas sus referencias bibliográficas.

*   **Body (Multipart):**
    *   `manuscript`: Archivo PDF o TXT.
    *   `engine`: Motor a usar (ej. `auto`).
*   **Respuesta:**
    *   `references`: Lista de referencias extraídas.
    *   `stats`: Estadísticas del proceso.

## Endpoints de Datos de Lectura

### `GET /api/reader-data/<int:report_id>/`
Obtiene todos los datos necesarios para inicializar el "Citation Reader" (visor) para un reporte específico.

*   **Parámetros:** `report_id` (ID del `IncorrectCitation`).
*   **Respuesta:**
    *   `pdf_url`: URL del PDF.
    *   `snippets`: Fragmentos de texto.
    *   `mentions`: Menciones de citas en el texto.
    *   `references`: Bibliografía del documento.

## Endpoints de Análisis Semántico

### `GET /api/semantic-citation-analysis/`
Realiza un análisis profundo de quién cita a un DOI dado.

*   **Parámetros:**
    *   `doi`: DOI original.
    *   `max_citing`: Máximo de papers a analizar.
*   **Respuesta:** Estructura compleja con los papers citantes y sus contextos de cita.

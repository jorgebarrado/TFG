# API REST

CiteCheck expone una API RESTful para permitir que el frontend (y potenciales clientes externos) interactúen con los servicios de extracción y datos.

Las vistas de la API se encuentran en `citations/views_api.py`.

## Endpoints Principales

### 1. Obtener Contexto de Citación

Extrae el contexto donde un artículo A cita a un artículo B.

*   **URL:** `/api/citation/context`
*   **Métodos:** `GET`, `POST`
*   **Parámetros (JSON body o QueryString):**
    *   `citing_doi` (Requerido): DOI del artículo que cita.
    *   `target_title`: Título del artículo citado (para búsqueda por texto).
    *   `target_first_author`: Apellido del primer autor (para búsqueda tipo "Author et al.").
    *   `target_year`: Año de publicación.
    *   `target_doi`: DOI del artículo citado.
    *   `debug`: `1` para incluir trazas de depuración.

*   **Respuesta Exitosa (200 OK):**
    ```json
    {
      "ok": true,
      "source": "semanticscholar",
      "pdf": "openAccess",
      "count": 5,
      "contexts": [
        {
          "paragraph": "...",
          "snippet": "...",
          "page": 3,
          "section": "body"
        }
      ]
    }
    ```

### 2. Procesar Manuscrito Subido

Analiza un archivo PDF local subido por el usuario.

*   **URL:** `/api/extract/citations`
*   **Métodos:** `POST`
*   **Body (Multipart Form-Data):**
    *   `manuscript`: Archivo (PDF o TXT).
    *   `engine`: Motor de extracción (`auto`, `science-parse`, etc.).

### 3. Análisis de PDF por URL (PaperMage)

Analiza un PDF accesible públicamente buscando patrones genéricos o específicos.

*   **URL:** `/api/pdf/citation/contexts`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `pdf_url` (Requerido): URL directa al PDF.
    *   `pattern` (Opcional, múltiple): Regex personalizada para buscar.
*   **Respuesta:** Lista de contextos encontrados.

### 4. Análisis Semántico Avanzado

Realiza una búsqueda inversa: dado un artículo, busca quién lo cita y extrae los contextos automáticamente.

*   **URL:** `/api/semantic/citation/analysis`
*   **Métodos:** `GET`
*   **Parámetros:**
    *   `doi`: DOI del artículo original.
    *   `max_citing`: Número máximo de artículos citadores a analizar (default: 5).

## Manejo de Errores

La API utiliza códigos de estado HTTP estándar:
*   `400 Bad Request`: Parámetros faltantes o inválidos.
*   `404 Not Found`: No se encontró el artículo o el PDF Open Access.
*   `502 Bad Gateway`: Error al comunicarse con Semantic Scholar o al descargar el PDF.
*   `500 Internal Server Error`: Errores no controlados en el procesamiento.

## Debugging

Varios endpoints soportan el flag `?debug=1`. Esto añade un campo `trace` en la respuesta JSON con detalles paso a paso de la ejecución (tiempos, éxitos/fallos parciales, tamaños de archivo).

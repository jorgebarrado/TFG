# Arquitectura del Backend

El backend de CiteCheck está construido sobre **Django**, siguiendo una arquitectura MVT (Model-View-Template) estándar, pero con una fuerte separación de la lógica de negocio en una capa de **Servicios**.

## Estructura de Directorios

La aplicación principal se encuentra en `tfg_project/citations/`.

*   **`models.py`**: Definición del esquema de base de datos.
*   **`views.py`**: Vistas estándar que renderizan HTML (Templates Django).
*   **`views_api.py`**: Vistas dedicadas a la API REST (retornan JSON).
*   **`services/`**: Directorio crítico que contiene toda la lógica de procesamiento, extracción e integración externa.
*   **`urls.py`**: Enrutamiento de URLs.
*   **`templates/`**: Archivos HTML con sintaxis de plantillas Django.

## Capa de Servicios (`citations/services/`)

Para evitar vistas ("Views") sobrecargadas ("Fat Models, Thin Views" o "Service Layer"), la lógica compleja se delega a módulos en `services/`.

### Principales Módulos de Servicio:

1.  **Extracción de PDF (`papermage_extractor.py`, `citation_extractor.py`):**
    *   Encapsulan la complejidad de librerías como `PaperMage` y `PDFPlumber`.
    *   Normalizan el texto extraído y buscan patrones.

2.  **Integraciones Externas (`semantic_scholar_client.py`, `dblp_client.py`):**
    *   Manejan la comunicación HTTP con APIs de terceros.
    *   Gestionan errores de red, rate limiting y parseo de respuestas.

3.  **Lógica de Negocio (`semantic_citation_pipeline.py`):**
    *   Orquestan flujos complejos: "Dado un DOI, buscar citas en Semantic Scholar, descargar esos PDFs, y buscar dónde citan al original".

## Autenticación

El proyecto utiliza `django-allauth` para gestionar el ciclo de vida de los usuarios.
*   Soporte para Login Social: Google y ORCID.
*   El modelo de usuario se extiende mediante `UserProfile` (relación One-to-One) para almacenar datos específicos del investigador (biografía, enlaces sociales, afiliación).

## Logging y Trazabilidad

Se implementa un sistema de logging estructurado (ver `views_api.py` y `trace.py`) para el endpoint crítico de extracción de contextos.
*   Permite depurar qué paso falló (descarga de PDF, extracción de texto, búsqueda de patrón) sin interrumpir la experiencia del usuario.
*   Los logs se pueden activar/desactivar vía variables de entorno (`LOG_CITATIONS`).

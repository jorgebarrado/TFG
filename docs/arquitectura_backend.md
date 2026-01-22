# Arquitectura del Backend

El backend de CiteCheck está construido sobre el framework **Django**. Sigue una arquitectura MVT (Modelo-Vista-Template) estándar, enriquecida con servicios especializados para el procesamiento de documentos científicos.

## Estructura del Proyecto

El proyecto se organiza en un directorio principal `tfg_project/` que contiene:

*   **`tfg_project/` (Configuración):** Contiene `settings.py`, `urls.py` principal, y configuración WSGI/ASGI.
*   **`citations/` (Aplicación Principal):** Contiene la lógica de negocio.

### Aplicación `citations`

Esta aplicación encapsula la mayor parte de la funcionalidad:

*   **`models.py`:** Definición del esquema de base de datos (ver `modelos_datos.md`).
*   **`views/`:** Vistas organizadas por funcionalidad:
    *   `page_views.py`: Vistas que renderizan páginas HTML completas.
    *   `api_views.py` / `views_api.py`: Endpoints REST que devuelven JSON.
    *   `user_views.py`: Gestión de perfiles y configuraciones de usuario.
    *   `auth_views.py`: Vistas personalizadas de autenticación.
*   **`services/`:** Capa de servicios para lógica compleja (ver `servicios_extraccion.md`). Aquí reside la inteligencia de extracción de citas y conexión con APIs externas.
*   **`templates/`:** Plantillas HTML usando el motor de Django y Bootstrap 5.
*   **`static/`:** Archivos estáticos (CSS, JS, imágenes).

## Integraciones Externas

El backend actúa como orquestador entre la base de datos local y varios servicios externos:

1.  **Semantic Scholar API:** Utilizada para obtener metadatos de artículos, identificar citas y obtener enlaces a PDFs de acceso abierto.
2.  **CrossRef API:** Fuente alternativa de metadatos bibliográficos.
3.  **DBLP:** Para obtener listas de publicaciones de los usuarios.
4.  **Google / ORCID (Auth):** Proveedores de identidad mediante OAuth (vía `django-allauth`).

## Flujo de Datos Típico (Extracción de Contexto)

1.  **Solicitud:** El usuario (o frontend) solicita el contexto de una cita mediante un DOI.
2.  **Vista API:** `views_api.get_citation_context` recibe la petición.
3.  **Servicio:** Se invoca a `semantic_fetch` o `semantic_scholar_client` para obtener el PDF.
4.  **Procesamiento:** `papermage_extractor` descarga y analiza el PDF.
    *   Convierte el PDF a objetos manipulables.
    *   Busca patrones de citación (ej. "[1]", "Smith et al. (2020)").
    *   Extrae el texto circundante (contexto).
5.  **Respuesta:** Se devuelve un JSON con los fragmentos de texto encontrados.

## Sistema de Tareas y Asincronía

Actualmente, el procesamiento es síncrono en las vistas, aunque algunas operaciones pesadas (descarga y análisis de PDF) pueden tomar tiempo. Se recomienda el uso de `Trace` y logs estructurados (`citations.context`) para monitorear el rendimiento y errores en estos procesos.

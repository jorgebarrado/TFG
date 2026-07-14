# Introducción a CiteCheck

**CiteCheck** es una plataforma diseñada para mejorar la integridad de la investigación académica permitiendo a los usuarios identificar, reportar y discutir citas incorrectas en artículos científicos.

El proyecto combina una aplicación web tradicional (Django) con capacidades avanzadas de procesamiento de lenguaje natural y análisis de documentos PDF para automatizar la detección de contextos de citas.

## Objetivos del Proyecto

*   **Detección de Errores:** Facilitar la identificación de citas que no respaldan las afirmaciones hechas (ej. "no dicho", "malinterpretación").
*   **Comunidad:** Crear un entorno colaborativo donde los investigadores pueden validar reportes mediante votos y comentarios.
*   **Automatización:** Utilizar herramientas de extracción de texto y APIs externas (Semantic Scholar, CrossRef) para agilizar el análisis de documentos.

## Tecnologías Principales

### Backend
*   **Lenguaje:** Python 3.13+
*   **Framework:** Django 5.x
*   **Base de Datos:** SQLite (Entorno de desarrollo), extensible a PostgreSQL.
*   **Procesamiento PDF:** PaperMage, PDFPlumber, PyPDF2.
*   **Autenticación:** Django Allauth (Google, ORCID).

### Frontend
*   **Framework Web:** Bootstrap 5 (Renderizado por Django Templates).
*   **Lector de PDF Interactivo:** React + Vite (integrado en vistas específicas).
*   **Librerías JS:** PaperCraft.js (visualización de coordenadas en PDF).

### Integraciones Externas
*   **Semantic Scholar API:** Búsqueda de metadatos de artículos y enlaces a PDFs Open Access.
*   **CrossRef API:** Validación de DOIs y metadatos adicionales.
*   **DBLP:** Vinculación de perfiles de investigadores y publicaciones.

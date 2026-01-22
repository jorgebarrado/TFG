# Introducción a CiteCheck

CiteCheck es una plataforma web diseñada para abordar el problema de las citas incorrectas en la literatura académica. Permite a los investigadores y lectores identificar, reportar y discutir citas que no respaldan adecuadamente las afirmaciones hechas en los artículos científicos.

El proyecto combina una aplicación web robusta construida con Django con potentes herramientas de procesamiento de lenguaje natural y análisis de documentos (como PaperMage y Semantic Scholar) para extraer y verificar contextos de citación automáticamente.

## Propósito

La integridad científica depende de la precisión de las referencias. CiteCheck busca:
1.  **Democratizar la verificación:** Permitir que la comunidad académica colabore en la detección de errores.
2.  **Automatizar el análisis:** Utilizar herramientas de IA y extracción de texto para facilitar la validación de citas en archivos PDF.
3.  **Centralizar la discusión:** Proveer un espacio dedicado para debatir la validez de las citas con un sistema de comentarios y votos.

## Características Principales

*   **Gestión de Perfiles de Usuario:**
    *   Registro e inicio de sesión (incluyendo soporte para Google y ORCID).
    *   Perfiles públicos con estadísticas de actividad.
    *   Integración con DBLP para vincular publicaciones académicas.

*   **Reporte de Citas Incorrectas:**
    *   Formularios detallados para reportar errores de citación (DOI original vs. DOI incorrecto).
    *   Clasificación de errores (ej. malinterpretación, no mencionado).
    *   Soporte para metadatos y extracción de contextos.

*   **Análisis Automático y Extracción:**
    *   **Extracción de Contexto:** Identificación automática de frases citantes dentro de PDFs.
    *   **Integración con APIs:** Uso de Semantic Scholar y CrossRef para obtener metadatos y PDFs de acceso abierto.
    *   **Visor de PDF Enriquecido:** Un frontend especializado en React para visualizar documentos y sus referencias.

*   **Comunidad:**
    *   Sistema de votos (positivo/negativo) para validar reportes.
    *   Hilos de comentarios anidados.
    *   Mensajería privada entre usuarios.
    *   Notificaciones de actividad.

*   **API REST:**
    *   Endpoints públicos para integrar funcionalidades de extracción de citas en otras herramientas.

## Tecnologías Utilizadas

*   **Backend:** Python, Django 5.x.
*   **Base de Datos:** SQLite (por defecto).
*   **Frontend:** HTML/CSS (Bootstrap 5) y React 17 (para el visor de documentos).
*   **Procesamiento de Datos:** PaperMage, PyPDF2, Semantic Scholar API.
*   **Autenticación:** Django Allauth.

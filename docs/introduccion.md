# Documentación Técnica de CiteCheck

Bienvenido a la documentación técnica de **CiteCheck**. Este conjunto de documentos está dirigido a desarrolladores y mantenedores del proyecto.

CiteCheck es una plataforma de ingeniería de software diseñada para la **verificación y análisis de citas académicas**. Su objetivo técnico es automatizar la detección de inconsistencias entre lo que un artículo dice (citador) y lo que la referencia realmente contiene (citado).

## Arquitectura Conceptual

El sistema se basa en la interacción de tres componentes principales ("Las 3 Herramientas"):

1.  **Buscador de Citadores (Semantic Pipeline):**
    *   *Input:* Un DOI original.
    *   *Proceso:* Consulta grafos de citas (Semantic Scholar), descarga PDFs Open Access y escanea su contenido.
    *   *Output:* Lista de citas encontradas con su contexto textual.

2.  **Viewer / Reader (Visor PDF Enriquecido):**
    *   *Tech:* React + PDF.js (vía `@allenai/pdf-components`).
    *   *Función:* Permite a un humano visualizar un paper, ver dónde están las referencias y validar si el texto extraído es correcto.
    *   *Interacción:* Puente bidireccional con el sistema de reportes.

3.  **Sistema de Reportes (Gestión de Errores):**
    *   *Modelo:* `IncorrectCitation`.
    *   *Función:* Persistencia estructurada de la denuncia (DOI A vs DOI B, tipo de error, evidencia textual).
    *   *Comunidad:* Sistema de discusión, votación y reputación sobre los reportes.

## Índice de Documentación

Para navegar por el código y entender los subsistemas, consulta los siguientes documentos especializados:

### Nivel Alto (Arquitectura y Datos)
*   [Estado del Sistema](estado_del_sistema.md): **Lectura obligatoria.** Tabla de madurez de módulos, riesgos y deuda técnica actual.
*   [Arquitectura Backend](arquitectura_backend.md): Visión general de Django, organización de carpetas y capas.
*   [Modelos y Relaciones](modelos_y_relaciones.md): Esquema de base de datos, entidades principales (`IncorrectCitation`, `UserProfile`) y decisiones de diseño.
*   [Flujo de Datos End-to-End](flujo_datos_end_to_end.md): Diagramas de cómo viaja la información entre las 3 herramientas.

### Nivel Bajo (Ingeniería e Implementación)
*   [Referencia API](api_reference_completa.md): Documentación técnica de endpoints REST (inputs, outputs JSON).
*   [Servicios de Extracción](servicios_extraccion.md): Lógica interna de `citations/services/` (PaperMage, Regex, Pipelines).
*   [Frontend Reader](frontend_reader.md): Arquitectura de la aplicación React y su integración con Django.
*   [Dependencias y Limitaciones](dependencias_y_limitaciones.md): Fronteras del sistema (APIs externas, PDFs ilegibles, fallbacks).

### Otros
*   [Instalación](instalacion.md): Guía de despliegue local.
*   [Manual de Usuario](manual_usuario.md): Guía funcional básica (contexto no técnico).

## Tecnologías Core

*   **Backend:** Python 3.10+, Django 5.x.
*   **Frontend:** React 17 (Vite), Bootstrap 5.
*   **NLP / PDF:** PaperMage, PDFPlumber, Regex.
*   **APIs Externas:** Semantic Scholar Graph API.

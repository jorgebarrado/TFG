# Introducción

CiteCheck es una plataforma para documentar y revisar posibles errores de citación en literatura académica. Su flujo central permite indicar qué artículo fue citado, qué artículo lo citó, por qué la cita es problemática y qué fragmento del texto sirve como evidencia.

La aplicación está pensada como una herramienta de apoyo: automatiza búsquedas, extracción de PDFs y enriquecimiento bibliográfico cuando las fuentes externas lo permiten, pero conserva al usuario como responsable de validar el hallazgo.

## Componentes Principales

1. **Sistema de reportes**
   - Modelo principal: `IncorrectCitation`.
   - Guarda DOI original, DOI citador, tipo de error, área, explicación, metadatos y contextos.
   - Incluye comentarios, votos, guardados, notificaciones y mensajes.

2. **Reader PDF**
   - Aplicación React/Vite ubicada en `frontend_reader/`.
   - Se integra en Django mediante `citations/templates/citations/reader.html`.
   - Renderiza PDFs, muestra capas de texto, extrae referencias y conecta referencias con menciones.

3. **Servicios de extracción y enriquecimiento**
   - Motor: `papermage`.
   - Pipeline semántico con Semantic Scholar para buscar citadores open access.
   - Enriquecimiento DOI con Crossref y Semantic Scholar.
   - Herramientas de regresión para comparar resultados sobre PDFs reales.

4. **Experimentos aislados**
   - GROBID para comparar extracción TEI contra el pipeline actual.
   - Parsers alternativos de referencias: refextract, AnyStyle y LLM.
   - Módulos IA para detección/evaluación de citas, todavía fuera del flujo principal.

## Alcance Actual

El flujo de producción usa `IncorrectCitation`. El modelo `CitationReport` y el wizard asociado existen como flujo legacy/inactivo y no deben usarse como referencia principal para nuevas funcionalidades.

El análisis automático depende de disponibilidad de PDFs open access y de APIs externas. Si no hay PDF descargable, el sistema puede registrar el reporte, pero no siempre podrá extraer contexto automáticamente.

## Tecnologías

| Capa | Tecnologías |
| --- | --- |
| Backend | Python 3.11 recomendado, Django 5.1, django-allauth |
| Base de datos | SQLite por defecto en desarrollo |
| Frontend HTML | Django templates, Bootstrap, JavaScript propio |
| Reader | React 17, Vite 5, `@allenai/pdf-components`, `react-pdf` |
| PDF/NLP | PaperMage, PyMuPDF, pdfplumber, PyTorch CPU |
| APIs | Semantic Scholar, Crossref, DBLP, Google/ORCID auth |
| Experimentos | GROBID, refextract, AnyStyle, OpenAI/Google AI opcionales |

## Cómo Navegar La Documentación

- Instalación local: [instalacion.md](instalacion.md)
- Estado real del sistema: [estado_del_sistema.md](estado_del_sistema.md)
- Arquitectura backend: [arquitectura_backend.md](arquitectura_backend.md)
- Datos y modelos: [modelos_y_relaciones.md](modelos_y_relaciones.md)
- Endpoints: [api_reference_completa.md](api_reference_completa.md)
- Reader: [frontend_reader.md](frontend_reader.md)
- Extracción: [servicios_extraccion.md](servicios_extraccion.md)

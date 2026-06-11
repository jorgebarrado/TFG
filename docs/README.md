# Índice de Documentación

Esta carpeta contiene la documentación mantenida de CiteCheck. Si estás entrando al proyecto por primera vez, lee primero `introduccion.md`, `instalacion.md` y `estado_del_sistema.md`.

## Lecturas Principales

| Documento | Audiencia | Contenido |
| --- | --- | --- |
| [introduccion.md](introduccion.md) | Todos | Qué es CiteCheck, componentes principales y alcance actual. |
| [instalacion.md](instalacion.md) | Desarrollo | Entorno local, Docker, variables y verificación inicial. |
| [estado_del_sistema.md](estado_del_sistema.md) | Mantenimiento | Madurez de módulos, riesgos y prioridades técnicas. |
| [manual_usuario.md](manual_usuario.md) | Usuario final | Flujos funcionales: perfiles, reportes, comentarios, reader y mensajes. |
| [arquitectura_backend.md](arquitectura_backend.md) | Backend | Estructura Django, capas, rutas y puntos de extensión. |
| [modelos_y_relaciones.md](modelos_y_relaciones.md) | Backend/datos | Modelos, relaciones y decisiones de persistencia. |
| [flujo_datos_end_to_end.md](flujo_datos_end_to_end.md) | Producto/ingeniería | Cómo viajan DOI, PDFs, referencias, contextos y reportes. |
| [api_reference_completa.md](api_reference_completa.md) | Integraciones | Endpoints JSON/AJAX y payloads relevantes. |
| [frontend_reader.md](frontend_reader.md) | Frontend | Reader React/Vite, integración Django y APIs consumidas. |
| [servicios_extraccion.md](servicios_extraccion.md) | Extracción | Motores, pipelines, referencias, enriquecimiento y clientes externos. |
| [dependencias_y_limitaciones.md](dependencias_y_limitaciones.md) | Operación | Dependencias externas, degradaciones esperadas y variables opcionales. |

## Herramientas y Experimentos

| Documento | Contenido |
| --- | --- |
| [tests_y_verificacion.md](tests_y_verificacion.md) | Suite de tests, qué cubre cada módulo y qué ejecutar según el cambio. |
| [extractor_referencias_y_regresion.md](extractor_referencias_y_regresion.md) | `references_data.py` y runner de regresión sobre PDFs reales. |
| [reference_pipeline_baseline.md](reference_pipeline_baseline.md) | Test de baseline del pipeline de referencias. |
| [reference_parsing_experiment.md](reference_parsing_experiment.md) | Comparativa aislada entre refextract, AnyStyle y LLM. |
| [grobid_experiment.md](grobid_experiment.md) | Integración experimental completa con GROBID. |
| [grobid_pdf_debug.md](grobid_pdf_debug.md) | Comando simple para probar un PDF contra GROBID. |
| [../STYLE.md](../STYLE.md) | Estilo de código, Black/isort/Flake8 y pre-commit. |

## Qué No Es Documentación Viva

- `tmp/`: resultados de ejecuciones, comparativas y artefactos de debug. Pueden ser útiles como evidencia histórica, pero no son manuales.
- `docs/superpowers/`: especificaciones y planes de trabajo de sesiones anteriores.

## Regla de Mantenimiento

Cuando cambies rutas, comandos, endpoints o variables de entorno, actualiza al menos `README.md`, `instalacion.md`, `api_reference_completa.md` y el documento especializado correspondiente.

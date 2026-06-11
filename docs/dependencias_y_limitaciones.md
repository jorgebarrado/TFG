# Dependencias y Limitaciones

CiteCheck depende de APIs externas, librerías pesadas de PDF/NLP y disponibilidad de PDFs open access. Este documento describe qué puede degradarse y cómo diagnosticarlo.

## Dependencias Externas

| Servicio | Uso | Variable | Fallback |
| --- | --- | --- | --- |
| Semantic Scholar | Metadatos, citadores y PDFs open access | `SEMANTIC_SCHOLAR_API_KEY` opcional | Crossref parcial, entrada manual o PDF subido. |
| Crossref | Metadatos DOI, referencias y cited-by | Ninguna | Semantic Scholar o datos locales. |
| DBLP | Publicaciones de perfiles | Ninguna | Edición manual de perfil. |
| Google/ORCID auth | Login social vía allauth | Configuración allauth/admin | Login local si está habilitado. |
| GROBID | Experimento de comparación TEI | `GROBID_BASE_URL`, `GROBID_TIMEOUT` | Pipeline actual sin GROBID. |
| OpenAI | Parser LLM experimental y evaluador IA | `OPENAI_API_KEY` | El experimento omite LLM si falta la clave. |
| Google Generative AI | Detector IA experimental | `GOOGLE_API_KEY` | No ejecutar acción IA. |

## Dependencias Locales Pesadas

| Componente | Uso | Riesgo |
| --- | --- | --- |
| PaperMage | Único motor de extracción estructural de PDFs | Instalación pesada (se instala desde un commit fijo de GitHub), PyTorch, cambios upstream. Sin fallback: si falla, la extracción devuelve error. |
| PyTorch CPU | Dependencia de PaperMage/modelos | Instalación lenta; requiere índice CPU en pip. |
| PyMuPDF (`fitz`) | Texto, referencias y capas | Diferencias por versión en extracción de texto. |
| pdfplumber/pdfminer | Dependencias de PaperMage y utilidades de texto | Puede fallar con PDFs protegidos o layouts complejos. |
| Vite/React reader | UI de PDF | Bundle debe estar compilado o Vite disponible. |

## Limitaciones de PDF

| Tipo de PDF | Comportamiento esperado | Motivo |
| --- | --- | --- |
| Texto seleccionable | Mejor caso | Las librerías pueden leer spans/texto. |
| Escaneado/imagen | Normalmente falla o devuelve 0 contextos | No hay OCR integrado. |
| Protegido/encriptado | Puede fallar al abrir | Restricciones del archivo. |
| Dos columnas complejo | Parcial | La reconstrucción de orden de lectura puede mezclar columnas. |
| Bibliografía sin encabezado claro | Parcial | Se usan heurísticas de últimas páginas. |
| Referencias no numeradas | Parcial | Matching y cobertura son más difíciles que en estilo numérico. |

## Limitaciones de Open Access

El pipeline automático de citadores solo puede analizar texto cuando Semantic Scholar devuelve un `openAccessPdf` válido o cuando el usuario sube un PDF legalmente accesible.

Si un citador está detrás de paywall:

- puede aparecer como citador en metadatos;
- no se podrá extraer contexto automáticamente;
- el reporte puede crearse con explicación manual;
- el usuario puede subir un PDF si tiene derecho a usarlo.

## Rate Limits y Latencia

Semantic Scholar y Crossref pueden devolver errores, respuestas incompletas o latencia alta. La clave `SEMANTIC_SCHOLAR_API_KEY` mejora estabilidad, pero no elimina límites.

Riesgos actuales:

- extracciones síncronas durante una petición web;
- falta de cola de trabajos para análisis largos;
- caché local en memoria, no persistente;
- errores JSON no totalmente estandarizados.

## Variables de Diagnóstico

| Variable | Efecto |
| --- | --- |
| `LOG_CITATIONS=1` | Activa logging de `citations` y `citations.context`. |
| `LOG_CITATIONS_LEVEL=DEBUG` | Aumenta detalle del logger de contexto. |
| `TRACE_CITATIONS=1` | Activa trazas internas en `reader_data.py` y servicios asociados. |
| `TRACE_REFERENCES=1` | Activa trazas internas en `references_data.py`. |
| `INCLUDE_TRACE_IN_RESPONSE=1` | Incluye la traza interna en respuestas de `views_api.py`. |
| `debug=1` | En endpoints compatibles, incluye información adicional. |
| `debug_reference_detection=1` | Genera debug profundo de referencias en extracción de reader. |

Logs:

- `tfg_project/logs/citations_context.log`
- consola del servidor Django
- artefactos bajo `tmp/reference_debug/` y `tmp/reference_regression/`

## Fallbacks Funcionales

| Fallo | Resultado | Acción recomendada |
| --- | --- | --- |
| Semantic Scholar no responde | Error en búsqueda/descarga | Reintentar, usar DOI manual o subir PDF. |
| Crossref no resuelve DOI | Enriquecimiento incompleto | Mantener referencia local y revisar manualmente. |
| PaperMage no disponible | Motor no disponible o error | Revisar instalación de PaperMage. |
| PDF sin texto | 0 snippets/contextos | Añadir OCR fuera del sistema o copiar contexto manual. |
| Vite no está levantado | Reader no carga en modo dev | Borrar `READER_VITE_DEV_SERVER` o arrancar `npm run dev`. |
| GROBID no responde | Experimento falla | Levantar Docker local o ignorar GROBID. |

## Qué No Garantiza El Sistema

- Que un PDF descargado o subido corresponda inequívocamente al DOI indicado.
- Que una cita encontrada sea incorrecta; la decisión sigue siendo humana.
- Que todas las referencias del PDF puedan reconstruirse en orden.
- Que APIs externas tengan datos completos o consistentes entre sí.
- Que los módulos IA sean reproducibles o aptos para producción.

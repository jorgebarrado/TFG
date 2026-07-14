# Servicios de Extracción

El núcleo de la inteligencia de CiteCheck reside en sus servicios de procesamiento de documentos, ubicados en `citations/services/`.

## PaperMage Extractor (`papermage_extractor.py`)

Este servicio utiliza la librería **PaperMage** (desarrollada por el Allen Institute for AI) para un análisis estructural profundo de los documentos científicos.

### Funcionalidades
1.  **Carga de Documentos:** Utiliza `PDFPlumberParser` para convertir PDFs en objetos `Document` estructurados con entidades (páginas, líneas, spans).
2.  **Segmentación de Párrafos:** Reconstruye párrafos lógicos a partir de líneas, limpiando saltos de línea y espaciado inconsistente (`_clean_paragraph`, `_split_paragraphs`).
3.  **Detección de Contextos (`extract_contexts_from_pdf`):**
    *   Recibe una lista de **patrones regex** (ej. `\[\d+\]`, `Et al., 2020`).
    *   Itera sobre todos los párrafos del documento.
    *   Identifica si el párrafo pertenece a la sección de referencias o al cuerpo del texto.
    *   Devuelve una lista de `ContextHit` con metadatos precisos: página, índices de inicio/fin, y el texto del párrafo.

### Estructura `ContextHit`
```python
class ContextHit(TypedDict):
    paragraph: str  # Texto completo del párrafo
    snippet: str    # Fragmento recortado alrededor de la cita
    page: int       # Número de página (comienza en 1)
    start: int      # Índice de inicio en el párrafo
    end: int        # Índice de fin en el párrafo
    pattern: str    # Patrón que hizo match
    section: str    # "body" o "references"
```

## Citation Extractor (`citation_extractor.py`)

Proporciona una capa de abstracción para procesar manuscritos completos subidos por el usuario.
*   Detecta referencias bibliográficas y las estructura.
*   Calcula estadísticas del documento (número de referencias, páginas).

## Semantic Scholar Client (`semantic_scholar_client.py` y `semanticscholar.py`)

Cliente para interactuar con la API pública de Semantic Scholar.
*   **Búsqueda de Papers:** Por DOI o título.
*   **Resolución de PDFs:** Identifica si un artículo tiene un PDF de acceso abierto (`openAccessPdf`).
*   **Descarga Temporal:** Descarga PDFs a archivos temporales para su procesamiento inmediato por `papermage_extractor`.

## Pipeline Semántico (`semantic_citation_pipeline.py`)

Unifica los servicios anteriores en un flujo de trabajo coherente para el usuario final:
1.  El usuario consulta un DOI original.
2.  El sistema consulta a Semantic Scholar quién cita ese DOI.
3.  Para cada citador, intenta descargar el PDF.
4.  Si se descarga, ejecuta `papermage_extractor` buscando menciones al autor/año o número de referencia del DOI original.
5.  Devuelve los contextos hallados.

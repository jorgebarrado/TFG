# Servicios de Extracción y Procesamiento

La lógica pesada de CiteCheck reside en `citations/services/`. Estos módulos se encargan de interactuar con el mundo exterior (APIs) y procesar documentos (PDFs).

## Pipeline de Citas Semánticas

### `semantic_citation_pipeline.py`
Orquesta el proceso de búsqueda inversa.
1.  Dado un DOI original.
2.  Busca en Semantic Scholar qué artículos lo citan.
3.  Filtra aquellos con PDF de acceso abierto.
4.  Descarga y analiza los PDFs para encontrar *dónde* y *cómo* se cita al original.

### `semantic_scholar_client.py` y `semanticscholar.py`
Cliente para la API de Semantic Scholar.
*   Funciones para buscar papers por DOI, obtener referencias, y obtener URLs de PDFs (`get_openaccess_pdf_url`).
*   Manejo de errores y límites de API.

## Extracción de Contexto en PDF

### `papermage_extractor.py`
Utiliza la librería **PaperMage** (desarrollada por AI2) para un análisis profundo de PDFs.
*   **Funcionalidad:** Convierte el PDF en una estructura de objetos (Páginas, Tokens, Bloques).
*   **Búsqueda:** Busca patrones de referencia (ej. `[12]`, `(Smith, 2019)`).
*   **Contexto:** Extrae la sentencia o párrafo que contiene la cita, permitiendo entender la afirmación que se hace.

### `pdf_citation_analyzer.py`
Módulo de alto nivel que combina la descarga de PDFs y el uso de extractores.
*   `analyze_pdf_citations_from_url`: Descarga un PDF desde una URL y ejecuta la extracción de contextos.

## Otros Extractores

### `citation_extractor.py` y `generic_extractor.py`
Enfoques alternativos o legacy para extraer texto y referencias.
*   Pueden usar `PyPDF2` o expresiones regulares más simples para procesar texto plano o PDFs menos estructurados.
*   `process_manuscript`: Función de entrada para subir un manuscrito y extraer todas sus referencias.

### `dblp_client.py`
Cliente para la API de DBLP.
*   Permite buscar autores y obtener su lista de publicaciones en formato XML/JSON.
*   Usado para poblar el perfil del usuario con sus artículos.

## Inteligencia Artificial (Experimental)

### `ai_citation_detector.py` y `ai_report_evaluator.py`
Módulos preparados para integrar modelos de lenguaje (LLMs) o clasificadores para:
1.  Detectar automáticamente si una cita es sospechosa.
2.  Evaluar la calidad de un reporte generado por un usuario.

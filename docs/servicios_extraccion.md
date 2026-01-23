# Servicios de Extracción y Procesamiento

Este documento detalla la lógica interna de los servicios ubicados en `citations/services/`. Estos módulos son el motor de CiteCheck, encargados de interactuar con APIs externas, descargar documentos y procesar texto científico.

## 1. Pipeline Semántico (`semantic_citation_pipeline.py`)

**Responsabilidad:** Orquestar el flujo "dado un artículo A, encuentra quién lo cita (B, C, D...) y qué dicen de él".

### Función Principal
```python
def analyze_citations_for_original_doi(original_doi: str, max_citing_papers: int = 5) -> SemanticCitationAnalysisResult
```
*   **Input:** DOI del artículo original.
*   **Output:** Diccionario con metadatos de artículos citadores y, crucialmente, la lista de `contexts` (frases) extraídas de sus PDFs.

### Flujo Lógico
1.  Llama a `get_citing_papers_for_doi` (Semantic Scholar) para obtener una lista de DOIs que citan al original.
2.  Filtra aquellos que tienen `open_access_pdf_url`. **Punto Crítico:** Si no hay PDF Open Access, el artículo se descarta del análisis textual (aunque se cuente como cita).
3.  Para cada PDF válido, llama a `analyze_pdf_citations_from_url`.
4.  Agrega los resultados a una lista estructurada.

---

## 2. Cliente Semantic Scholar (`semantic_scholar_client.py`)

**Responsabilidad:** Abstraer la comunicación con la API pública de Semantic Scholar.

*   **Endpoint Principal:** `https://api.semanticscholar.org/graph/v1/paper/{doi}`
*   **Campos Solicitados:** `title`, `year`, `authors`, `openAccessPdf`, `citations.title`, `citations.year`, `citations.openAccessPdf`.

### Gestión de Errores
*   Captura excepciones de red y códigos de estado HTTP no 200.
*   **Limitación:** Actualmente no implementa reintentos automáticos (backoff) ni gestión de rate limits (claves de API).

---

## 3. Extractor PaperMage (`papermage_extractor.py`)

**Responsabilidad:** Procesamiento profundo de PDFs para entender su estructura (páginas, párrafos, referencias). Utiliza la librería `papermage` del Allen Institute for AI.

### Funciones Clave

#### `extract_contexts_from_pdf(pdf_path, patterns)`
Es el núcleo de la búsqueda de texto.
1.  **Carga:** `_load_document` usa `PDFPlumberParser` para convertir el PDF binario en objetos `Document`.
2.  **Iteración:** `_iter_paragraphs` recorre el documento intentando reconstruir párrafos lógicos (uniendo líneas cortadas).
3.  **Filtrado:** Detecta si está en la sección de referencias (`in_references`) buscando headers como "Bibliography".
4.  **Matching:** Aplica Regex (`patterns`) sobre cada párrafo.
5.  **Snippet:** Genera un recorte del texto alrededor del hallazgo con `_make_snippet`.

### Dependencias Críticas
*   Requiere `papermage` y sus dependencias (puede incluir PyTorch y Java para ciertos parsers, aunque aquí usamos `PDFPlumberParser` que es más ligero).
*   **Fallback:** Si `papermage` no está instalado, el módulo define flags (`PM_AVAILABLE = False`) para no romper la importación, pero las funciones lanzarán error en tiempo de ejecución.

---

## 4. Analizador de PDFs (`pdf_citation_analyzer.py`)

**Responsabilidad:** Puente entre la descarga de archivos y la extracción.

#### `analyze_pdf_citations_from_url(pdf_url, patterns)`
1.  Descarga el PDF a un archivo temporal (`tempfile`).
2.  Invoca a `extract_contexts_from_pdf`.
3.  **Limpieza:** Asegura el borrado del archivo temporal en un bloque `finally` para evitar llenar el disco del servidor.

---

## 5. Extractores Legacy (`citation_extractor.py`, `generic_extractor.py`)

**Responsabilidad:** Métodos alternativos de extracción, usados principalmente cuando se sube un manuscrito "en crudo" en el Reader.

*   **Science Parse / Grobid:** El código tiene hooks para llamar a estos servicios si están configurados (docker local), pero por defecto usa regex ("auto").
*   **Uso:** Principalmente para extraer *la lista de referencias bibliográficas* al final del documento, no el contexto en el cuerpo.

## Dónde Tocar para Mejorar

1.  **Mejorar OCR:** Integrar OCR (Tesseract) en `papermage_extractor.py` para PDFs escaneados (imagen) que actualmente devuelven texto vacío.
2.  **Soporte CrossRef:** Añadir un cliente CrossRef robusto en `semantic_scholar_client.py` como fallback cuando Semantic Scholar no tenga datos.
3.  **Async:** Mover `analyze_citations_for_original_doi` a una tarea de Celery, ya que descargar 5 PDFs puede tardar >30 segundos y causar timeout en la vista HTTP.

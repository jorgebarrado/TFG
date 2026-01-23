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

## 2. Motores de Extracción (`engines.py`)

**Responsabilidad:** Gestionar la disponibilidad de las distintas librerías de extracción y seleccionar cuál usar.

*   **Motores Soportados:**
    *   `papermage`: Wrapper sobre la librería AI2 PaperMage.
    *   `papercraft`: Extractor alternativo (en desarrollo).
    *   `generic`: Extractor basado en regex (fallback).
*   **Lógica de Selección:** La función `run_engine(requested, path)` decide. Si `requested="auto"`, prueba en cascada: `papermage` -> `papercraft` -> `generic`.

### Puntos de Extensión: ¿Cómo añadir un nuevo motor?
1.  Crea un archivo `nuevo_extractor.py` en `services/` con una función `extract_paragraphs(pdf_path)`.
2.  Importa el módulo en `engines.py` dentro de un bloque `try/except` para manejar dependencias faltantes.
3.  Añade la clave a `ENGINE_LABELS` y actualiza `list_extractor_engines`.
4.  Añade la lógica de llamada en `run_engine` (o en `_attempt`).

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

---

## 4. Analizador de PDFs (`pdf_citation_analyzer.py`)

**Responsabilidad:** Puente entre la descarga de archivos y la extracción.

#### `analyze_pdf_citations_from_url(pdf_url, patterns)`
1.  Descarga el PDF a un archivo temporal (`tempfile`).
2.  Invoca a `extract_contexts_from_pdf`.
3.  **Limpieza:** Asegura el borrado del archivo temporal en un bloque `finally` para evitar llenar el disco del servidor.

## Dónde Tocar para Mejorar

1.  **Mejorar OCR:** Integrar OCR (Tesseract) en `papermage_extractor.py` para PDFs escaneados (imagen) que actualmente devuelven texto vacío.
    *   *Archivo:* `services/papermage_extractor.py` -> `_load_document`.
2.  **Soporte CrossRef:** Añadir un cliente CrossRef robusto en `semantic_scholar_client.py` como fallback cuando Semantic Scholar no tenga datos.
    *   *Archivo:* `services/semantic_scholar_client.py`.
3.  **Async:** Mover `analyze_citations_for_original_doi` a una tarea de Celery, ya que descargar 5 PDFs puede tardar >30 segundos y causar timeout en la vista HTTP.
    *   *Archivo:* Crear `citations/tasks.py` y mover la lógica de `semantic_citation_pipeline.py`.

# Flujo de Datos End-to-End

Este documento explica cómo interactúan las tres herramientas principales de CiteCheck: **Reportes**, **Viewer** (Visor) y **Buscador de Citadores**.

## Diagrama de Flujo Global

```mermaid
graph TD
    User((Usuario))

    subgraph "Herramienta 1: Buscador de Citadores"
        Search[Búsqueda de Citadores]
        Pipeline[Semantic Pipeline]
        ExtraccionAuto[Extracción Auto (PaperMage)]
    end

    subgraph "Herramienta 2: Viewer (Reader)"
        ViewerUI[Interfaz React Reader]
        PDFRender[Renderizado PDF]
        RefExtract[Extracción de Referencias]
    end

    subgraph "Herramienta 3: Reportes"
        CreateForm[Formulario IncorrectCitation]
        DB[(Base de Datos)]
    end

    %% Flujo 1: Búsqueda -> Reporte
    User -->|1. Busca DOI Original| Search
    Search -->|2. Obtiene Citadores| Pipeline
    Pipeline -->|3. Descarga & Analiza| ExtraccionAuto
    ExtraccionAuto -->|4. Muestra Contextos| Search
    Search -->|5. Click 'Reportar'| CreateForm

    %% Flujo 2: Viewer -> Reporte
    User -->|1. Sube PDF / Abre PDF| ViewerUI
    ViewerUI -->|2. Extrae Refs| RefExtract
    ViewerUI -->|3. Click en Cita| ViewerUI
    ViewerUI -->|4. Click 'Reportar esta cita'| CreateForm

    %% Flujo 3: Reporte -> Viewer
    User -->|1. Ve Reporte Existente| DB
    DB -->|2. 'Ver en Contexto'| ViewerUI
    ViewerUI -->|3. Carga Datos (API reader-data)| DB
```

---

## Detalle de Flujos

### 1. De Búsqueda a Reporte
Es el flujo automatizado ideal.
1.  El usuario introduce un DOI "Víctima" (Artículo A).
2.  El backend (`semantic_citation_pipeline.py`) busca en Semantic Scholar quién cita a A.
3.  El sistema descarga los PDFs de los citadores (B, C...) y busca frases como "[12]" o "(Smith, 2020)".
4.  Si encuentra una frase sospechosa, el usuario pulsa "Reportar".
5.  Se pre-llena el formulario `IncorrectCitation` con:
    *   DOI Original (A).
    *   DOI Citador (B).
    *   **Contexto:** La frase exacta encontrada en el PDF.

### 2. Del Viewer al Reporte
Flujo manual asistido.
1.  El usuario abre el **Viewer** (Reader) con un PDF (artículo B).
2.  El Viewer llama a `/api/extract-citations/` para identificar todas las referencias.
3.  El usuario navega por el PDF. Al hacer clic en una referencia (ej. "[4]"), el visor resalta dónde aparece en el texto.
4.  Si el usuario detecta que lo que dice el texto no coincide con el título de la referencia [4], inicia el reporte desde el visor.
5.  El Viewer envía los metadatos de [4] (Original) y del PDF actual (Citador) al formulario de creación.

### 3. Del Reporte al Viewer
Flujo de verificación / consumo.
1.  Un usuario navega por la lista de reportes existentes.
2.  Ve una denuncia: "El paper B cita mal al paper A".
3.  Pulsa "Ver contexto completo".
4.  Se abre el **Viewer** cargando el PDF de B (si es Open Access).
5.  El Viewer consulta `/api/reader-data/<report_id>/`.
6.  El backend devuelve la ubicación exacta (`page`, `snippet`) guardada en el reporte.
7.  El Viewer hace **scroll automático** hasta la página y resalta la frase controvertida.

---

## Estructuras de Datos de Intercambio

### Objeto `ContextHit` (Backend -> Frontend)
Estructura estándar para pasar fragmentos de texto.

```json
{
  "paragraph": "Texto completo del párrafo...",
  "snippet": "Texto recortado...",
  "page": 5,          // Número de página (1-based)
  "start": 102,       // Índice inicio match
  "end": 140,         // Índice fin match
  "pattern": "[12]"   // Patrón que lo detectó
}
```

### Objeto `ReaderData` (API -> Viewer)
Datos para inicializar el visor en modo "Ver Reporte".

```json
{
  "pdf_url": "https://...",
  "mentions": [ ...ContextHit... ],  // Dónde se cita
  "references": [ ...Reference... ]  // Lista biblio
}
```

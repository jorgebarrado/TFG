# Frontend Reader (React)

El **Reader** es una aplicación React (Single Page Application) incrustada dentro del proyecto Django. Su función es visualizar PDFs, gestionar el resaltado de citas y facilitar la navegación entre referencias bibliográficas y sus menciones en el texto.

## Ubicación y Arquitectura
*   **Código Fuente:** `frontend_reader/`
*   **Entrada:** `frontend_reader/src/main.jsx`
*   **Componente Principal:** `frontend_reader/src/reader-app.jsx`
*   **Build:** Utiliza **Vite**. Los archivos compilados (`assets/`) se generan y Django los sirve como archivos estáticos.
*   **Librería Core:** `@allenai/pdf-components` (React PDF).

## Integración con Django
La aplicación React no corre en un puerto separado en producción. Se compila y se inyecta en una plantilla Django (`citations/templates/citations/reader.html`).

```html
<!-- Ejemplo conceptual de integración -->
<div id="root"
     data-api-url="..."
     data-pdf-url="..."
     data-report-id="...">
</div>
<script src="{% static 'reader/index.js' %}"></script>
```

## Estado de la Aplicación (`reader-app.jsx`)

El componente `ReaderApp` gestiona un estado complejo para sincronizar la vista del PDF con los datos de citas.

### Estados Principales
*   `activeFile` / `previewUrl`: El archivo PDF binario o URL que se está visualizando.
*   `snippetsData`: Lista de menciones en el texto (ej. "[1]", "Smith et al.").
*   `referencesData`: Lista de referencias bibliográficas (al final del documento).
*   `activeTab`: Pestaña lateral activa (`snippets`, `references`, `stats`, `extract`).
*   `selectedSnippet`: El fragmento de texto actualmente seleccionado/resaltado.
*   `activeCitation`: La cita sobre la que el usuario ha hecho clic en el PDF (capa interactiva).

### Hooks y Efectos Clave
1.  **Carga Inicial:** Al montar, si hay `apiUrl` (modo "Ver Reporte"), hace fetch para traer los datos del backend.
2.  **Resaltado (`useHighlightedSnippet`):**
    *   Escucha cambios en `selectedSnippet`.
    *   Busca en la capa de texto del PDF (`.textLayer`) el texto coincidente.
    *   Dibuja cajas de resaltado (`.reader-highlight` o `.reader-paragraph-layer`) sobre las coordenadas calculadas.
    *   *Nota Técnica:* Usa un algoritmo difuso (fuzzy) simple si el match exacto falla, buscando keywords.
3.  **Detección de Citas (`collectCitationHitsForPage`):**
    *   Escanea el DOM de cada página renderizada buscando patrones regex (`[1]`, `Name et al.`).
    *   Crea una capa interactiva transparente sobre el texto para hacer las citas clicables.

## Comunicación con Backend

El Reader consume las siguientes APIs (ver `api_reference_completa.md`):

1.  **`GET /citations/api/reader-data/<id>/`**: Inicializa el visor con datos de un reporte.
2.  **`POST /citations/api/extract-citations/`**: Envía el PDF actual para que el backend extraiga referencias y snippets (cuando el usuario sube un archivo manualmente).
3.  **`GET /citations/api/extractor-engines/`**: Obtiene lista de motores disponibles (`auto`, `science-parse`).

## Estilos
*   **CSS:** `frontend_reader/src/styles.css`.
*   Usa variables CSS y prefijos `reader-` para evitar colisiones con el CSS de Bootstrap de Django.

## Desarrollo Local
Para trabajar en el frontend sin recompilar Django constantemente:
1.  Ir a `frontend_reader/`.
2.  `npm install`.
3.  `npm run dev`.
4.  *Nota:* Esto levantará un servidor Vite separado. Para verlo integrado en Django, se debe configurar Django para apuntar al servidor de desarrollo de Vite o hacer `npm run build` tras cada cambio.

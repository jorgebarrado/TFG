# Frontend Reader (React)

El **Reader** es una aplicación React (Single Page Application) incrustada dentro del proyecto Django. Su función es visualizar PDFs, gestionar el resaltado de citas y facilitar la navegación entre referencias bibliográficas y sus menciones en el texto.

## Estructura Híbrida

La aplicación no es 100% SPA; vive dentro de una plantilla de Django.

### 1. El Wrapper Legacy (Django)
*   **Archivo:** `citations/templates/citations/reader.html`
*   **Responsabilidad:**
    *   Provee el contenedor HTML (`<div id="root">`).
    *   Inyecta datos iniciales desde el backend (URL del PDF, ID del reporte) usando `data-attributes`.
    *   Carga el bundle de JavaScript compilado (`{% static 'assets/index.js' %}`).

```html
<!-- Ejemplo conceptual de integración -->
<div id="root"
     data-api-url="/citations/api/reader-data/123/"
     data-pdf-url="..."
     data-report-id="123">
</div>
```

### 2. La Aplicación React (Moderna)
*   **Directorio:** `frontend_reader/`
*   **Entrada:** `frontend_reader/src/main.jsx`
*   **Responsabilidad:**
    *   Lee los `data-attributes` del div `#root`.
    *   Monta el componente raíz `ReaderApp`.
    *   Gestiona todo el renderizado del PDF y la interactividad.

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

| API Endpoint | Método | Uso |
| :--- | :--- | :--- |
| `/citations/api/reader-data/<id>/` | GET | Inicializa el visor con datos de un reporte existente. |
| `/citations/api/extract-citations/` | POST | Envía el PDF actual para que el backend extraiga referencias y snippets (modo subida manual). |
| `/citations/api/extractor-engines/` | GET | Obtiene lista de motores disponibles (`auto`, `science-parse`) para poblar el dropdown. |

## Desarrollo Local

Para trabajar en el frontend sin recompilar Django constantemente:
1.  Ir a `frontend_reader/`.
2.  `npm install`.
3.  `npm run dev`.
4.  *Nota:* Esto levantará un servidor Vite separado. Para verlo integrado en Django, se debe configurar Django para apuntar al servidor de desarrollo de Vite o hacer `npm run build` tras cada cambio.

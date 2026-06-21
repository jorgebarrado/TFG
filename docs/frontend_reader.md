# Frontend Reader

App React/Vite integrada en Django para visualizar PDFs, extraer referencias, mostrar menciones y navegar entre contexto y bibliografía.

## Arquitectura visual

Dos paneles fijos:

```
┌────────────────────┬──────────────────────────┐
│  Sidebar (360px)   │      PDF Viewer           │
│                    │                           │
│  Tab: Extraer      │  + Overlay citas          │
│  Tab: Snippets     │  + Overlay referencias    │
│  Tab: Referencias  │  + Overlay capas v2       │
└────────────────────┴──────────────────────────┘
```

Las tres pestañas del sidebar:

- **Extraer** — dropzone para subir PDF, botón para lanzar extracción, barra de progreso.
- **Snippets** — lista citas encontradas en el texto. Al clicar una, el PDF hace scroll y resalta el fragmento.
- **Referencias** — lista referencias bibliográficas con mapa cita↔referencia. Al clicar, se resalta en el PDF con un overlay SVG.

## Flujo de datos

```
1. Django abre el reader en ventana nueva y pone el PDF en IndexedDB
2. main.jsx lee IndexedDB, monta ReaderApp
3. Usuario sube PDF (o viene precargado) → se renderiza con @allenai/pdf-components
4. Usuario pulsa "Extraer" → POST /citations/api/extract-citations/ con el PDF
5. Backend devuelve snippets + referencias + datos visuales
6. El reader pinta overlays SVG encima del PDF
7. Clic en snippet → scroll + highlight en PDF
   Clic en referencia → resaltado + popover con metadata
```

## Bootstrap (main.jsx)

Antes de montar React hace tres cosas:

1. Lee config del HTML (`apiUrl`, `pdfUrl`, `reportId`…) desde atributos `data-*`.
2. Recupera el PDF de **IndexedDB** y la metadata de **sessionStorage** (la ventana padre los deposita ahí antes de abrir el reader).
3. Notifica al opener con `postMessage` que está listo (`reader:ready`).

## Detección de citas en el PDF

Busca patrones con regex sobre el `textLayer` de cada página:

| Tipo | Ejemplo |
|---|---|
| Numérica | `[12]`, `[1,3]`, `[1-4]` |
| Autor-año narrativo | `Smith et al. (2020)` |
| Autor-año parentético | `(Smith, 2020; Jones, 2021)` |
| DOI desnudo | `10.1234/algo` |

## Sistema de overlays

Capas SVG apiladas sobre el PDF (z-index):

| z-index | Capa | Contenido |
|---|---|---|
| 24 | `reader-v2-overlay` | Tokens, párrafos, filas (capas papermage) |
| 25 | `reader-ref-overlay` | Referencias y contextos (azul/cyan) |
| 26 | `reader-paragraph-layer` | Snippet resaltado actual (naranja) |
| 28 | `reader-citation-layer` | Citas detectadas en el texto |

## Ubicación

```text
frontend_reader/
├── package.json
├── vite.config.js
├── index.html
└── src/
    ├── main.jsx
    ├── reader-app.jsx
    └── styles.css
```

Build de producción:

```text
tfg_project/citations/static/reader/
├── index.html
├── reader.js
├── reader.js.map
└── reader.css
```

## Integración con Django

Plantillas:

- `tfg_project/citations/templates/citations/reader.html`
- `tfg_project/citations/templates/citations/reader_preview.html`

Ambas montan React en:

```html
<div id="reader-root" class="reader-root-fullscreen"></div>
```

`reader.html` añade datos de reporte:

- `data-api-url`;
- `data-pdf-url`;
- `data-report-id`;
- `data-original-doi`;
- `data-incorrect-doi`.

En producción o sin Vite, Django carga:

```django
{% static 'reader/reader.css' %}
{% static 'reader/reader.js' %}
```

En desarrollo, si `READER_VITE_DEV_SERVER` está definido y `DJANGO_DEBUG=1`, carga:

```html
<script type="module" src="<vite>/@vite/client"></script>
<script type="module" src="<vite>/src/main.jsx"></script>
```

## Dependencias

`frontend_reader/package.json` usa:

- React 17;
- Vite 5;
- `@allenai/pdf-components`;
- `react-pdf`;
- Less.

El único paquete npm mantenido está en `frontend_reader/`.

## Build y Desarrollo

Instalación:

```powershell
cd frontend_reader
npm install
```

Servidor Vite:

```powershell
npm run dev
```

Build integrado:

```powershell
npm run build
```

`vite.config.js` escribe el build en `../tfg_project/citations/static/reader`, con nombres estables `reader.js` y `reader.css`.

## APIs Consumidas

| Endpoint | Método | Uso |
| --- | --- | --- |
| `/citations/api/reader-data/<id>/` | GET | Carga datos para un reporte existente. |
| `/citations/api/extract-citations/` | POST | Procesa PDF subido y devuelve referencias/snippets/capas. |
| `/citations/api/detect-article-doi/` | POST | Intenta detectar DOI del PDF. |
| `/citations/api/extractor-engines/` | GET | Lista motores disponibles. |
| `/citations/api/pdf-reader-v2-upload/` | POST | Devuelve páginas y capas para overlays. |
| `/citations/api/reference-debug-download/` | GET | Descarga debug de referencias si se activó. |

## Estado Interno Relevante

`reader-app.jsx` coordina:

- PDF activo (`activeFile`, `previewUrl`, `pdfUrl`);
- referencias (`referencesData`);
- snippets/menciones (`snippetsData`, `selectedSnippet`, `activeCitation`);
- capas del PDF (`pages`, `layers`);
- pestañas y paneles laterales;
- stats, enriquecimiento y datos del artículo;
- modo debug de detección de referencias.

El resaltado depende de la capa de texto del PDF. Cambios en `@allenai/pdf-components`, `react-pdf` o CSS pueden afectar el cálculo visual de cajas.

## Contrato de Datos

El reader espera referencias con campos como:

```json
{
  "index": 1,
  "raw": "[1] Smith ...",
  "doi": "10.1000/example",
  "title": "Optional title",
  "authors": ["Smith"],
  "year": 2020,
  "confidence": 1.0,
  "numbered": true
}
```

Y snippets/contextos con:

```json
{
  "id": "snippet-1",
  "page": 3,
  "snippet": "...",
  "type": "numeric",
  "confidence": 0.8
}
```

Antes de cambiar nombres de campos, revisa `reader-app.jsx`, `views_api.py`, `reader_data.py` y `references_data.py`.

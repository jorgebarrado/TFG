# Frontend Reader

El reader es una aplicación React/Vite integrada en Django para visualizar PDFs, extraer referencias, mostrar menciones y navegar entre contexto y bibliografía.

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

El `package.json` de la raíz contiene dependencias frontend históricas y no sustituye al paquete real del reader.

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

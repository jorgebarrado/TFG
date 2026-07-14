# Frontend Reader (Lector PDF)

El proyecto incluye un componente frontend especializado para la visualización de PDFs y la interacción con los contextos extraídos. Este componente se encuentra en el directorio `frontend_reader/`.

## Arquitectura

*   **Tecnología Base:** React 17 + Vite.
*   **Librería PDF:** `@allenai/pdf-components` (basada en `react-pdf`). Esta librería facilita el renderizado de PDFs y la superposición de capas (highlights) sobre el canvas del documento.

## Estructura del Proyecto (`frontend_reader/src/`)

*   **`main.jsx`**: Punto de entrada de la aplicación React. Monta el componente en el DOM.
*   **`reader-app.jsx`**: Componente principal. Gestiona el estado de la aplicación:
    *   Carga del PDF.
    *   Renderizado de la lista de contextos/highlights laterales.
    *   Sincronización entre el clic en un contexto y el scroll automático a la posición en el PDF.
*   **`styles.css`**: Estilos globales para el lector (layout de dos columnas: visor PDF + panel lateral).

## Integración con Django

El frontend no funciona como una SPA (Single Page Application) aislada, sino como un componente embebido dentro de las plantillas de Django cuando se requiere visualizar un reporte.

1.  **Build:** El frontend se compila con `npm run build`.
2.  **Archivos Estáticos:** Vite genera archivos JS y CSS en `dist/assets/`.
3.  **Template Django:** Las vistas de Django que necesitan el lector incluyen estos archivos estáticos compilados en su HTML.
4.  **Paso de Datos:** Django pasa datos iniciales (URL del PDF, lista de contextos JSON) al componente React, a menudo inyectándolos como variables globales en `window` o atributos `data-` en el elemento raíz donde se monta React.

## Desarrollo Local

Para desarrollar cambios en el lector sin tener que recompilar constantemente:

1.  Ejecutar `npm run dev` en `frontend_reader/`.
2.  Configurar la plantilla de Django para cargar el script desde `http://localhost:5173/main.jsx` (puerto por defecto de Vite) cuando `DEBUG=True`, en lugar de cargar los archivos estáticos compilados. Esto permite Hot Module Replacement (HMR).

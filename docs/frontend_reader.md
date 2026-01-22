# Frontend Reader (React)

El proyecto incluye una aplicación de frontend moderna construida con **React 17** y **Vite**, ubicada en el directorio `frontend_reader/`. Esta aplicación sirve como el visor avanzado de documentos ("Citation Reader").

## Arquitectura

*   **Framework:** React 17.
*   **Build Tool:** Vite.
*   **Librerías Clave:**
    *   `@allenai/pdf-components`: Componentes especializados para renderizar PDFs y superponer anotaciones (bboxes) para citas científicas.
    *   `react-pdf`: Renderizado de PDFs en el navegador.

## Integración con Django

Aunque es una aplicación React SPA (Single Page Application), está diseñada para integrarse dentro de las plantillas de Django.

1.  **Desarrollo:**
    *   Se ejecuta independientemente con `npm run dev`.
    *   Django puede servirla mediante proxy o CORS durante el desarrollo.
2.  **Producción:**
    *   Se ejecuta `npm run build`.
    *   Vite genera los archivos estáticos (JS y CSS) en `dist/`.
    *   Estos archivos deben ser recogidos por el sistema de archivos estáticos de Django o servidos por Nginx/Apache.
    *   La vista de Django `citation_reader` carga una plantilla HTML que incluye estos scripts compilados y pasa los datos iniciales (como el `report_id` o JSONs de configuración) mediante variables globales de ventana o atributos data.

## Componentes Principales

*   **Visor de PDF:** Carga el PDF desde una URL (proxy o directa).
*   **Sidebar de Citas:** Muestra la lista de referencias detectadas.
*   **Highlighter:** Dibuja cajas (bounding boxes) sobre el PDF donde se encuentran las menciones a las citas, permitiendo interactividad (clic para ver detalle).

## Comandos

Desde el directorio `frontend_reader/`:

```bash
# Instalar dependencias
npm install

# Servidor de desarrollo
npm run dev

# Construir para producción
npm run build
```

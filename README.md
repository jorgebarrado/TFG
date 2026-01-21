# Proyecto de Fin de Grado: CiteCheck

CiteCheck es una plataforma para la validación colaborativa y el análisis automatizado de citas en artículos científicos.

Para una documentación detallada del proyecto, por favor consulta el directorio `docs/`:

## Índice de Documentación

1.  **[Introducción](docs/introduccion.md)**: Visión general, objetivos y tecnologías.
2.  **[Instalación y Despliegue](docs/instalacion_despliegue.md)**: Guía paso a paso para configurar el entorno backend (Django) y frontend (React/Vite).
3.  **[Arquitectura del Backend](docs/backend_arquitectura.md)**: Estructura del código Django, apps y organización.
4.  **[Modelos de Datos](docs/modelos_datos.md)**: Descripción de la base de datos (Usuarios, Reportes, Votos).
5.  **[Servicios de Extracción](docs/servicios_extraccion.md)**: Detalles técnicos sobre PaperMage, extracción de texto y pipelines de análisis.
6.  **[API REST](docs/api_rest.md)**: Documentación de los endpoints de la API.
7.  **[Frontend Reader](docs/frontend_reader.md)**: Documentación del componente visor de PDFs en React.

## Resumen Rápido (Quickstart)

```bash
# Backend
python -m venv venv
source venv/bin/activate
pip install -r requirements-3.13.txt --extra-index-url https://download.pytorch.org/whl/cpu
python tfg_project/manage.py migrate
python tfg_project/manage.py runserver

# Frontend (opcional para desarrollo)
cd frontend_reader
npm install
npm run dev
```

La aplicación estará disponible en `http://127.0.0.1:8000/`.

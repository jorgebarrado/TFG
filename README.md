# Proyecto de Fin de Grado: CiteCheck

CiteCheck es una aplicación web desarrollada en Django que permite a los investigadores identificar y reportar citas incorrectas en artículos académicos.

## Documentación

La documentación completa del proyecto se encuentra en el directorio `docs/`:

-   [**Introducción**](docs/introduccion.md): Visión general del proyecto y sus objetivos.
-   [**Guía de Instalación**](docs/instalacion.md): Pasos para configurar el entorno de desarrollo.
-   [**Manual de Usuario**](docs/manual_usuario.md): Guía para registrarse, reportar citas y usar la plataforma.
-   [**Arquitectura del Backend**](docs/arquitectura_backend.md): Estructura del proyecto Django.
-   [**Modelos de Datos**](docs/modelos_datos.md): Descripción de la base de datos.
-   [**Servicios de Extracción**](docs/servicios_extraccion.md): Detalles técnicos sobre la extracción de citas y uso de APIs.
-   [**API REST**](docs/api_rest.md): Documentación de los endpoints disponibles.
-   [**Frontend Reader**](docs/frontend_reader.md): Información sobre el visor de documentos en React.

## Características Rápidas

-   **Registro de usuarios y perfiles:** Los usuarios pueden registrarse, iniciar sesión y gestionar sus perfiles.
-   **Integración con DBLP:** Los usuarios pueden vincular sus perfiles de DBLP para ver sus publicaciones.
-   **Reporte de citas incorrectas:** Los usuarios pueden reportar citas incorrectas proporcionando los DOIs de los artículos implicados.
-   **Sistema de comentarios y votos:** Los usuarios pueden comentar y votar en los reportes de citas incorrectas.
-   **Extracción de contexto:** La aplicación puede extraer el contexto de las citas de archivos PDF.
-   **API REST:** Proporciona endpoints para la extracción de citas y contextos.

## Uso Rápido

1.  **Iniciar servidor:** `python tfg_project/manage.py runserver`
2.  **Acceder:** `http://127.0.0.1:8000/`

## Configuración Opcional

Para mejorar la estabilidad de las peticiones a Semantic Scholar puedes definir `SEMANTIC_SCHOLAR_API_KEY` en tu `.env` local. Es opcional para desarrollo: si no existe, la aplicación usa peticiones no autenticadas. No subas nunca una key real al repositorio; el plan actual de Semantic Scholar limita a 1 request/segundo.

# Proyecto de Fin de Grado: CiteCheck

CiteCheck es una aplicación web desarrollada en Django que permite a los investigadores identificar y reportar citas incorrectas en artículos académicos.

## Características

- **Registro de usuarios y perfiles:** Los usuarios pueden registrarse, iniciar sesión y gestionar sus perfiles.
- **Integración con DBLP:** Los usuarios pueden vincular sus perfiles de DBLP para ver sus publicaciones.
- **Reporte de citas incorrectas:** Los usuarios pueden reportar citas incorrectas proporcionando los DOIs de los artículos implicados.
- **Sistema de comentarios y votos:** Los usuarios pueden comentar y votar en los reportes de citas incorrectas.
- **Extracción de contexto:** La aplicación puede extraer el contexto de las citas de archivos PDF.
- **API REST:** Proporciona endpoints para la extracción de citas y contextos.

## Instalación

1.  **Clonar el repositorio:**

    ```bash
    git clone https://github.com/tu-usuario/tu-repositorio.git
    cd tu-repositorio
    ```

2.  **Crear un entorno virtual e instalar las dependencias:**

    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    pip install -r requirements-3.13.txt
    ```

3.  **Configurar la base de datos:**

    ```bash
    python tfg_project/manage.py migrate
    ```

4.  **Crear un superusuario:**

    ```bash
    python tfg_project/manage.py createsuperuser
    ```

5.  **Iniciar el servidor de desarrollo:**

    ```bash
    python tfg_project/manage.py runserver
    ```

La aplicación estará disponible en `http://127.0.0.1:8000/`.

## Uso

- **Accede al panel de administración:** `http://127.0.0.1:8000/admin`
- **Página de inicio:** `http://127.0.0.1:8000/`
- **Lista de reportes:** `http://127.0.0.1:8000/list/`

## Estructura del proyecto

- `tfg_project/`: Directorio principal del proyecto Django.
  - `citations/`: La aplicación principal de Django que contiene la lógica de negocio.
    - `models.py`: Define los modelos de la base de datos.
    - `views.py`: Contiene las vistas que renderizan las páginas HTML.
    - `views_api.py`: Contiene los endpoints de la API.
    - `services/`: Contiene la lógica de negocio para interactuar con APIs externas y procesar documentos.
    - `forms.py`: Define los formularios de la aplicación.
    - `urls.py`: Define las rutas de la aplicación.
    - `templates/`: Contiene las plantillas HTML.
  - `tfg_project/`: Contiene la configuración del proyecto Django.
- `requirements-3.13.txt`: Lista de dependencias de Python.
- `manage.py`: Script de gestión de Django.

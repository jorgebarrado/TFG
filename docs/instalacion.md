# Guía de Instalación y Configuración

Esta guía detalla los pasos necesarios para configurar el entorno de desarrollo de CiteCheck, tanto para el backend (Django) como para el frontend (React).

## Requisitos Previos

*   **Python 3.13** o superior.
*   **Node.js** y **npm** (para el frontend).
*   **Git**.

## Configuración del Backend (Django)

1.  **Clonar el repositorio:**

    ```bash
    git clone <url-del-repositorio>
    cd <nombre-del-directorio>
    ```

2.  **Crear un entorno virtual:**

    Es recomendable usar un entorno virtual para aislar las dependencias.

    ```bash
    python -m venv venv
    # Activar en Linux/macOS
    source venv/bin/activate
    # Activar en Windows
    venv\Scripts\activate
    ```

3.  **Instalar dependencias:**

    El proyecto requiere dependencias específicas, incluyendo versiones de PyTorch para CPU (si no dispones de GPU).

    ```bash
    pip install -r requirements-3.13.txt --extra-index-url https://download.pytorch.org/whl/cpu
    ```

4.  **Configurar variables de entorno:**

    Crea un archivo `.env` en la raíz del proyecto (`tfg_project/`) o configura las variables en tu sistema. Las variables principales son:

    *   `DJANGO_SECRET_KEY`: Clave secreta de Django.
    *   `DJANGO_DEBUG`: `True` para desarrollo, `False` para producción.
    *   `ALLOWED_HOSTS`: Lista de hosts permitidos (ej. `localhost,127.0.0.1`).
    *   `LOG_CITATIONS`: `1` para activar logs detallados de extracción.
    *   `SEMANTIC_SCHOLAR_API_KEY`: opcional para desarrollo. Si se configura, se envía a Semantic Scholar como `x-api-key` y mejora la estabilidad de las peticiones. No subas nunca una key real al repositorio; el plan actual limita a 1 request/segundo.

5.  **Migrar la base de datos:**

    ```bash
    python tfg_project/manage.py migrate
    ```

6.  **Crear un superusuario (Administrador):**

    ```bash
    python tfg_project/manage.py createsuperuser
    ```

7.  **Compilar archivos de traducción (Opcional):**
    Si necesitas asegurar que las traducciones estén actualizadas.
    ```bash
    # Requiere gettext instalado en el sistema
    python tfg_project/manage.py compilemessages
    ```

8.  **Iniciar el servidor de desarrollo:**

    ```bash
    python tfg_project/manage.py runserver
    ```
    El backend estará disponible en `http://127.0.0.1:8000/`.

## Configuración del Frontend (Lector PDF - React)

El proyecto incluye un visor de PDF avanzado basado en React ubicado en `frontend_reader/`.

1.  **Navegar al directorio del frontend:**

    ```bash
    cd frontend_reader
    ```

2.  **Instalar dependencias de Node:**

    ```bash
    npm install
    ```

3.  **Ejecutar en modo desarrollo:**

    ```bash
    npm run dev
    ```

4.  **Compilar para producción:**

    Para integrar los cambios en Django, debes compilar el proyecto. Los archivos generados se deben mover/referenciar en los estáticos de Django (según la configuración de despliegue específica).

    ```bash
    npm run build
    ```

## Notas Adicionales

*   **Logs:** Los logs de extracción de citas se guardan en `tfg_project/logs/citations_context.log`.
*   **APIs Externas:** Algunas funcionalidades dependen de la disponibilidad de la API de Semantic Scholar. Asegúrate de tener conexión a internet. Puedes configurar `SEMANTIC_SCHOLAR_API_KEY` en tu `.env` local, pero es opcional y la app funciona sin ella usando peticiones no autenticadas.

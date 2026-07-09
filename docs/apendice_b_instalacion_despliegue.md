# Apéndice B. Guía de Instalación y Despliegue

Este apéndice describe cómo preparar un entorno para ejecutar CiteCheck, incluyendo la configuración local, variables de entorno y despliegue usando contenedores Docker.

## B.1. Requisitos

- Python 3.11 recomendado. (El archivo `docker/Dockerfile` utiliza `python:3.11-slim`).
- Node.js y npm para compilar el frontend en `frontend_reader/`.
- Git.
- Docker (opcional, pero recomendado) para ejecutar la aplicación o los servicios experimentales como GROBID.

En Windows, el archivo `requirements.txt` incluye `pywin32`. En Linux o macOS, puedes usar Docker o crear una copia local del archivo de requerimientos excluyendo `pywin32==311` si la instalación directa falla.

## B.2. Instalación del Backend (Django)

Para realizar una instalación directa desde la raíz del repositorio:

**En Windows (PowerShell):**
```powershell
python -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

**En Linux/macOS:**
```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

Aplica las migraciones y arranca el servidor:

```bash
python tfg_project/manage.py migrate
python tfg_project/manage.py createsuperuser
python tfg_project/manage.py runserver
```

La aplicación estará disponible localmente en `http://127.0.0.1:8000/`.

## B.3. Variables de Entorno

Crea un archivo `.env` en la raíz desde la que ejecutes Django. La biblioteca `python-dotenv` se encargará de cargarlo al iniciar `settings.py`.

```env
DJANGO_DEBUG=1
DJANGO_SECRET_KEY=dev-only-change-me
ALLOWED_HOSTS=localhost,127.0.0.1,[::1]
LOG_CITATIONS=1
LOG_CITATIONS_LEVEL=INFO
SEMANTIC_SCHOLAR_API_KEY=
READER_VITE_DEV_SERVER=
GROBID_BASE_URL=http://localhost:8070
GROBID_TIMEOUT=120
```

**Variables opcionales clave:**
- `SEMANTIC_SCHOLAR_API_KEY`: Mejora las cuotas y la estabilidad del cliente de Semantic Scholar.
- `OPENAI_API_KEY`: Requerida solo por el parser LLM experimental y el evaluador IA.
- `GOOGLE_API_KEY`: Requerida solo por el detector IA experimental basado en Google Generative AI.
- `READER_VITE_DEV_SERVER`: Si su valor es `http://localhost:5173`, Django cargará el reader desde Vite durante el desarrollo.

## B.4. Instalación del Frontend Reader

El reader (frontend) se encuentra en el directorio `frontend_reader/` y genera los archivos estáticos finales en `tfg_project/citations/static/reader`.

```bash
cd frontend_reader
npm install
npm run build
```

Para desarrollo con recarga en caliente utilizando Vite:

```bash
cd frontend_reader
npm run dev
```

En este caso, define la variable de entorno correspondiente en tu archivo `.env`:

```env
READER_VITE_DEV_SERVER=http://localhost:5173
```

Con esa variable definida y `DJANGO_DEBUG=1`, las plantillas `reader.html` y `reader_preview.html` cargarán los módulos dinámicamente desde Vite. Sin ella, cargarán los archivos estáticos precompilados.

## B.5. Docker

CiteCheck incluye una configuración completa para ejecutar el proyecto en contenedores. El sistema de despliegue se define mediante los siguientes archivos dentro del directorio `docker/`:

- **`docker/Dockerfile`**: Construye la imagen del backend basado en `python:3.11-slim`, limpia el archivo `requirements.txt` y prepara las dependencias.
- **`docker/Dockerfile.dockerignore`**: Excluye elementos innecesarios (carpetas .git, entornos virtuales, caches, y node_modules) del contexto de construcción para acelerar el proceso y evitar exponer secretos.
- **`docker/compose.yml`**: Orquesta los contenedores, exponiendo el servicio Django en `8000` y configurando el servicio experimental GROBID en `8070`.

### Uso de Docker

Para arrancar el backend únicamente:

```bash
docker compose -f docker/compose.yml up web
```

Para arrancar el backend junto con el servicio GROBID (experimental y más pesado):

```bash
docker compose -f docker/compose.yml --profile experimental up
```

Para reconstruir la imagen tras cambios en dependencias:

```bash
docker compose -f docker/compose.yml build web
```

## B.6. Traducciones

El proyecto utiliza soporte de internacionalización. Para recompilar los mensajes:

```bash
python tfg_project/manage.py compilemessages
```

*Nota:* Esto requiere que `gettext` esté instalado en tu sistema operativo.

## B.7. Verificación Inicial

Para verificar que el sistema y el pipeline de referencia funcionan correctamente, ejecuta:

```bash
python tfg_project/manage.py check
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
```

Toma en cuenta que los tests de baseline utilizan PDFs reales, por lo que su ejecución puede tomar más tiempo que las validaciones habituales de Django.

# Instalación y Configuración

Esta guía prepara un entorno local para ejecutar CiteCheck, compilar el reader React y activar herramientas opcionales como GROBID.

## Requisitos

- Python 3.11 recomendado. `docker/Dockerfile` usa `python:3.11-slim`.
- Node.js y npm para `frontend_reader/`.
- Git.
- Docker opcional para ejecutar la app o GROBID en contenedores.

En Windows, `requirements.txt` incluye `pywin32`. En Linux/macOS, usa Docker o crea una copia local de requirements sin `pywin32==311` si la instalación directa falla.

## Backend Django

Desde la raíz del repositorio:

```powershell
python -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

En Linux/macOS:

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

Aplica migraciones y arranca el servidor:

```powershell
python tfg_project/manage.py migrate
python tfg_project/manage.py createsuperuser
python tfg_project/manage.py runserver
```

URL local: `http://127.0.0.1:8000/`.

## Variables de Entorno

Crea un `.env` en la raíz desde la que ejecutes Django. `python-dotenv` lo carga al iniciar `settings.py`.

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

Variables opcionales:

- `SEMANTIC_SCHOLAR_API_KEY`: mejora cuotas y estabilidad de Semantic Scholar.
- `OPENAI_API_KEY`: requerida solo por el parser LLM experimental y evaluador IA.
- `GOOGLE_API_KEY`: requerida solo por el detector IA experimental basado en Google Generative AI.
- `READER_VITE_DEV_SERVER`: si vale `http://localhost:5173`, Django cargará el reader desde Vite durante desarrollo.

## Docker

Ver [docker.md](docker.md) para la descripción completa de los archivos y su función.

Ejecutar el backend:

```powershell
docker compose -f docker/compose.yml up -d web
```

Levantar GROBID experimental:

```powershell
docker compose -f docker/compose.yml --profile experimental up -d grobid
```

`docker/compose.yml` expone Django en `8000` y GROBID en `8070`.

## Frontend Reader

El reader vive en `frontend_reader/` y genera los estáticos finales en `tfg_project/citations/static/reader`.

```powershell
cd frontend_reader
npm install
npm run build
```

Para desarrollo con Vite:

```powershell
cd frontend_reader
npm run dev
```

Después define:

```env
READER_VITE_DEV_SERVER=http://localhost:5173
```

Con esa variable y `DJANGO_DEBUG=1`, las plantillas `reader.html` y `reader_preview.html` cargarán los módulos desde Vite. Sin esa variable, cargarán `static/reader/reader.js` y `static/reader/reader.css`.

## Traducciones

El proyecto usa `locale/` y `LocaleMiddleware`. Para recompilar mensajes:

```powershell
python tfg_project/manage.py compilemessages
```

Requiere `gettext` instalado en el sistema.

## Verificación Inicial

```powershell
python tfg_project/manage.py check
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
```

La baseline de referencias usa PDFs reales y puede tardar más que un check de Django.

# CiteCheck

CiteCheck es una aplicación web para registrar, revisar y contextualizar citas académicas potencialmente incorrectas. El proyecto combina un backend Django, una interfaz HTML con Bootstrap, un lector PDF en React y servicios de extracción/enriquecimiento bibliográfico.

## Capacidades Principales

- Reportes de citas incorrectas basados en `IncorrectCitation`, con DOI original, DOI citador, tipo de error, área de publicación, explicación y contextos extraídos.
- Comunidad: comentarios con respuestas, votos, reportes guardados, perfiles públicos, mensajes privados y notificaciones.
- Integración académica: búsqueda de metadatos DOI, DBLP para publicaciones de usuario, Semantic Scholar para citadores y PDFs open access, y Crossref como fuente complementaria.
- Reader PDF: visor React/Vite integrado en Django para subir PDFs, extraer referencias, detectar menciones y navegar entre referencia y contexto.
- Herramientas de ingeniería: runner de regresión para referencias, experimentos aislados con GROBID y comparativas de parsers de referencias.

## Inicio Rápido

Requisitos recomendados: Python 3.11, Node.js/npm para el reader, Git y Docker opcional para GROBID o para ejecutar el servicio web en contenedor.

Windows (PowerShell):

```powershell
python -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
python tfg_project/manage.py migrate
python tfg_project/manage.py runserver
```

Linux/macOS:

```bash
python3.11 -m venv .venv311
source .venv311/bin/activate
python -m pip install --upgrade pip
python -m pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
python tfg_project/manage.py migrate
python tfg_project/manage.py runserver
```

Notas para Linux/macOS: `requirements.txt` está codificado en UTF-16 (pip lo lee gracias al BOM; el Dockerfile lo re-codifica automáticamente) e incluye `pywin32`, que solo aplica a Windows. Si la instalación falla por estos motivos, consulta [docs/instalacion.md](docs/instalacion.md).

La aplicación queda disponible en `http://127.0.0.1:8000/`.

Para compilar el reader React integrado en Django:

```powershell
cd frontend_reader
npm install
npm run build
```

Para desarrollo con Docker:

```powershell
docker compose up -d web
```

Para levantar GROBID, que es experimental y no forma parte del flujo principal:

```powershell
docker compose --profile experimental up -d grobid
```

## Configuración

El backend carga variables desde `.env` mediante `python-dotenv`. Las más relevantes son:

| Variable | Uso |
| --- | --- |
| `DJANGO_SECRET_KEY` | Clave secreta de Django. En desarrollo se genera una si falta. |
| `DJANGO_DEBUG` | `1`, `true` o `yes` para modo desarrollo. |
| `ALLOWED_HOSTS` | Hosts separados por coma. Valor por defecto: `localhost,127.0.0.1,[::1]`. |
| `SEMANTIC_SCHOLAR_API_KEY` | Opcional. Mejora estabilidad y cuotas de Semantic Scholar. |
| `LOG_CITATIONS` / `LOG_CITATIONS_LEVEL` | Activa y ajusta logs de extracción. |
| `READER_VITE_DEV_SERVER` | URL del Vite dev server, por ejemplo `http://localhost:5173`. |
| `GROBID_BASE_URL` / `GROBID_TIMEOUT` | Configuración del experimento GROBID. |
| `OPENAI_API_KEY` / `GOOGLE_API_KEY` | Solo para módulos IA experimentales. |

No subas claves reales al repositorio.

## Documentación

El índice mantenido está en [docs/README.md](docs/README.md). Lecturas principales:

- [Introducción](docs/introduccion.md)
- [Instalación](docs/instalacion.md)
- [Estado del sistema](docs/estado_del_sistema.md)
- [Arquitectura backend](docs/arquitectura_backend.md)
- [Modelos y relaciones](docs/modelos_y_relaciones.md)
- [Referencia de API](docs/api_reference_completa.md)
- [Frontend Reader](docs/frontend_reader.md)
- [Servicios de extracción](docs/servicios_extraccion.md)
- [Tests y verificación](docs/tests_y_verificacion.md)
- [Manual de usuario](docs/manual_usuario.md)

Los directorios `tmp/` y `docs/superpowers/` contienen artefactos de pruebas, experimentos o planes históricos; no sustituyen a la documentación mantenida.

## Verificación Básica

```powershell
python tfg_project/manage.py check
python tfg_project/manage.py test citations
python tfg_project/manage.py test citations.tests_reference_pipeline_baseline
```

El último comando ejecuta una línea base pesada sobre PDFs reales. Úsalo cuando toques extracción, referencias o el reader. La guía completa de tests está en [docs/tests_y_verificacion.md](docs/tests_y_verificacion.md).

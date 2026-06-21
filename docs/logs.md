# Logs

El proyecto tiene dos carpetas de logs con propósitos distintos.

## Ubicaciones

### `logs/` (raíz)

Carpeta rastreada en git solo mediante `.gitkeep` para que exista vacía al clonar. Su contenido real (archivos `.log`) está en `.gitignore`.

Contiene los ficheros de salida del servidor Django cuando se redirige manualmente:

| Archivo | Contenido |
|---|---|
| `django_runserver.out.log` | Stdout del proceso `manage.py runserver` |
| `django_runserver.err.log` | Stderr (warnings de librerías, requests HTTP, errores de sesión) |

### `tfg_project/logs/`

Generada automáticamente por Django al arrancar (`LOGS_DIR.mkdir(parents=True, exist_ok=True)` en `settings.py`). También ignorada en `.gitignore`.

| Archivo | Contenido |
|---|---|
| `citations_context.log` | Log estructurado JSON de toda la actividad del sistema de citas |

## Sistema de logging

Configurado en `tfg_project/tfg_project/settings.py`. Dos formateadores y dos loggers:

### Formateadores (`citations/logging_formatters.py`)

- **`ColorFormatter`** — consola en desarrollo. Formato legible con colores ANSI por nivel (gris/verde/amarillo/rojo). Incluye timestamp, nivel, nombre del logger y `request_id`.
- **`StructuredJsonFormatter`** — fichero. Una línea JSON por entrada con `timestamp`, `level`, `logger`, `message`, `request_id`, y campos adicionales de contexto (`phase`, `extra`).

### Loggers

| Logger | Destino | Nivel |
|---|---|---|
| `citations` | fichero + consola | DEBUG (dev) / INFO (prod) |
| `citations.context` | fichero + consola | Configurable via `LOG_CITATIONS_LEVEL` |

### Variables de entorno

| Variable | Defecto | Efecto |
|---|---|---|
| `LOG_CITATIONS` | `1` | `0` desactiva el handler de fichero |
| `LOG_CITATIONS_LEVEL` | `INFO` | Nivel mínimo del logger `citations.context` |

### Rotación

`citations_context.log` usa `RotatingFileHandler`: máximo 10 MB por fichero, 5 backups (`citations_context.log.1` … `.5`).

## Ejemplo de entrada en `citations_context.log`

```json
{
  "timestamp": "2026-04-02 17:38:19,336",
  "level": "INFO",
  "logger": "citations.references",
  "message": "build_references_data: 37 referencias, 103 snippets.",
  "request_id": "fb065d58-da58-4eb6-ad50-97d888f8f9db"
}
```

Cada petición de extracción genera un `request_id` UUID que permite filtrar todas las líneas de una misma solicitud:

```powershell
Select-String -Path tfg_project/logs/citations_context.log -Pattern "fb065d58"
```

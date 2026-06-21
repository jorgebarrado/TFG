# Docker

Los tres archivos de `docker/` forman el sistema de despliegue en contenedores.

## Archivos

### `docker/Dockerfile`

Define cómo construir la imagen del backend. Hace cuatro cosas en orden:

1. **Base**: arranca desde `python:3.11-slim` e instala `build-essential` y `git` (necesario para `papermage @ git+...`).
2. **Limpieza del requirements**: ejecuta un script Python inline que convierte el `requirements.txt` a UTF-8, elimina `pywin32` (solo Windows) y ajusta las ruedas de `torchaudio`/`torchvision` en ARM64 donde el índice de PyTorch omite el sufijo `+cpu`. Guarda el resultado como `/tmp/requirements.linux.txt`.
3. **Instala dependencias** desde ese fichero limpio con el índice extra de PyTorch CPU.
4. **Copia el código** y arranca Django con `runserver 0.0.0.0:8000` en el puerto 8000.

### `docker/Dockerfile.dockerignore`

Le dice a Docker qué carpetas no copiar al construir la imagen. Excluye el `.git`, entornos virtuales, cachés, `node_modules`, los frontends y archivos sensibles como `.env` y la base de datos SQLite. Esto reduce el tamaño del contexto de build y evita filtrar secretos.

El nombre `Dockerfile.dockerignore` asocia este archivo a `Dockerfile` concreto, en vez del `.dockerignore` de la raíz del repositorio.

### `docker/compose.yml`

Orquesta los contenedores con `docker compose`. Define dos servicios:

- **`web`**: construye la imagen con el Dockerfile, monta el repo en `/app` como volumen (los cambios locales se reflejan sin rebuild) y expone Django en `http://localhost:8000`.
- **`grobid`**: levanta el servidor GROBID en `http://localhost:8070`. Solo se activa con `--profile experimental` para no arrancarlo por defecto, ya que pesa bastante.

## Uso

Arrancar solo el backend:

```powershell
docker compose -f docker/compose.yml up web
```

Arrancar también GROBID:

```powershell
docker compose -f docker/compose.yml --profile experimental up
```

Reconstruir la imagen tras cambios en dependencias:

```powershell
docker compose -f docker/compose.yml build web
```

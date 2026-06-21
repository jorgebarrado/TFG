# GROBID PDF Debug

`debug_grobid_pdf` es un comando mínimo para enviar un PDF local a GROBID y guardar XML, JSON parseado y resumen. No ejecuta el extractor actual ni compara resultados.

Para el comando completo con comparación, consulta [grobid_experiment.md](grobid_experiment.md).

## Requisitos

Levanta GROBID:

```powershell
docker compose -f docker/compose.yml --profile experimental up -d grobid
```

O manualmente:

```powershell
docker run --rm --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.1
```

Verifica disponibilidad:

```powershell
curl http://localhost:8070/api/isalive
```

Opcional:

```powershell
curl http://localhost:8070/api/health
```

La demo pública o HF Spaces no es fiable para evaluación seria.

## Uso

Desde `tfg_project/`:

```powershell
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode header
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode references
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode fulltext
```

Opciones:

| Opción | Uso |
| --- | --- |
| `--pdf PATH` | PDF obligatorio. |
| `--mode header|references|fulltext` | Endpoint a ejecutar. Default: `fulltext`. |
| `--grobid-url URL` | Override de `GROBID_BASE_URL`. |
| `--timeout N` | Timeout en segundos. Default: `120`. |
| `--output-dir DIR` | Directorio de salida. |
| `--check-health` | Además de `isalive`, consulta `/api/health`. |

## Modos

- `header`: `/api/processHeaderDocument`; título, autores, abstract e identificadores.
- `references`: `/api/processReferences`; referencias bibliográficas con campos detectados.
- `fulltext`: `/api/processFulltextDocument`; metadatos, secciones, referencias y citas inline.

## Artefactos

Run exitoso:

- `response.xml`
- `parsed.json`
- `summary.txt`

Run con error:

- `error.json`
- `response_body.txt` si hubo cuerpo inválido útil para diagnóstico.

Los artefactos son diagnósticos y deben quedarse fuera del flujo de producción.

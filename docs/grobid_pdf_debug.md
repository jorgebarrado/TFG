# GROBID PDF Debug (Simple Experimental Tool)

Comando experimental mínimo para probar GROBID con un PDF local.

No usa el extractor actual del proyecto, no compara resultados y no afecta el flujo principal.

## Requisitos

1. Tener una instancia real de GROBID levantada (recomendado: local con Docker):

```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.1
```

2. Verificar disponibilidad:

```bash
curl http://localhost:8070/api/isalive
# esperado: true
```

Opcional:

```bash
curl http://localhost:8070/api/health
```

Nota: la demo pública (por ejemplo HF Spaces) no es fiable para evaluación seria.

## Comando

Desde `tfg_project/`:

```bash
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode header
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode references
python manage.py debug_grobid_pdf --pdf /ruta/paper.pdf --mode fulltext
```

Opciones:
- `--pdf PATH` (obligatorio)
- `--mode header|references|fulltext` (obligatorio lógico, default `fulltext`)
- `--grobid-url URL` (opcional, default `GROBID_BASE_URL`)
- `--timeout N` (opcional, default `120`)
- `--output-dir DIR` (opcional)
- `--check-health` (opcional, además de `isalive`)

## Qué devuelve cada modo

- `header` (`/api/processHeaderDocument`)
  - título
  - autores
  - abstract
  - DOI/identificadores si aparecen

- `references` (`/api/processReferences`)
  - lista de referencias
  - por referencia: `id`, `title`, `authors`, `doi`, `year`, `venue`, `pages`, `raw_citation` (si aparece)

- `fulltext` (`/api/processFulltextDocument`)
  - metadata del paper
  - secciones básicas
  - referencias
  - citas inline
  - counts

## Artefactos

Run exitoso:
- `response.xml`
- `parsed.json`
- `summary.txt`

Run con error:
- `error.json`
- `response_body.txt` (solo si hubo body inválido útil para diagnóstico)

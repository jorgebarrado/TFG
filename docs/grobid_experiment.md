# Experimento GROBID

Integración experimental y aislada de GROBID para comparar su extracción TEI con el extractor actual de CiteCheck.

No reemplaza PaperMage, no cambia el flujo principal, no añade migraciones y no modifica la UI de usuario.

## Archivos

| Archivo | Uso |
| --- | --- |
| `citations/services/grobid_client.py` | Cliente HTTP de GROBID. |
| `citations/services/grobid_parser.py` | Parser TEI XML a dict Python. |
| `citations/services/grobid_extractor.py` | Orquestador: cliente, parser y artefactos. |
| `citations/management/commands/debug_grobid.py` | Comando completo con comparación opcional. |
| `citations/management/commands/debug_grobid_pdf.py` | Comando simple por PDF. |
| `docs/grobid_experiment.md` | Esta guía. |
| `docs/grobid_pdf_debug.md` | Guía corta del comando simple. |

## Levantar GROBID

Opción recomendada con compose:

```powershell
docker compose --profile experimental up -d grobid
```

Verificación:

```powershell
curl http://localhost:8070/api/isalive
```

Debe devolver `true`.

Opción manual:

```powershell
docker run --rm --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.1
```

GROBID puede tardar 30-60 segundos en estar listo.

## Configuración

Valores por defecto en `settings.py`:

```env
GROBID_BASE_URL=http://localhost:8070
GROBID_TIMEOUT=120
```

También puedes pasar `--grobid-url` y `--timeout` al comando.

## Comando Principal

Desde `tfg_project/`:

```powershell
python manage.py debug_grobid --pdf ../tfg_project/citations/static/citations/PDFs-Reales/JScientometRes-14-3-838.pdf --mode fulltext
```

Modos:

| Modo | Endpoint GROBID | Uso |
| --- | --- | --- |
| `fulltext` | `/api/processFulltextDocument` | Paper completo: metadatos, secciones, referencias y citas inline. |
| `references` | `/api/processReferences` | Bibliografía y campos bibliográficos. |
| `both` | Ambos | Ejecuta los dos y separa artefactos por prefijo. |

Ejemplos:

```powershell
python manage.py debug_grobid --pdf /ruta/paper.pdf --mode references
python manage.py debug_grobid --pdf /ruta/paper.pdf --mode both
python manage.py debug_grobid --pdf /ruta/paper.pdf --compare-current --engine papermage
python manage.py debug_grobid --pdf /ruta/paper.pdf --grobid-url http://localhost:8070 --timeout 180
```

## Opciones

| Opción | Uso |
| --- | --- |
| `--pdf PATH` | PDF obligatorio. |
| `--compare-current` | Ejecuta también el extractor actual y genera comparación. |
| `--output-dir DIR` | Directorio de salida. |
| `--grobid-url URL` | URL base de GROBID. |
| `--timeout N` | Timeout en segundos. |
| `--mode fulltext|references|both` | Endpoint a ejecutar. |
| `--skip-alive-check` | Omite `/api/isalive`. |
| `--warmup-retries N` | Reintentos para HF Space dormido. |
| `--warmup-wait N` | Espera entre reintentos. |
| `--no-warmup-retry` | Desactiva warmup automático. |

## Artefactos

Cada run crea un directorio bajo `tmp/grobid_debug/`:

```text
tmp/grobid_debug/
└── 20260412-153012_mi_paper/
    ├── availability_check.json
    ├── summary.txt
    ├── current.json
    ├── tei.xml
    ├── parsed.json
    ├── comparison.json
    ├── error.json
    └── response_body.txt
```

En `--mode both` se generan prefijos:

- `fulltext_tei.xml`
- `fulltext_parsed.json`
- `fulltext_error.json`
- `references_tei.xml`
- `references_parsed.json`
- `references_error.json`
- `comparison_fulltext.json`
- `comparison_references.json`

## Respuesta Parseada

`fulltext`:

```json
{
  "metadata": {
    "title": "Título",
    "authors": ["Apellido, Nombre"],
    "abstract": "..."
  },
  "sections": [
    { "head": "Introduction", "paragraphs": ["..."] }
  ],
  "references": [
    {
      "id": "b0",
      "title": "Referencia",
      "authors": ["Smith, John"],
      "doi": "10.1234/example",
      "year": 2020,
      "venue": "Journal",
      "pages": "1-10",
      "identifiers": {}
    }
  ],
  "inline_citations": [
    { "target_id": "b0", "anchor_text": "[1]" }
  ],
  "inline_citation_count": 42,
  "reference_count": 35,
  "_warnings": []
}
```

`references`:

```json
{
  "mode": "references",
  "references": [
    {
      "id": "b0",
      "title": "Referencia",
      "authors": ["Smith, John"],
      "doi": "10.1234/example",
      "year": 2020,
      "venue": "Journal",
      "raw_citation": "Smith J. ...",
      "identifiers": {}
    }
  ],
  "reference_count": 35,
  "_warnings": []
}
```

## Comparación Con Extractor Actual

Con `--compare-current`, el comando guarda `comparison*.json` con conteos como:

```json
{
  "grobid_ref_count": 35,
  "current_ref_count": 33,
  "grobid_inline_citation_count": 42,
  "grobid_refs_with_doi": 20,
  "current_refs_with_doi": 18,
  "dois_in_common": 17,
  "dois_only_in_grobid": ["10.xxx/yyy"],
  "dois_only_in_current": ["10.aaa/bbb"]
}
```

## Errores Clasificados

| `error_type` | Causa |
| --- | --- |
| `huggingface_space_warming_up` | HF Space devolvió HTML mientras arrancaba. |
| `huggingface_space_warming_up_timeout` | Warmup agotado. |
| `non_tei_html_response` | HTML donde se esperaba TEI. |
| `non_tei_response` | Respuesta no TEI y no HTML. |
| `invalid_response` | Respuesta inválida genérica. |
| `parse_error` | XML malformado o sin raíz TEI. |
| `connection` | No se pudo conectar. |
| `http` | GROBID devolvió HTTP de error. |

Un TEI válido empieza con `<TEI xmlns="http://www.tei-c.org/ns/1.0" ...>`.

## Limitaciones

- No extrae contexto textual alrededor de citas inline; solo anchor y destino cuando GROBID lo expone.
- `processReferences` no aporta secciones ni citas inline.
- La demo pública en Hugging Face puede dormirse y devolver HTML con HTTP 200.
- El rendimiento depende mucho del PDF y hardware.
- `grobid-client-python` está instalado, pero el proyecto usa `requests` directamente para controlar errores y artefactos.
- La comparación se basa principalmente en DOI y conteos, no en equivalencia semántica completa.

## Criterio Para Integrarlo En Producción

No integres GROBID en el flujo principal hasta tener:

- benchmark reproducible frente a `scripts/run_reference_regression.py`;
- mejora clara en referencias, DOI o citas inline;
- coste de despliegue asumible;
- manejo de timeouts y colas;
- contrato JSON estable para el reader.

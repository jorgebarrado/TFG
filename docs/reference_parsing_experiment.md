# Reference Parsing Experiment

Este experimento está aislado del flujo de aplicación. No modifica vistas, modelos, URLs ni frontend.

## Objetivo

Comparar alternativas para parsear/enriquecer referencias ya segmentadas por el extractor actual:

1. `refextract`
2. `anystyle`
3. `llm`

Ruta conceptual:

```text
PDF -> extractor actual -> referencias raw -> parser alternativo -> comparación
```

## Código

| Archivo | Responsabilidad |
| --- | --- |
| `reference_parsing_experiments/input_common.py` | Construye entrada compartida llamando a `extract_pdf_references()`. |
| `runners/refextract_runner.py` | Ejecuta refextract en modo string. |
| `runners/anystyle_runner.py` | Ejecuta `anystyle parse` si el CLI está en `PATH`. |
| `runners/llm_runner.py` | Construye prompt JSON estricto y valida respuesta. |
| `normalization.py` | Normaliza salidas a un schema común. |
| `comparison.py` | Genera conteos y comparaciones. |
| `experiment.py` | Orquesta la ejecución. |
| `scripts/run_reference_parsing_experiment.py` | CLI standalone. |

## Ejecución

Muestra curada por defecto:

```powershell
python scripts/run_reference_parsing_experiment.py
```

PDFs explícitos:

```powershell
python scripts/run_reference_parsing_experiment.py --pdf JScientometRes-14-3-838.pdf --pdf 2023.emnlp-demo.45.pdf
```

Todos los PDFs disponibles:

```powershell
python scripts/run_reference_parsing_experiment.py --all-pdfs
```

Listar PDFs por defecto:

```powershell
python scripts/run_reference_parsing_experiment.py --list-default-pdfs
```

Listar todos los PDFs detectados:

```powershell
python scripts/run_reference_parsing_experiment.py --list-all-pdfs
```

## Opciones

| Opción | Uso |
| --- | --- |
| `--pdf NAME` | Puede repetirse para seleccionar PDFs concretos. |
| `--all-pdfs` | Usa todos los PDFs detectados. |
| `--run-id ID` | Fija el nombre del run. |
| `--output-root DIR` | Cambia la raíz de salida. |
| `--comparison-limit N` | Limita ejemplos en comparaciones. |
| `--llm-model MODEL` | Modelo usado por el runner LLM. |
| `--list-default-pdfs` | Lista muestra curada y termina. |
| `--list-all-pdfs` | Lista todos los PDFs y termina. |

No combines `--all-pdfs` y `--pdf`.

## Artefactos

Cada run se escribe en:

```text
tmp/reference_parser_experiments/<run_id>/
```

Estructura esperada:

- `config.json`
- `summary.md`
- `summary.json`
- `inputs/<paper_slug>_raw_references.json`
- `refextract/<paper_slug>.json`
- `anystyle/<paper_slug>.json`
- `llm/<paper_slug>.json`
- `llm/<paper_slug>_prompt.txt`
- `llm/<paper_slug>_raw_response.txt`
- `comparisons/<paper_slug>.json`
- `comparisons/aggregate.json`

## Notas de Entorno

- `refextract`: se valida sobre referencias ya segmentadas. En Windows, el runner instala un shim local para `magic` si hace falta.
- `anystyle`: requiere Ruby/anystyle-cli instalado y disponible en `PATH`.
- `llm`: requiere `OPENAI_API_KEY`. Si falta, el runner registra que no se ejecutó y no fabrica resultados.

## Criterio de Integración

Este experimento no debe integrarse en producción hasta que haya:

- comparación reproducible contra el runner de regresión;
- mejora clara sobre métricas actuales;
- coste/latencia aceptable;
- manejo de dependencias externas documentado.

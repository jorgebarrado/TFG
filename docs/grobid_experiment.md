# Experimento GROBID

Integración **experimental y aislada** de [GROBID](https://github.com/kermitt2/grobid) para comparar su extracción de referencias con el sistema actual del proyecto.

No modifica ni reemplaza ningún extractor existente. No afecta al flujo principal de la app.

---

## Qué hace esta integración

1. Envía un PDF a una instancia local de GROBID.
2. Recibe el TEI XML resultante.
3. Parsea el XML a una estructura Python/JSON sencilla (metadatos, secciones, referencias, citas inline).
4. Guarda los artefactos crudos y parseados para inspección manual.
5. Opcionalmente ejecuta el extractor actual del proyecto sobre el mismo PDF y genera una comparación numérica básica.

---

## Requisitos previos

### 1. Levantar GROBID localmente

La forma más rápida es con Docker:

```bash
docker pull lfoppiano/grobid:0.8.1
docker run --rm --gpus all --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.1
```

Sin GPU (más lento pero funciona):
```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 lfoppiano/grobid:0.8.1
```

Verificar que GROBID está arriba:
```bash
curl http://localhost:8070/api/isalive
# Debe devolver: true
```

GROBID tarda ~30-60 segundos en arrancar la primera vez. No hay output visible hasta que está listo.

### 2. Alternativa sin Docker: HuggingFace Space

Se puede usar el Space público de GROBID en HuggingFace, **pero con limitaciones importantes** (ver la sección "Comportamiento observado" más abajo):

```bash
python manage.py debug_grobid \
    --pdf /ruta/paper.pdf \
    --grobid-url https://kermitt2-grobid.hf.space
```

### 3. Configuración (opcional)

Por defecto apunta a `http://localhost:8070`. Para cambiarlo, añadir al `.env`:

```env
GROBID_BASE_URL=http://localhost:8070
GROBID_TIMEOUT=120
```

O pasar `--grobid-url` directamente al comando.

---

## Cómo ejecutar

Desde `tfg_project/`:

```bash
# Prueba básica sobre un PDF
python manage.py debug_grobid --pdf ../tfg_project/citations/static/citations/PDFs-Reales/tu_paper.pdf

# Con comparación frente al extractor actual
python manage.py debug_grobid \
    --pdf ../tfg_project/citations/static/citations/PDFs-Reales/tu_paper.pdf \
    --compare-current

# Especificando el motor de extracción actual para la comparación
python manage.py debug_grobid \
    --pdf /ruta/absoluta/paper.pdf \
    --compare-current \
    --engine papermage

# Override de URL y timeout
python manage.py debug_grobid \
    --pdf /ruta/absoluta/paper.pdf \
    --grobid-url http://localhost:8070 \
    --timeout 180
```

---

## Comportamiento observado en pruebas reales

### HuggingFace Space dormido (`huggingface_space_warming_up`)

Cuando se usa `--grobid-url https://kermitt2-grobid.hf.space` y el Space está inactivo (se duerme tras ~15 min sin uso), tanto `/api/isalive` como `/api/processFulltextDocument` **devuelven HTTP 200 con una página HTML** en lugar de la respuesta esperada.

Esto se detecta como `error_type: huggingface_space_warming_up` y produce:
- `error.json` con el tipo clasificado y preview del HTML recibido
- `response_body.txt` con el body completo para inspección
- `availability_check.json` con el resultado del check de `/api/isalive`
- **NO** se generan `tei.xml` ni `parsed.json` (no hubo TEI real)

Lo más importante: el extractor actual del proyecto **sí funciona con normalidad** durante este fallo (GROBID es una capa de comparación, no parte del flujo principal).

Solución: abrir el Space en el navegador, esperar que arranque (~30-60 s) y reintentar. O usar Docker local.

---

## Dónde mirar los resultados

Cada ejecución crea un subdirectorio en `tmp/grobid_debug/` con el formato `YYYYMMDD-HHMMSS_<nombre_pdf>/`:

```
tmp/grobid_debug/
└── 20260412-153012_mi_paper/
    ├── availability_check.json  # Resultado del check /api/isalive
    ├── summary.txt              # Resumen legible en texto plano
    │
    │   # Solo cuando GROBID respondió con TEI válido:
    ├── tei.xml                  # TEI XML crudo de GROBID
    ├── parsed.json              # Estructura Python/JSON parseada
    ├── current.json             # Extractor actual (solo con --compare-current)
    └── comparison.json          # Comparación numérica (solo con --compare-current)
    │
    │   # Solo cuando GROBID falló:
    ├── response_body.txt        # Body completo recibido (HTML u otro)
    └── error.json               # Tipo de error, URL, Content-Type, preview
```

### Tipos de error (`error_type` en `error.json`)

| error_type | Causa |
|---|---|
| `huggingface_space_warming_up` | HF Space dormido, devolvió HTML |
| `non_tei_html_response` | Otro origen devolvió HTML (proxy, landing page) |
| `non_tei_response` | Respuesta sin `<TEI>` pero no HTML |
| `invalid_response` | Respuesta inválida genérica |
| `parse_error` | XML malformado o sin raíz `<TEI>` |
| `connection` | No se pudo conectar al servidor |
| `http` | GROBID devolvió código HTTP de error |

### Cómo reconocer una respuesta válida de GROBID

El `tei.xml` real empieza siempre así:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" ...>
```
Si `response_body.txt` empieza por `<!DOCTYPE html` o `<html`, la URL no era un endpoint de GROBID activo.

---

### Estructura de `parsed.json`

```json
{
  "metadata": {
    "title": "Título del paper",
    "authors": ["Apellido, Nombre"],
    "abstract": "..."
  },
  "sections": [
    {"head": "Introduction", "paragraphs": ["..."]}
  ],
  "references": [
    {
      "id": "b0",
      "title": "Título de la referencia",
      "authors": ["Smith, John"],
      "doi": "10.1234/example",
      "year": 2020,
      "venue": "Journal Name",
      "pages": "1–10",
      "identifiers": {}
    }
  ],
  "inline_citations": [
    {"target_id": "b0", "anchor_text": "[1]"}
  ],
  "inline_citation_count": 42,
  "reference_count": 35,
  "_warnings": []
}
```

### Estructura de `comparison.json`

```json
{
  "grobid_ref_count": 35,
  "current_ref_count": 33,
  "grobid_inline_citation_count": 42,
  "grobid_refs_with_doi": 20,
  "current_refs_with_doi": 18,
  "dois_in_common": 17,
  "dois_only_in_grobid": ["10.xxx/yyy"],
  "dois_only_in_current": ["10.aaa/bbb"],
  "grobid_first5": [...],
  "current_first5": [...]
}
```

---

## Archivos creados por esta integración

| Archivo | Propósito |
|---------|-----------|
| `citations/services/grobid_client.py` | Cliente HTTP para GROBID |
| `citations/services/grobid_parser.py` | Parser TEI XML → dict Python |
| `citations/services/grobid_extractor.py` | Orquestador (cliente + parser + artefactos) |
| `citations/management/commands/debug_grobid.py` | Management command Django |
| `docs/grobid_experiment.md` | Esta documentación |
| `tfg_project/settings.py` (modificado) | Añadidas `GROBID_BASE_URL` y `GROBID_TIMEOUT` |

---

## Limitaciones conocidas de esta prueba

1. **Contexto de citas inline**: El parser extrae el texto del anchor de cada cita (`[1]`, `(Smith, 2020)`, etc.) pero no el fragmento de texto circundante, porque `xml.etree.ElementTree` no expone el elemento padre. Para obtener contexto completo habría que usar `lxml`.

2. **HuggingFace Space poco fiable**: El Space público de GROBID se duerme tras ~15 min de inactividad y devuelve HTML con HTTP 200, lo que se detecta como `huggingface_space_warming_up`. Para uso estable usar Docker local.

3. **Rendimiento**: GROBID puede tardar 10-60 segundos por PDF dependiendo del tamaño y del hardware. El timeout por defecto es 120 segundos.

4. **grobid-client-python instalado pero no usado**: El proyecto tiene `grobid-client-python==0.0.5` en requirements.txt, pero se usa `requests` directamente para mayor control y transparencia.

5. **Comparación de autores no normalizada**: La comparación entre GROBID y el extractor actual se basa principalmente en DOIs. La comparación por texto de referencia no se implementa aquí para evitar complejidad innecesaria.

6. **Solo procesa un PDF a la vez**: Para procesar varios PDFs en batch, lanzar el comando varias veces o adaptar el extractor.

---

## Cómo revertir esta integración

Para eliminar completamente esta integración experimental:

```bash
# Eliminar archivos nuevos
rm tfg_project/citations/services/grobid_client.py
rm tfg_project/citations/services/grobid_parser.py
rm tfg_project/citations/services/grobid_extractor.py
rm tfg_project/citations/management/commands/debug_grobid.py
rm tfg_project/citations/management/commands/__init__.py
rm tfg_project/citations/management/__init__.py
rm docs/grobid_experiment.md

# Revertir settings.py (eliminar el bloque GROBID)
# Eliminar las líneas GROBID_BASE_URL y GROBID_TIMEOUT de settings.py

# Eliminar artefactos de debug (opcional)
rm -rf tmp/grobid_debug/
```

No hay migraciones de base de datos, no hay cambios en modelos, no hay cambios en la UI.

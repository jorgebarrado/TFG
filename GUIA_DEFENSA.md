# Guía de Defensa del TFG — CiteCheck

> **Cómo usar esta guía.** Léela una vez de arriba abajo. Después, para cada bloque vuelve al código (las rutas están en formato `archivo:línea` para que puedas saltar rápido). Termina con la sección 13 (preguntas anticipadas) y practica respuestas en voz alta. Las secciones marcadas con ⭐ son las más sensibles a preguntas del tutor — empieza por ahí si vas justo de tiempo.

---

## Tabla de contenidos

1. [Resumen ejecutivo (1 minuto)](#1-resumen-ejecutivo-1-minuto)
2. [Stack tecnológico](#2-stack-tecnológico)
3. [Arquitectura global](#3-arquitectura-global)
4. [Modelos de datos](#4-modelos-de-datos)
5. [Capa de servicios (corazón del sistema)](#5-capa-de-servicios-corazón-del-sistema)
6. [⭐ Commit `70e50cd` — referencia del tutor](#6--commit-70e50cd--referencia-del-tutor)
7. [URLs, vistas y APIs](#7-urls-vistas-y-apis)
8. [Frontend Reader (React)](#8-frontend-reader-react)
9. [Scripts auxiliares y experimentos](#9-scripts-auxiliares-y-experimentos)
10. [Configuración, settings y deployment](#10-configuración-settings-y-deployment)
11. [Decisiones de diseño (el "por qué")](#11-decisiones-de-diseño-el-por-qué)
12. [Limitaciones conocidas y trabajo futuro](#12-limitaciones-conocidas-y-trabajo-futuro)
13. [⭐ Preguntas anticipadas con respuestas](#13--preguntas-anticipadas-con-respuestas)
14. [Plan de repaso (calendario sugerido)](#14-plan-de-repaso-calendario-sugerido)

---

## 1. Resumen ejecutivo (1 minuto)

**CiteCheck** es una aplicación web (Django + React) que ayuda a investigadores a **identificar, documentar y discutir citas incorrectas** en la literatura académica. Una cita incorrecta es aquella en la que un paper B cita a un paper A pero atribuye algo que A nunca dijo, malinterpreta su contenido, o lo usa fuera de contexto.

**Tres herramientas integradas:**

1. **Buscador de citantes**: dado el DOI de un paper, se consulta Semantic Scholar (con fallback a Crossref) y se obtienen los papers que lo citan, junto con los contextos textuales donde aparece la cita.
2. **Reader interactivo**: SPA en React que carga el PDF de un paper, extrae sus referencias y citas inline, y permite navegar entre cita y referencia con resaltado visual.
3. **Sistema de reportes comunitarios**: cualquier usuario registrado puede crear un reporte (`IncorrectCitation`) y la comunidad puede votar, comentar (con threads anidados) y discutir si la cita realmente es incorrecta.

**Diferencial técnico:** es uno de los pocos sistemas que combina (a) extracción estructural de PDFs (PaperMage + fallbacks), (b) enriquecimiento de metadata con APIs externas, (c) detección regex de citas in-text consistente entre backend y frontend, y (d) detección con LLM (Gemini) como segunda opinión.

---

## 2. Stack tecnológico

| Capa | Tecnología | Decisión |
|------|------------|----------|
| Backend | **Django 5.1.7** | Monolito modular: ORM maduro, admin gratis, allauth para OAuth |
| Lenguaje | Python 3.11+ (target en `pyproject.toml`) | Soporte de tipo moderno |
| BD dev | SQLite | Cero configuración para desarrollo |
| BD prod | PostgreSQL (planeado) | El ORM hace agnóstico el código |
| Frontend | **React 18 + Vite** | SPA montada en template Django, no Next.js — el servidor sigue siendo Django |
| PDF viewer | `@allenai/pdf-components` (wrapper sobre PDF.js) | Allen AI lo mantiene; integra bien con su ecosistema (PaperMage) |
| Auth | `django-allauth` | OAuth Google + ORCID en académico |
| APIs externas | Semantic Scholar (primary), Crossref (fallback), DBLP | S2 es el más rico en contextos de cita |
| Extracción PDF | PaperMage / PaperCraft / GROBID (experimental) / pdfplumber+fitz | Cadena de fallbacks: siempre hay un motor que funciona |
| IA | Google Gemini 1.5 Flash | Detección automática de citas como "segunda opinión" |
| Containers | Docker + docker-compose | Servicio `web` + servicio `grobid` opcional |
| Calidad | black, isort, flake8, pre-commit | Estilo unificado, hooks bloquean commits sucios |

---

## 3. Arquitectura global

```
┌──────────────────────────────────────────────────────────────────┐
│  NAVEGADOR                                                       │
│  ┌────────────────────┐   ┌──────────────────────────────────┐   │
│  │ Plantillas HTML    │   │ React Reader (SPA)               │   │
│  │ + HTMX para AJAX   │   │ - PDF.js (Allen AI components)   │   │
│  │ (listado, perfil,  │   │ - Overlays SVG sobre páginas     │   │
│  │  reportes, login)  │   │ - Sidebar: snippets / refs       │   │
│  └─────────┬──────────┘   └──────────────┬───────────────────┘   │
└────────────┼──────────────────────────────┼──────────────────────┘
             │ HTML + form posts            │ JSON (REST)
             │                              │
┌────────────▼──────────────────────────────▼──────────────────────┐
│  DJANGO 5.1 (tfg_project/citations/)                             │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐    │
│  │ views/      │  │ views_api.py │  │ views_ai.py /         │    │
│  │ page_views  │  │ ajax_views.py│  │ views_reports.py      │    │
│  │ auth/user/  │  │              │  │                       │    │
│  │ tutor/msg   │  │ JSON REST    │  │ AI + wizard legacy    │    │
│  └──────┬──────┘  └──────┬───────┘  └───────────┬───────────┘    │
│         │                │                      │                │
│         └────────┬───────┴──────────────────────┘                │
│                  │                                               │
│         ┌────────▼─────────┐    ┌──────────────────────┐         │
│         │ models.py        │    │ services/            │         │
│         │ - IncorrectCit.  │    │ - semantic_scholar_  │         │
│         │ - UserProfile    │    │   client.py ⭐       │         │
│         │ - Comment/Vote   │    │ - crossref_client    │         │
│         │ - Conversation   │    │ - dblp_client        │         │
│         │ - Notification   │    │ - papermage_extr.    │         │
│         └────────┬─────────┘    │ - citation_patterns  │         │
│                  │              │ - reference_         │         │
│                  │              │   reconciliation     │         │
│                  │              │ - ai_citation_det.   │         │
│                  │              │ - engines (fallback) │         │
│                  │              └──────────┬───────────┘         │
└──────────────────┼─────────────────────────┼─────────────────────┘
                   │                         │
            ┌──────▼──────┐         ┌────────▼─────────────────┐
            │ SQLite/Pg   │         │ APIs externas            │
            │ Django ORM  │         │ - Semantic Scholar       │
            │             │         │ - Crossref               │
            │ Cache       │         │ - DBLP                   │
            │ (LocMem)    │         │ - GROBID (Docker, exp)   │
            │             │         │ - Gemini (Google)        │
            └─────────────┘         └──────────────────────────┘
```

**Idea central:** Django actúa de monolito que sirve tanto HTML clásico (listados, perfil, login) como JSON para la SPA Reader. La capa de servicios encapsula todo el "trabajo sucio" (APIs externas, parsing de PDFs, scoring) para mantener las vistas finas.

---

## 4. Modelos de datos

Archivo: `tfg_project/citations/models.py`

### 4.1 Diagrama de relaciones

```
User (Django built-in)
 │
 ├──1:1── UserProfile          (perfil extendido: bio, DBLP, redes, notif prefs)
 │
 ├──1:N── IncorrectCitation    (reportes que ha creado)  ◄──┐
 │                                                          │
 ├──1:N── Comment ──parent── self  (replies anidadas)  ─────┤
 │                                                          │
 ├──1:N── Vote   (unique(user,citation))                ────┤
 │                                                          │
 ├──1:N── SavedCitation  (favoritos, unique(user,cit))  ────┘
 │
 ├──M:N── Conversation ──1:N── Message
 │
 └──1:N── Notification  (actor opcional → otro User)
```

### 4.2 Modelo central: `IncorrectCitation` (models.py:150)

Es el **núcleo del dominio**. Si te preguntan "¿qué es lo que se almacena?", apunta aquí.

| Campo | Tipo | Por qué |
|-------|------|---------|
| `author` | FK→User, nullable | Quién reportó (nullable para preservar reportes si el usuario se borra) |
| `doi_original` | CharField | DOI del paper que recibe la cita incorrecta (paper A) |
| `doi_incorrect` | CharField | DOI del paper que cita mal (paper B) |
| `incorrect_reason` | TextField | Explicación libre del reporter |
| `metadata_original` | JSONField | Snapshot de metadata de A (título, autores, año, venue) |
| `metadata_incorrect` | JSONField | Snapshot de B |
| `citation_contexts` | JSONField | Lista de fragmentos `{page, paragraph, snippet, pattern}` |
| `citation_type` | CharField choices | `not said` / `misinterpretation` / `contextual misattribution` |
| `publication_area` | CharField choices | 17 áreas (ENG, PHY, CIS, LIF, etc.) para filtrado |
| `created_at` | DateTimeField | Timestamp |

**Decisión clave (te la van a preguntar):** **¿por qué JSONField y no tablas relacionales para metadata y contextos?**

> "Las APIs externas (S2, Crossref, DBLP, GROBID) devuelven estructuras heterogéneas que evolucionan con el tiempo. JSONField nos da flexibilidad para guardar lo que cada fuente devuelve sin migrar la BD cada vez que añadimos un campo. Los contextos son siempre del mismo paper y se consultan en bloque, así que normalizar a tabla aparte no daba ventaja. **Si en el futuro necesitamos buscar por campos internos, PostgreSQL soporta índices GIN sobre JSONB.**"

### 4.3 Resto de modelos (resumen)

- **`UserProfile`** (models.py:8): 1:1 con `User`. Bio, DBLP URL (para listar publicaciones del usuario), redes sociales, preferencias de notificación (`notify_comments`, `notify_votes`...), flags de privacidad. Decisión: separar de `User` para no tocar el modelo base de Django.
- **`Comment`** (models.py:179): `parent` FK a self → threads anidados sin tabla auxiliar. Método `is_reply()`.
- **`Vote`** (models.py:198): `value ∈ {-1, +1}`. `unique_together(user, citation)` evita votos duplicados.
- **`SavedCitation`** (models.py:217): es una M:N explícita (en vez de `ManyToManyField`) porque incluye `created_at`.
- **`Conversation`** + **`Message`** (models.py:237, 249): mensajería 1:1. La conversación es M:N (`participants`); el código filtra `count == 2` para garantizar 1:1.
- **`Notification`** (models.py:267): tipos `NEW_COMMENT`, `NEW_VOTE`, `NEW_MESSAGE`, `SYSTEM`. `actor` opcional (sistema puede notificar sin usuario causante). Campo `url` libre → flexible para apuntar a cualquier destino.
- **`CitationReport`** (models.py:305) ⚠️ **legacy**: modelo del wizard antiguo. Ya no se usa en producción pero se mantiene porque hay migraciones que lo referencian. Si te preguntan, di esto literalmente y que lo borrarías en una limpieza futura.

---

## 5. Capa de servicios (corazón del sistema)

Directorio: `tfg_project/citations/services/`

Es donde está la mayor parte de la lógica no-trivial. Las vistas son finas; los servicios hacen el trabajo. Agrúpalos mentalmente en cuatro familias:

### 5.1 Clientes de APIs externas

| Archivo | Responsabilidad |
|---------|-----------------|
| `semantic_scholar_client.py` ⭐ | Cliente HTTP para S2 (rate limit, retries, cache). **Ver sección 6.** |
| `semantic_fetch.py` | Capa de conveniencia sobre el anterior + fallback a Crossref |
| `crossref_client.py` | Cliente para Crossref (sin rate limit propio, sin cache, fallos silenciosos) |
| `dblp_client.py` | Lista de publicaciones de un autor a partir de su perfil DBLP (parsing XML) |
| `external_api.py` | Helper `build_external_api_session()` → ignora proxies rotos del entorno (`session.trust_env = False`) |

**Por qué S2 es primary y Crossref es fallback:** S2 expone `contexts` (snippets de dónde se cita el paper), Crossref no. S2 tiene rate limit estricto (1 req/s sin key), Crossref no — por eso si S2 falla o agota la cuota, caemos a Crossref para al menos recuperar metadata.

### 5.2 Extracción de texto de PDFs

| Archivo | Responsabilidad |
|---------|-----------------|
| `engines.py` | Orquestador: elige motor (`papermage` / `papercraft` / `generic`) o ejecuta cadena de fallbacks si `engine="auto"` |
| `papermage_extractor.py` | Wrapper sobre PaperMage de Allen AI (layout-aware, lento, preciso) |
| `papercraft_extractor.py` | Alternativa experimental |
| `generic_extractor.py` | Fallback con `pdfplumber` y `fitz` (PyMuPDF). Siempre funciona |
| `grobid_client.py`, `grobid_extractor.py`, `grobid_parser.py` | Cliente HTTP para servidor GROBID + parser del TEI XML (**experimental**, no en flujo principal) |

**Cadena de fallback de `engine="auto"`** (engines.py:109+): `papermage → papercraft → generic`. Si el usuario fuerza un motor específico y falla, **no** cae a otro — devuelve error explícito. Esto es deliberado: en modo automático queremos robustez; en modo explícito queremos reproducibilidad.

### 5.3 Detección de citas in-text

| Archivo | Responsabilidad |
|---------|-----------------|
| `citation_patterns.py` (~405 líneas) | **Los regex** de citas. Compartidos backend ↔ frontend mediante un export consistente |
| `citation_extractor.py` | Orquesta: extrae párrafos + ejecuta patrones + genera resultados con `page`, `start`, `end`, `confidence` |

**Patrones soportados:**

1. **Numéricas**: `[1]`, `[1, 2]`, `[1-3]`, `[1; 2-4]` — `\[\s*\d{1,4}(?:\s*(?:[,;]\s*\d{1,4}|\s*[-–—]\s*\d{1,4}))*\s*\]`
2. **Autor-año narrativo**: `Smith (2020)`, `Smith et al. (2020)`, `García-López and Müller (2021a)` — el `_NAME` soporta diacríticos y guiones
3. **Autor-año parentético**: `(Smith, 2020)`, `(Smith et al., 2020; Jones, 2021)`
4. **DOI desnudo**: `10.1145/123456` con recorte de trailing (`.`, `,`, `)`, `.pdf`)

**Filtro de falsos positivos** (citation_patterns.py:214): elimina cosas como `Figure (2020)` o `Table (2020)` porque empiezan con palabras que no son apellidos.

### 5.4 Reconciliación, matching y enriquecimiento

| Archivo | Responsabilidad |
|---------|-----------------|
| `reference_reconciliation.py` (~1008 líneas) | Combina referencias de dos fuentes (base + structured), evalúa salud de cada fuente, rescata índices faltantes |
| `doi_enrichment_service.py` | Para cada referencia local sin DOI, busca en S2/Crossref y puntúa la coincidencia |
| `references_data.py` | Transforma referencias + snippets + capas del Reader en el payload final que consume el frontend |
| `evidence.py` | Normaliza items de evidencia (snippets que el usuario adjunta como prueba) |
| `reader_data.py` | Construye el payload del Reader (`/api/reader-data/<id>/`): PDF URL, snippets, referencias, contexto inicial |
| `pdf_citation_analyzer.py` | Puente "descarga PDF de un DOI + extrae contextos" |
| `report_tags.py` | Normaliza tags/áreas de publicación |
| `notifications.py` | Crea notificaciones cuando ocurren eventos relevantes |

**Scoring de matching** (reference_reconciliation.py:185+, función `validate_reference_against_metadata`):

| Factor | Peso | Cómo se calcula |
|--------|------|-----------------|
| DOI exacto | 0.42 | Match binario sobre DOI normalizado |
| Overlap de título | 0.28 | Tokens compartidos / tokens totales |
| Apellidos de autores | 0.16 | Surnames presentes en la referencia |
| Año | 0.08 | Exacto (1.0), ±1 (0.4), otro (0) |
| Venue | 0.06 | Tokens compartidos del venue |

**Umbrales de aceptación**:
- `match_score ≥ 0.72` y `mixed_score < 0.55` → ACEPTA
- DOI exacto y `match_score ≥ 0.52` y `mixed_score < 0.50` → ACEPTA
- `title_score ≥ 0.66` y `mixed_score < 0.45` → ACEPTA
- `mixed_score ≥ 0.68` → RECHAZA (referencia ambigua, varios anchors o varios DOIs en el mismo bloque)

### 5.5 IA y análisis avanzado

| Archivo | Responsabilidad |
|---------|-----------------|
| `ai_citation_detector.py` | Llama a Gemini 1.5 Flash con un prompt estructurado: "dado paper A y los párrafos de paper B, dime en cuáles se cita a A". Devuelve `{page, paragraph_index, confidence, reason, text}` |
| `ai_report_evaluator.py` | Evalúa con IA si un reporte es correcto/incorrecto |
| `semantic_citation_pipeline.py` | Pipeline end-to-end: DOI → citantes → descarga PDFs → extrae contextos automáticamente |

**Por qué Gemini y no GPT-4:** Gemini Flash 1.5 es barato y rápido para detección estructurada con JSON; no necesitamos razonamiento profundo, solo localización. Para razonamiento sobre si la cita es incorrecta (ai_report_evaluator) se podría considerar Claude/GPT-4, pero está como "segunda opinión", la decisión final la toma la comunidad.

---

## 6. ⭐ Commit `70e50cd` — referencia del tutor

**Mensaje del commit:** `Key Semantic Scholar,`
**Fecha:** 10 mayo 2026
**Stats:** 12 archivos, +582 líneas, -208 líneas

Este es el commit que tu tutor menciona como referencia. **Espera preguntas concretas sobre esto.**

### 6.1 ¿Qué problema resolvía?

Antes del commit:
- La API key de Semantic Scholar se leía **una sola vez** al importar el módulo (`SEMANTIC_SCHOLAR_API_KEY = os.getenv(...)`) — imposible reconfigurar en tests, no se podía pasar por `settings.py`.
- Cada función (`get_citing_papers_for_doi`, `get_paper_metadata_by_doi`, `get_citation_counts_for_dois`, etc.) **duplicaba** el código de hacer la petición, manejar errores, parsear el JSON.
- **No había rate limiting**: si lanzabas muchas peticiones, S2 devolvía 429 y el código se rompía.
- **No había retries**: un fallo de red transitorio (5xx, timeout) era error definitivo.
- `semantic_fetch.py` y `utils.py` hacían sus propias llamadas HTTP a S2 con `_safe_get` o `requests.get` directos, **sin pasar por el cliente común** → tres lugares distintos para el mismo problema.
- Logging con `print()` — invisible en producción.

### 6.2 ¿Qué cambia el commit?

#### A) Lectura jerárquica de la API key
**Archivo:** `semantic_scholar_client.py:77-86` (función `_get_api_key`)
```python
def _get_api_key() -> str:
    try:
        configured = str(getattr(settings, "SEMANTIC_SCHOLAR_API_KEY", "") or "").strip()
    except ImproperlyConfigured:
        configured = ""
    if configured:
        return configured
    return str(os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
```
**Por qué:** Django settings tiene prioridad sobre env var. Permite que los tests sobrescriban con `@override_settings(SEMANTIC_SCHOLAR_API_KEY="test")`. Si no hay nada configurado, devuelve `""` y el cliente sigue funcionando (sin la cabecera `x-api-key`) — degradación elegante.

También se añade `tfg_project/.env.example` con `SEMANTIC_SCHOLAR_API_KEY=` como documentación de la variable, y se registra en `settings.py:194` (`SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")`).

#### B) Rate limiting thread-safe
**Archivo:** `semantic_scholar_client.py:103-110`
```python
RATE_LIMIT_INTERVAL_SECONDS = 1.1   # plan free de S2 es ~1 req/s
_rate_limit_lock = threading.Lock()
_last_request_monotonic = 0.0

def _apply_rate_limit() -> None:
    global _last_request_monotonic
    with _rate_limit_lock:
        now = time.monotonic()
        wait_seconds = RATE_LIMIT_INTERVAL_SECONDS - (now - _last_request_monotonic)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_request_monotonic = time.monotonic()
```
**Por qué `time.monotonic()` y no `time.time()`:** monotonic no se ve afectado por cambios del reloj del sistema (sync NTP, cambio de hora). Para medir intervalos siempre se usa monotonic.

**Limitación que debes admitir:** este lock solo coordina **dentro de un mismo proceso Python**. Si en producción tienes Gunicorn con 4 workers, cada uno puede emitir 1 req/s → 4 req/s totales y volverá el 429. La solución sería un lock distribuido en Redis. **Esto está documentado como comentario en el código** (línea 49-50) — si te lo preguntan, di que es trabajo futuro consciente.

#### C) Manejo del header `Retry-After`
**Archivo:** `semantic_scholar_client.py:113-125`
```python
def _retry_after_seconds(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))                # formato "30" (segundos)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(raw)      # formato HTTP-date RFC 2822
        return max(0.0, retry_at.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None
```
**Por qué dos formatos:** el RFC 7231 permite que `Retry-After` sea o un número entero de segundos o una fecha HTTP. Hay que parsear ambos.

#### D) Función centralizada `_request_semantic_scholar_json`
**Archivo:** `semantic_scholar_client.py:128-221`

Es la **única** función que hace HTTP a S2. Todas las funciones públicas (`get_paper_by_id`, `get_paper_by_doi`, `search_papers`, `get_paper_citations`, `get_paper_references`, `search_author`, `get_author_papers`) la usan.

Flujo:
1. Aplica rate limit.
2. Lanza request (GET o POST).
3. Si `RequestException` (red caída) → backoff exponencial `2**attempt` segundos, reintenta.
4. Si `200` → devuelve JSON.
5. Si `401/403` → log warning ("posible problema con la API key") y propaga.
6. Si en `{429, 500, 502, 503, 504}` (transient) → lee `Retry-After`, espera, reintenta.
7. Si agota reintentos → `SemanticScholarHTTPError(status_code, detail)`.

**Configuración por defecto:**
- `DEFAULT_TIMEOUT = 20` segundos por intento.
- `DEFAULT_RETRIES = 3` → en total 4 intentos.

#### E) Excepción granular
**Archivo:** `semantic_scholar_client.py:58-65`
```python
class SemanticScholarHTTPError(SemanticScholarError):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Error en la API de Semantic Scholar (HTTP {status_code})...")
```
**Por qué:** permite a los callers diferenciar 404 (paper no existe → devuelve `None`) de 429 (rate limit → reintenta más tarde) de 5xx (error de S2 → log y degrada). Ejemplo en `get_paper_metadata_by_doi`:
```python
except SemanticScholarHTTPError as exc:
    if exc.status_code == 404: return None
    if exc.status_code == 429: raise SemanticScholarError("Rate limit...")
    raise SemanticScholarError(...)
```

#### F) Nuevas funciones públicas

Antes el cliente solo exponía `get_citing_papers_for_doi` y `get_citation_counts_for_dois`. El commit añade:
- `get_paper_by_id(paper_id, fields)` — paper por su ID interno
- `get_paper_by_doi(doi, fields)` — paper por DOI (resuelve a `DOI:...` prefix)
- `search_papers(query, limit, fields)` — búsqueda libre
- `get_paper_citations(paper_id, limit, offset, fields)` — citas entrantes (paginado)
- `get_paper_references(paper_id, limit, offset, fields)` — referencias salientes
- `search_author(query, limit, fields)`
- `get_author_papers(author_id, limit, offset, fields)`

#### G) Migración de los callers
Como parte del commit:

- **`semantic_fetch.py`** ya no llama a S2 con `_safe_get`; usa `get_paper_by_doi` y `get_paper_citations`. Ahora se beneficia automáticamente del rate limit, retries y cache.
- **`utils.py`** (`get_citing_articles`, `check_doi_has_citations`): se elimina el código HTTP duplicado, se reemplazan `print(...)` por `logger.warning(...)` con formato estructurado.
- **`scripts/inspect_reference_sources.py`** se actualiza para usar las nuevas funciones.

### 6.3 Cómo defender el commit en una pregunta

**Si te preguntan: "explícame qué hiciste en este commit"** → resume así (estructurado, 60-90 segundos):

> "Antes el cliente de Semantic Scholar era frágil: cada función duplicaba el código HTTP, no había rate limiting (Semantic Scholar limita a 1 req/s sin API key y devolvía 429), no había retries para errores transitorios, y la API key se leía una sola vez al importar el módulo, sin poder configurarse por tests. Refactoricé todo el cliente para que (1) toda petición pasa por una función central `_request_semantic_scholar_json` con rate limiting thread-safe, backoff exponencial, lectura del header `Retry-After` y diferenciación de errores HTTP transitorios vs permanentes; (2) la API key se lee desde Django settings con fallback a env var, lo que la hace inyectable en tests; (3) se añadieron funciones públicas para los endpoints que faltaban (`search_papers`, `get_paper_references`, etc.); y (4) se migraron los callers existentes (`semantic_fetch.py`, `utils.py`) para que se beneficien del nuevo cliente. El commit también añadió 143 líneas de tests nuevos sobre el comportamiento de rate limit y retries."

**Si te preguntan: "¿por qué 1.1 segundos y no exactamente 1?"** → Margen de seguridad: S2 mide el intervalo en su lado y la latencia de red puede hacer que dos peticiones consecutivas lleguen demasiado seguidas si yo emito exactamente cada 1.0 s. 1.1 da margen.

**Si te preguntan: "¿qué hubieras hecho diferente?"** → Idealmente un lock distribuido en Redis para coordinar entre workers (lo dejé documentado como TODO). Y un patrón circuit breaker — ahora reintentamos siempre 4 veces aunque la API esté caída, sería mejor "abrir el circuito" tras X fallos consecutivos y devolver inmediatamente sin reintentar durante unos minutos.

---

## 7. URLs, vistas y APIs

### 7.1 URLs raíz (`tfg_project/tfg_project/urls.py`)

| Ruta | Vista |
|------|-------|
| `/` | `home` |
| `/accounts/` | allauth (Google, ORCID) |
| `/admin/` | admin Django |
| `/notifications/` | listar notifs |
| `/citations/` | include de la app citations |
| `/messages/` | inbox y conversaciones |
| `/perfil/<username>/` | perfil público |
| `/i18n/` | cambio de idioma |

### 7.2 URLs de citations (`citations/urls.py`)

Agrúpalas mentalmente por funcionalidad:

**A) Listado y detalle de reportes (HTML):**
`/list/`, `/report/<id>/`, `/report/<id>/edit/`, `/report/<id>/delete/`, `/report/<id>/preview/`, `/report/<id>/discard-draft/`, `/report/<id>/evidence/add/`, `/report/<id>/uploaded-pdf/`, `/report/<id>/extract-contexts/`

**B) Perfil del usuario:**
`/perfil/`, `/perfil/ajustes/`, `/perfil/mis-reportes/`, `/perfil/mis-comentarios/`, `/perfil/guardados/`, `/perfil/dblp-articulos/`, `/buscar-doi/`

**C) Reader (PDF interactivo):**
`/reader/<report_id>/`, `/reader/preview/`

**D) Flujo "tutor" (revisión sistemática):**
`/revision-citas/`, `/revision-citas/<id>/citers/`, `/revision-citas/aleatorio/`, `/revision-citas/create-report/`

**E) IA:**
`/reports/<id>/ai-detect/`, `/reports/<id>/ai-evaluate/`

**F) AJAX (devuelven JSON o HTML parcial vía HTMX):**
`/ajax_submit/`, `/comments/delete/<id>/`, `/citations/toggle_saved/`, `/vote/`, `/ajax/register/`, `/search_suggest/`, `/api/doi/`

**G) APIs REST públicas (consumidas por el Reader):**
- `POST /api/extract-citations/` — subes un PDF, devuelve refs + snippets + stats
- `POST /api/detect-article-doi/` — intenta deducir el DOI del PDF
- `GET /api/extractor-engines/` — lista motores disponibles para selector del frontend
- `GET /api/reference-debug-download/` — descarga un dump de debug
- `GET /api/reader-data/<id>/` — payload completo para inicializar el Reader con un reporte
- `GET /api/get-citation-context/` — contexto puntual de una cita
- `POST /api/pdf-contexts/`, `/api/pdf-contexts-upload/` — extracción de contextos
- `POST /api/pdf-reader-v2-upload/` — pipeline v2
- `GET /api/get-semantic-citations/`
- `POST /api/semantic-citation-analysis/` — análisis end-to-end

**H) Autenticación local:**
`/login/`, `/register/`, `/logout/`

### 7.3 Organización de las vistas

| Archivo | Tipo |
|---------|------|
| `views/page_views.py` (~1000 líneas) | HTML completo: listado, detalle, edición, reader, home |
| `views/auth_views.py` | login / register / logout locales (allauth maneja OAuth aparte) |
| `views/user_views.py` | perfil, ajustes, mis-reportes, dblp-articles, doi-search |
| `views/tutor_views.py` | flujo de revisión por papers del autor |
| `views/ajax_views.py` | endpoints AJAX que devuelven HTML parcial (HTMX) o JSON |
| `views/message_views.py` | mensajería 1:1 |
| `views/notification_views.py` | listar/marcar notificaciones |
| `views_api.py` | APIs REST públicas |
| `views_ai.py` | endpoints que llaman a IA (detect, evaluate) |
| `views_reports.py` | wizard legacy de creación |

**Decisión a defender:** "separamos por *responsabilidad*, no por modelo. Las vistas HTML están separadas de las AJAX/API porque tienen contratos de respuesta muy distintos (template HTML vs JSON), y mezclarlas obliga a comprobar `request.is_ajax()` en cada handler."

---

## 8. Frontend Reader (React)

### 8.1 Stack

- **Bundler:** Vite (configuración en `frontend_reader/vite.config.js`).
- **React 18** + ReactDOM.
- **PDF viewer:** `@allenai/pdf-components` — wrapper de Allen AI sobre PDF.js. Lo elegimos porque integra bien con PaperMage y porque añade soporte de overlays geométricos.
- **CSS:** propio (no Tailwind/Bootstrap en el reader), con variables CSS.

### 8.2 Componentes y hooks principales

Archivo: `frontend_reader/src/reader-app.jsx` (~6000 líneas)

- **`ReaderApp`** — raíz. Mantiene estado: PDF activo, snippets, referencias, citas detectadas, tab del sidebar.
- **`useHighlightedSnippet`** (~líneas 823-1187) — hook que recibe un snippet y lo dibuja sobre la capa de texto del PDF (clase `reader-highlight`). Hace búsqueda fuzzy en NFKD para sobrevivir a diacríticos y guiones suaves.
- **`useReaderV2Overlay`** — renderiza capas geométricas (tokens, párrafos, referencias) sobre el PDF para depuración.
- **`collectCitationHitsForPage`** (~líneas 665-821) — detecta citas en el texto vivo de la página usando los regex compartidos con backend.
- **Regex patterns** (~líneas 20-85) — réplica de `citation_patterns.py` en JS. **Aquí va a haber preguntas** (ver sección 13).

### 8.3 Comunicación con el backend

| Acción | Endpoint |
|--------|----------|
| Cargar reporte para Reader | `GET /citations/api/reader-data/<report_id>/` |
| Subir PDF para análisis | `POST /citations/api/extract-citations/` (multipart, campo `manuscript`) |
| Listar motores | `GET /citations/api/extractor-engines/` |

### 8.4 Sidebar

Cuatro tabs:
1. **Snippets** — lista de citas encontradas, filtrable por tipo (`bracket`, `author-year`, `doi`).
2. **References** — lista bibliográfica final con badges de status (`matched`, `unmatched`, `ambiguous`).
3. **Stats** — métricas: nº de citas detectadas, distribución por tipo, cobertura de referencias.
4. **Extract** — formulario para subir un PDF nuevo.

Cada snippet y referencia son clickables: hacen scroll al lugar exacto del PDF y resaltan con overlay SVG (cajas de color según tipo).

---

## 9. Scripts auxiliares y experimentos

Directorio: `scripts/`

| Script | Qué hace |
|--------|----------|
| `compare_citation_detectors.py` | Compara detector regex viejo vs nuevo. Modo `-v` lista cada cita ganada/perdida, `--samples` usa ejemplos sintéticos en lugar de PDFs. Útil cuando refactorizas patrones |
| `run_grobid_eval.py` | Ejecuta GROBID (fulltext/references) sobre un batch de PDFs, parsea el TEI XML, compara contra el extractor actual. Genera `tmp/grobid_debug/<timestamp>/` con `parsed.json`, `comparison.json`, `summary.txt` |
| `inspect_reference_sources.py` | Diagnóstico: para cada referencia, dice qué fuente la proveyó (Reader data, Crossref, GROBID, papermage). Usado para entender baja cobertura de DOI |
| `compare_reference_sources.py` | Compara el extractor actual contra baselines (GROBID, refextract). Métricas: count, cobertura de DOI, precisión |
| `run_reference_regression.py` | **Suite de regresión.** Corre el pipeline completo sobre `PDFs-Reales/`, guarda artefactos reproducibles en `tmp/reference_regression/<timestamp>/`. Incluye timing y debug del pipeline |
| `run_reference_parsing_experiment.py` | Experimentos sobre parseo de referencias con distintos motores |
| `test_papermage_raw.py`, `test_papermage_reader_json.py` | Pruebas aisladas de PaperMage |
| `test_citation_contexts.py` | Pruebas de extracción de contextos |
| `debug_references_ct_pdf.py` | Debug puntual sobre un PDF concreto |
| `inspect_reference_parsers.py` | Inspecciona la salida de cada parser |

**Mensaje a transmitir:** "tenemos disciplina experimental — el pipeline de extracción se evalúa con scripts de regresión que generan artefactos comparables entre versiones, no solo con tests unitarios."

---

## 10. Configuración, settings y deployment

### 10.1 `settings.py` (decisiones clave)

- `SECRET_KEY`: env var, con generación aleatoria si falta (solo dev).
- `DEBUG`: env var `DJANGO_DEBUG` (default `False`).
- `ALLOWED_HOSTS`: env var, default `localhost,127.0.0.1,[::1]`.
- **Middleware custom:** `citations.middleware.RequestIdMiddleware` el primero — genera UUID por request, lo guarda en `ContextVar`, lo añade al response header `X-Request-Id`. Sirve para correlacionar logs de una misma petición.
- **Context processors custom** (`citations/context_processors.py`):
  - `login_register_forms` — inyecta los forms de login/register a todos los templates → permite poner el modal en el navbar global.
  - `notifications_context` — inyecta `notifications_unread_count` + últimas 5 notifs.
  - `next_report_number_context` — próximo ID de reporte para mostrar "Reporte #XXX" sin query en cada vista.
- **i18n:** `LANGUAGE_CODE="es"`, idiomas `en` y `es`, `LOCALE_PATHS` apuntando a `locale/`. `TIME_ZONE="Europe/Madrid"`.
- **OAuth:** `INSTALLED_APPS` incluye `allauth.socialaccount.providers.google` y `allauth.socialaccount.providers.orcid`. ACCOUNT_FORMS sobrescritos con nuestros forms para mantener estilos.
- **Cache:** `LocMemCache` en dev (no tienes que correr Redis). En producción se sustituye por Redis con cambio de una sola línea.
- **Logging estructurado:** formatter `StructuredJsonFormatter` (citations/logging_formatters.py) emite JSON. Logger `citations.context` tiene rotación en `logs/citations_context.log` (10MB, 5 backups). Flag `LOG_CITATIONS` para habilitar verbosidad de contextos.
- **Variables de servicios:**
  - `GROBID_BASE_URL` (default `http://localhost:8070`)
  - `GROBID_TIMEOUT` (default 120 s)
  - `SEMANTIC_SCHOLAR_API_KEY` — añadida en el commit `70e50cd`
- **Seguridad:** `CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE` activos cuando `DEBUG=False`, `SECURE_BROWSER_XSS_FILTER`, `SECURE_CONTENT_TYPE_NOSNIFF`.

### 10.2 Docker

`Dockerfile`:
- Base: `python:3.11-slim`.
- `gcc` para compilaciones C (PaperMage tiene deps nativas).
- PyTorch CPU-only (`--extra-index-url https://download.pytorch.org/whl/cpu`) — sin CUDA, pesa mucho menos.
- Workdir: `/app/tfg_project`, comando: `runserver 0.0.0.0:8000`.

`compose.yml`:
- Servicio **`web`**: build local, puerto 8000, volumen `.:/app`.
- Servicio **`grobid`** (perfil `experimental`): imagen oficial `lfoppiano/grobid:0.8.1`, puerto 8070. Solo se levanta con `docker compose --profile experimental up`.

### 10.3 Pre-commit

`.pre-commit-config.yaml`: black (formateo), isort (orden de imports), flake8 (lint), `end-of-file-fixer`, `trailing-whitespace`. Hooks bloquean commits sucios.

### 10.4 Tests

| Archivo | Cobertura |
|---------|-----------|
| `tests.py` | OAuth (Google, ORCID), setup de SocialApp |
| `tests_dblp_client.py` | Parsing XML DBLP, caching, errores |
| `tests_dblp_loading.py` | Integración: carga de artículos en UI |
| `tests_semantic_scholar_client.py` | **Cliente S2: rate limiting, cache, parsing.** Tests añadidos por el commit `70e50cd` |
| `tests_citation_patterns.py` | Regex (numeric, author-year, DOI) |
| `tests_reference_anchors.py` | Detección de anchors en bloques de referencias |
| `tests_reference_pipeline_baseline.py` | Pipeline end-to-end sobre PDFs reales |
| `tests_reference_reconciliation.py` | Reconciliación entre fuentes |
| `tests_compare_reference_sources.py` | Comparación multi-fuente |
| `tests_reference_source_inspection.py` | Inspección de campos de APIs externas |

---

## 11. Decisiones de diseño (el "por qué")

> Tu tutor seguramente preguntará "¿por qué...?". Ten estas listas:

### Por qué Django y no FastAPI/Flask
- ORM maduro + migraciones (importante para un modelo con M:N y constraints).
- Admin gratis → moderación rápida.
- `django-allauth` cubre OAuth Google + ORCID sin escribir código.
- Sistema de templates + i18n + context processors → muy productivo para UI clásica.
- React solo donde aporta (el Reader, que es interactivo); el resto es server-rendered → SEO y simplicidad.

### Por qué React solo en el Reader
- El listado, perfil, formularios, mensajería se sirven más rápido como HTML normal y son SEO-amigables.
- El Reader es la única vista que justifica una SPA: necesita sincronizar PDF + overlays + sidebar interactivo.
- HTMX cubre la interactividad puntual (votos, comentarios) sin SPA.

### Por qué JSONField para metadata y contextos
- Schema heterogéneo según fuente (S2/Crossref/DBLP).
- Evita migraciones por cada cambio de campo externo.
- Postgres soporta índices GIN sobre JSONB si en el futuro se necesita buscar dentro.

### Por qué tres motores de extracción de PDFs
- Trade-off velocidad/precisión: PaperMage es preciso pero lento; generic es rápido pero pierde estructura.
- Robustez: `engine="auto"` siempre encuentra uno que funcione.
- Reproducibilidad: si el usuario fija un motor, no caemos a otro (modo "experimental").

### Por qué Semantic Scholar primary + Crossref fallback
- S2 expone `contexts` (los snippets donde se cita) — Crossref no.
- S2 tiene rate limit estricto (1 req/s); Crossref es laxo.
- Si S2 falla o agota la cuota, Crossref nos da al menos la metadata básica.

### Por qué regex compartidos backend ↔ frontend
- Misma definición de "cita" en los dos sitios → consistencia.
- El frontend resalta lo que el backend detectó, sin discrepancias.
- Si se cambia un patrón, hay que tocarlo en dos sitios — coste asumido.

### Por qué Gemini Flash para detección IA
- Es barato y rápido para localización estructurada con JSON.
- No necesitamos razonamiento profundo, solo "¿este párrafo cita al paper A?".
- Para el `ai_report_evaluator` (juicio de "incorrección") tiene más sentido un modelo de razonamiento, pero está fuera del flujo crítico (segunda opinión).

### Por qué context processors para forms de auth y notificaciones
- Evita pasar las mismas variables desde cada vista.
- Reduce boilerplate.
- El navbar es global → los datos que consume deben ser globales.

### Por qué `RequestIdMiddleware`
- Trazabilidad: en logs JSON puedes correlacionar todas las líneas de una misma request.
- Si un usuario reporta un bug y te da el `X-Request-Id`, puedes grep en logs y reconstruir todo lo que pasó.

### Por qué dos forms separados para perfil (`UserProfileForm`, `ProfileForm`)
- `ProfileForm` toca el modelo `User` (username, first_name, last_name).
- `UserProfileForm` toca el modelo extendido `UserProfile`.
- En ajustes, cada sección envía solo su form, no se mezclan.

---

## 12. Limitaciones conocidas y trabajo futuro

**Sé honesto sobre esto: los tribunales valoran que conozcas las limitaciones de tu propio trabajo.**

1. **Rate limiting no coordinado entre workers.** El lock está en memoria del proceso. En producción con varios workers Gunicorn, el rate efectivo se multiplica → vuelve a fallar 429. **Solución: lock distribuido en Redis** (documentado como TODO en el código).
2. **GROBID experimental.** No está en el flujo principal porque requiere un servidor Docker separado y añade ~10 s por PDF. Tenemos scripts para evaluarlo (`run_grobid_eval.py`) pero la decisión de integrarlo o no depende de cuánto ganamos en precisión. La evaluación está pendiente de cerrarse.
3. **PDFs escaneados (sin OCR).** Si el PDF es una imagen sin texto seleccionable, el pipeline falla. No tenemos OCR integrado. Solución futura: Tesseract + redirigir el flujo cuando se detecte un PDF "ciego".
4. **Paywalls.** Solo trabajamos con open access. Si el paper no expone `openAccessPdf` en S2 no podemos descargar el PDF para extraer contextos. Fallback: subida manual por el usuario.
5. **Sin circuit breaker para APIs.** Si S2 está caído, reintentamos 4 veces cada llamada → multiplicamos la latencia por 4. Mejor: tras N fallos consecutivos, abrir el circuito y devolver inmediatamente sin reintentar durante X minutos.
6. **Cache local en memoria (LocMemCache).** En multi-worker cada uno tiene su propia cache. Solución directa: Redis/Memcached (la API de Django cache es la misma).
7. **`CitationReport` legacy.** Modelo del wizard antiguo que ya no se usa pero permanece por compatibilidad de migraciones. Habría que limpiar.
8. **Tests no completos.** Tenemos cobertura buena en cliente S2, patrones de citas, DBLP. Falta cobertura en vistas (especialmente `page_views.py` que es enorme) y en flujos AJAX.
9. **API REST sin versionado.** Si cambia el contrato del Reader rompe a versiones antiguas. Habría que poner `/api/v1/...`.
10. **Sin auth en APIs públicas.** Algunos endpoints (`extract-citations`) son anónimos. Sirve para uso experimental, pero en producción habría que limitar por IP o requerir token.

---

## 13. ⭐ Preguntas anticipadas con respuestas

### A) Modelado de datos

**Q: ¿Por qué `IncorrectCitation.author` es `null=True`?**
A: Para preservar reportes históricos si un usuario borra su cuenta. La cita incorrecta es información del dominio académico que sobrevive al usuario. Si se elimina el `User`, el FK pasa a `NULL` y el reporte queda como "anónimo" en lugar de borrarse.

**Q: ¿Por qué `Vote.value` es entero y no boolean?**
A: Soporta `+1` y `-1`. Si fuera booleano solo distinguiría "votó" vs "no votó", pero queremos diferenciar upvote y downvote. Y `unique_together(user, citation)` impide doble voto.

**Q: ¿Cómo soportas threads anidados de comentarios?**
A: `Comment.parent` es FK self-referencial nullable. Si es `None`, es comentario raíz; si tiene valor, es reply. En el template se construye el árbol con `_build_comment_threads` (en `page_views.py`), que hace un pase O(n) en memoria agrupando por parent. Para no hacer queries recursivas usamos `select_related('parent')`.

**Q: ¿Por qué `SavedCitation` y no `ManyToManyField`?**
A: Porque necesito el campo `created_at` (cuándo lo guardó). Un `ManyToManyField` simple no permite campos extra; sí lo permite con `through=...`, pero tenerlo como modelo explícito es más limpio y consultable.

**Q: ¿Cómo escalaría el modelo si tuviera millones de citas?**
A: (1) Particionado por año en PostgreSQL. (2) Mover JSONField a JSONB con índices GIN. (3) Cache de denormalización (counts de votos, comments) para evitar `count()` en cada render. (4) Search engine externo (Meilisearch / Elasticsearch) para `citation_suggest` en lugar de LIKE sobre BD.

### B) Arquitectura y servicios

**Q: ¿Por qué separar vistas en `views/` por funcionalidad?**
A: `page_views.py` ya supera las 1000 líneas. Separar por dominio (`auth`, `user`, `message`, `tutor`, `notification`) mantiene cada archivo manejable. Convención: las vistas relacionadas con el mismo modelo o flujo viven juntas.

**Q: ¿Por qué tener `ajax_views.py` separado de `views_api.py`?**
A: Tienen contratos diferentes. `ajax_views` devuelve **HTML parcial** vía HTMX (para inyectar en el DOM directamente). `views_api` devuelve **JSON puro** consumido por el Reader React. Mezclarlos obligaría a comprobar headers en cada vista.

**Q: ¿Qué pasa si el servidor reinicia mientras un usuario está reportando una cita?**
A: El borrador `IncorrectCitation` no se persiste hasta que se hace submit final (`ajax_submit_citation`). Las ediciones interim se guardan en localStorage en el frontend del Reader. Como mejora se podría auto-guardar el borrador en la BD cada N segundos.

### C) Servicios externos y `70e50cd`

**Q: ¿Qué pasa si Semantic Scholar devuelve 429?**
A: En `_request_semantic_scholar_json` lo detectamos como transient. Leemos el header `Retry-After` (numérico o HTTP-date). Esperamos ese tiempo (o `2**attempt` si no viene). Reintentamos hasta `DEFAULT_RETRIES = 3` veces. Si agotamos, lanzamos `SemanticScholarHTTPError(429, ...)`. El caller decide: en `get_citation_counts_for_dois` lo convierte en `SemanticScholarError("Rate limit, intenta más tarde")` para que el usuario vea un mensaje claro.

**Q: ¿El rate limit funciona si tengo varios procesos?**
A: **No, en multi-worker no.** El lock es a nivel de proceso (threading.Lock). En Gunicorn con 4 workers, cada uno emite 1 req/s → 4 req/s totales. Documentado como TODO. Solución: lock distribuido en Redis con `SETNX` y `EXPIRE`.

**Q: ¿Por qué cacheas durante 24 h?**
A: Los metadatos académicos (título, autores, año, citationCount) cambian muy lentamente. 24 h es un buen compromiso entre frescura y aliviar la API. La paginación de citantes (`citing_papers_paginated`) cachea solo 1 h porque puede crecer más rápido.

**Q: ¿Qué claves de cache usas?**
A: SHA1 del DOI normalizado para evitar caracteres conflictivos (`/`, `:`). Prefijo según el tipo: `semantic_scholar:citation_count:<sha1>`, `:paper_id:<sha1>`, etc.

**Q: ¿Cómo desambiguas entre Semantic Scholar y Crossref?**
A: `reference_reconciliation.validate_reference_against_metadata`. Calculo un `match_score` ponderado: DOI (0.42), título (0.28), autores (0.16), año (0.08), venue (0.06). Si `match_score ≥ 0.72` y el `mixed_score` (penaliza ambigüedad) es bajo, acepto. Si dos candidatos pasan el umbral, el de mayor score gana. Si ninguno, dejo la referencia como `unmatched`.

**Q: ¿Por qué la prioridad S2 > Crossref?**
A: S2 expone `contexts` (los snippets de dónde se cita el paper), que es la información que más nos importa. Crossref solo da metadata. Y S2 enlaza al openAccess PDF cuando existe; Crossref no.

**Q: ¿Has probado OpenAlex?**
A: Es la alternativa más obvia (open data, sin rate limit estricto). No la integramos por tiempo, pero la arquitectura del cliente S2 está pensada para reutilizarse: tendría el mismo patrón (`_request_openalex_json`, mismo caching y retries). Está en el roadmap.

### D) Extracción de PDFs

**Q: ¿Por qué PaperMage y no GROBID directamente?**
A: PaperMage corre en proceso Python, integra layout-aware extraction sin dependencias externas. GROBID requiere un servicio Docker en puerto 8070, añade ~10 s por PDF y obliga a parsear TEI XML. Lo mantenemos como experimento porque su extracción de referencias es muy buena, pero no en el flujo principal por ese coste operativo.

**Q: ¿Qué pasa si el PDF es una imagen escaneada?**
A: PaperMage devuelve poco o nada de texto. El extractor genérico (pdfplumber/fitz) tampoco. Devolvemos una lista vacía de párrafos y el frontend muestra "no se pudo extraer texto". No tenemos OCR integrado — es trabajo futuro.

**Q: ¿Cómo manejas PDFs encriptados?**
A: pdfplumber/fitz lanzan excepción. Lo capturamos en el motor `generic` y propagamos como error. El usuario ve un mensaje de "PDF protegido".

**Q: ¿Por qué los regex están duplicados en backend y frontend?**
A: Para que el frontend resalte exactamente lo que el backend detectó. La alternativa sería que el backend devuelva offsets exactos en el texto y el frontend solo pinte, pero entonces el frontend no podría detectar citas en texto subido directamente (sin viajar al backend). Como tradeoff, mantenemos los patrones sincronizados manualmente y tenemos tests en ambos lados.

### E) Frontend

**Q: ¿Por qué Vite y no webpack/CRA?**
A: Vite es más rápido en dev (HMR instantáneo) y la configuración es mínima. CRA está deprecado. Para una SPA single-purpose como el Reader, Vite es la opción razonable.

**Q: ¿Por qué `@allenai/pdf-components` y no react-pdf directamente?**
A: `@allenai/pdf-components` es un wrapper sobre PDF.js diseñado pensando en anotaciones académicas (overlays, highlight, bounding boxes). Integra naturalmente con el ecosistema de Allen AI (PaperMage). React-pdf es más genérico y habría que reescribir las primitivas de overlay.

**Q: ¿Cómo gestionas el estado de muchos snippets sobre muchas páginas?**
A: Mantengo un Map `pageNumber → snippets[]` en el estado del root component. Los componentes de página suscritos solo reciben sus snippets. Para los hover/scroll uso refs + callbacks, no estado, para evitar re-renders.

### F) Performance y escalabilidad

**Q: ¿Cuánto tarda procesar un PDF?**
A: Con `engine="generic"` ~1-2 segundos para 50 páginas. Con PaperMage 10-15 segundos. Con GROBID 8-12 segundos (más latencia HTTP). El cuello es PaperMage si lo usamos.

**Q: ¿Cómo evitas que un usuario tumbe el servidor subiendo PDFs?**
A: Actualmente solo tenemos `DATA_UPLOAD_MAX_MEMORY_SIZE` de Django. Como mejora habría que: (1) limitar tamaño del PDF (e.g. 20MB), (2) rate-limitar el endpoint `/api/extract-citations/` por IP, (3) mover la extracción a una task de Celery.

**Q: ¿Por qué no usas Celery/Redis para tareas asíncronas?**
A: Para mantener la arquitectura simple. Los flujos actuales son síncronos y el usuario espera el resultado. Si añadimos OCR o procesamiento en background, Celery sería el siguiente paso. Decisión consciente: YAGNI.

**Q: ¿Has hecho profiling?**
A: Tengo logs estructurados con timing por etapa (extracción, matching, reconciliación). El `run_reference_regression.py` mide y guarda el timing. Esto me permite detectar regresiones de rendimiento entre versiones.

### G) Seguridad

**Q: ¿Cómo proteges contra CSRF?**
A: Django CSRF middleware activo. `CSRF_TRUSTED_ORIGINS` configurado. En endpoints AJAX el token va en el header `X-CSRFToken`.

**Q: ¿Cómo proteges contra XSS?**
A: Templates de Django escapan por defecto. En el Reader (React) todo input se renderiza como texto (no `dangerouslySetInnerHTML`). El campo `incorrect_reason` se sanitiza en el form.

**Q: ¿SQL injection?**
A: Usamos el ORM de Django siempre. No hay raw queries. Las búsquedas usan `__icontains` (parametrizado).

**Q: ¿OAuth: qué scopes pides?**
A: Google: email + profile básico. ORCID: identificador público. No pedimos permisos extra. allauth gestiona el callback y el token, no manejamos credenciales nosotros.

**Q: ¿Y los uploads de PDFs?**
A: Django MEDIA_ROOT, nombres saneados, sin ejecución. El servidor no sirve directamente desde MEDIA en producción; iría tras nginx con `internal`. En dev se sirve con `runserver`.

### H) Trabajo futuro / mejora

**Q: ¿Qué cambiarías si lo hicieras de nuevo?**
A: (1) Integrar OpenAlex desde el inicio como fuente principal junto a S2 (open data, sin rate limit estricto). (2) Lock distribuido en Redis para el rate limiter. (3) Mover extracción a tareas Celery con feedback en tiempo real (WebSocket o polling). (4) Versionar la API REST (`/api/v1/`). (5) Integrar OCR (Tesseract) para PDFs escaneados. (6) Tests E2E con Playwright sobre el Reader.

**Q: ¿Cuál es la próxima funcionalidad que añadirías?**
A: Detección semántica de "no said" usando un LLM más capaz que compare el snippet de la cita con el abstract/conclusion del paper citado. El `ai_report_evaluator` ya existe pero podría hacerse más robusto con embedding similarity como pre-filtro.

---

## 14. Plan de repaso (calendario sugerido)

Asumiendo que tienes ~5 días antes de la defensa:

### Día 1 — Visión global
- Leer esta guía entera (1-2 h).
- Releer el README y `docs/introduccion.md`, `docs/arquitectura_backend.md`, `docs/flujo_datos_end_to_end.md`.
- Dibujar a mano el diagrama de la sección 3 sin mirar.

### Día 2 — Modelos y URLs
- Abrir `models.py` y recorrer cada modelo. Saber de memoria los campos de `IncorrectCitation`.
- Abrir `citations/urls.py` y poder explicar cada grupo de rutas (HTML, AJAX, API, AI).
- Practicar respuesta corta a "¿qué hace `view X`?" para 5-6 vistas clave.

### Día 3 — Servicios (énfasis aquí)
- Leer `semantic_scholar_client.py` entero. Es crítico (commit del tutor).
- Releer la sección 6 de esta guía.
- Abrir el commit `git show 70e50cd` y revisarlo línea por línea.
- Repasar la cadena de fallbacks: engines → patterns → reconciliation.
- Saber recitar el algoritmo de scoring (5.4).

### Día 4 — Frontend y experimentos
- Abrir `frontend_reader/src/reader-app.jsx` y entender los hooks principales.
- Levantar el proyecto localmente, subir un PDF, navegar el reader. **Esto vale más que leer el código.**
- Pasear por `scripts/run_reference_regression.py` y `compare_citation_detectors.py`.

### Día 5 — Q&A drilling
- Sección 13 entera: leer cada pregunta, responder en voz alta sin mirar la respuesta, luego comparar.
- Pedir a alguien que te haga 10 preguntas aleatorias del documento.
- Anotar las dos preguntas en las que titubeaste y reforzarlas.

---

## Apéndice: rutas rápidas a archivos clave

| Tema | Archivo |
|------|---------|
| Modelos | `tfg_project/citations/models.py` |
| URLs de la app | `tfg_project/citations/urls.py` |
| Settings | `tfg_project/tfg_project/settings.py` |
| Cliente S2 ⭐ | `tfg_project/citations/services/semantic_scholar_client.py` |
| Cliente Crossref | `tfg_project/citations/services/crossref_client.py` |
| Cliente DBLP | `tfg_project/citations/services/dblp_client.py` |
| Patrones de citas | `tfg_project/citations/services/citation_patterns.py` |
| Reconciliación | `tfg_project/citations/services/reference_reconciliation.py` |
| Detector IA | `tfg_project/citations/services/ai_citation_detector.py` |
| Engines | `tfg_project/citations/services/engines.py` |
| Reader (frontend) | `frontend_reader/src/reader-app.jsx` |
| Suite de regresión | `scripts/run_reference_regression.py` |
| Comparador citas | `scripts/compare_citation_detectors.py` |
| Eval GROBID | `scripts/run_grobid_eval.py` |

**Mucha suerte. Si dominas las secciones 4, 5, 6 y 13, vas a ir sobrado.**

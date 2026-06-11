# Arquitectura Backend

El backend es un monolito Django 5.1 con una aplicación principal, `citations`, que agrupa vistas HTML, endpoints JSON, servicios de dominio, modelos y plantillas.

## Estructura

```text
tfg_project/
├── manage.py
├── tfg_project/
│   ├── settings.py          # configuración Django, logging, static/media, GROBID
│   ├── urls.py              # rutas raíz, allauth, admin, messages, notifications
│   ├── asgi.py
│   └── wsgi.py
└── citations/
    ├── models.py            # modelos de dominio y comunidad
    ├── forms.py             # formularios de perfil, auth, reportes, comentarios
    ├── urls.py              # rutas internas de la app
    ├── middleware.py        # request id
    ├── signals.py           # creación de perfiles/notificaciones
    ├── views/
    │   ├── page_views.py    # páginas HTML principales
    │   ├── ajax_views.py    # AJAX de plantillas
    │   ├── user_views.py    # perfiles, DBLP, ajustes
    │   ├── tutor_views.py   # revisión de citadores
    │   ├── message_views.py
    │   ├── notification_views.py
    │   └── auth_views.py
    ├── views_api.py         # endpoints JSON de extracción/reader/semantic
    ├── views_ai.py          # acciones IA experimentales
    ├── views_reports.py     # wizard legacy/inactivo
    ├── services/            # lógica pesada y clientes externos
    ├── management/commands/ # comandos GROBID experimentales
    ├── templates/
    ├── static/
    └── tests*.py
```

## Capas

### Vistas HTML

`citations/views/` renderiza páginas con Django templates. Aquí viven los flujos visibles para usuarios: home, listado de reportes, detalle, perfiles, ajustes, DBLP, mensajes, notificaciones y reader.

`page_views.py` también contiene acciones vinculadas a reportes, por ejemplo editar, borrar, descartar borradores, extraer contextos o abrir el reader.

### AJAX y APIs JSON

Hay dos familias:

- `views/ajax_views.py`: endpoints ligados a formularios y fragmentos HTML, como voto, guardar, comentarios, registro modal, sugerencias y DOI metadata.
- `views_api.py`: endpoints JSON usados por el reader, scripts y pruebas externas, como extracción de referencias, capas del reader, contextos PDF y análisis semántico.

La referencia completa está en [api_reference_completa.md](api_reference_completa.md).

### Servicios

`citations/services/` contiene la lógica que no debe estar en vistas:

- clientes externos: Semantic Scholar, Crossref, DBLP y GROBID;
- extracción: PaperMage y análisis de contextos;
- reader: construcción de capas, referencias, snippets y datos de inicialización;
- reconciliación y enriquecimiento DOI;
- notificaciones;
- experimentos aislados de parsers de referencias.

La vista debe validar parámetros, llamar a servicios y serializar respuestas. Si una función necesita descargar PDFs, comparar referencias, llamar APIs externas o aplicar heurísticas, pertenece a `services/`.

### Modelos

`models.py` define el dominio persistido:

- `IncorrectCitation` como reporte principal;
- `UserProfile`;
- `Comment`, `Vote`, `SavedCitation`;
- `Conversation`, `Message`, `Notification`;
- `CitationReport` como modelo legacy/inactivo.

Detalles en [modelos_y_relaciones.md](modelos_y_relaciones.md).

## Rutas Principales

`tfg_project/urls.py` monta:

- `/`: home;
- `/admin/`: Django admin;
- `/accounts/`: django-allauth;
- `/citations/`: rutas de `citations.urls`;
- `/messages/`: mensajes privados;
- `/notifications/`: notificaciones;
- `/perfil/<username>/`: perfil público;
- `/i18n/`: cambio de idioma.

`citations/urls.py` agrupa:

- páginas: `/citations/list/`, `/citations/report/<pk>/`, `/citations/reader/<report_id>/`;
- perfiles: `/citations/perfil/`, `/citations/perfil/ajustes/`, `/citations/perfil/dblp-articulos/`;
- revisión: `/citations/revision-citas/`;
- AJAX: votos, guardados, comentarios, DOI metadata;
- APIs: `/citations/api/...`.

## Configuración Relevante

- Base de datos: SQLite por defecto (`BASE_DIR / "db.sqlite3"`).
- Idioma: español por defecto, inglés disponible.
- Static: `citations/static/`, con build del reader en `citations/static/reader/`.
- Media: `tfg_project/media/`.
- Logs: `tfg_project/logs/citations_context.log`.
- GROBID: `GROBID_BASE_URL` y `GROBID_TIMEOUT`.
- Semantic Scholar: `SEMANTIC_SCHOLAR_API_KEY`.

## Flujo de Petición Ejemplo

Extracción de referencias desde el reader preview:

1. El navegador envía `POST /citations/api/extract-citations/` con `multipart/form-data` y campo `manuscript`.
2. `views_api.api_extract_citations` valida `engine`, `debug` y `article_doi`.
3. Si es PDF, `extract_pdf_references()` obtiene referencias base con PyMuPDF.
4. `process_manuscript()` ejecuta el motor solicitado.
5. `extract_pdf_data()` prepara capas del reader.
6. `build_references_data()` reconstruye referencias estructuradas y diagnósticos.
7. `reconcile_reference_sources()` decide la lista final.
8. `enrich_extraction_with_doi()` usa Crossref/Semantic Scholar si hay DOI del artículo.
9. La API devuelve referencias, snippets, capas, estadísticas, enriquecimiento y datos de artículo.

## Puntos de Extensión

Para añadir un endpoint JSON:

1. Implementa la vista en `views_api.py` o `ajax_views.py` según el consumidor.
2. Registra la ruta en `citations/urls.py`.
3. Documenta payload, errores y consumidores en `api_reference_completa.md`.
4. Añade tests si el endpoint modifica datos o encapsula lógica no trivial.

Para añadir un motor de extracción:

1. Crea un servicio nuevo en `citations/services/`.
2. Declara disponibilidad y función de extracción en `engines.py`.
3. Añade la clave a `ENGINE_LABELS` y a la política de `run_engine()`.
4. Actualiza `servicios_extraccion.md`, `api_reference_completa.md` y pruebas de regresión.

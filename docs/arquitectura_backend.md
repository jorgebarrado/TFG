# Arquitectura del Backend

El backend de CiteCheck está construido sobre **Django 5.x**, siguiendo una arquitectura monolítica modular. Este documento ofrece una visión de alto nivel de cómo se organizan los componentes del servidor.

## Estructura de Directorios

```text
tfg_project/
├── manage.py              # CLI de Django
├── tfg_project/           # Configuración global (settings, wsgi, asgi)
│   ├── settings.py        # Configuración (DB, Apps, Middleware)
│   └── urls.py            # Enrutador principal
└── citations/             # APLICACIÓN PRINCIPAL (Business Logic)
    ├── models.py          # Definición de esquema de datos
    ├── views/             # Vistas HTML (User-facing)
    ├── views_api.py       # API REST (JSON endpoints)
    ├── services/          # Lógica de dominio compleja (Extracción, APIs externas)
    ├── urls.py            # Rutas internas de la app
    └── templates/         # Plantillas HTML (Django Template Language)
```

## Componentes Clave

### 1. Vistas (Views)
El proyecto separa claramente las vistas que renderizan HTML de las que sirven JSON.
*   **Vistas HTML (`citations/views/`):** Usan plantillas Django + Bootstrap. Gestionan la navegación, perfiles de usuario y formularios tradicionales.
*   **API REST (`citations/views_api.py`):** Controladores que responden JSON. Son consumidos por el Frontend React (Reader) y por scripts JS en las plantillas.
    *   *Ver `api_reference_completa.md` para detalles de endpoints.*

### 2. Capa de Servicios (`citations/services/`)
Para mantener las vistas "delgadas" (thin views), la lógica pesada se delega a servicios especializados.
*   **Extractores:** `papermage_extractor.py`, `pdf_citation_analyzer.py`.
*   **Clientes API:** `semantic_scholar_client.py`, `dblp_client.py`.
*   **Pipelines:** `semantic_citation_pipeline.py`.
    *   *Ver `servicios_extraccion.md` para profundidad técnica.*

### 3. Base de Datos
*   **Motor:** SQLite por defecto (desarrollo), compatible con PostgreSQL.
*   **ORM:** Django ORM.
*   **Datos No Estructurados:** Uso extensivo de `JSONField` en modelos como `IncorrectCitation` para almacenar metadatos bibliográficos variables y coordenadas de texto (snippets).
    *   *Ver `modelos_y_relaciones.md`.*

### 4. Autenticación
*   Delegada a `django-allauth`.
*   Soporta Login local (username/password) y Social (Google, ORCID).
*   **Extensión:** El modelo `UserProfile` (relación 1:1 con `User`) almacena datos académicos adicionales.

## Puntos de Extensión (Dónde tocar)

### ¿Cómo añadir un nuevo Endpoint API?
1.  Crea la función de vista en `citations/views_api.py`.
    *   Usa anotaciones de tipo (`-> JsonResponse`).
    *   Decora con `@require_GET` o `@require_POST`.
2.  Registra la URL en `citations/urls.py` bajo el comentario `# APIs nuevas/ajustadas`.

### ¿Cómo añadir una nueva Notificación?
1.  Define el tipo en `Notification.NotificationType` (`models.py`).
2.  Crea la lógica de disparo en `citations/services/notifications.py`.
3.  Llama al servicio desde la vista correspondiente (ej. al crear un comentario).

### ¿Cómo modificar el Logging?
*   El logger se configura en `tfg_project/settings.py` -> `LOGGING`.
*   Para añadir trazas a un módulo nuevo, usa:
    ```python
    import logging
    logger = logging.getLogger("citations.context") # O crea uno nuevo
    logger.info("...")
    ```

## Flujo de Petición Típico (Ejemplo: Ver Contexto)

1.  **Request:** Cliente GET `/citations/get_citation_context/?citing_doi=...`
2.  **Routing:** `tfg_project/urls.py` -> `citations/urls.py` -> `views_api.get_citation_context`.
3.  **Controller:** La vista valida parámetros.
4.  **Service:** Llama a `services.semanticscholar.get_openaccess_pdf_url`.
5.  **Service:** Si hay PDF, llama a `services.papermage_extractor.extract_contexts_from_pdf`.
    *   *Este paso descarga el PDF a `/tmp`, lo procesa y devuelve objetos Python.*
6.  **Response:** La vista serializa los objetos a JSON y retorna HTTP 200.

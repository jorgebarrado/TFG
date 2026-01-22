# Modelos de Datos

La base de datos de CiteCheck utiliza SQLite por defecto y está gestionada por el ORM de Django. A continuación se detallan los modelos principales definidos en `citations/models.py`.

## Usuarios y Perfiles

### `UserProfile`
Extiende el modelo `User` de Django mediante una relación One-to-One.
*   **Información Personal:** `date_of_birth`, `country`, `bio`, `avatar`.
*   **Información Académica:** `dblp_url`, `research_area`, `profession`, `institution`.
*   **Redes Sociales:** `twitter_url`, `github_url`, `linkedin_url`, `personal_website` y campos genéricos (`social_link_1`...`4`).
*   **Preferencias:** `preferred_language`, configuraciones de notificaciones (`notify_comments...`).

## Reportes de Citas

### `IncorrectCitation`
El núcleo de la aplicación. Representa un reporte de error.
*   **Identificadores:** `doi_original` (artículo citado), `doi_incorrect` (artículo citante).
*   **Metadatos:** `metadata_original`, `metadata_incorrect` (JSONField para almacenar info bibliográfica).
*   **Análisis:**
    *   `citation_contexts`: JSONField con los fragmentos de texto extraídos.
    *   `incorrect_reason`: Texto explicativo del usuario.
    *   `citation_type`: Clasificación ("not said", "misinterpretation", "contextual misattribution").
*   **Auditoría:** `author` (Usuario), `created_at`.

### `CitationReport` (Experimental/Futuro)
Modelo diseñado para un flujo de "wizard" más complejo, con soporte para subida de archivos PDF (`original_pdf_uploaded`, `citing_pdf_uploaded`) y evaluación por IA (`ai_assessment`).

## Interacción Social

### `Comment`
Comentarios en los reportes.
*   `citation`: FK a `IncorrectCitation`.
*   `author`: FK a `User`.
*   `content`: Texto del comentario.
*   `parent`: Auto-referencia para permitir respuestas anidadas (hilos).

### `Vote`
Votos en los reportes.
*   `user`: FK a `User`.
*   `citation`: FK a `IncorrectCitation`.
*   `value`: Entero (+1 para upvote, -1 para downvote).
*   Restricción `unique_together` para evitar votos múltiples por usuario/reporte.

### `SavedCitation`
Permite a los usuarios marcar reportes como favoritos/guardados.

## Comunicación y Notificaciones

### `Conversation` y `Message`
Sistema de mensajería privada.
*   `Conversation`: Agrupa a los participantes (`ManyToManyField` a `User`).
*   `Message`: Contenido del mensaje, remitente y fecha.

### `Notification`
Sistema de alertas para el usuario.
*   `notification_type`: Tipo de evento (NUEVO_COMENTARIO, NUEVO_VOTO, etc.).
*   `actor`: Usuario que originó la notificación.
*   `is_read`: Estado de lectura.

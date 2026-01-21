# Modelos de Datos

A continuación se describen los principales modelos definidos en `citations/models.py`. Estos modelos forman el núcleo de la base de datos relacional.

## Usuarios y Perfiles

### `UserProfile`
Extiende el modelo `User` nativo de Django. Almacena información profesional y preferencias.

*   **Relación:** One-to-One con `django.contrib.auth.models.User`.
*   **Campos Clave:**
    *   `dblp_url`: Enlace al perfil de DBLP.
    *   `research_area`, `profession`, `institution`: Datos demográficos académicos.
    *   `social_link_X`: URLs a redes sociales (Twitter, GitHub, LinkedIn).
    *   `notify_*`: Configuración booleana de notificaciones.
    *   `avatar`: Imagen de perfil.

## Reportes de Citas

### `IncorrectCitation`
El modelo central que representa un reporte de una cita problemática.

*   **`doi_original`**: DOI del artículo que fue citado (el "citado").
*   **`doi_incorrect`**: DOI del artículo que contiene la cita errónea (el "citador").
*   **`citation_type`**: Clasificación del error:
    *   `not said`: El texto citado no dice lo que se afirma.
    *   `misinterpretation`: Se malinterpreta el hallazgo.
    *   `contextual misattribution`: Error de atribución en el contexto.
*   **`citation_contexts`**: JSONField. Almacena los fragmentos de texto exactos donde ocurre la cita en el PDF.
*   **`metadata_original` / `metadata_incorrect`**: JSONField. Cache de metadatos (título, autores) obtenidos de APIs externas para evitar consultas repetitivas.

## Interacción Social

### `Comment`
Permite discusiones en hilo sobre un reporte.
*   **Relación:** ForeignKey a `IncorrectCitation` y `User`.
*   **`parent`**: Auto-referencia para permitir respuestas anidadas (hilos).

### `Vote`
Sistema de votación para validar o rechazar reportes.
*   **Valores:** +1 (Upvote), -1 (Downvote).
*   **Unicidad:** Un usuario solo puede votar una vez por reporte (`unique_together = ("user", "citation")`).

### `SavedCitation`
Permite a los usuarios guardar reportes ("marcadores") para leer después.

## Mensajería y Notificaciones

### `Conversation` y `Message`
Sistema de mensajería privada interna.
*   **`Conversation`**: Agrupa a los participantes (Many-to-Many con User).
*   **`Message`**: Contenido textual vinculado a una conversación.

### `Notification`
Sistema de alertas para el usuario.
*   **Tipos:** Nuevo comentario, Nuevo voto, Nuevo mensaje, Sistema.
*   **`actor`**: Usuario que desencadenó la notificación (opcional).

## Modelos Experimentales / Futuros

### `CitationReport`
Modelo destinado a un flujo de creación de reportes más avanzado ("Wizard"), con soporte para subida de PDFs originales y citadores, y evaluación por IA. Actualmente coexiste con `IncorrectCitation` pero representa una evolución del modelo de datos.

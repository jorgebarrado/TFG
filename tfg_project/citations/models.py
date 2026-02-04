"""Models for citations app."""

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserProfile(models.Model):
    """
    Perfil extendido de usuario que complementa al modelo User de Django.

    Almacena información adicional sobre el investigador, sus preferencias,
    enlaces sociales y configuración de notificaciones.

    Attributes:
        user (OneToOneField): Relación uno a uno con el modelo User.
        dblp_url (URLField): URL del perfil de DBLP del usuario.
        date_of_birth (DateField): Fecha de nacimiento.
        country (CharField): País de residencia.
        preferred_language (CharField): Idioma preferido para la interfaz ('es' o 'en').
        research_area (CharField): Área principal de investigación (ej. Computer Science).
        profession (CharField): Rol profesional (ej. PhD Student, Professor).
        institution (CharField): Institución a la que pertenece.
        contact_email (EmailField): Correo electrónico visible para contacto público.
        social_link_1 (URLField): Primer enlace a red social o web personal.
        social_link_2 (URLField): Segundo enlace a red social.
        social_link_3 (URLField): Tercer enlace a red social.
        social_link_4 (URLField): Cuarto enlace a red social.
        notify_comments_on_my_reports (BooleanField): Preferencia para recibir notificaciones
            de comentarios en reportes propios.
        notify_comments_on_followed (BooleanField): Preferencia para recibir notificaciones
            de comentarios en reportes seguidos.
        notify_votes_on_my_reports (BooleanField): Preferencia para recibir notificaciones
            de votos en reportes propios.
        notify_news_and_updates (BooleanField): Preferencia para recibir noticias de la plataforma.
        avatar (ImageField): Imagen de perfil del usuario.
        bio (TextField): Biografía corta o descripción.
        twitter_url (URLField): URL de Twitter/X (legacy).
        github_url (URLField): URL de GitHub (legacy).
        linkedin_url (URLField): URL de LinkedIn (legacy).
        personal_website (URLField): Sitio web personal (legacy).
        is_public (BooleanField): Indica si el perfil es visible públicamente.
        show_activity (BooleanField): Indica si se muestra la actividad reciente en el perfil.
        show_social_links (BooleanField): Indica si se muestran los enlaces sociales.
    """

    LANGUAGE_CHOICES = [
        ("", _("Sin preferencia")),
        ("es", _("Español")),
        ("en", _("Inglés")),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    dblp_url = models.URLField(blank=True, null=True)

    date_of_birth = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("Fecha de nacimiento"),
    )
    country = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("País"),
    )
    preferred_language = models.CharField(
        max_length=5,
        blank=True,
        choices=LANGUAGE_CHOICES,
        verbose_name=_("Idioma preferido"),
    )

    research_area = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Área de investigación"),
        help_text=_("Ej. Computer Science, Quantum Computing, Physics..."),
    )
    profession = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Profesión o rol"),
        help_text=_("Ej. PhD Student, Researcher, Professor, QA Engineer..."),
    )
    institution = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Institución / organización"),
        help_text=_("Ej. Universidad, centro de investigación o empresa."),
    )

    contact_email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Correo de contacto"),
        help_text=_("Correo que otros usuarios pueden usar para contactar contigo."),
    )
    social_link_1 = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Enlace social 1"),
        help_text=_("Ej. perfil de X/Twitter, GitHub, LinkedIn, página personal..."),
    )
    social_link_2 = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Enlace social 2"),
        help_text=_("Opcional."),
    )
    social_link_3 = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Enlace social 3"),
        help_text=_("Opcional."),
    )
    social_link_4 = models.URLField(
        blank=True,
        null=True,
        verbose_name=_("Enlace social 4"),
        help_text=_("Opcional."),
    )

    notify_comments_on_my_reports = models.BooleanField(
        default=True,
        verbose_name=_("Avisarme cuando comenten mis reportes"),
    )
    notify_comments_on_followed = models.BooleanField(
        default=True,
        verbose_name=_("Avisarme cuando haya nuevos comentarios en reportes que sigo"),
    )
    notify_votes_on_my_reports = models.BooleanField(
        default=False,
        verbose_name=_("Avisarme cuando mis reportes reciban nuevos votos"),
    )
    notify_news_and_updates = models.BooleanField(
        default=False,
        verbose_name=_("Recibir noticias y novedades de CiteCheck"),
    )

    avatar = models.ImageField(
        upload_to="avatars/",
        blank=True,
        null=True,
        verbose_name=_("Avatar"),
    )
    bio = models.TextField(
        blank=True,
        verbose_name=_("Bio"),
    )
    twitter_url = models.URLField(blank=True, null=True)
    github_url = models.URLField(blank=True, null=True)
    linkedin_url = models.URLField(blank=True, null=True)
    personal_website = models.URLField(blank=True, null=True)

    is_public = models.BooleanField(default=True)
    show_activity = models.BooleanField(default=True)
    show_social_links = models.BooleanField(default=True)

    def __str__(self):
        """Devuelve el nombre de usuario asociado al perfil."""
        return self.user.username


AREA_CHOICES = [
    ("ENG", _("Engineering")),
    ("PHY", _("Physical Sciences")),
    ("ENV", _("Environmental Sciences")),
    ("MAT", _("Mathematics")),
    ("CIS", _("Computer and Information Sciences")),
    ("LIF", _("Life Sciences")),
    ("PSY", _("Psychology")),
    ("SOC", _("Social Sciences")),
    ("OTH", _("Other Sciences")),
    ("EDU", _("Education")),
    ("LAW", _("Law")),
    ("HUM", _("Humanities")),
    ("ART", _("Visual and Performing Arts")),
    ("BUS", _("Business and Management")),
    ("COM", _("Communication and Journalism")),
    ("SWK", _("Social Work")),
    ("NON", _("Other Non-Science & Engineering Fields")),
]


class IncorrectCitation(models.Model):
    """
    Representa un reporte de una cita incorrecta entre dos artículos científicos.

    Attributes:
        author (ForeignKey): Usuario que creó el reporte.
        doi_original (CharField): DOI del artículo original (el que debería haber sido citado o el citado).
        doi_incorrect (CharField): DOI del artículo que cita incorrectamente.
        incorrect_reason (TextField): Explicación del usuario sobre por qué la cita es incorrecta.
        metadata_original (JSONField): Metadatos en JSON del artículo original (título, autores, etc.).
        metadata_incorrect (JSONField): Metadatos en JSON del artículo citador.
        citation_contexts (JSONField): Fragmentos de texto donde aparece la cita.
        citation_type (CharField): Tipo de error de citación (ej. malinterpretación).
        publication_area (CharField): Área científica de la publicación.
        created_at (DateTimeField): Fecha y hora de creación del reporte.
    """

    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    doi_original = models.CharField(max_length=255)
    doi_incorrect = models.CharField(max_length=255)
    incorrect_reason = models.TextField()
    metadata_original = models.JSONField(null=True, blank=True)
    metadata_incorrect = models.JSONField(null=True, blank=True)
    citation_contexts = models.JSONField(null=True, blank=True)
    citation_type = models.CharField(
        max_length=50,
        choices=[
            ("not said", "Not Said"),
            ("misinterpretation", "Misinterpretation"),
            ("contextual misattribution", "Contextual Misattribution"),
        ],
    )
    publication_area = models.CharField(
        max_length=4, choices=AREA_CHOICES, verbose_name=_("Área de publicación")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Devuelve una representación legible del reporte."""
        return f"{self.doi_original} citado incorrectamente por {self.doi_incorrect}"


class Comment(models.Model):
    """
    Representa un comentario realizado por un usuario en un reporte de cita incorrecta.

    Permite hilos de conversación mediante una referencia al comentario padre.

    Attributes:
        citation (ForeignKey): El reporte al que pertenece el comentario.
        author (ForeignKey): Usuario que escribió el comentario.
        content (TextField): Contenido textual del comentario.
        created_at (DateTimeField): Fecha de creación.
        parent (ForeignKey): Referencia a un comentario padre para respuestas anidadas.
    """

    citation = models.ForeignKey(
        "IncorrectCitation", on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies"
    )

    def is_reply(self):
        """Determina si el comentario es una respuesta a otro comentario."""
        return self.parent is not None


class Vote(models.Model):
    """
    Representa un voto (positivo o negativo) emitido por un usuario sobre un reporte.

    Attributes:
        user (ForeignKey): Usuario que emite el voto.
        citation (ForeignKey): Reporte votado.
        value (IntegerField): Valor del voto (1 para positivo, -1 para negativo).
    """

    VOTE_CHOICES = (
        (1, "Upvote"),
        (-1, "Downvote"),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    citation = models.ForeignKey(
        IncorrectCitation, on_delete=models.CASCADE, related_name="votes"
    )
    value = models.IntegerField(choices=VOTE_CHOICES)

    class Meta:
        unique_together = ("user", "citation")


class SavedCitation(models.Model):
    """
    Representa la acción de un usuario de guardar un reporte para verlo después.

    Attributes:
        user (ForeignKey): Usuario que guarda el reporte.
        citation (ForeignKey): El reporte guardado.
        created_at (DateTimeField): Fecha en que se guardó.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="saved_citations"
    )
    citation = models.ForeignKey(
        IncorrectCitation, on_delete=models.CASCADE, related_name="saved_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "citation")

    def __str__(self):
        """Representación en cadena de la cita guardada."""
        return f"{self.user.username} -> {self.citation.id}"


class Conversation(models.Model):
    """
    Representa un hilo de conversación privada entre usuarios.

    Attributes:
        participants (ManyToManyField): Usuarios que participan en la conversación.
        created_at (DateTimeField): Fecha de inicio de la conversación.
    """

    participants = models.ManyToManyField(User, related_name="conversations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Devuelve una descripción de la conversación con los participantes."""
        users = ", ".join(self.participants.values_list("username", flat=True))
        return f"Conversación entre {users}"


class Message(models.Model):
    """
    Representa un mensaje individual dentro de una conversación.

    Attributes:
        conversation (ForeignKey): La conversación a la que pertenece el mensaje.
        sender (ForeignKey): Usuario que envió el mensaje.
        content (TextField): Contenido del mensaje.
        created_at (DateTimeField): Fecha de envío.
        is_read (BooleanField): Estado de lectura del mensaje.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        """Representación en cadena del mensaje."""
        return (
            f"Mensaje de {self.sender.username} en conversación {self.conversation_id}"
        )


class Notification(models.Model):
    """
    Representa una notificación para un usuario sobre eventos en la plataforma.

    Attributes:
        user (ForeignKey): Destinatario de la notificación.
        actor (ForeignKey): Usuario que generó la acción (opcional).
        notification_type (CharField): Tipo de evento (comentario, voto, mensaje, sistema).
        title (CharField): Título de la notificación.
        message (CharField): Cuerpo del mensaje de la notificación.
        url (CharField): URL de destino al hacer clic en la notificación.
        is_read (BooleanField): Indica si la notificación ha sido leída.
        created_at (DateTimeField): Fecha de creación.
    """

    class NotificationType(models.TextChoices):
        NEW_COMMENT = "NEW_COMMENT", _("Nuevo comentario")
        NEW_VOTE = "NEW_VOTE", _("Nuevo voto")
        NEW_MESSAGE = "NEW_MESSAGE", _("Nuevo mensaje")
        SYSTEM = "SYSTEM", _("Sistema")

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications_sent",
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """Representación en cadena de la notificación."""
        return f"{self.title} -> {self.user.username}"


# TODO: futuro flujo avanzado de reportes (CitationReport).
# Ahora mismo no se usa en produccion, el flujo real va con IncorrectCitation.
class CitationReport(models.Model):
    """
    Modelo para el flujo avanzado de creación de reportes (Wizard).

    Este modelo está diseñado para almacenar reportes enriquecidos con
    metadatos completos, archivos PDF subidos y análisis detallado,
    aunque actualmente el flujo principal utiliza IncorrectCitation.

    Attributes:
        created_by (ForeignKey): Usuario que inicia el reporte.
        original_doi (CharField): DOI del artículo citado.
        original_metadata (JSONField): Metadatos del artículo citado.
        original_pdf_url (URLField): URL del PDF del artículo citado.
        original_pdf_uploaded (FileField): Archivo PDF subido del artículo citado.
        original_snippet (TextField): Fragmento de texto relevante del original.
        citing_doi (CharField): DOI del artículo que cita.
        citing_metadata (JSONField): Metadatos del artículo que cita.
        citing_pdf_url (URLField): URL del PDF del artículo que cita.
        citing_pdf_uploaded (FileField): Archivo PDF subido del artículo que cita.
        citing_paragraphs (JSONField): Lista de párrafos extraídos del artículo que cita.
        citing_pages (JSONField): Información de paginación.
        error_type (CharField): Tipo de error reportado.
        user_explanation (TextField): Explicación detallada del usuario.
        ai_assessment (JSONField): Resultado de la evaluación automática por IA.
        created_at (DateTimeField): Fecha de creación.
    """

    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL
    )

    # Artículo original (A)
    original_doi = models.CharField(max_length=255)
    original_metadata = models.JSONField(null=True, blank=True)
    original_pdf_url = models.URLField(null=True, blank=True)
    original_pdf_uploaded = models.FileField(
        upload_to="original_pdfs/", null=True, blank=True
    )
    original_snippet = models.TextField(null=True, blank=True)

    # Artículo que cita (B)
    citing_doi = models.CharField(max_length=255)
    citing_metadata = models.JSONField(null=True, blank=True)
    citing_pdf_url = models.URLField(null=True, blank=True)
    citing_pdf_uploaded = models.FileField(
        upload_to="citing_pdfs/", null=True, blank=True
    )

    # Párrafos seleccionados donde aparece la cita
    citing_paragraphs = models.JSONField(null=True, blank=True)  # lista de dicts
    citing_pages = models.JSONField(null=True, blank=True)

    # Datos del reporte
    error_type = models.CharField(max_length=100)
    user_explanation = models.TextField()

    # Resultado IA (relleno en fases siguientes)
    ai_assessment = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Devuelve una descripción breve del reporte."""
        return f"Reporte: {self.original_doi} vs {self.citing_doi}"

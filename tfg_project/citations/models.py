# Modelos de la BD: IncorrectCitation, Comment, Vote, SavedCitation, UserProfile, Notification, Conversation, Message.
"""Models for citations app."""

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserProfile(models.Model):
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
    Representa un reporte de una cita incorrecta.
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
        return f"{self.doi_original} citado incorrectamente por {self.doi_incorrect}"


class Comment(models.Model):
    """
    Representa un comentario en un reporte de cita incorrecta.
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
        return self.parent is not None


class Vote(models.Model):
    """
    Representa un voto (positivo o negativo) de un usuario en un reporte.
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
    Representa una cita incorrecta guardada por un usuario.
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
        return f"{self.user.username} -> {self.citation.id}"


class Conversation(models.Model):
    participants = models.ManyToManyField(User, related_name="conversations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        users = ", ".join(self.participants.values_list("username", flat=True))
        return f"Conversación entre {users}"


class Message(models.Model):
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
        return (
            f"Mensaje de {self.sender.username} en conversación {self.conversation_id}"
        )


class Notification(models.Model):
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
        return f"{self.title} -> {self.user.username}"


# Modelo legacy conservado por compatibilidad de migraciones.
# El producto final crea y muestra reportes con IncorrectCitation.
class CitationReport(models.Model):
    """
    Flujo antiguo de wizard. No forma parte del flujo productivo actual.
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

    # Campo legacy de párrafos seleccionados donde aparecía la cita
    citing_paragraphs = models.JSONField(null=True, blank=True)  # lista de dicts
    citing_pages = models.JSONField(null=True, blank=True)

    # Datos del reporte
    error_type = models.CharField(max_length=100)
    user_explanation = models.TextField()

    # Resultado IA (relleno en fases siguientes)
    ai_assessment = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reporte: {self.original_doi} vs {self.citing_doi}"

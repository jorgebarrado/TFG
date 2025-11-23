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

    # NUEVO
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

    # NUEVO: info visual y redes
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

    # NUEVO: opciones de privacidad
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

    Atributos:
        author (User): El usuario que reportó la cita.
        doi_original (CharField): El DOI del artículo original.
        doi_incorrect (CharField): El DOI del artículo que cita incorrectamente.
        incorrect_reason (TextField): La explicación del error.
        metadata_original (JSONField): Metadatos del artículo original.
        metadata_incorrect (JSONField): Metadatos del artículo que cita incorrectamente.
        citation_type (CharField): El tipo de error en la cita.
        publication_area (CharField): El área de publicación del artículo.
        created_at (DateTimeField): La fecha y hora en que se creó el reporte.
    """

    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    doi_original = models.CharField(max_length=255)  # DOI del artículo original
    doi_incorrect = models.CharField(max_length=255)  # DOI del artículo que cita mal
    incorrect_reason = models.TextField()  # Explicación del por qué está mal
    metadata_original = models.JSONField(null=True, blank=True)
    metadata_incorrect = models.JSONField(null=True, blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha de registro

    def __str__(self):
        """
        Devuelve una representación en cadena del reporte de cita incorrecta.

        Returns:
            str: Una cadena que identifica el reporte.
        """
        return f"{self.doi_original} citado incorrectamente por {self.doi_incorrect}"


class Comment(models.Model):
    """
    Representa un comentario en un reporte de cita incorrecta.

    Atributos:
        citation (IncorrectCitation): El reporte al que pertenece el comentario.
        author (User): El autor del comentario.
        content (TextField): El contenido del comentario.
        created_at (DateTimeField): La fecha y hora de creación del comentario.
        parent (Comment): El comentario padre, si es una respuesta.
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
        """
        Comprueba si el comentario es una respuesta a otro comentario.

        Returns:
            bool: True si el comentario tiene un padre, False en caso contrario.
        """
        return self.parent is not None


class Vote(models.Model):
    """
    Representa un voto (positivo o negativo) de un usuario en un reporte de cita incorrecta.

    Atributos:
        user (User): El usuario que emitió el voto.
        citation (IncorrectCitation): El reporte que se está votando.
        value (IntegerField): El valor del voto (1 para positivo, -1 para negativo).
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
        """
        Configuración del modelo Vote.
        """

        unique_together = ("user", "citation")


class SavedCitation(models.Model):
    """
    Representa una cita incorrecta guardada por un usuario.

    Atributos:
        user (User): El usuario que guardó la cita.
        citation (IncorrectCitation): El reporte de cita incorrecta guardado.
        created_at (DateTimeField): La fecha y hora en que se guardó la cita.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="saved_citations"
    )
    citation = models.ForeignKey(
        "IncorrectCitation", on_delete=models.CASCADE, related_name="saved_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Configuración del modelo SavedCitation.
        """

        unique_together = ("user", "citation")

    def __str__(self):
        """
        Devuelve una representación en cadena de la cita guardada.

        Returns:
            str: Una cadena que indica qué usuario guardó qué cita.
        """
        return f"{self.user.username} → {self.citation.id}"

"""Models for citations app."""

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserProfile(models.Model):
    """
    Extends the default User model with additional profile information.

    Attributes:
        user: A one-to-one link to the default Django User model.
        dblp_url: A URL to the user's DBLP profile.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    dblp_url = models.URLField(blank=True, null=True)

    def __str__(self):
        """
        Returns the username of the associated user.

        Returns:
            str: The username.
        """
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
    Represents a reported incorrect citation.

    Attributes:
        author: The user who reported the incorrect citation.
        doi_original: The DOI of the original article.
        doi_incorrect: The DOI of the article with the incorrect citation.
        incorrect_reason: An explanation of why the citation is incorrect.
        metadata_original: JSON field to store metadata of the original article.
        metadata_incorrect: JSON field to store metadata of the incorrect article.
        citation_type: The type of error in the citation.
        publication_area: The publication area of the article.
        created_at: The date and time when the report was created.
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
        Returns a string representation of the incorrect citation.

        Returns:
            str: A string in the format "doi_original incorrectly cited by
                 doi_incorrect".
        """
        return f"{self.doi_original} citado incorrectamente por {self.doi_incorrect}"


class Comment(models.Model):
    """
    Represents a comment on an incorrect citation report.

    Attributes:
        citation: The incorrect citation report that the comment belongs to.
        author: The user who wrote the comment.
        content: The content of the comment.
        created_at: The date and time when the comment was created.
        parent: The parent comment if this is a reply.
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
        Checks if the comment is a reply to another comment.

        Returns:
            bool: True if the comment is a reply, False otherwise.
        """
        return self.parent is not None


class Vote(models.Model):
    """
    Represents a user's vote on an incorrect citation report.

    Attributes:
        user: The user who voted.
        citation: The incorrect citation report that was voted on.
        value: The value of the vote (1 for upvote, -1 for downvote).
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
        Meta options for the Vote model.

        Ensures that a user can only vote once per citation.
        """

        unique_together = ("user", "citation")


class SavedCitation(models.Model):
    """
    Represents a user's saved incorrect citation report.

    Attributes:
        user: The user who saved the citation.
        citation: The incorrect citation report that was saved.
        created_at: The date and time when the citation was saved.
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
        Meta options for the SavedCitation model.

        Ensures that a user can only save a citation once.
        """

        unique_together = ("user", "citation")

    def __str__(self):
        """
        Returns a string representation of the saved citation.

        Returns:
            str: A string in the format "username → citation_id".
        """
        return f"{self.user.username} → {self.citation.id}"

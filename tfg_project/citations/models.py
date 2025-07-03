from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

AREA_CHOICES = [
    ('ENG', _('Engineering')),
    ('PHY', _('Physical Sciences')),
    ('ENV', _('Environmental Sciences')),
    ('MAT', _('Mathematics')),
    ('CIS', _('Computer and Information Sciences')),
    ('LIF', _('Life Sciences')),
    ('PSY', _('Psychology')),
    ('SOC', _('Social Sciences')),
    ('OTH', _('Other Sciences')),
    ('EDU', _('Education')),
    ('LAW', _('Law')),
    ('HUM', _('Humanities')),
    ('ART', _('Visual and Performing Arts')),
    ('BUS', _('Business and Management')),
    ('COM', _('Communication and Journalism')),
    ('SWK', _('Social Work')),
    ('NON', _('Other Non-Science & Engineering Fields')),
]

class IncorrectCitation(models.Model):
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    doi_original = models.CharField(max_length=255)  # DOI del artículo original
    doi_incorrect = models.CharField(max_length=255)  # DOI del artículo que cita mal
    incorrect_reason = models.TextField()  # Explicación del por qué está mal
    metadata_original  = models.JSONField(null=True, blank=True)
    metadata_incorrect = models.JSONField(null=True, blank=True)
    citation_type = models.CharField(
        max_length=50,
        choices=[
            ("not said", "Not Said"),
            ("misinterpretation", "Misinterpretation"),
            ("contextual misattribution", "Contextual Misattribution")
        ]
    )
    publication_area = models.CharField(
        max_length=4,
        choices=AREA_CHOICES,
        verbose_name=_("Área de publicación")
    )
    created_at = models.DateTimeField(auto_now_add=True)  # Fecha de registro

    def __str__(self):
        return f"{self.doi_original} citado incorrectamente por {self.doi_incorrect}"


class Comment(models.Model):
    citation = models.ForeignKey('IncorrectCitation', on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')

    def is_reply(self):
        return self.parent is not None
    
class Vote(models.Model):
    VOTE_CHOICES = (
        (1, 'Upvote'),
        (-1, 'Downvote'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    citation = models.ForeignKey(IncorrectCitation, on_delete=models.CASCADE, related_name='votes')
    value = models.IntegerField(choices=VOTE_CHOICES)

    class Meta:
        unique_together = ('user', 'citation')

class SavedCitation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_citations')
    citation = models.ForeignKey('IncorrectCitation', on_delete=models.CASCADE, related_name='saved_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'citation')

    def __str__(self):
        return f"{self.user.username} → {self.citation.id}"
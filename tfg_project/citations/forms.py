from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from .models import IncorrectCitation, Comment


class LoginForm(AuthenticationForm):
    """Login con placeholders y clase Bootstrap."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Usuario / email
        self.fields["username"].widget.attrs.update({
            "placeholder": _("Usuario o email"),
            "class": "form-control",
        })

        # Contraseña
        self.fields["password"].widget.attrs.update({
            "placeholder": _("Contraseña"),
            "class": "form-control",
        })


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "password1", "password2")


class IncorrectCitationForm(forms.ModelForm):
    class Meta:
        model = IncorrectCitation
        fields = [
            "doi_original",
            "doi_incorrect",
            "incorrect_reason",
            "citation_type",
            "publication_area",
        ]
        labels = {
            "publication_area": _("Área de publicación"),
        }



class CommentForm(forms.ModelForm):
    parent_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Comment
        fields = ["content", "parent_id"]
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": _("Escribe tu comentario…"),
                }
            )
        }

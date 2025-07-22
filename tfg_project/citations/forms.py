from django import forms
from django.contrib.auth.forms import (
    AuthenticationForm,
    UserCreationForm,
)
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from .models import IncorrectCitation, Comment, UserProfile

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import get_user_model

User = get_user_model()

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['dblp_url']
        widgets = {
            'dblp_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://dblp.org/pid/...'
            })
        }

class RegisterForm(UserCreationForm):
    class Meta:
        model  = User
        fields = ("username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update({
            "placeholder": "Usuario",
            "class": "form-control",
        })
        self.fields["password1"].widget.attrs.update({
            "placeholder": "Contraseña",
            "class": "form-control",
        })
        self.fields["password2"].widget.attrs.update({
            "placeholder": "Confirmar contraseña",
            "class": "form-control",
        })


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "username")
        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nombre"
            }),
            "username": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nombre de usuario"
            }),
        }

class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Igual que PasswordChangeForm pero con Bootstrap.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({
                "class": "form-control",
                "placeholder": field.label
            })

class LoginForm(AuthenticationForm):
    """Login con placeholders y clase Bootstrap."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Usuario / email
        self.fields["username"].widget.attrs.update({
            "placeholder": _("Usuario"),
            "class": "form-control",
        })

        # Contraseña
        self.fields["password"].widget.attrs.update({
            "placeholder": _("Contraseña"),
            "class": "form-control",
        })


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

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.utils.translation import gettext_lazy as _

from .models import Comment, IncorrectCitation, UserProfile

User = get_user_model()


class UserProfileForm(forms.ModelForm):
    """
    Formulario para actualizar la URL de DBLP de un perfil de usuario.
    """

    class Meta:
        model = UserProfile
        fields = ["dblp_url", "avatar", "twitter_url", "linkedin_url", "github_url"]
        widgets = {
            "dblp_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://dblp.org/pid/...",
                }
            ),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "twitter_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://twitter.com/..."}
            ),
            "linkedin_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://linkedin.com/in/...",
                }
            ),
            "github_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://github.com/..."}
            ),
        }


class RegisterForm(UserCreationForm):
    """
    Formulario de registro de nuevos usuarios.
    """

    class Meta:
        model = User
        fields = ("username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update(
            {
                "placeholder": "Usuario",
                "class": "form-control",
            }
        )
        self.fields["password1"].widget.attrs.update(
            {
                "placeholder": "Contraseña",
                "class": "form-control",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "placeholder": "Confirmar contraseña",
                "class": "form-control",
            }
        )


class ProfileForm(forms.ModelForm):
    """
    Formulario para actualizar el nombre y nombre de usuario de un usuario.
    """

    class Meta:
        model = User
        fields = ("first_name", "username")
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nombre"}
            ),
            "username": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Nombre de usuario"}
            ),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """
    Formulario de cambio de contraseña con estilos de Bootstrap.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "form-control", "placeholder": field.label}
            )


class LoginForm(AuthenticationForm):
    """
    Formulario de inicio de sesión con placeholders y estilos de Bootstrap.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Usuario / email
        self.fields["username"].widget.attrs.update(
            {
                "placeholder": _("Usuario"),
                "class": "form-control",
            }
        )

        # Contraseña
        self.fields["password"].widget.attrs.update(
            {
                "placeholder": _("Contraseña"),
                "class": "form-control",
            }
        )


class IncorrectCitationForm(forms.ModelForm):
    """
    Formulario para reportar una cita incorrecta.
    """

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
    """
    Formulario para crear y responder a comentarios.
    """

    parent_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    content = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _("Escribe tu comentario…"),
            }
        ),
        error_messages={
            "required": _("El comentario no puede estar vacío."),
        },
    )

    class Meta:
        model = Comment
        fields = ["content", "parent_id"]
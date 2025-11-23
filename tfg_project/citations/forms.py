from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    UserCreationForm,
)
from django.utils.translation import gettext_lazy as _

from .models import Comment, IncorrectCitation, UserProfile

COUNTRY_CHOICES = [
    ("", _("Selecciona un país")),
    ("Afghanistan", "Afghanistan"),
    ("Albania", "Albania"),
    ("Algeria", "Algeria"),
    ("Andorra", "Andorra"),
    ("Argentina", "Argentina"),
    ("Australia", "Australia"),
    ("Austria", "Austria"),
    ("Belgium", "Belgium"),
    ("Brazil", "Brazil"),
    ("Canada", "Canada"),
    ("Chile", "Chile"),
    ("China", "China"),
    ("Colombia", "Colombia"),
    ("Croatia", "Croatia"),
    ("Czech Republic", "Czech Republic"),
    ("Denmark", "Denmark"),
    ("Estonia", "Estonia"),
    ("Finland", "Finland"),
    ("France", "France"),
    ("Germany", "Germany"),
    ("Greece", "Greece"),
    ("Hungary", "Hungary"),
    ("Iceland", "Iceland"),
    ("India", "India"),
    ("Ireland", "Ireland"),
    ("Israel", "Israel"),
    ("Italy", "Italy"),
    ("Japan", "Japan"),
    ("Latvia", "Latvia"),
    ("Lithuania", "Lithuania"),
    ("Luxembourg", "Luxembourg"),
    ("Mexico", "Mexico"),
    ("Netherlands", "Netherlands"),
    ("New Zealand", "New Zealand"),
    ("Norway", "Norway"),
    ("Poland", "Poland"),
    ("Portugal", "Portugal"),
    ("Romania", "Romania"),
    ("Russia", "Russia"),
    ("Saudi Arabia", "Saudi Arabia"),
    ("Singapore", "Singapore"),
    ("Slovakia", "Slovakia"),
    ("Slovenia", "Slovenia"),
    ("South Africa", "South Africa"),
    ("South Korea", "South Korea"),
    ("Spain", "Spain"),
    ("Sweden", "Sweden"),
    ("Switzerland", "Switzerland"),
    ("Turkey", "Turkey"),
    ("Ukraine", "Ukraine"),
    ("United Arab Emirates", "United Arab Emirates"),
    ("United Kingdom", "United Kingdom"),
    ("United States", "United States"),
    ("Venezuela", "Venezuela"),
    ("Vietnam", "Vietnam"),
]

User = get_user_model()


class UserProfileForm(forms.ModelForm):
    """
    Formulario para actualizar la info extendida del perfil.
    """

    country = forms.ChoiceField(
        choices=COUNTRY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
        label=_("País"),
    )

    class Meta:
        model = UserProfile
        fields = [
            "dblp_url",
            "date_of_birth",
            "country",
            "preferred_language",
            "avatar",
            "bio",
            "twitter_url",
            "github_url",
            "linkedin_url",
            "personal_website",
            "is_public",
            "show_activity",
            "show_social_links",
        ]
        widgets = {
            "dblp_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://dblp.org/pid/...",
                }
            ),
            "date_of_birth": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                }
            ),
            "preferred_language": forms.Select(
                attrs={"class": "form-control"},
            ),
            "bio": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Breve descripción sobre ti…",
                }
            ),
            "twitter_url": forms.URLInput(attrs={"class": "form-control"}),
            "github_url": forms.URLInput(attrs={"class": "form-control"}),
            "linkedin_url": forms.URLInput(attrs={"class": "form-control"}),
            "personal_website": forms.URLInput(attrs={"class": "form-control"}),
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
        # Quitar autofocus del campo antiguo para evitar scroll no deseado
        if "old_password" in self.fields:
            self.fields["old_password"].widget.attrs.pop("autofocus", None)

        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


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

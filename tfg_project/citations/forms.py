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
    A form for updating a user's DBLP profile URL.

    This form is linked to the `UserProfile` model and specifically targets the
    `dblp_url` field, providing a URL input widget with appropriate styling
    and a placeholder.
    """

    class Meta:
        model = UserProfile
        fields = ["dblp_url"]
        widgets = {
            "dblp_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://dblp.org/pid/...",
                }
            )
        }


class RegisterForm(UserCreationForm):
    """
    A user registration form with Bootstrap styling.

    Inherits from Django's `UserCreationForm` and customizes the widgets for
    the username and password fields to include placeholders and Bootstrap's
    'form-control' class.
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
    A form for updating a user's first name and username.

    This form is linked to the `User` model and provides styled text inputs
    for the `first_name` and `username` fields.
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
    A password change form with Bootstrap styling.

    Inherits from `PasswordChangeForm` and applies the 'form-control' class
    and a placeholder to each field for a consistent look and feel with the
    rest of the application.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update(
                {"class": "form-control", "placeholder": field.label}
            )


class LoginForm(AuthenticationForm):
    """
    An authentication form with Bootstrap styling and placeholders.

    Inherits from `AuthenticationForm` and customizes the username and
    password fields with placeholders and the 'form-control' class.
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
    A form for reporting incorrect citations.

    This form is linked to the `IncorrectCitation` model and includes fields
    for the original and incorrect DOIs, the reason for the error, citation
    type, and publication area.
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
    A form for creating and replying to comments.

    This form is linked to the `Comment` model and includes a `content`
    textarea and a hidden `parent_id` field to support threaded comments.
    """

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

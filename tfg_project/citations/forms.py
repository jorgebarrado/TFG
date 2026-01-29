"""Formularios de la aplicación citations."""

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
    """Formulario para crear o actualizar el perfil de usuario extendido.

    Permite editar campos como país, biografía, enlaces sociales y preferencias.
    Utiliza widgets personalizados para estilizado con Bootstrap.
    """

    country = forms.ChoiceField(
        choices=COUNTRY_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control", "data-select2": "country"}),
        label=_("País"),
    )

    class Meta:
        model = UserProfile
        fields = [
            "date_of_birth",
            "country",
            "preferred_language",
            "avatar",
            "bio",
            "dblp_url",
            "research_area",
            "profession",
            "institution",
            "contact_email",
            "social_link_1",
            "social_link_2",
            "social_link_3",
            "social_link_4",
            "notify_comments_on_my_reports",
            "notify_comments_on_followed",
            "notify_votes_on_my_reports",
            "notify_news_and_updates",
            "is_public",
            "show_activity",
            "show_social_links",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "preferred_language": forms.Select(attrs={"class": "form-control"}),
            "bio": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": _("Breve descripción sobre ti…"),
                }
            ),
            "dblp_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://dblp.org/pid/...",
                }
            ),
            "research_area": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ej. Computer Science, Quantum Computing…"),
                }
            ),
            "profession": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ej. PhD Student, Researcher, QA Engineer…"),
                }
            ),
            "institution": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Ej. UPM, CSIC, CERN, Google Research…"),
                }
            ),
            "contact_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Correo visible para otros usuarios"),
                }
            ),
            "social_link_1": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Enlace a perfil social 1"),
                }
            ),
            "social_link_2": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Enlace a perfil social 2"),
                }
            ),
            "social_link_3": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Enlace a perfil social 3"),
                }
            ),
            "social_link_4": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": _("Enlace a perfil social 4"),
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario y añade clases CSS a los campos checkbox.

        Args:
            *args: Argumentos posicionales variables.
            **kwargs: Argumentos de palabras clave variables.
        """
        super().__init__(*args, **kwargs)
        checkbox_fields = [
            "notify_comments_on_my_reports",
            "notify_comments_on_followed",
            "notify_votes_on_my_reports",
            "notify_news_and_updates",
            "is_public",
            "show_activity",
            "show_social_links",
        ]
        for name in checkbox_fields:
            if name in self.fields:
                self.fields[name].widget.attrs.setdefault("class", "form-check-input")


class DBLPUrlForm(forms.ModelForm):
    """Formulario reducido para actualizar únicamente la URL de DBLP."""

    dblp_url = forms.URLField(
        required=False,
        widget=forms.URLInput(
            attrs={
                "class": "form-control form-control-sm",
                "placeholder": "https://dblp.org/pid/...",
            }
        ),
        label=_("DBLP"),
    )

    class Meta:
        model = UserProfile
        fields = ["dblp_url"]


class RegisterForm(UserCreationForm):
    """Formulario para el registro de nuevos usuarios en el sistema.

    Extiende UserCreationForm de Django para usar el modelo User y
    añadir estilos Bootstrap a los campos.
    """

    class Meta:
        model = User
        fields = ("username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario de registro con estilos personalizados.

        Args:
            *args: Argumentos posicionales variables.
            **kwargs: Argumentos de palabras clave variables.
        """
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
    """Formulario para actualizar información básica del usuario (User model).

    Permite cambiar el nombre completo y el nombre de usuario.
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
    """Formulario de cambio de contraseña personalizado con estilos Bootstrap.

    Extiende PasswordChangeForm para mejorar la presentación.
    """

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario de cambio de contraseña.

        Elimina el autofocus del campo de contraseña antigua y añade clases CSS.

        Args:
            *args: Argumentos posicionales variables.
            **kwargs: Argumentos de palabras clave variables.
        """
        super().__init__(*args, **kwargs)
        # Quitar autofocus del campo antiguo para evitar scroll no deseado
        if "old_password" in self.fields:
            self.fields["old_password"].widget.attrs.pop("autofocus", None)

        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class LoginForm(AuthenticationForm):
    """Formulario de inicio de sesión personalizado con placeholders y estilos.

    Extiende AuthenticationForm para adaptar la interfaz de usuario.
    """

    def __init__(self, *args, **kwargs):
        """Inicializa el formulario de login.

        Añade placeholders y clases CSS a los campos de usuario y contraseña.

        Args:
            *args: Argumentos posicionales variables.
            **kwargs: Argumentos de palabras clave variables.
        """
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
    """Formulario para reportar una nueva cita incorrecta.

    Utilizado para crear instancias de IncorrectCitation.
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
    """Formulario para publicar comentarios o respuestas en reportes.

    Incluye un campo oculto para el ID del comentario padre en caso de respuesta.
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


class MessageForm(forms.Form):
    """Formulario simple para enviar mensajes privados en una conversación."""

    content = forms.CharField(
        label="",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": _("Escribe un mensaje…"),
            }
        ),
        error_messages={"required": _("El mensaje no puede estar vacío.")},
    )

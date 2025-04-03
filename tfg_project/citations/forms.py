from django import forms
from .models import IncorrectCitation
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User

class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'password1', 'password2']

class LoginForm(AuthenticationForm):
    username = forms.CharField(label='Usuario', widget=forms.TextInput(attrs={'autofocus': True}))
    password = forms.CharField(label='Contraseña', strip=False, widget=forms.PasswordInput)
class IncorrectCitationForm(forms.ModelForm):
    class Meta:
        model = IncorrectCitation
        fields = ['doi_original', 'doi_incorrect', 'incorrect_reason', 'citation_type']
        widgets = {
            'incorrect_reason': forms.Textarea(attrs={'rows': 4}),
        }

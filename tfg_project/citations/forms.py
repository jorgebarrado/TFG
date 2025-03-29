from django import forms
from .models import IncorrectCitation

class IncorrectCitationForm(forms.ModelForm):
    class Meta:
        model = IncorrectCitation
        fields = ['doi_original', 'doi_incorrect', 'incorrect_reason', 'citation_type']
        widgets = {
            'incorrect_reason': forms.Textarea(attrs={'rows': 4}),
        }

from django.shortcuts import render, redirect
from .forms import IncorrectCitationForm
import requests
from django.http import JsonResponse

from django.urls import reverse
from urllib.parse import urlencode

def submit_incorrect_citation(request):
    if request.method == 'POST':
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            saved = form.save()
            # Redirige incluyendo el DOI original en la URL
            params = urlencode({'doi': saved.doi_original})
            return redirect(f"{reverse('citation_submitted')}?{params}")
    else:
        form = IncorrectCitationForm()
    return render(request, 'citations/submit_citation.html', {'form': form})

def citation_submitted(request):
    return render(request, 'citations/citation_submitted.html')

def get_all_metadata_from_doi(request):
    doi = request.GET.get('doi')
    if not doi:
        return JsonResponse({'error': 'No DOI provided'}, status=400)

    url = f'https://api.crossref.org/works/{doi}'
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()['message']
        return JsonResponse(data, safe=False)
    else:
        return JsonResponse({'error': 'DOI not found or invalid'}, status=404)
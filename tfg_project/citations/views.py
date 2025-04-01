from django.shortcuts import render, redirect
from .forms import IncorrectCitationForm
import requests
from django.http import JsonResponse
from django.urls import reverse
from urllib.parse import urlencode
from .models import IncorrectCitation
from django.contrib.auth import login, authenticate
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm


# Landing page
def home(request):
    return render(request, 'citations/home.html', {
        'register_form': UserCreationForm(),
        'login_form': AuthenticationForm(),
    })

def login_user(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('home')
        else:
            return render(request, 'citations/home.html', {
                'login_form': form,
                'register_form': UserCreationForm(),  # igual que el registro
            })
    return redirect('home')

def register_user(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # login automático
            return redirect('home')
        else:
            return render(request, 'citations/home.html', {
                'register_form': form,
                'login_form': AuthenticationForm(),  # para que no pete el login
            })
    return redirect('home')

# Vista AJAX para guardar el formulario desde el modal
def ajax_submit_citation(request):
    if request.method == 'POST':
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            form.save()
            return JsonResponse({'success': True})
        return JsonResponse({'errors': form.errors}, status=400)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

def citation_list(request):
    citations = IncorrectCitation.objects.all().order_by('-created_at')
    return render(request, 'citations/citation_list.html', {'citations': citations})

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
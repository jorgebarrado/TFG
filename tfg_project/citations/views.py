from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from urllib.parse import urlencode
import requests

from django.contrib.auth import authenticate, login, logout
from .forms import IncorrectCitationForm, LoginForm, RegisterForm
from .models import IncorrectCitation

# Landing page
def home(request):
    return render(request, 'citations/home.html')

# Vista de login con soporte para `next`
def login_view(request):
    next_url = request.POST.get('next', request.GET.get('next', '/'))
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(next_url or '/')
    else:
        form = LoginForm(request)
    return render(request, 'citations/home.html', {
        'login_form': form,
        'register_form': RegisterForm(),
        'show_login_modal': True
    })

# Vista de registro con soporte para `next`
def register_view(request):
    next_url = request.POST.get('next', request.GET.get('next', '/'))
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(next_url or '/')
    else:
        form = RegisterForm()
    return render(request, 'citations/home.html', {
        'register_form': form,
        'login_form': LoginForm(request),
        'show_register_modal': True
    })

# Logout
def logout_view(request):
    logout(request)
    return redirect(request.GET.get('next', '/'))

# Vista AJAX para guardar el reporte
def ajax_submit_citation(request):
    if request.method == 'POST':
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            citation = form.save(commit=False)
            if request.user.is_authenticated:
                citation.author = request.user
            citation.save()
            return JsonResponse({'success': True})
        return JsonResponse({'errors': form.errors}, status=400)
    return JsonResponse({'error': 'Método no permitido'}, status=405)

# Lista de citas reportadas
def citation_list(request):
    citations = IncorrectCitation.objects.all().order_by('-created_at')
    return render(request, 'citations/citation_list.html', {'citations': citations})

# Página del reporte individual
def citation_detail(request, pk):
    citation = get_object_or_404(IncorrectCitation, pk=pk)
    return render(request, 'citations/citation_detail.html', {'citation': citation})

# Vista alternativa (usada antes)
def submit_incorrect_citation(request):
    if request.method == 'POST':
        form = IncorrectCitationForm(request.POST)
        if form.is_valid():
            citation = form.save(commit=False)
            if request.user.is_authenticated:
                citation.author = request.user
            citation.save()
            return redirect('citation_submitted')
    else:
        form = IncorrectCitationForm()
    return render(request, 'citations/submit_citation.html', {'form': form})

# Página de confirmación tras reporte
def citation_submitted(request):
    return render(request, 'citations/citation_submitted.html')

# Obtener metadatos del DOI
def get_all_metadata_from_doi(request):
    doi = request.GET.get('doi')
    if not doi:
        return JsonResponse({'error': 'No DOI provided'}, status=400)

    url = f'https://api.crossref.org/works/{doi}'
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json().get('message', {})
        return JsonResponse(data, safe=False)
    return JsonResponse({'error': 'DOI not found or invalid'}, status=404)

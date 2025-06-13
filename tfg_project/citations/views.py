from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from urllib.parse import urlencode
import requests
from django.contrib.auth import authenticate, login, logout
from .forms import IncorrectCitationForm, LoginForm, RegisterForm
from .models import IncorrectCitation
from .forms import CommentForm
from .models import Comment
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from .models import Comment  # o el nombre de tu modelo
from django.shortcuts import render, get_object_or_404, redirect
from .models import IncorrectCitation, Comment
from .forms import CommentForm
from django.shortcuts import get_object_or_404
from .models import IncorrectCitation
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Vote, IncorrectCitation
from .models import SavedCitation
from django.contrib.auth.decorators import login_required
from .models import IncorrectCitation, Comment, SavedCitation
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.shortcuts import redirect
from django.shortcuts import redirect
from django.conf import settings
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.google.provider import GoogleProvider
from urllib.parse import urlencode
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import login
from citations.forms import LoginForm

def login_view(request):
    next_url = request.POST.get("next", request.GET.get("next", "/"))

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()                 
            login(request, user)
            return redirect(next_url or "/")
    else:
        form = LoginForm(request)

    return render(
        request,
        "citations/home.html",
        {
            "login_form": form,
            "register_form": RegisterForm(),
            "show_login_modal": True,
        },
    )

User = get_user_model()

@login_required
def account_settings(request):
    user = request.user

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        username = request.POST.get('username', '').strip()

        if not first_name or not username:
            messages.error(request, "Rellena ambos campos.")
        elif User.objects.filter(username=username).exclude(pk=user.pk).exists():
            messages.error(request, "Ese nombre de usuario ya existe.")
        else:
            user.first_name = first_name
            user.username = username
            user.save()
            messages.success(request, "Perfil actualizado correctamente.")
            return redirect('account_settings')

    return render(request, 'citations/account_settings.html', {'user': user})

def google_direct_login(request):
    app = SocialApp.objects.get(provider='google')

    base_url = "https://accounts.google.com/o/oauth2/auth"
    callback_uri = request.build_absolute_uri('/accounts/google/login/callback/')

    params = {
        "client_id": app.client_id,
        "redirect_uri": callback_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "consent",
    }

    url = f"{base_url}?{urlencode(params)}"
    return redirect(url)

# Landing page
def home(request):
    return render(request, 'citations/home.html')

# Vista de login con soporte para `next`
def login_view(request):
    next_url = request.POST.get('next', request.GET.get('next', '/'))
    if request.method == 'POST':
        form = LoginForm(request=request, data=request.POST)
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
            return redirect(next_url or '/')  # Redirección limpia
        else:
            return render(request, 'citations/home.html', {
                'register_form': form,
                'login_form': LoginForm(),
                'show_register_modal': True  # Solo si hay errores
            })
    else:
        form = RegisterForm()
        return render(request, 'citations/home.html', {
            'register_form': form,
            'login_form': LoginForm(),
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
    comments = Comment.objects.filter(citation=citation).select_related('author', 'parent').order_by('created_at')
    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()

    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.citation = citation
            comment.author = request.user
            parent_id = request.POST.get('parent_id')
            if parent_id:
                comment.parent_id = int(parent_id)
            comment.save()
            return redirect('citation_detail', pk=pk)
    else:
        form = CommentForm()

    user_vote = None
    if request.user.is_authenticated:
        vote = Vote.objects.filter(citation=citation, user=request.user).first()
        if vote:
            user_vote = vote.value

    is_saved = False
    if request.user.is_authenticated:
        is_saved = SavedCitation.objects.filter(user=request.user, citation=citation).exists()

    return render(request, 'citations/citation_detail.html', {
        'citation': citation,
        'comment_form': form,
        'comments': comments,
        'upvotes': upvotes,
        'downvotes': downvotes,
        'user_vote': user_vote,
        'is_saved': is_saved,
    })

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

@login_required
def delete_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    if request.user == comment.author or request.user.is_superuser:
        comment.delete()
        messages.success(request, "Comentario eliminado correctamente.")
    else:
        return HttpResponseForbidden("No tienes permiso para eliminar este comentario.")
    return redirect('citation_detail', pk=comment.citation.pk)

@require_POST
def vote_view(request):
    citation_id = request.POST.get('citation_id')
    vote_value = int(request.POST.get('vote'))  # 1 o -1

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'not_authenticated'}, status=403)

    citation = IncorrectCitation.objects.get(id=citation_id)

    # Busca si el usuario ya votó
    existing_vote = Vote.objects.filter(citation=citation, user=request.user).first()

    if existing_vote:
        if existing_vote.value == vote_value:
            existing_vote.delete()  # desmarcar voto
        else:
            existing_vote.value = vote_value
            existing_vote.save()
    else:
        Vote.objects.create(citation=citation, user=request.user, value=vote_value)

    # Conteos actualizados
    upvotes = citation.votes.filter(value=1).count()
    downvotes = citation.votes.filter(value=-1).count()

    # Obtener el voto actual del usuario (puede ser None si lo borró)
    current_vote = Vote.objects.filter(citation=citation, user=request.user).first()
    user_vote = current_vote.value if current_vote else 0

    return JsonResponse({
        'upvotes': upvotes,
        'downvotes': downvotes,
        'user_vote': user_vote,  # Esto es lo que faltaba
    })

@require_POST
@login_required
def toggle_saved(request):
    citation_id = request.POST.get('citation_id')
    citation = get_object_or_404(IncorrectCitation, id=citation_id)

    saved, created = SavedCitation.objects.get_or_create(user=request.user, citation=citation)

    if not created:
        saved.delete()
        is_saved = False
    else:
        is_saved = True

    return JsonResponse({'is_saved': is_saved})

@login_required
def my_reports(request):
    reports = IncorrectCitation.objects.filter(author=request.user).order_by('-created_at')
    return render(request, 'citations/my_reports.html', {'reports': reports})

@login_required
def my_comments(request):
    comments = Comment.objects.filter(author=request.user).select_related('citation').order_by('-created_at')
    return render(request, 'citations/my_comments.html', {'comments': comments})

@login_required
def my_saved(request):
    saved = SavedCitation.objects.filter(user=request.user).select_related('citation').order_by('-created_at')
    return render(request, 'citations/my_saved.html', {'saved': saved})
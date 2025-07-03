from urllib.parse import urlencode
import requests
from django.views.decorators.http import require_POST
from django.shortcuts import (
    render,
    redirect,
    get_object_or_404,
)
from django.http import (
    JsonResponse,
    HttpResponseForbidden,
)
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    get_user_model,
)
from django.contrib.auth.decorators import login_required

# Formularios propios
from .forms import (
    IncorrectCitationForm,
    LoginForm,
    RegisterForm,
    CommentForm,
)

# Modelos propios
from .models import (
    IncorrectCitation,
    AREA_CHOICES,
    Comment,
    Vote,
    SavedCitation,
)

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from citations.forms import ProfileForm, CustomPasswordChangeForm
from django.db.models import Q, Value
from django.db.models.functions import ExtractYear

def citation_suggest(request):
    term = request.GET.get("term","")
    qs = IncorrectCitation.objects.filter(
        Q(doi_original__icontains=term) |
        Q(metadata__title__icontains=term)
    ).values("doi_original","metadata__title")[:5]

    return JsonResponse(list(qs), safe=False)

def fetch_doi_metadata(request):
    doi = request.GET.get("doi")
    if not doi:
        return JsonResponse({"error": "No DOI"}, status=400)

    url = f"https://api.crossref.org/works/{doi}"
    r = requests.get(url, timeout=6)
    if r.status_code == 200:
        return JsonResponse(r.json()["message"])
    return JsonResponse({"error": "Not found"}, status=404)

def citation_list(request):
    qs = IncorrectCitation.objects.all().order_by("-created_at")

    # -------------------- búsqueda libre --------------------
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(doi_original__icontains=q) |
            Q(doi_incorrect__icontains=q) |
            Q(metadata__title__icontains=q) |
            Q(metadata__authors__icontains=q)
        )

    area  = request.GET.get("area")
    ctype = request.GET.get("ctype")
    year  = request.GET.get("year")

    if area:
        qs = qs.filter(publication_area=area)
    if ctype:
        qs = qs.filter(citation_type=ctype)
    if year and year.isdigit():
        qs = qs.filter(created_at__year=year)

    areas = AREA_CHOICES
    citation_types = IncorrectCitation._meta.get_field("citation_type").choices
    years = (IncorrectCitation.objects
             .annotate(y=ExtractYear("created_at"))
             .values_list("y", flat=True)
             .distinct()
             .order_by("-y"))

    context = {
        "citations": qs,
        "areas": areas,
        "citation_types": citation_types,
        "years": years,
    }
    return render(request, "citations/citation_list.html", context)

User = get_user_model()

@login_required
def account_settings(request):
    user = request.user

    profile_form = ProfileForm(instance=user)
    pwd_form      = CustomPasswordChangeForm(user)

    if request.method == "POST":
        if "save_profile" in request.POST:
            profile_form = ProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Perfil actualizado.")
                return redirect("account_settings")

        elif "change_password" in request.POST:
            pwd_form = CustomPasswordChangeForm(user, request.POST)
            if pwd_form.is_valid():
                pwd_form.save()
                update_session_auth_hash(request, pwd_form.user)  # ← sigues logueado
                messages.success(request, "Contraseña cambiada.")
                return redirect("account_settings")

    context = {
        "profile_form": profile_form,
        "pwd_form": pwd_form,
    }
    return render(request, "citations/account_settings.html", context)


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



def register_view(request):
    next_url = request.POST.get("next", request.GET.get("next", "/"))

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            # ① Crear el usuario en la BD
            user = form.save()

            # ② Autenticarlo de nuevo con las credenciales recién creadas
            auth_user = authenticate(
                request,
                username=user.username,
                password=form.cleaned_data["password1"],
            )

            # ③ Iniciar sesión (login) con el backend correcto
            if auth_user is not None:
                login(request, auth_user)

            return redirect(next_url or "/")
    else:
        form = RegisterForm()

    return render(
        request,
        "citations/home.html",
        {
            "register_form": form,
            "login_form": LoginForm(),
            "show_register_modal": True,
        },
    )
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

@require_POST
def register_ajax(request):
    """
    Recibe el formulario de registro vía fetch/AJAX
    y devuelve JSON en lugar de redirección.
    """
    form = RegisterForm(request.POST)
    if form.is_valid():
        user = form.save()
        auth_user = authenticate(
            request,
            username=user.username,
            password=form.cleaned_data["password1"],
        )
        if auth_user:
            login(request, auth_user)
        return JsonResponse({"success": True})

    errors = {field: errs.get_json_data() for field, errs in form.errors.items()}
    return JsonResponse({"success": False, "errors": errors}, status=400)


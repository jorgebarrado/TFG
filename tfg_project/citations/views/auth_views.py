"""Views for handling user authentication (login, logout, registration)."""

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render

from ..forms import LoginForm, RegisterForm


def login_view(request):
    """
    Gestiona el inicio de sesión de los usuarios.

    Si la solicitud es POST, valida el formulario y autentica al usuario.
    Si es GET, muestra el formulario de login.

    Args:
        request: HttpRequest.

    Returns:
        HttpResponse: Renderiza 'citations/home.html' con el formulario o redirige.
    """
    next_url = request.POST.get("next", request.GET.get("next", "/"))
    if request.method == "POST":
        form = LoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect(next_url or "/")
    else:
        form = LoginForm(request)
    return render(
        request,
        "citations/home.html",
        {"login_form": form, "register_form": RegisterForm(), "show_login_modal": True},
    )


def register_view(request):
    """
    Gestiona el registro de nuevos usuarios.

    Si el registro es exitoso, autentica y loguea automáticamente al usuario.

    Args:
        request: HttpRequest.

    Returns:
        HttpResponse: Renderiza 'citations/home.html' con el formulario o redirige.
    """
    next_url = request.POST.get("next", request.GET.get("next", "/"))
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_user = authenticate(
                request,
                username=user.username,
                password=form.cleaned_data["password1"],
            )
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


def logout_view(request):
    """
    Cierra la sesión del usuario actual.

    Args:
        request: HttpRequest.

    Returns:
        HttpResponseRedirect: Redirige a la página de inicio o 'next'.
    """
    logout(request)
    return redirect(request.GET.get("next", "/"))

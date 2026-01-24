"""Vistas para manejar la autenticación de usuarios (login, logout, registro)."""

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render

from ..forms import LoginForm, RegisterForm


def login_view(request):
    """Gestiona el inicio de sesión de los usuarios.

    Muestra el formulario de login o procesa el envío del mismo.
    Si el login es exitoso, redirige a la URL 'next' o al inicio.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponse: La página renderizada o una redirección.
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
    """Gestiona el registro de nuevos usuarios.

    Muestra el formulario de registro o procesa el envío del mismo.
    Si el registro es exitoso, loguea al usuario automáticamente y redirige.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponse: La página renderizada o una redirección.
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
    """Cierra la sesión del usuario actual.

    Args:
        request: Objeto HttpRequest.

    Returns:
        HttpResponse: Redirección a la página de inicio o 'next'.
    """
    logout(request)
    return redirect(request.GET.get("next", "/"))

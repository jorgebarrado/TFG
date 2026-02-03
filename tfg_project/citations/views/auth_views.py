"""Views for handling user authentication (login, logout, registration)."""

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render

from ..forms import LoginForm, RegisterForm


def login_view(request):
    """Gestiona el inicio de sesión de los usuarios.

    Muestra el formulario de login y procesa la autenticación. Si es exitosa,
    redirige a la URL solicitada o al inicio.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La página con el formulario o una redirección.
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

    Muestra el formulario de registro y crea el usuario si los datos son válidos.
    Autentica automáticamente al usuario tras el registro.

    Args:
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: La página con el formulario o una redirección al inicio.
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
        request (HttpRequest): La solicitud HTTP.

    Returns:
        HttpResponse: Redirección a la página de inicio o a la URL especificada en 'next'.
    """
    logout(request)
    return redirect(request.GET.get("next", "/"))

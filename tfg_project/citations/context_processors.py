from .forms import LoginForm, RegisterForm


def login_register_forms(request):
    return {
        'login_form': LoginForm(),
        'register_form': RegisterForm(),
    }

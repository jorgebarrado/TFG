from .forms import LoginForm, RegisterForm


def login_register_forms(request):
    """
    Provides login and registration forms to the template context.

    This context processor makes the login and registration forms available
    globally in all templates, so they can be rendered on any page without

    Args:
        request: The HttpRequest object.

    Returns:
        A dictionary containing instances of `LoginForm` and `RegisterForm`.
    """
    return {
        "login_form": LoginForm(),
        "register_form": RegisterForm(),
    }

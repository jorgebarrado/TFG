from django import template

register = template.Library()

@register.filter
def count_upvotes(votes):
    """Cuenta el número de votos positivos (valor == 1) en una lista de votos.

    Args:
        votes (iterable): Lista o QuerySet de objetos Vote.

    Returns:
        int: Cantidad de votos positivos.
    """
    return sum(1 for vote in votes if vote.value == 1)

@register.filter
def count_downvotes(votes):
    """Cuenta el número de votos negativos (valor == -1) en una lista de votos.

    Args:
        votes (iterable): Lista o QuerySet de objetos Vote.

    Returns:
        int: Cantidad de votos negativos.
    """
    return sum(1 for vote in votes if vote.value == -1)

@register.filter
def user_vote(votes, user):
    """Devuelve el valor del voto del usuario en una lista de votos, si existe.

    Args:
        votes (iterable): Lista o QuerySet de objetos Vote.
        user (User): El usuario actual.

    Returns:
        int: El valor del voto (1 o -1), o 0 si no ha votado o no está autenticado.
    """
    if not user.is_authenticated:
        return 0
    for vote in votes:
        if vote.user == user:
            return vote.value
    return 0

@register.filter
def is_saved_by(citation, user):
    """Verifica si un reporte de cita ha sido guardado por el usuario.

    Args:
        citation (IncorrectCitation): El reporte de cita.
        user (User): El usuario actual.

    Returns:
        bool: True si está guardado, False en caso contrario.
    """
    if not user.is_authenticated:
        return False
    return citation.saved_by.filter(user=user).exists()

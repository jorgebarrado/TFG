from django import template

register = template.Library()

@register.filter
def count_upvotes(votes):
    """Cuenta el número de votos positivos."""
    return sum(1 for vote in votes if vote.value == 1)

@register.filter
def count_downvotes(votes):
    """Cuenta el número de votos negativos."""
    return sum(1 for vote in votes if vote.value == -1)

@register.filter
def user_vote(votes, user):
    """
    Devuelve el valor del voto del usuario en una lista de votos.

    Args:
        votes (list): Lista de objetos Vote.
        user (User): El usuario actual.

    Returns:
        int: 1, -1 o 0 si no ha votado.
    """
    if not user.is_authenticated:
        return 0
    for vote in votes:
        if vote.user == user:
            return vote.value
    return 0

@register.filter
def is_saved_by(citation, user):
    """
    Verifica si una cita está guardada por el usuario.

    Args:
        citation (IncorrectCitation): La cita a verificar.
        user (User): El usuario actual.

    Returns:
        bool: True si está guardada, False de lo contrario.
    """
    if not user.is_authenticated:
        return False
    return citation.saved_by.filter(user=user).exists()

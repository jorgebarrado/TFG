from django import template

register = template.Library()

@register.filter
def count_upvotes(votes):
    """Cuenta el número de votos positivos en una lista de votos.

    Args:
        votes: Lista de objetos Vote.

    Returns:
        int: Número de votos positivos.
    """
    return sum(1 for vote in votes if vote.value == 1)

@register.filter
def count_downvotes(votes):
    """Cuenta el número de votos negativos en una lista de votos.

    Args:
        votes: Lista de objetos Vote.

    Returns:
        int: Número de votos negativos.
    """
    return sum(1 for vote in votes if vote.value == -1)

@register.filter
def user_vote(votes, user):
    """Obtiene el valor del voto de un usuario específico en una lista de votos.

    Args:
        votes: Lista de objetos Vote.
        user: El usuario actual.

    Returns:
        int: 1 si positivo, -1 si negativo, 0 si no ha votado.
    """
    if not user.is_authenticated:
        return 0
    for vote in votes:
        if vote.user == user:
            return vote.value
    return 0

@register.filter
def is_saved_by(citation, user):
    """Verifica si una cita ha sido guardada por el usuario.

    Args:
        citation: El objeto IncorrectCitation.
        user: El usuario actual.

    Returns:
        bool: True si está guardada, False en caso contrario.
    """
    if not user.is_authenticated:
        return False
    return citation.saved_by.filter(user=user).exists()

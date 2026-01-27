from django import template

register = template.Library()

@register.filter
def count_upvotes(votes):
    """Cuenta los votos positivos en una lista de votos."""
    return sum(1 for vote in votes if vote.value == 1)

@register.filter
def count_downvotes(votes):
    """Cuenta los votos negativos en una lista de votos."""
    return sum(1 for vote in votes if vote.value == -1)

@register.filter
def user_vote(votes, user):
    """Devuelve el valor del voto del usuario actual (1, -1 o 0)."""
    if not user.is_authenticated:
        return 0
    for vote in votes:
        if vote.user == user:
            return vote.value
    return 0

@register.filter
def is_saved_by(citation, user):
    """Devuelve True si el usuario ha guardado esta cita."""
    if not user.is_authenticated:
        return False
    return citation.saved_by.filter(user=user).exists()

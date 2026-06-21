# Filtros de plantilla personalizados: conteo de votos positivos/negativos y otras utilidades para templates Django.
from django import template

register = template.Library()


@register.filter
def count_upvotes(votes):
    return sum(1 for vote in votes if vote.value == 1)


@register.filter
def count_downvotes(votes):
    return sum(1 for vote in votes if vote.value == -1)


@register.filter
def user_vote(votes, user):
    if not user.is_authenticated:
        return 0
    for vote in votes:
        if vote.user == user:
            return vote.value
    return 0


@register.filter
def is_saved_by(citation, user):
    if not user.is_authenticated:
        return False
    return citation.saved_by.filter(user=user).exists()

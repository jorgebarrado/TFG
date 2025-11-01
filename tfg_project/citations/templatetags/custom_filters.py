from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, None) if isinstance(dictionary, dict) else None


@register.filter
def get_index(value, index):
    try:
        return value[index]
    except Exception:
        return None

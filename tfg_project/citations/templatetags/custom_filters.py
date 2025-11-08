from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Custom template filter to get an item from a dictionary.

    This filter allows accessing a dictionary value by its key within a Django
    template. It returns None if the key is not found or if the provided
    'dictionary' is not actually a dictionary.

    Args:
        dictionary (dict): The dictionary to access.
        key: The key to look up.

    Returns:
        The value associated with the key, or None if not found.
    """
    return dictionary.get(key, None) if isinstance(dictionary, dict) else None


@register.filter
def get_index(value, index):
    """
    Custom template filter to get an item from a list by its index.

    This filter allows accessing a list element by its index within a Django
    template. It returns None if the index is out of bounds or if any other
    error occurs.

    Args:
        value (list): The list to access.
        index (int): The index of the item to retrieve.

    Returns:
        The item at the specified index, or None on error.
    """
    try:
        return value[index]
    except Exception:
        return None

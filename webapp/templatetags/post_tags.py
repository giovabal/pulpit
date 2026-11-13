from django import template

register = template.Library()


@register.filter
def tag_ancestry(tag, tree) -> str:
    """``"Hand gestures › "`` for the sub-tag ``Nazi salute``; ``""`` for a top-level tag.

    ``tree`` is the request's lazily loaded ``TAG_TREE`` (``webapp.context_processors``):
    one query for every chip on the page, and none on a page without chips.
    """
    if tag is None or tree is None:
        return ""
    return tree.ancestry(tag.pk)

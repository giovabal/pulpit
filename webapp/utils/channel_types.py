from django.conf import settings
from django.db.models import Q

VALID_CHANNEL_TYPES = {"CHANNEL", "GROUP", "USER"}


def channel_type_filter() -> Q:
    """Return a Q filter matching the channel types enabled in CHANNEL_TYPES."""
    types = set(settings.CHANNEL_TYPES)
    q = Q(pk__in=[])  # start empty; OR in each enabled type
    if "CHANNEL" in types:
        # Broadcast channels (and unknowns with all flags False)
        q |= Q(is_user_account=False, megagroup=False, gigagroup=False)
    if "GROUP" in types:
        q |= Q(is_user_account=False, megagroup=True) | Q(is_user_account=False, gigagroup=True)
    if "USER" in types:
        q |= Q(is_user_account=True)
    return q

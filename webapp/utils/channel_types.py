from django.db.models import Q

VALID_CHANNEL_TYPES = {"CHANNEL", "GROUP", "USER"}


def channel_type_filter(channel_types: list[str] | None = None) -> Q:
    """Return a Q filter matching the given channel types. Defaults to CHANNEL (broadcast channels only)."""
    types = set(channel_types) if channel_types is not None else {"CHANNEL"}
    q = Q(pk__in=[])  # start empty; OR in each enabled type
    if "CHANNEL" in types:
        # Broadcast channels (and unknowns with all flags False)
        q |= Q(is_user_account=False, megagroup=False, gigagroup=False)
    if "GROUP" in types:
        q |= Q(is_user_account=False, megagroup=True) | Q(is_user_account=False, gigagroup=True)
    if "USER" in types:
        q |= Q(is_user_account=True)
    return q

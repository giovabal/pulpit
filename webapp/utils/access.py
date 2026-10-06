"""Who may see and edit analyst annotations (message tags) in the live web UI.

Writes follow the backoffice rule (:class:`backoffice.api.permissions.BackofficePermission`):
anyone when ``WEB_ACCESS=ALL``, staff otherwise. Reads are wider — any logged-in
user — but never anonymous visitors of an ``OPEN`` deployment, since tags and
their notes are working notes, not public content.
"""

from typing import Any

from django.conf import settings


def web_access_is_all() -> bool:
    return getattr(settings, "WEB_ACCESS", "ALL").upper() == "ALL"


def can_view_message_tags(user: Any) -> bool:
    return web_access_is_all() or bool(user and user.is_authenticated)


def can_edit_message_tags(user: Any) -> bool:
    return web_access_is_all() or bool(user and user.is_staff)

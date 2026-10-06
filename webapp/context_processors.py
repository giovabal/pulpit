from django.conf import settings

from webapp.models import Project
from webapp.utils.access import can_edit_message_tags, can_view_message_tags


def web_access(request):
    return {
        "WEB_ACCESS": getattr(settings, "WEB_ACCESS", "ALL"),
        "APP_VERSION": getattr(settings, "APP_VERSION", ""),
        "REPOSITORY_URL": getattr(settings, "REPOSITORY_URL", ""),
        # Project title (Manage › Project singleton) — shown in the page <title> and
        # the About modal, mirroring the title baked into HTML/XLSX exports.
        "PROJECT_TITLE": Project.load().title,
        # Message tags are working notes: hidden from anonymous visitors of an OPEN
        # deployment, editable by whoever may use the backoffice (webapp.utils.access).
        "CAN_VIEW_TAGS": can_view_message_tags(request.user),
        "CAN_EDIT_TAGS": can_edit_message_tags(request.user),
    }

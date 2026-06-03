from django.conf import settings

from webapp.models import Project


def web_access(request):
    return {
        "WEB_ACCESS": getattr(settings, "WEB_ACCESS", "ALL"),
        "APP_VERSION": getattr(settings, "APP_VERSION", ""),
        "REPOSITORY_URL": getattr(settings, "REPOSITORY_URL", ""),
        # Project title (Manage › Project singleton) — shown in the page <title> and
        # the About modal, mirroring the title baked into HTML/XLSX exports.
        "PROJECT_TITLE": Project.load().title,
    }

from django.conf import settings


def web_access(request):
    return {
        "WEB_ACCESS": getattr(settings, "WEB_ACCESS", "ALL"),
        "APP_VERSION": getattr(settings, "APP_VERSION", ""),
        "REPOSITORY_URL": getattr(settings, "REPOSITORY_URL", ""),
    }

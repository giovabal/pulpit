from django.conf import settings


def web_access(request):
    return {"WEB_ACCESS": getattr(settings, "WEB_ACCESS", "ALL")}

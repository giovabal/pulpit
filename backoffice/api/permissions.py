from django.conf import settings

from rest_framework.permissions import BasePermission


class BackofficePermission(BasePermission):
    """Allow unrestricted access when WEB_ACCESS=ALL; require is_staff otherwise."""

    def has_permission(self, request, view):
        if getattr(settings, "WEB_ACCESS", "ALL").upper() == "ALL":
            return True
        return bool(request.user and request.user.is_staff)

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden


class WebAccessMiddleware:
    """
    Enforce the WEB_ACCESS policy set in settings.

    ALL (default) — no restrictions; admin bypass remains active.
    OPEN          — /operations/ requires is_staff; everything else is public.
    PROTECTED     — /operations/ requires is_staff; all other paths require login.

    /admin/ is always left to Django's own authentication.
    /login/, /logout/, and /static/ are always exempt.
    """

    _ALWAYS_EXEMPT = ("/login/", "/logout/", "/admin/", "/static/")

    def __init__(self, get_response):
        from django.conf import settings

        self.get_response = get_response
        self.mode = getattr(settings, "WEB_ACCESS", "ALL").upper()

    def __call__(self, request):
        if self.mode == "ALL":
            return self.get_response(request)

        path = request.path_info

        if any(path.startswith(p) for p in self._ALWAYS_EXEMPT):
            return self.get_response(request)

        is_ops = path.startswith("/operations/")

        if is_ops:
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not request.user.is_staff:
                return HttpResponseForbidden("Staff access required.")
        elif self.mode == "PROTECTED" and not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        return self.get_response(request)

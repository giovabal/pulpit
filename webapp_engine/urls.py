"""
URL configuration for webapp_engine project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from webapp.views import serve_export

if settings.WEB_ACCESS == "ALL":

    class AccessUser:
        has_module_perms = has_perm = __getattr__ = lambda s, *a, **kw: True

    admin.site.has_permission = lambda r: setattr(r, "user", AccessUser()) or True

_graph_root = settings.BASE_DIR / settings.GRAPH_OUTPUT_DIR

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="webapp/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("stats/", include("stats.urls")),
    path("events/", include("events.urls")),
    *(
        [
            path("graph/", RedirectView.as_view(url="/graph/index.html", permanent=False)),
            re_path(r"^graph/(?P<path>.*)$", serve, {"document_root": _graph_root}),
            path("exports/<str:name>/", serve_export, {"path": ""}),
            re_path(r"^exports/(?P<name>[^/]+)/(?P<path>.+)$", serve_export),
        ]
        if settings.DEBUG
        else []
    ),
    path("operations/", include("runner.urls")),
    path("manage/", include("backoffice.urls", namespace="backoffice")),
    path("", include("webapp.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

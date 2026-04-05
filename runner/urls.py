from django.urls import path

from . import views

urlpatterns = [
    path("", views.OpsView.as_view(), name="ops"),
    path("run/<str:task>/", views.RunTaskView.as_view(), name="ops-run"),
    path("abort/<str:task>/", views.AbortTaskView.as_view(), name="ops-abort"),
    path("status/<str:task>/", views.TaskStatusView.as_view(), name="ops-status"),
]

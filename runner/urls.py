from django.urls import path

from . import views

urlpatterns = [
    path("", views.OperationsView.as_view(), name="operations"),
    path("run/<str:task>/", views.RunTaskView.as_view(), name="operations-run"),
    path("abort/<str:task>/", views.AbortTaskView.as_view(), name="operations-abort"),
    path("status/<str:task>/", views.TaskStatusView.as_view(), name="operations-status"),
]

from django.urls import path

from . import views

urlpatterns = [
    path("", views.OperationsView.as_view(), name="operations"),
    path("run/<str:task>/", views.RunTaskView.as_view(), name="operations-run"),
    path("abort/<str:task>/", views.AbortTaskView.as_view(), name="operations-abort"),
    path("status/<str:task>/", views.TaskStatusView.as_view(), name="operations-status"),
    path("graph-dirs/", views.GraphDirsView.as_view(), name="operations-graph-dirs"),
    path("exports/", views.ExportsListView.as_view(), name="operations-exports"),
    path("exports/<str:name>/", views.ExportDetailView.as_view(), name="operations-export-detail"),
]

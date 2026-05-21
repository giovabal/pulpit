from django.urls import path

from . import views

urlpatterns = [
    path("", views.OperationsView.as_view(), name="operations"),
    path("analysis/", views.AnalysisPageView.as_view(), name="analysis"),
    path("run/<str:task>/", views.RunTaskView.as_view(), name="operations-run"),
    path("abort/<str:task>/", views.AbortTaskView.as_view(), name="operations-abort"),
    path("reset/<str:task>/", views.ResetTaskView.as_view(), name="operations-reset"),
    path("status/<str:task>/", views.TaskStatusView.as_view(), name="operations-status"),
    path("graph-dirs/", views.GraphDirsView.as_view(), name="operations-graph-dirs"),
    path("exports/", views.ExportsListView.as_view(), name="operations-exports"),
    path("exports/<str:name>/", views.ExportDetailView.as_view(), name="operations-export-detail"),
    path(
        "save-defaults/<str:task>/",
        views.SaveDefaultsView.as_view(),
        name="operations-save-defaults",
    ),
    path(
        "load-defaults/<str:task>/",
        views.LoadDefaultsView.as_view(),
        name="operations-load-defaults",
    ),
    path("palette/<str:name>/", views.PaletteColorsView.as_view(), name="operations-palette"),
]

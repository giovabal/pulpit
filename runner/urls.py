from django.urls import path

from . import views

urlpatterns = [
    path("", views.OperationsView.as_view(), name="operations"),
    path("analysis/", views.AnalysisPageView.as_view(), name="analysis"),
    path("run/<str:task>/", views.RunTaskView.as_view(), name="operations-run"),
    path(
        "write-cli-command/<str:task>/",
        views.WriteCliCommandView.as_view(),
        name="operations-write-cli-command",
    ),
    path("abort/<str:task>/", views.AbortTaskView.as_view(), name="operations-abort"),
    path("reset/<str:task>/", views.ResetTaskView.as_view(), name="operations-reset"),
    path("status/<str:task>/", views.TaskStatusView.as_view(), name="operations-status"),
    path("graph-dirs/", views.GraphDirsView.as_view(), name="operations-graph-dirs"),
    path("exports/", views.ExportsListView.as_view(), name="operations-exports"),
    path("exports/<str:name>/", views.ExportDetailView.as_view(), name="operations-export-detail"),
    path(
        "defaults/<str:task>/",
        views.DefaultsListView.as_view(),
        name="operations-defaults",
    ),
    path(
        "defaults/<str:task>/<str:snapshot_id>/",
        views.DefaultsItemView.as_view(),
        name="operations-defaults-item",
    ),
    path("palette/<str:name>/", views.PaletteColorsView.as_view(), name="operations-palette"),
]

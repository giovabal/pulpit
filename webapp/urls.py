from django.urls import path

from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
    path("channels/vacancies/", views.VacanciesView.as_view(), name="channel-vacancies"),
    path("channels/emoji-packs/", views.EmojiPacksView.as_view(), name="emoji-packs"),
    path("channels/emoji-packs/usage.csv", views.EmojiPackUsageCSVView.as_view(), name="emoji-pack-usage-csv"),
    path("channels/emoji-packs/<int:pk>/", views.EmojiPackDetailView.as_view(), name="emoji-pack-detail"),
    path("channels/emoji-packs/emoji/", views.CustomEmojiListView.as_view(), name="custom-emoji-list"),
    path(
        "channels/emoji-packs/emoji/usage.csv", views.CustomEmojiUsageCSVView.as_view(), name="custom-emoji-usage-csv"
    ),
    path("channels/emoji-packs/emoji/<int:pk>/", views.CustomEmojiDetailView.as_view(), name="custom-emoji-detail"),
    path("channel/<int:pk>/", views.ChannelDetailView.as_view(), name="channel-detail"),
    path("channel/<int:pk>/vacancy-analysis/", views.VacancyAnalysisView.as_view(), name="channel-vacancy-analysis"),
    path(
        "channel/<int:channel_pk>/message/<int:telegram_id>/replies/",
        views.MessageRepliesView.as_view(),
        name="message-replies",
    ),
    path(
        "channel/<int:channel_pk>/message/<int:telegram_id>/",
        views.MessageJumpView.as_view(),
        name="message-jump",
    ),
    path("search/", views.MessageSearchView.as_view(), name="message-search"),
    path("messages/highlights/", views.MessageHighlightsView.as_view(), name="message-highlights"),
    path("version/check/", views.VersionCheckView.as_view(), name="version-check"),
]

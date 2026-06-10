import datetime
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Prefetch, Q, QuerySet, Subquery, Sum
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import ListView, TemplateView
from django.views.static import serve as _static_serve

from network.utils import channel_cutoff_q, channel_period_date_q
from network.vacancy_analysis import _scores_abc, _shift_months
from webapp.paginator import DiggPaginator

from .models import (
    Channel,
    ChannelAttribution,
    ChannelGroup,
    ChannelVacancy,
    Message,
    MessageReaction,
    MessageReply,
    Organization,
    ProfilePicture,
)
from .utils.channel_types import channel_type_filter
from .utils.dates import fmt_date, fmt_ttl
from .utils.emoji import emoji_present
from .version_check import version_status


def _in_target_attr_exists() -> Exists:
    """Exists(): the channel has at least one in-target attribution period (any time)."""
    return Exists(ChannelAttribution.objects.filter(channel=OuterRef("pk"), organization__is_in_target=True))


# ---- message list options ------------------------------------------------

# Standard prefetch set for every Message-list view: each card needs all five
# media types plus reactions, and rendering them per-row without prefetching
# fires a query storm. ChannelDetailView additionally prefetches
# ``references`` because its template shows the t.me link column.
_MESSAGE_LIST_PREFETCH: tuple[str, ...] = (
    "messagepicture_set",
    "messagevideo_set",
    "messageaudio_set",
    "messagesticker_set",
    "messageothermedia_set",
    "reactions",
    "channel__attributions__organization",
)

_CONTENT_TYPES = ["text", "image", "video", "sound", "sticker", "other"]

_CONTENT_TYPE_Q: dict[str, Q] = {
    # "none" is the sentinel ``--fix-missing-media`` writes after confirming a
    # message has no downloadable media on Telegram, so it must be treated as
    # text here (and excluded from "other") to keep the message-list filter
    # consistent with the legacy empty-string value.
    "text": Q(media_type__in=["", "none"]),
    "image": Q(media_type="photo"),
    "video": Q(media_type="video"),
    "sound": Q(media_type="audio"),
    "sticker": Q(media_type="sticker"),
    "other": ~Q(media_type__in=["", "none", "photo", "video", "audio", "sticker"]),
}


_LOST_MODES = ("exclude", "include", "only")

_DEFAULT_SORT = "date_desc"
# Backward-compat for pre-2026 URLs that used the bare asc/desc vocabulary.
_LEGACY_SORTS = {"asc": "date_asc", "desc": "date_desc"}
# Every order_by tuple terminates with -pk / pk so pagination is stable across
# ties — MessageJumpView relies on (-date, -pk) for the default sort.
_SORT_ORDER_BY: dict[str, tuple] = {
    "date_desc": ("-date", "-pk"),
    "date_asc": ("date", "pk"),
    "views_desc": (F("views").desc(nulls_last=True), "-date", "-pk"),
    "views_asc": (F("views").asc(nulls_last=True), "-date", "-pk"),
    "reactions_desc": ("-total_reactions", "-date", "-pk"),
    "reactions_asc": ("total_reactions", "-date", "-pk"),
    # Per-channel z-scored composite (webapp.scoring). NULL when the channel
    # has too little history to baseline; pushed to the bottom by nulls_last.
    "interest_desc": (F("interest_score").desc(nulls_last=True), "-date", "-pk"),
    "interest_asc": (F("interest_score").asc(nulls_last=True), "-date", "-pk"),
}


def _parse_iso_date(s: str | None) -> datetime.date | None:
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _resolve_sort(raw: str | None) -> str:
    sort = _LEGACY_SORTS.get(raw or "", raw or "")
    return sort if sort in _SORT_ORDER_BY else _DEFAULT_SORT


def _exclude_album_tails(qs: QuerySet) -> QuerySet:
    """Hide messages that are part of a Telegram media-group album but not its head.

    Telegram emits each photo/video of an album as a separate ``Message`` with
    a shared ``grouped_id``. Treating the message with the smallest
    ``telegram_id`` in each group as the head and dropping the rest collapses
    multi-item albums into a single visible card; the head's
    ``album_pictures`` / ``album_videos`` / etc. then expose the union of media
    across siblings.
    """
    has_earlier_sibling = Message.objects.filter(
        channel_id=OuterRef("channel_id"),
        grouped_id=OuterRef("grouped_id"),
        telegram_id__lt=OuterRef("telegram_id"),
    )
    return qs.annotate(_is_album_tail=Exists(has_earlier_sibling)).filter(
        Q(grouped_id__isnull=True) | Q(_is_album_tail=False)
    )


def _apply_message_options(qs: QuerySet, params: Any) -> QuerySet:
    sort = _resolve_sort(params.get("sort"))
    qs = qs.order_by(*_SORT_ORDER_BY[sort])
    date_from = _parse_iso_date(params.get("date_from"))
    if date_from:
        qs = qs.filter(date__date__gte=date_from)
    date_to = _parse_iso_date(params.get("date_to"))
    if date_to:
        qs = qs.filter(date__date__lte=date_to)
    selected = [t for t in params.getlist("type") if t in _CONTENT_TYPE_Q]
    if selected and set(selected) != set(_CONTENT_TYPES):
        type_q: Q = Q(pk__in=[])
        for t in selected:
            type_q |= _CONTENT_TYPE_Q[t]
        qs = qs.filter(type_q)
    lost = params.get("lost", "exclude")
    if lost not in _LOST_MODES:
        lost = "exclude"
    if lost == "exclude":
        qs = qs.filter(is_lost=False)
    elif lost == "only":
        qs = qs.filter(is_lost=True)
    return _exclude_album_tails(qs)


def _message_options_context(params: Any) -> dict[str, Any]:
    sort = _resolve_sort(params.get("sort"))
    date_from = _parse_iso_date(params.get("date_from"))
    date_to = _parse_iso_date(params.get("date_to"))
    selected = [t for t in params.getlist("type") if t in _CONTENT_TYPE_Q]
    if not selected:
        selected = list(_CONTENT_TYPES)
    lost = params.get("lost", "exclude")
    if lost not in _LOST_MODES:
        lost = "exclude"
    options_active = (
        sort != _DEFAULT_SORT
        or date_from is not None
        or date_to is not None
        or set(selected) != set(_CONTENT_TYPES)
        or lost != "exclude"
    )

    extra: dict[str, Any] = {}
    if params.get("q"):
        extra["q"] = params["q"]
    if sort != _DEFAULT_SORT:
        extra["sort"] = sort
    if date_from:
        extra["date_from"] = date_from.isoformat()
    if date_to:
        extra["date_to"] = date_to.isoformat()
    if set(selected) != set(_CONTENT_TYPES):
        extra["type"] = selected
    if lost != "exclude":
        extra["lost"] = lost
    original_query = ("&" + urlencode(extra, doseq=True)) if extra else ""

    return {
        "sort": sort,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "selected_types": selected,
        "all_types": _CONTENT_TYPES,
        "lost": lost,
        "options_active": options_active,
        "original_query": original_query,
    }


class HomeView(ListView):
    template_name = "webapp/home.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        q = self.request.GET.get("q", "").strip()
        qs = (
            Message.objects.filter(channel__in=Channel.objects.in_target())
            .select_related("channel", "forwarded_from")
            .prefetch_related(*_MESSAGE_LIST_PREFETCH)
        )
        if q:
            qs = qs.filter(message__icontains=q)
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        ctx = super().get_context_data(*args, **kwargs)
        Message.attach_album_data(ctx["object_list"])

        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        ctx.update(_message_options_context(self.request.GET))

        # Two rows of ecosystem-stat cards aggregated over the Message + Channel
        # tables. Cached for an hour and invalidated at the start of every
        # crawl_channels run — see webapp/cache.py.
        from webapp.cache import get_home_summary

        ctx["summary_rows"] = get_home_summary()
        ctx["panels"] = [
            {
                "id": "messages-history",
                "title": "Messages per month",
                "icon": "bi-bar-chart-line",
                "url": reverse("messages-history-data"),
                "description": "Total number of messages posted by monitored channels each month.",
            },
            {
                "id": "active-channels-history",
                "title": "Active channels per month",
                "icon": "bi-broadcast",
                "url": reverse("active-channels-history-data"),
                "description": "Number of distinct monitored channels that posted at least one message each month.",
            },
            {
                "id": "forwards-history",
                "title": "Forwards per month",
                "icon": "bi-forward",
                "url": reverse("forwards-history-data"),
                "description": "Number of messages forwarded from other monitored channels each month. A proxy for cross-channel amplification activity.",
            },
            {
                "id": "views-history",
                "title": "Views per month",
                "icon": "bi-eye",
                "url": reverse("views-history-data"),
                "description": "Sum of view counts across all messages posted by monitored channels each month.",
            },
            {
                "id": "avg-involvement-history",
                "title": "Average involvement per month",
                "icon": "bi-graph-up",
                "url": reverse("avg-involvement-history-data"),
                "description": "Average number of views per message across monitored channels each month. A proxy for audience engagement intensity.",
            },
            {
                "id": "reactions-history",
                "title": "Reactions per month",
                "icon": "bi-emoji-smile",
                "url": reverse("reactions-history-data"),
                "description": "Total reactions to messages posted by monitored channels each month, broken down by the eight most-used emojis. Custom and sticker reactions are aggregated together under the 'custom' bucket.",
            },
        ]
        return ctx


class ChannelListView(ListView):
    template_name = "webapp/channels.html"
    model = Channel
    context_object_name = "channel_list"

    _pic_prefetch = Prefetch(
        "profilepicture_set",
        queryset=ProfilePicture.objects.order_by("-date")[:1],
        to_attr="_prefetched_profile_pics",
    )

    def get_queryset(self) -> QuerySet[Channel]:
        return (
            Channel.objects.in_target()
            .prefetch_related(self._pic_prefetch, "groups", "attributions__organization")
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        _status_qs = (
            Channel.objects.filter(_in_target_attr_exists())
            .prefetch_related(self._pic_prefetch, "attributions__organization")
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )
        ctx["excluded_list"] = (
            Channel.objects.filter(_in_target_attr_exists())
            .exclude(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_lost=True)
            .exclude(is_private=True)
            .prefetch_related(self._pic_prefetch, "attributions__organization")
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )
        ctx["to_inspect_list"] = (
            Channel.objects.filter(to_inspect=True)
            .exclude(_in_target_attr_exists())
            .prefetch_related(self._pic_prefetch, "groups", "attributions__organization")
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )
        ctx["lost_list"] = _status_qs.filter(is_lost=True)
        ctx["private_list"] = _status_qs.filter(is_private=True)
        ctx["organizations"] = Organization.objects.filter(is_in_target=True).order_by("name")
        ctx["groups"] = (
            ChannelGroup.objects.filter(channels__in=Channel.objects.in_target()).distinct().order_by("name")
        )
        ctx["has_vacancies"] = ChannelVacancy.objects.exists()
        return ctx


class VacanciesView(TemplateView):
    template_name = "webapp/vacancies.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        # Count the distinct in-target channels that forwarded from the vacancy channel.
        # Grouping by the (constant) forwarded-from target collapses to a single row;
        # .order_by() clears any model default ordering that would otherwise leak an
        # extra column into the GROUP BY and split the count across rows.
        orphaned_sub = Subquery(
            Channel.objects.in_target()
            .filter(message_set__forwarded_from=OuterRef("channel"))
            .order_by()
            .values("message_set__forwarded_from")
            .annotate(c=Count("pk", distinct=True))
            .values("c")
        )
        rows = [
            {"vacancy": vac, "channel": vac.channel, "orphaned_amplifier_count": vac.orphaned_amplifier_count or 0}
            for vac in ChannelVacancy.objects.select_related("channel")
            .prefetch_related("channel__attributions__organization")
            .annotate(orphaned_amplifier_count=orphaned_sub)
            .order_by("-closure_date")
        ]
        ctx["vacancies"] = rows
        return ctx


def serve_export(request: HttpRequest, name: str, path: str = "") -> HttpResponse:
    """Serve static files from BASE_DIR/exports/{name}/ (development only)."""
    if not re.match(r"^[\w\-]+$", name):
        raise Http404
    doc_root = Path(settings.BASE_DIR) / "exports" / name
    if not doc_root.is_dir():
        raise Http404
    return _static_serve(request, path or "index.html", document_root=str(doc_root))


class MessageSearchView(ListView):
    template_name = "webapp/message_search.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        qs = (
            Message.objects.filter(channel__in=Channel.objects.in_target())
            .select_related("channel", "forwarded_from")
            .prefetch_related(*_MESSAGE_LIST_PREFETCH)
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(message__icontains=q)
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(*args, **kwargs)
        Message.attach_album_data(ctx["object_list"])
        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        ctx.update(_message_options_context(self.request.GET))
        return ctx


class MessageHighlightsView(ListView):
    """Global feed of messages ranked by ``interest_score`` (the hot-layer
    composite of per-channel z-scored views, forwards, reactions).

    Cold-start channels — those below ``webapp.scoring.MIN_SAMPLE`` alive
    messages — emit ``NULL`` interest scores and are filtered out: the page
    is a ranking, not a catch-all browser.
    """

    template_name = "webapp/message_highlights.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def _params(self) -> Any:
        # Default the sort to interest_desc on first visit, but keep any
        # explicit ?sort= from the dropdown.
        params = self.request.GET.copy()
        if "sort" not in self.request.GET:
            params["sort"] = "interest_desc"
        return params

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        qs = (
            Message.objects.filter(
                channel__in=Channel.objects.in_target(),
                interest_score__isnull=False,
            )
            .select_related("channel", "forwarded_from")
            .prefetch_related(*_MESSAGE_LIST_PREFETCH)
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(message__icontains=q)
        return _apply_message_options(qs, self._params())

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(*args, **kwargs)
        Message.attach_album_data(ctx["object_list"])
        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        ctx.update(_message_options_context(self._params()))
        return ctx


class ChannelDetailView(ListView):
    template_name = "webapp/channel_detail.html"
    model = Message
    paginator_class = DiggPaginator
    paginate_by = 50
    paginate_orphans = 15
    page_kwarg = "page"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.selected_channel = get_object_or_404(Channel, pk=kwargs.get("pk"))
        return super().get(request, *args, **kwargs)

    def get_queryset(self, *args: Any, **kwargs: Any) -> QuerySet[Message]:
        tab = self.request.GET.get("tab", "messages")
        q = self.request.GET.get("q", "").strip()
        if tab == "received":
            # Period-aware: a forward by an in-target amplifier counts only when
            # the amplifier was in an in-target period at the message date,
            # matching the summary card on the same page (line 584).
            qs = (
                Message.objects.filter(
                    forwarded_from=self.selected_channel,
                    channel__in=Channel.objects.in_target().values("pk"),
                )
                .filter(channel_cutoff_q())
                .select_related("channel", "forwarded_from")
                .prefetch_related("references", *_MESSAGE_LIST_PREFETCH)
            )
            if q:
                qs = qs.filter(message__icontains=q)
            self_ref = self.request.GET.get("self_ref", "include")
            if self_ref == "exclude":
                qs = qs.exclude(channel=self.selected_channel)
            elif self_ref == "only":
                qs = qs.filter(channel=self.selected_channel)
            return _apply_message_options(qs, self.request.GET)
        qs = (
            Message.objects.filter(channel=self.selected_channel)
            .select_related("forwarded_from")
            .prefetch_related("references", *_MESSAGE_LIST_PREFETCH)
        )
        if self.selected_channel.in_target_periods.exists():
            qs = qs.filter(channel_period_date_q(self.selected_channel))
        if q:
            qs = qs.filter(message__icontains=q)
        if self.request.GET.get("forwards_only"):
            qs = qs.filter(forwarded_from__isnull=False)
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        context_data = super().get_context_data(*args, **kwargs)
        Message.attach_album_data(context_data["object_list"])
        ch = self.selected_channel
        q = self.request.GET.get("q", "").strip()
        context_data["query"] = q
        tab = self.request.GET.get("tab", "messages")
        context_data["active_tab"] = tab
        context_data["forwards_only"] = bool(self.request.GET.get("forwards_only"))
        self_ref = self.request.GET.get("self_ref", "include")
        context_data["self_ref"] = self_ref
        context_data.update(_message_options_context(self.request.GET))
        # Extend original_query so pagination links preserve tab, self_ref, and forwards_only.
        extra = ""
        if tab == "received":
            extra += "&tab=received"
            if self_ref != "include":
                extra += f"&self_ref={self_ref}"
        if self.request.GET.get("forwards_only"):
            extra += "&forwards_only=1"
        context_data["original_query"] = context_data["original_query"] + extra

        is_in_target = Channel.objects.in_target().filter(pk=ch.pk).exists()

        msg_qs = Message.objects.alive().filter(channel=ch)
        if ch.in_target_periods.exists():
            msg_qs = msg_qs.filter(channel_period_date_q(ch))
        total_messages = msg_qs.count()
        total_views = msg_qs.aggregate(total=Sum("views"))["total"] or 0
        replies_allowed = ch.has_link or not ch.broadcast
        total_replies = MessageReply.objects.filter(parent_message__in=msg_qs).count() if replies_allowed else 0
        media_known_types = ["photo", "video", "audio", "sticker"]
        media_agg = msg_qs.aggregate(
            pictures=Count("id", filter=Q(media_type="photo")),
            videos=Count("id", filter=Q(media_type="video")),
            audio=Count("id", filter=Q(media_type="audio")),
            stickers=Count("id", filter=Q(media_type="sticker")),
            # "none"/"" are confirmed-no-media / text sentinels — exclude them so this
            # matches the list view's _CONTENT_TYPE_Q["other"] (which classes them as text).
            other=Count("id", filter=~Q(media_type__in=["", "none", *media_known_types])),
        )
        total_media = sum(media_agg.values())
        media_breakdown = [
            (media_agg["pictures"], "picture", "pictures"),
            (media_agg["videos"], "video", "videos"),
            (media_agg["audio"], "audio", "audio"),
            (media_agg["stickers"], "sticker", "stickers"),
            (media_agg["other"], "other", "other"),
        ]
        in_target_pks = Channel.objects.in_target().values("pk")

        # Collapse the engagement counts into four aggregate queries (down
        # from fourteen separate .count() / .distinct().count() calls). Each
        # aggregate fans out into conditional ``Count(..., filter=Q(...))``
        # expressions over a single base scan — the same shape as the 0.19
        # home-page summary fix.
        fwd_in_target_q = Q(forwarded_from__in=in_target_pks) & ~Q(forwarded_from=ch)
        fwd_out_of_target_q = Q(forwarded_from__isnull=False) & ~Q(forwarded_from__in=in_target_pks)
        fwd_sent_agg = msg_qs.aggregate(
            in_target=Count("id", filter=fwd_in_target_q),
            in_target_channels=Count("forwarded_from", filter=fwd_in_target_q, distinct=True),
            out_of_target=Count("id", filter=fwd_out_of_target_q),
            out_of_target_channels=Count("forwarded_from", filter=fwd_out_of_target_q, distinct=True),
            self_=Count("id", filter=Q(forwarded_from=ch)),
        )
        total_forwards_sent_in_target = fwd_sent_agg["in_target"]
        fwd_sent_in_target_channels = fwd_sent_agg["in_target_channels"]
        total_forwards_sent_out_of_target = fwd_sent_agg["out_of_target"]
        fwd_sent_out_of_target_channels = fwd_sent_agg["out_of_target_channels"]
        total_forwards_sent_self = fwd_sent_agg["self_"]

        fwd_received_agg = (
            Message.objects.alive()
            .filter(channel_cutoff_q(), channel__in=in_target_pks, forwarded_from=ch)
            .exclude(channel=ch)
            .aggregate(total=Count("id"), channels=Count("channel", distinct=True))
        )
        total_forwards_received = fwd_received_agg["total"]
        fwd_received_channels = fwd_received_agg["channels"]

        refs_through = Message.references.through.objects
        mentions_in_target_q = Q(channel__in=in_target_pks) & ~Q(channel=ch)
        mentions_out_of_target_q = ~Q(channel__in=in_target_pks) & ~Q(channel=ch)
        mentions_sent_agg = refs_through.filter(message__channel=ch, message__is_lost=False).aggregate(
            in_target=Count("id", filter=mentions_in_target_q),
            in_target_channels=Count("channel", filter=mentions_in_target_q, distinct=True),
            out_of_target=Count("id", filter=mentions_out_of_target_q),
            out_of_target_channels=Count("channel", filter=mentions_out_of_target_q, distinct=True),
            self_=Count("id", filter=Q(channel=ch)),
        )
        total_mentions_sent_in_target = mentions_sent_agg["in_target"]
        mentions_sent_in_target_channels = mentions_sent_agg["in_target_channels"]
        total_mentions_sent_out_of_target = mentions_sent_agg["out_of_target"]
        mentions_sent_out_of_target_channels = mentions_sent_agg["out_of_target_channels"]
        total_mentions_sent_self = mentions_sent_agg["self_"]

        mentions_received_agg = (
            refs_through.filter(
                channel_cutoff_q("message__channel", "message__date"),
                message__channel__in=in_target_pks,
                message__is_lost=False,
                channel=ch,
            )
            .exclude(message__channel=ch)
            .aggregate(total=Count("id"), channels=Count("message__channel", distinct=True))
        )
        total_mentions_received = mentions_received_agg["total"]
        mentions_received_channels = mentions_received_agg["channels"]

        def channels_phrase(prefix: str, count: int, kind: str) -> str:
            word = "channel" if count == 1 else "channels"
            return f"{prefix} <strong>{count:,}</strong> {kind} {word}"

        date_agg = msg_qs.filter(date__isnull=False).aggregate(earliest=Min("date"), latest=Max("date"))

        summary = [
            {
                "icon": "bi-chat-left-text",
                "label": "Messages",
                "value": f"{total_messages:,}",
                "secondary": [
                    {"value": f"{total_replies:,}", "label": "reply" if total_replies == 1 else "replies"}
                    if replies_allowed
                    else {"label": "no replies allowed"},
                ],
            },
            {
                "icon": "bi-images",
                "label": "Media",
                "value": f"{total_media:,}",
                "inline_secondary": True,
                "secondary": [
                    {"value": f"{n:,}", "label": singular if n == 1 else plural}
                    for n, singular, plural in media_breakdown
                    if n
                ],
            },
            {"icon": "bi-eye", "label": "Total views", "value": f"{total_views:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
            },
        ]
        engagement = [
            {
                "icon": "bi-forward",
                "label": "Forwards sent",
                "value": f"{total_forwards_sent_in_target:,}",
                "note": channels_phrase("from", fwd_sent_in_target_channels, "other in-target"),
                "secondary": [
                    {"value": f"{total_forwards_sent_self:,}", "label": "self-forwards"},
                    {
                        "value": f"{total_forwards_sent_out_of_target:,}",
                        "label": channels_phrase("from", fwd_sent_out_of_target_channels, "non-in-target"),
                    },
                ],
            },
            {
                "icon": "bi-at",
                "label": "Mentions sent",
                "value": f"{total_mentions_sent_in_target:,}",
                "note": channels_phrase("of", mentions_sent_in_target_channels, "other in-target"),
                "secondary": [
                    {"value": f"{total_mentions_sent_self:,}", "label": "self-mentions"},
                    {
                        "value": f"{total_mentions_sent_out_of_target:,}",
                        "label": channels_phrase("of", mentions_sent_out_of_target_channels, "non-in-target"),
                    },
                ],
            },
            {
                "icon": "bi-arrow-return-right",
                "label": "Forwards received",
                "value": f"{total_forwards_received:,}",
                "note": channels_phrase("by", fwd_received_channels, "other in-target"),
            },
            {
                "icon": "bi-chat-quote",
                "label": "Mentions received",
                "value": f"{total_mentions_received:,}",
                "note": channels_phrase("by", mentions_received_channels, "other in-target"),
            },
        ]
        top_reactions_qs = (
            MessageReaction.objects.filter(message__channel=ch)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:10]
        )
        top_reactions_raw = list(top_reactions_qs)
        total_reactions = sum(r["total"] for r in top_reactions_raw)
        top_reactions = [{"emoji": emoji_present(r["emoji"]), "total": f"{r['total']:,}"} for r in top_reactions_raw]

        if not is_in_target:
            for card in summary:
                card["dim"] = True
            for card in engagement:
                if card["label"] not in ("Forwards received", "Mentions received"):
                    card["dim"] = True

        panels = [
            {
                "id": "ch-messages-history",
                "title": "Messages per month",
                "icon": "bi-bar-chart-line",
                "url": reverse("channel-messages-history", kwargs={"pk": ch.pk}),
                "description": "Number of messages posted by this channel each month.",
            },
            {
                "id": "ch-views-history",
                "title": "Views per month",
                "icon": "bi-eye",
                "url": reverse("channel-views-history", kwargs={"pk": ch.pk}),
                "description": "Sum of view counts across all messages posted by this channel each month.",
            },
            {
                "id": "ch-forwards-history",
                "title": "Forwards sent per month",
                "icon": "bi-forward",
                "url": reverse("channel-forwards-history", kwargs={"pk": ch.pk}),
                "description": "Number of messages this channel forwarded from other channels each month.",
            },
            {
                "id": "ch-forwards-received-history",
                "title": "Forwards received per month",
                "icon": "bi-arrow-return-right",
                "url": reverse("channel-forwards-received-history", kwargs={"pk": ch.pk}),
                "description": "Number of times this channel's content was forwarded by other monitored channels each month.",
            },
            {
                "id": "ch-avg-involvement-history",
                "title": "Average involvement per month",
                "icon": "bi-graph-up",
                "url": reverse("channel-avg-involvement-history", kwargs={"pk": ch.pk}),
                "description": "Average number of views per message for this channel each month. A proxy for audience engagement intensity.",
            },
            {
                "id": "ch-reactions-history",
                "title": "Reactions per month",
                "icon": "bi-emoji-smile",
                "url": reverse("channel-reactions-history", kwargs={"pk": ch.pk}),
                "type": "reactions-chart",
                "description": "Monthly breakdown of the top emoji reactions on this channel's messages.",
            },
            {
                "id": "ch-cross-refs",
                "title": "Channel connections",
                "icon": "bi-arrow-left-right",
                "url": reverse("channel-cross-refs", kwargs={"pk": ch.pk}),
                "type": "cross-refs",
                "description": "Channels this channel mentions (via t.me/ links) and channels that mention it.",
            },
            {
                "id": "ch-contact-info",
                "title": "Domains & emails mentioned",
                "icon": "bi-link-45deg",
                "url": reverse("channel-contact-info", kwargs={"pk": ch.pk}),
                "type": "table",
                "description": "External domains and email addresses found in this channel's messages.",
            },
        ]

        if not is_in_target:
            panels = [p for p in panels if p["id"] == "ch-cross-refs"]

        try:
            vacancy = ch.vacancy
        except ChannelVacancy.DoesNotExist:
            vacancy = None

        linked_channel = Channel.objects.filter(telegram_id=ch.linked_chat_id).first() if ch.linked_chat_id else None
        parent_channel = Channel.objects.filter(linked_chat_id=ch.telegram_id).first() if ch.telegram_id else None
        if parent_channel and linked_channel and parent_channel.pk == linked_channel.pk:
            parent_channel = None
        context_data.update(
            {
                "selected_channel": ch,
                "summary_rows": [summary, engagement],
                "panels": panels,
                "is_in_target": is_in_target,
                "message_ttl_display": fmt_ttl(ch.message_ttl) if ch.message_ttl else "",
                "top_reactions": top_reactions,
                "total_reactions": f"{total_reactions:,}",
                "channel_groups": list(ch.groups.order_by("name")),
                "vacancy": vacancy,
                "linked_channel": linked_channel,
                "parent_channel": parent_channel,
            }
        )
        return context_data


class VacancyAnalysisView(View):
    """JSON endpoint: replacement candidates for a vacancy channel."""

    _CACHE_TTL = 60  # seconds; brief enough that fresh crawl data shows up quickly

    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        ch = get_object_or_404(Channel, pk=pk)
        try:
            vacancy = ch.vacancy
        except ChannelVacancy.DoesNotExist:
            return JsonResponse({"error": "no vacancy for this channel"}, status=404)

        try:
            # Cap the window at 10 years on each side so a crafted (or fat-fingered)
            # GET param can't force a multi-decade message scan; the analysis is
            # meaningless beyond that horizon anyway.
            months_before = max(1, min(120, int(request.GET.get("months_before", 12))))
            months_after = max(1, min(120, int(request.GET.get("months_after", 24))))
        except (TypeError, ValueError):
            return JsonResponse({"error": "invalid parameters"}, status=400)
        only_after_vacancy = request.GET.get("only_after_vacancy", "1") != "0"

        cache_key = f"vacancy_analysis:{pk}:{months_before}:{months_after}:{int(only_after_vacancy)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached)

        closure_date = vacancy.closure_date
        before_start = datetime.datetime.combine(
            _shift_months(closure_date, -months_before), datetime.time.min, tzinfo=datetime.timezone.utc
        )
        closure_dt = datetime.datetime.combine(closure_date, datetime.time.min, tzinfo=datetime.timezone.utc)
        after_end = datetime.datetime.combine(
            _shift_months(closure_date, months_after), datetime.time.max, tzinfo=datetime.timezone.utc
        )

        # Period-aware (channel_cutoff_q): only messages sent while the forwarding channel
        # was in-target at that date count — matching the graph pipeline and the shared
        # structural-analysis scorer, so the card and the export agree by construction.
        orphaned_pks: set[int] = set(
            Message.objects.alive()
            .filter(
                channel__in=Channel.objects.in_target(),
                forwarded_from=ch,
                date__gte=before_start,
                date__lt=closure_dt,
            )
            .filter(channel_cutoff_q())
            .values_list("channel_id", flat=True)
            .distinct()
        )
        total_orphaned = len(orphaned_pks)

        raw = list(
            Message.objects.alive()
            .filter(
                channel__in=orphaned_pks,
                forwarded_from__in=Channel.objects.in_target(),
                date__gte=closure_dt,
                date__lte=after_end,
            )
            .filter(channel_cutoff_q())
            .exclude(forwarded_from=ch)
            .values("forwarded_from")
            .annotate(amplifier_count=Count("channel", distinct=True), last_forwarded=Max("date"))
            .order_by("-amplifier_count")[:30]
        )

        cand_ids = [r["forwarded_from"] for r in raw]
        cand_map = {r["forwarded_from"]: r for r in raw}
        cand_qs = (
            Channel.objects.filter(pk__in=cand_ids)
            .prefetch_related("attributions__organization")
            .annotate(first_msg=Min("message_set__date"))
        )
        if only_after_vacancy:
            cand_qs = cand_qs.filter(first_msg__gte=closure_dt)
        cand_channels = {c.pk: c for c in cand_qs}

        # ── Strategy scores A / B / C ─────────────────────────────────────
        # Shared with the structural-analysis export (network.vacancy_analysis) so the card
        # and the export agree by construction. Scoped to the (possibly only_after_vacancy-
        # filtered) candidate set; candidates the loop below skips are simply not scored.
        score_map = _scores_abc(
            ch.pk,
            orphaned_pks,
            list(cand_channels),
            before_start,
            closure_dt,
            after_end,
            {"AMPLIFIER_JACCARD", "STRUCTURAL_EQUIV", "BROKERAGE"},
        )

        # ── Build candidate list ──────────────────────────────────────────
        candidates = []
        for cid in cand_ids:
            c = cand_channels.get(cid)
            if not c:
                continue
            amp_count: int = cand_map[cid]["amplifier_count"]
            lf = cand_map[cid]["last_forwarded"]
            fm = c.first_msg

            s = score_map.get(cid, {})
            score_a = s.get("AMPLIFIER_JACCARD", 0.0)  # amplifier coverage (recall): |A ∩ B| / |A|
            score_b = s.get("STRUCTURAL_EQUIV", 0.0)  # neighbour-set equiv. (binary Ochiai): 0.5·cos_in + 0.5·cos_out
            score_c: float | None = s.get("BROKERAGE")  # brokerage overlap: Jaccard of spanned (src-org, amp-org) pairs (structural position, one-degree)

            candidates.append(
                {
                    "pk": c.pk,
                    "title": c.title,
                    "url": c.get_absolute_url(),
                    "org_color": c.current_organization.color if c.current_organization else None,
                    "amplifier_count": amp_count,
                    "score_a": score_a,
                    "score_b": score_b,
                    "score_c": score_c,
                    "last_forwarded": lf.strftime("%b %-d, %Y") if lf else None,
                    "last_forwarded_iso": lf.date().isoformat() if lf else None,
                    "first_activity": fm.strftime("%b %-d, %Y") if fm else None,
                    "first_activity_iso": fm.date().isoformat() if fm else None,
                }
            )
        candidates.sort(key=lambda r: r["first_activity_iso"] or "")

        payload = {
            "candidates": candidates,
            "orphaned_count": total_orphaned,
            "months_before": months_before,
            "months_after": months_after,
            "only_after_vacancy": only_after_vacancy,
        }
        cache.set(cache_key, payload, self._CACHE_TTL)
        return JsonResponse(payload)


class MessageRepliesView(View):
    """JSON endpoint returning stored reply messages for a single channel post.

    GET /channel/<channel_pk>/message/<telegram_id>/replies/

    Response shape:
        {
          "count": <int>,
          "fetched": <bool>,   # False means replies>0 but not yet crawled
          "replies": [{"id", "date", "text", "sender_name", "views"}, ...]
        }
    """

    def get(self, request: HttpRequest, channel_pk: int, telegram_id: int) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=channel_pk)
        msg = get_object_or_404(Message, channel=channel, telegram_id=telegram_id)
        stored = list(msg.reply_set.values("id", "date", "text", "sender_name", "views"))
        fetched = bool(stored) or not msg.replies or msg.replies_fetched
        return JsonResponse(
            {
                "count": len(stored),
                "fetched": fetched,
                "unavailable": msg.replies_unavailable,
                "replies": [{**r, "date": r["date"].isoformat() if r["date"] else None} for r in stored],
            }
        )


class MessageJumpView(View):
    """Redirect to the channel-detail page that displays a specific message.

    GET /channel/<channel_pk>/message/<telegram_id>/

    Album tails resolve to their head (the only sibling listed). The page
    number is derived from the channel-detail default queryset; ``lost=include``
    is added when the target is a lost message so the row is visible. Falls
    back to the bare channel URL when the message is not in the database or
    falls outside the channel's in-target attribution periods.
    """

    PAGE_SIZE = ChannelDetailView.paginate_by
    ORPHANS = ChannelDetailView.paginate_orphans

    def get(self, request: HttpRequest, channel_pk: int, telegram_id: int) -> HttpResponse:
        from django.urls import reverse

        channel = get_object_or_404(Channel, pk=channel_pk)
        channel_url = reverse("channel-detail", kwargs={"pk": channel.pk})

        target = Message.objects.filter(channel=channel, telegram_id=telegram_id).first()
        if target is None:
            return HttpResponseRedirect(channel_url)

        if target.grouped_id is not None:
            head = Message.objects.filter(channel=channel, grouped_id=target.grouped_id).order_by("telegram_id").first()
            if head is not None:
                target = head

        if target.date is None:
            return HttpResponseRedirect(channel_url)
        in_target_periods = list(channel.in_target_periods.values_list("start", "end"))
        target_date = target.date.date()
        if in_target_periods and not any(
            (s is None or s <= target_date) and (e is None or e >= target_date) for s, e in in_target_periods
        ):
            return HttpResponseRedirect(channel_url)

        qs = Message.objects.filter(channel=channel)
        if in_target_periods:
            qs = qs.filter(channel_period_date_q(channel))
        extra_params: dict[str, str] = {}
        if target.is_lost:
            extra_params["lost"] = "include"
        else:
            qs = qs.filter(is_lost=False)
        qs = _exclude_album_tails(qs)

        preceding = qs.filter(Q(date__gt=target.date) | Q(date=target.date, pk__gt=target.pk)).count()
        count = qs.count()
        hits = max(1, count - self.ORPHANS)
        num_pages = max(1, math.ceil(hits / self.PAGE_SIZE))
        page = min(preceding // self.PAGE_SIZE + 1, num_pages)

        query = urlencode({"page": page, **extra_params})
        return HttpResponseRedirect(f"{channel_url}?{query}#post-{target.pk}")


class VersionCheckView(View):
    """Report whether a newer Pulpit release is available upstream.

    Reads the day-cached upstream version (see :mod:`webapp.version_check`); the
    web UI polls this to toggle the "update available" dots and the Maintenance
    banner. A short ``Cache-Control`` keeps the browser from re-hitting it on
    every navigation.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        response = JsonResponse(version_status())
        response["Cache-Control"] = "max-age=3600"
        return response

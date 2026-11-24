import re
from collections import Counter
from collections.abc import Iterable
from statistics import median
from typing import Any, ClassVar

from django.db import models
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View

from stats.queries import channel_month_spine, global_month_spine, reindex_to_spine
from webapp.models import Channel, Message, MessageReaction
from webapp.utils.emoji import emoji_present

import pandas as pd

_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")


def _scoped_in_target_channels(request: HttpRequest):
    """In-target channels, restricted to the home page's ``?filter=`` voice when present.

    The voice is a container-group label (e.g. Continents → Europe); the scope is
    the channels holding it or one of its child labels. Unknown / absent values
    fall back to the full in-target set, matching ``Label.from_filter_param``.
    """
    from webapp.models import Label

    qs = Channel.objects.in_target()
    voice = Label.from_filter_param(request.GET.get("filter"))
    if voice is not None:
        qs = qs.in_container_label(voice)
    return qs


def _medians_by_month(values: Iterable[tuple[Any, float]], spine: list[str]) -> list[float | None]:
    """The median of each month's ``(month, value)`` pairs — one value per channel — over *spine*.

    ``None``, not 0, for a month with no value: there is no typical channel that month.
    """
    by_month: dict[str, list[float]] = {}
    for month, value in values:
        by_month.setdefault(month.strftime("%Y-%m"), []).append(value)
    return [round(median(by_month[month]), 1) if month in by_month else None for month in spine]


class _GlobalScopeView(View):
    """A month-by-month series over the in-target messages of the home page's scope."""

    y_label: ClassVar[str]

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[Message]:
        """The in-scope messages, with their local ``month``."""
        from network.utils import channel_cutoff_q

        in_target_pks = _scoped_in_target_channels(request).values("pk")
        return (
            Message.objects.alive()
            .filter(channel__in=in_target_pks, date__isnull=False)
            .filter(channel_cutoff_q())
            .annotate(month=TruncMonth("date"))
        )


class _GlobalTwoLinesBase(_GlobalScopeView):
    """Two lines on one axis: ``values`` under ``values_label``, plus one ``extra_lines`` entry."""

    values_label: ClassVar[str]
    extra_label: ClassVar[str]
    #: First month (``YYYY-MM``) the figure can exist for; earlier months are left off the chart.
    first_month: ClassVar[str] = ""

    def get_lines(self, request: HttpRequest, spine: list[str]) -> tuple[list[float | None], list[float | None]]:
        raise NotImplementedError

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = [month for month in global_month_spine() if month >= self.first_month]
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})
        values, extra = self.get_lines(request, spine)
        return JsonResponse(
            {
                "labels": spine,
                "values": values,
                "y_label": self.y_label,
                "values_label": self.values_label,
                "extra_lines": [{"label": self.extra_label, "values": extra}],
            }
        )


class _GlobalTimeSeriesBase(_GlobalScopeView):
    annotate_field: ClassVar[str]

    def get_annotation(self) -> Count | Sum | Avg:
        raise NotImplementedError

    def extra_payload(self, request: HttpRequest, spine: list[str]) -> dict[str, Any]:
        """Further keys of the response (more series on the same axis)."""
        return {}

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})

        monthly_data = (
            self.get_queryset(request)
            .values("month")
            .annotate(**{self.annotate_field: self.get_annotation()})
            .order_by("month")
        )
        df = pd.DataFrame(
            [{"month": e["month"].strftime("%Y-%m"), self.annotate_field: e[self.annotate_field]} for e in monthly_data]
        )
        df = (
            reindex_to_spine(df, spine)
            if not df.empty
            else pd.DataFrame({"month": spine, self.annotate_field: [0] * len(spine)})
        )
        return JsonResponse(
            {
                "labels": list(df["month"]),
                "values": list(df[self.annotate_field]),
                "y_label": self.y_label,
                **self.extra_payload(request, spine),
            }
        )


class MessagesHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_messages"
    y_label = "messages"

    def get_annotation(self) -> Count:
        return Count("id")


class ActiveChannelsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_active_channels"
    y_label = "active channels"

    def get_annotation(self) -> Count:
        return Count("channel", distinct=True)


class ForwardsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_forwards"
    y_label = "forwards"

    def get_annotation(self) -> Count:
        return Count("id", filter=models.Q(forwarded_from__isnull=False))


class ViewsHistoryDataView(_GlobalTimeSeriesBase):
    annotate_field = "total_views"
    y_label = "views"

    def get_annotation(self) -> Sum:
        return Sum("views", default=0)


class AvgInvolvementHistoryDataView(_GlobalTimeSeriesBase):
    """Views per post, read two ways: the mean over all the month's posts, where channels posting a lot weigh
    more, and the median across the month's active channels of each one's own mean, where each counts once."""

    annotate_field = "avg_involvement"
    y_label = "avg views"

    def get_annotation(self) -> Avg:
        return Avg("views", default=0)

    def extra_payload(self, request: HttpRequest, spine: list[str]) -> dict[str, Any]:
        by_channel = (
            self.get_queryset(request)
            .filter(views__isnull=False)
            .values("month", "channel_id")
            .annotate(mean_views=Avg("views"))
            .order_by()
        )
        medians = _medians_by_month(((row["month"], row["mean_views"]) for row in by_channel), spine)
        return {
            "values_label": "mean of all posts",
            "extra_lines": [{"label": "median of active channels", "values": medians}],
        }


class OwnForwardedViewsHistoryDataView(_GlobalTwoLinesBase):
    """Views per post of own posts and of forwards: the median across channels of each one's mean of the kind.

    A forward is any message with a forward header (``forward_header_q``). Messages count as in the mean-and-median
    chart, so the lines compare with its median.
    """

    y_label = "views per post"
    values_label = "own posts"
    extra_label = "forwards"

    def get_lines(self, request: HttpRequest, spine: list[str]) -> tuple[list[float | None], list[float | None]]:
        from network.near_copies import forward_header_q

        def medians(messages: models.QuerySet[Message]) -> list[float | None]:
            rows = messages.values("month", "channel_id").annotate(mean_views=Avg("views")).order_by()
            return _medians_by_month(((row["month"], row["mean_views"]) for row in rows), spine)

        messages = self.get_queryset(request).filter(views__isnull=False)
        return medians(messages.filter(~forward_header_q())), medians(messages.filter(forward_header_q()))


class ReactionRateHistoryDataView(_GlobalTwoLinesBase):
    """Reactions per 1,000 views of own posts: of all of them together, and of the median channel.

    An album is one post: Telegram puts its reactions on a single message while every message carries views,
    so counting messages would read an album of five at a fifth of its rate. Its views are its best-seen
    message's. Forwards are left out, and posts with no view count cannot have a rate.
    """

    first_month = "2022-01"  # Telegram added reactions on 30 December 2021: before, 0 would mean nothing
    y_label = "reactions per 1,000 views"
    values_label = "all own posts"
    extra_label = "median of active channels"

    def get_lines(self, request: HttpRequest, spine: list[str]) -> tuple[list[float | None], list[float | None]]:
        from network.near_copies import forward_header_q

        rows = (
            self.get_queryset(request)
            .filter(~forward_header_q(), views__gt=0)
            .values_list("month", "channel_id", "grouped_id", "pk", "views", "total_reactions")
            .order_by()
        )
        posts: dict[tuple, list[int]] = {}
        for month, channel_id, grouped_id, pk, views, reactions in rows:
            album = ("album", grouped_id) if grouped_id is not None else ("post", pk)
            post = posts.setdefault((month, channel_id, album), [0, 0])
            post[0] = max(post[0], views)
            post[1] += reactions
        by_channel: dict[tuple, list[int]] = {}
        by_month: dict[str, list[int]] = {}
        for (month, channel_id, _album), (views, reactions) in posts.items():
            for totals in (
                by_channel.setdefault((month, channel_id), [0, 0]),
                by_month.setdefault(month.strftime("%Y-%m"), [0, 0]),
            ):
                totals[0] += views
                totals[1] += reactions
        overall = [
            round(1000 * by_month[month][1] / by_month[month][0], 1) if month in by_month else None for month in spine
        ]
        rates = ((month, 1000 * reactions / views) for (month, _), (views, reactions) in by_channel.items())
        return overall, _medians_by_month(rates, spine)


class _ChannelTimeSeriesBase(View):
    """Per-channel monthly aggregation pipeline.

    Mirrors ``_GlobalTimeSeriesBase``: subclasses only declare ``annotate_field``,
    ``y_label``, and ``get_annotation()`` (plus optional ``extra_filters`` and
    ``post_process_value`` / ``get_queryset`` hooks for the two outliers).
    """

    annotate_field: ClassVar[str]
    y_label: ClassVar[str]
    extra_filters: ClassVar[dict[str, Any]] = {}

    def _msg_qs(self, channel: Channel, **filters):
        """Base Message queryset for a channel, restricted to its in-target periods and excluding lost."""
        from network.utils import channel_period_date_q

        qs = Message.objects.alive().filter(channel=channel, **filters)
        if channel.in_target_periods.exists():
            qs = qs.filter(channel_period_date_q(channel))
        return qs

    def get_annotation(self) -> Count | Sum | Avg:
        raise NotImplementedError

    def get_queryset(self, channel: Channel):
        """Queryset that feeds the monthly aggregation. Override for views that
        scope to in-target channels rather than the subject channel itself
        (e.g. ``ChannelForwardsReceivedHistoryView``)."""
        return self._msg_qs(channel, date__isnull=False, **self.extra_filters)

    def post_process_value(self, value: Any) -> Any:
        """Post-process each monthly value before serialising. Default: identity."""
        return value

    def get_spine(self, channel: Channel) -> list[str]:
        """Month spine the data are reindexed to. Default: the channel's own posting
        span. Views whose data come from *other* channels' messages must override
        this — ``reindex_to_spine`` drops any bucket outside the spine."""
        return channel_month_spine(channel)

    def _get_monthly_data(self, channel: Channel) -> list[dict]:
        qs = (
            self.get_queryset(channel)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(**{self.annotate_field: self.get_annotation()})
            .order_by("month")
        )
        return [
            {
                "month": e["month"].strftime("%Y-%m"),
                self.annotate_field: self.post_process_value(e[self.annotate_field]),
            }
            for e in qs
        ]

    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        spine = self.get_spine(channel)
        if not spine:
            return JsonResponse({"labels": [], "values": [], "y_label": self.y_label})
        rows = self._get_monthly_data(channel)
        df = pd.DataFrame(rows)
        df = (
            reindex_to_spine(df, spine)
            if not df.empty
            else pd.DataFrame({"month": spine, self.annotate_field: [0] * len(spine)})
        )
        return JsonResponse(
            {"labels": list(df["month"]), "values": list(df[self.annotate_field]), "y_label": self.y_label}
        )


class ChannelMessagesHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_messages"
    y_label = "messages"

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelViewsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_views"
    y_label = "views"
    extra_filters = {"views__isnull": False}

    def get_annotation(self) -> Sum:
        return Sum("views")


class ChannelForwardsHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "total_forwards"
    y_label = "forwards sent"
    extra_filters = {"forwarded_from__isnull": False}

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelForwardsReceivedHistoryView(_ChannelTimeSeriesBase):
    """Forwards received by this channel from in-target channels — needs a different
    base queryset (other channels' messages forwarding from us), so it overrides
    ``get_queryset`` instead of declaring ``extra_filters``."""

    annotate_field = "total_forwards_received"
    y_label = "forwards received"

    def get_queryset(self, channel: Channel):
        from network.utils import channel_cutoff_q

        in_target_pks = Channel.objects.in_target().values("pk")
        return (
            Message.objects.alive()
            .filter(channel__in=in_target_pks, forwarded_from=channel, date__isnull=False)
            .filter(channel_cutoff_q())
        )

    def get_spine(self, channel: Channel) -> list[str]:
        """Span the union of the channel's own months and the forwards' months.

        The data here are *other* channels' forwards, which can occur after the
        subject's last own post (post-closure amplification — exactly what the
        vacancy analysis studies) or when the subject has no alive posts at all;
        the default own-months spine would silently drop those buckets.
        """
        own = channel_month_spine(channel)
        agg = self.get_queryset(channel).aggregate(earliest=Min("date"), latest=Max("date"))
        if not agg["earliest"]:
            return own
        fwd_first = timezone.localtime(agg["earliest"]).strftime("%Y-%m")
        fwd_last = timezone.localtime(agg["latest"]).strftime("%Y-%m")
        start = min(own[0], fwd_first) if own else fwd_first
        end = max(own[-1], fwd_last) if own else fwd_last
        return pd.period_range(start=start, end=end, freq="M").strftime("%Y-%m").tolist()

    def get_annotation(self) -> Count:
        return Count("id")


class ChannelAvgInvolvementHistoryView(_ChannelTimeSeriesBase):
    annotate_field = "avg_involvement"
    y_label = "avg views"

    def get_annotation(self) -> Avg:
        return Avg("views", default=0)

    def post_process_value(self, value: Any) -> int:
        return round(value)


class ChannelCrossRefsView(_ChannelTimeSeriesBase):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        in_target_pks = Channel.objects.in_target().values("pk")

        from network.utils import channel_cutoff_q

        fwd_out = Counter(
            self._msg_qs(channel, forwarded_from__isnull=False)
            .exclude(forwarded_from=channel)
            .values_list("forwarded_from", flat=True)
        )
        ref_out = Counter(
            cpk
            for cpk in self._msg_qs(channel).values_list("references", flat=True)
            if cpk is not None and cpk != channel.pk
        )
        mentioned = fwd_out + ref_out

        fwd_in = Counter(
            Message.objects.alive()
            .filter(channel__in=in_target_pks, forwarded_from=channel)
            .filter(channel_cutoff_q())
            # Like the other three legs: the subject must not list itself.
            .exclude(channel=channel)
            .values_list("channel", flat=True)
        )
        ref_in = Counter(
            Message.objects.alive()
            .filter(channel__in=in_target_pks, references=channel)
            .filter(channel_cutoff_q())
            .exclude(channel=channel)
            .values_list("channel", flat=True)
        )
        mentioning = fwd_in + ref_in

        all_pks = [cpk for cpk in set(mentioned) | set(mentioning) if cpk is not None]
        channel_map = {
            c.pk: {"title": c.title or str(c.telegram_id), "url": c.get_absolute_url(), "telegram_url": c.telegram_url}
            for c in Channel.objects.filter(pk__in=all_pks)
        }

        def serialize(counter: Counter) -> list[dict]:
            return [
                {
                    "title": channel_map.get(cpk, {}).get("title", str(cpk)),
                    "url": channel_map.get(cpk, {}).get("url", ""),
                    "telegram_url": channel_map.get(cpk, {}).get("telegram_url", ""),
                    "count": count,
                }
                for cpk, count in counter.most_common()
                if cpk is not None
            ]

        return JsonResponse({"mentioned": serialize(mentioned), "mentioning": serialize(mentioning)})


class ReactionsHistoryDataView(View):
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        spine = global_month_spine()
        if not spine:
            return JsonResponse({"labels": [], "series": [], "y_label": "reactions"})

        from network.utils import channel_cutoff_q

        in_target_pks = _scoped_in_target_channels(request).values("pk")
        cutoff_q = channel_cutoff_q(channel_field="message__channel", date_field="message__date")

        top_emojis_qs = (
            MessageReaction.objects.filter(
                message__channel__in=in_target_pks, message__date__isnull=False, message__is_lost=False
            )
            .filter(cutoff_q)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:8]
        )
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        monthly = (
            MessageReaction.objects.filter(
                message__channel__in=in_target_pks,
                message__date__isnull=False,
                message__is_lost=False,
                emoji__in=top_emojis,
            )
            .filter(cutoff_q)
            .annotate(month=TruncMonth("message__date"))
            .values("month", "emoji")
            .annotate(total=Sum("count"))
            .order_by("month", "emoji")
        )
        rows = [{"month": r["month"].strftime("%Y-%m"), "emoji": r["emoji"], "total": r["total"]} for r in monthly]
        df = pd.DataFrame(rows)
        if not df.empty:
            pivot = df.pivot_table(index="month", columns="emoji", values="total", aggfunc="sum", fill_value=0)
            pivot = pivot.reindex(spine, fill_value=0)
            pivot = pivot.reindex(columns=top_emojis, fill_value=0)
        else:
            pivot = pd.DataFrame(0, index=spine, columns=top_emojis)
            pivot.index.name = "month"

        series = [
            {"emoji": emoji_present(emoji), "values": [int(v) for v in pivot[emoji].tolist()]} for emoji in top_emojis
        ]
        return JsonResponse({"labels": spine, "series": series, "y_label": "reactions"})


class ChannelReactionsHistoryView(View):
    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        channel = get_object_or_404(Channel, pk=pk)
        spine = channel_month_spine(channel)
        if not spine:
            return JsonResponse({"labels": [], "series": [], "y_label": "reactions"})

        from network.utils import channel_period_date_q

        period_q = channel_period_date_q(channel, "message__date") if channel.in_target_periods.exists() else None
        top_emojis_qs = MessageReaction.objects.filter(
            message__channel=channel, message__date__isnull=False, message__is_lost=False
        )
        if period_q is not None:
            top_emojis_qs = top_emojis_qs.filter(period_q)
        top_emojis_qs = top_emojis_qs.values("emoji").annotate(total=Sum("count")).order_by("-total")[:8]
        top_emojis = [r["emoji"] for r in top_emojis_qs]
        if not top_emojis:
            return JsonResponse({"labels": spine, "series": [], "y_label": "reactions"})

        monthly_qs = MessageReaction.objects.filter(
            message__channel=channel,
            message__date__isnull=False,
            message__is_lost=False,
            emoji__in=top_emojis,
        )
        if period_q is not None:
            monthly_qs = monthly_qs.filter(period_q)
        monthly = (
            monthly_qs.annotate(month=TruncMonth("message__date"))
            .values("month", "emoji")
            .annotate(total=Sum("count"))
            .order_by("month", "emoji")
        )
        rows = [{"month": r["month"].strftime("%Y-%m"), "emoji": r["emoji"], "total": r["total"]} for r in monthly]
        df = pd.DataFrame(rows)
        if not df.empty:
            pivot = df.pivot_table(index="month", columns="emoji", values="total", aggfunc="sum", fill_value=0)
            pivot = pivot.reindex(spine, fill_value=0)
            pivot = pivot.reindex(columns=top_emojis, fill_value=0)
        else:
            pivot = pd.DataFrame(0, index=spine, columns=top_emojis)
            pivot.index.name = "month"

        series = [
            {"emoji": emoji_present(emoji), "values": [int(v) for v in pivot[emoji].tolist()]} for emoji in top_emojis
        ]
        return JsonResponse({"labels": spine, "series": series, "y_label": "reactions"})


class ChannelContactInfoView(View):
    """The web sites a channel links to (``network.links``: one count per message and site, hidden links,
    buttons and previews included, t.me left out) and the e-mail addresses in its texts."""

    def get(self, request: HttpRequest, pk: int, *args: Any, **kwargs: Any) -> JsonResponse:
        from network.links import link_candidates_q, message_sites

        channel = get_object_or_404(Channel, pk=pk)
        msg_qs = Message.objects.alive().filter(channel=channel)
        if channel.in_target_periods.exists():
            from network.utils import channel_period_date_q

            msg_qs = msg_qs.filter(channel_period_date_q(channel))
        domain_counter: Counter = Counter()
        email_counter: Counter = Counter()
        for text, webpage_url, link_urls in msg_qs.filter(link_candidates_q() | Q(message__contains="@")).values_list(
            "message", "webpage_url", "link_urls"
        ):
            domain_counter.update(message_sites(text, webpage_url, link_urls))
            for email in _EMAIL_RE.findall(text or ""):
                email_counter[email.lower()] += 1
        return JsonResponse(
            {
                "domains": [{"domain": d, "count": c} for d, c in domain_counter.most_common()],
                "emails": [{"email": e, "count": c} for e, c in email_counter.most_common()],
            }
        )

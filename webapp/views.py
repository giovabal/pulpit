import datetime
import math
import re as _re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Max, Min, Prefetch, Q, QuerySet, Sum
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import ListView, TemplateView
from django.views.static import serve as _static_serve

from webapp.paginator import DiggPaginator

from .models import Channel, ChannelGroup, ChannelVacancy, Message, MessageReaction, Organization, ProfilePicture
from .utils.channel_types import channel_type_filter
from .utils.dates import fmt_date

# ---- message list options ------------------------------------------------

_CONTENT_TYPES = ["text", "image", "video", "sound", "other"]

_CONTENT_TYPE_Q: dict[str, Q] = {
    "text": Q(media_type=""),
    "image": Q(media_type="photo"),
    "video": Q(media_type="video"),
    "sound": Q(media_type="audio"),
    "other": ~Q(media_type__in=["", "photo", "video", "audio"]),
}


def _apply_message_options(qs: QuerySet, params: Any) -> QuerySet:
    sort = params.get("sort", "asc")
    qs = qs.order_by("date" if sort == "asc" else "-date")
    selected = [t for t in params.getlist("type") if t in _CONTENT_TYPE_Q]
    if selected and set(selected) != set(_CONTENT_TYPES):
        type_q: Q = Q(pk__in=[])
        for t in selected:
            type_q |= _CONTENT_TYPE_Q[t]
        qs = qs.filter(type_q)
    return qs


def _message_options_context(params: Any) -> dict[str, Any]:
    sort = params.get("sort", "asc")
    selected = [t for t in params.getlist("type") if t in _CONTENT_TYPE_Q]
    if not selected:
        selected = list(_CONTENT_TYPES)
    options_active = sort != "asc" or set(selected) != set(_CONTENT_TYPES)

    extra: dict[str, Any] = {}
    if params.get("q"):
        extra["q"] = params["q"]
    if sort != "asc":
        extra["sort"] = sort
    if set(selected) != set(_CONTENT_TYPES):
        extra["type"] = selected
    original_query = ("&" + urlencode(extra, doseq=True)) if extra else ""

    return {
        "sort": sort,
        "selected_types": selected,
        "all_types": _CONTENT_TYPES,
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
        if not q:
            return Message.objects.none()
        qs = (
            Message.objects.filter(channel__in=Channel.objects.interesting())
            .select_related("channel", "channel__organization", "forwarded_from")
            .filter(message__icontains=q)
        )
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        ctx = super().get_context_data(*args, **kwargs)

        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        ctx.update(_message_options_context(self.request.GET))

        interesting_qs = Channel.objects.interesting()
        interesting_channels = interesting_qs.count()
        interesting_msgs = Message.objects.filter(channel__in=interesting_qs.values("pk"))
        total_messages = interesting_msgs.count()
        total_subscribers = (
            interesting_qs.filter(participants_count__isnull=False).aggregate(total=Sum("participants_count"))["total"]
            or 0
        )
        date_agg = interesting_msgs.filter(date__isnull=False).aggregate(earliest=Min("date"), latest=Max("date"))
        total_forwards = interesting_msgs.filter(forwarded_from__isnull=False).count()

        ctx["summary"] = [
            {"icon": "bi-broadcast", "label": "Channels", "value": f"{interesting_channels:,}"},
            {"icon": "bi-chat-left-text", "label": "Messages collected", "value": f"{total_messages:,}"},
            {"icon": "bi-people", "label": "Total subscribers", "value": f"{total_subscribers:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
                "note": "first message - last message",
            },
            {
                "icon": "bi-forward",
                "label": "Forwards",
                "value": f"{total_forwards:,}",
                "note": "cross-channel amplifications",
            },
        ]
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
                "id": "subscribers-history",
                "title": "Cumulative subscribers",
                "icon": "bi-people",
                "url": reverse("subscribers-history-data"),
                "description": "Total subscriber count across all monitored channels, accumulated over time. Each channel is counted from its first observed subscriber figure.",
            },
            {
                "id": "avg-involvement-history",
                "title": "Average involvement per month",
                "icon": "bi-graph-up",
                "url": reverse("avg-involvement-history-data"),
                "description": "Average number of views per message across monitored channels each month. A proxy for audience engagement intensity.",
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
            Channel.objects.interesting()
            .select_related("organization")
            .prefetch_related(self._pic_prefetch, "groups")
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
            Channel.objects.filter(organization__is_interesting=True)
            .select_related("organization")
            .prefetch_related(self._pic_prefetch)
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )
        ctx["excluded_list"] = (
            Channel.objects.filter(organization__is_interesting=True)
            .exclude(channel_type_filter(settings.DEFAULT_CHANNEL_TYPES))
            .exclude(is_lost=True)
            .exclude(is_private=True)
            .select_related("organization")
            .prefetch_related(self._pic_prefetch)
            .annotate(
                messages_count=Count("message_set"),
                first_message_date=Min("message_set__date"),
                last_message_date=Max("message_set__date"),
            )
            .order_by("title")
        )
        ctx["lost_list"] = _status_qs.filter(is_lost=True)
        ctx["private_list"] = _status_qs.filter(is_private=True)
        ctx["organizations"] = Organization.objects.filter(is_interesting=True).order_by("name")
        ctx["groups"] = (
            ChannelGroup.objects.filter(channels__in=Channel.objects.interesting()).distinct().order_by("name")
        )
        return ctx


class VacanciesView(TemplateView):
    template_name = "webapp/vacancies.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        rows = []
        for vac in ChannelVacancy.objects.select_related("channel__organization").order_by("-death_date"):
            ch = vac.channel
            orphaned_count = Channel.objects.interesting().filter(message_set__forwarded_from=ch).distinct().count()
            rows.append({"vacancy": vac, "channel": ch, "orphaned_amplifier_count": orphaned_count})
        ctx["vacancies"] = rows
        return ctx


def serve_export(request: HttpRequest, name: str, path: str = "") -> HttpResponse:
    """Serve static files from BASE_DIR/exports/{name}/ (development only)."""
    if not _re.match(r"^[\w\-]+$", name):
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
        qs = Message.objects.filter(channel__in=Channel.objects.interesting()).select_related(
            "channel", "channel__organization", "forwarded_from"
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(message__icontains=q)
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(*args, **kwargs)
        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        ctx.update(_message_options_context(self.request.GET))
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
        qs = (
            Message.objects.filter(channel=self.selected_channel)
            .select_related("forwarded_from")
            .prefetch_related("references", "reactions")
        )
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(message__icontains=q)
        return _apply_message_options(qs, self.request.GET)

    def get_context_data(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from django.urls import reverse

        context_data = super().get_context_data(*args, **kwargs)
        ch = self.selected_channel
        q = self.request.GET.get("q", "").strip()
        context_data["query"] = q
        context_data.update(_message_options_context(self.request.GET))

        is_interesting = Channel.objects.interesting().filter(pk=ch.pk).exists()

        msg_qs = Message.objects.filter(channel=ch)
        total_messages = msg_qs.count()
        total_views = msg_qs.aggregate(total=Sum("views"))["total"] or 0
        total_forwards_sent = msg_qs.filter(forwarded_from__isnull=False).count()
        total_forwards_received = Message.objects.filter(
            channel__in=Channel.objects.interesting().values("pk"), forwarded_from=ch
        ).count()
        date_agg = msg_qs.filter(date__isnull=False).aggregate(earliest=Min("date"), latest=Max("date"))

        summary = [
            {"icon": "bi-chat-left-text", "label": "Messages", "value": f"{total_messages:,}"},
            {"icon": "bi-eye", "label": "Total views", "value": f"{total_views:,}"},
            {
                "icon": "bi-calendar-range",
                "label": "Date range",
                "value": f"{fmt_date(date_agg['earliest'])} – {fmt_date(date_agg['latest'])}",
            },
            {
                "icon": "bi-forward",
                "label": "Forwards sent",
                "value": f"{total_forwards_sent:,}",
                "note": "to other channels",
            },
            {
                "icon": "bi-arrow-return-right",
                "label": "Forwards received",
                "value": f"{total_forwards_received:,}",
                "note": "from other channels",
            },
        ]
        top_reactions_qs = (
            MessageReaction.objects.filter(message__channel=ch)
            .values("emoji")
            .annotate(total=Sum("count"))
            .order_by("-total")[:10]
        )
        top_reactions = [{"emoji": r["emoji"], "total": f"{r['total']:,}"} for r in top_reactions_qs]
        total_reactions = sum(int(r["total"].replace(",", "")) for r in top_reactions)
        if total_reactions:
            summary.append({"icon": "bi-emoji-smile", "label": "Total reactions", "value": f"{total_reactions:,}"})

        if not is_interesting:
            for card in summary[:-1]:
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

        if not is_interesting:
            panels = [p for p in panels if p["id"] == "ch-cross-refs"]

        try:
            vacancy = ch.vacancy
        except ChannelVacancy.DoesNotExist:
            vacancy = None

        context_data.update(
            {
                "selected_channel": ch,
                "summary": summary,
                "panels": panels,
                "is_interesting": is_interesting,
                "top_reactions": top_reactions,
                "channel_groups": list(ch.groups.order_by("name")),
                "vacancy": vacancy,
            }
        )
        return context_data


def _shift_months(d: datetime.date, n: int) -> datetime.date:
    import calendar

    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


class VacancyAnalysisView(View):
    """JSON endpoint: replacement candidates for a vacancy channel."""

    def get(self, request: HttpRequest, pk: int) -> JsonResponse:
        ch = get_object_or_404(Channel, pk=pk)
        try:
            vacancy = ch.vacancy
        except ChannelVacancy.DoesNotExist:
            return JsonResponse({"error": "no vacancy for this channel"}, status=404)

        try:
            months_before = max(1, int(request.GET.get("months_before", 12)))
            months_after = max(1, int(request.GET.get("months_after", 12)))
        except (TypeError, ValueError):
            return JsonResponse({"error": "invalid parameters"}, status=400)
        only_after_vacancy = request.GET.get("only_after_vacancy", "1") != "0"

        death = vacancy.death_date
        before_start = datetime.datetime.combine(
            _shift_months(death, -months_before), datetime.time.min, tzinfo=datetime.timezone.utc
        )
        death_dt = datetime.datetime.combine(death, datetime.time.min, tzinfo=datetime.timezone.utc)
        after_end = datetime.datetime.combine(
            _shift_months(death, months_after), datetime.time.max, tzinfo=datetime.timezone.utc
        )

        orphaned = (
            Channel.objects.interesting()
            .filter(
                message_set__forwarded_from=ch,
                message_set__date__gte=before_start,
                message_set__date__lt=death_dt,
            )
            .distinct()
        )
        orphaned_pks: set[int] = set(orphaned.values_list("pk", flat=True))
        total_orphaned = len(orphaned_pks)

        raw = list(
            Message.objects.filter(
                channel__in=orphaned_pks,
                forwarded_from__in=Channel.objects.interesting(),
                date__gte=death_dt,
                date__lte=after_end,
            )
            .exclude(forwarded_from=ch)
            .values("forwarded_from")
            .annotate(amplifier_count=Count("channel", distinct=True), last_forwarded=Max("date"))
            .order_by("-amplifier_count")[:30]
        )

        cand_ids = [r["forwarded_from"] for r in raw]
        cand_map = {r["forwarded_from"]: r for r in raw}
        cand_qs = (
            Channel.objects.filter(pk__in=cand_ids)
            .select_related("organization")
            .annotate(first_msg=Min("message_set__date"))
        )
        if only_after_vacancy:
            cand_qs = cand_qs.filter(first_msg__gte=death_dt)
        cand_channels = {c.pk: c for c in cand_qs}

        # ── Extra queries for strategies A / B / C ────────────────────────
        # Strategy B: vacancy's out-neighbors (sources it forwarded from) before death
        vac_out_rows = (
            Message.objects.filter(
                channel=ch,
                forwarded_from__isnull=False,
                date__gte=before_start,
                date__lt=death_dt,
            )
            .values("forwarded_from_id", "forwarded_from__organization_id")
            .distinct()
        )
        vacancy_out_pks: set[int] = set()
        vacancy_src_org_pks: set[int] = set()
        for r in vac_out_rows:
            vacancy_out_pks.add(r["forwarded_from_id"])
            if r["forwarded_from__organization_id"]:
                vacancy_src_org_pks.add(r["forwarded_from__organization_id"])

        # Strategy C: vacancy's amplifier orgs (orgs of orphaned channels)
        orphaned_org_map: dict[int, int] = dict(
            orphaned.filter(organization__isnull=False).values_list("pk", "organization_id")
        )
        vacancy_amp_org_pks: set[int] = set(orphaned_org_map.values())
        vacancy_org_pairs: frozenset[tuple[int, int]] = frozenset(
            (s, a) for s in vacancy_src_org_pks for a in vacancy_amp_org_pks
        )

        # Strategy B+C: each candidate's out-neighbors with orgs (batched)
        cand_out_rows = (
            Message.objects.filter(
                channel__in=list(cand_channels),
                forwarded_from__isnull=False,
                date__gte=death_dt,
                date__lte=after_end,
            )
            .values("channel_id", "forwarded_from_id", "forwarded_from__organization_id")
            .distinct()
        )
        cand_out_pks: dict[int, set[int]] = defaultdict(set)
        cand_src_org_pks: dict[int, set[int]] = defaultdict(set)
        for r in cand_out_rows:
            cand_out_pks[r["channel_id"]].add(r["forwarded_from_id"])
            if r["forwarded_from__organization_id"]:
                cand_src_org_pks[r["channel_id"]].add(r["forwarded_from__organization_id"])

        # Strategy C: which orphaned channels forward each candidate (for amp orgs)
        cand_amp_rows = (
            Message.objects.filter(
                channel__in=orphaned_pks,
                forwarded_from__in=list(cand_channels),
                date__gte=death_dt,
                date__lte=after_end,
            )
            .values("forwarded_from_id", "channel_id")
            .distinct()
        )
        cand_amp_org_pks: dict[int, set[int]] = defaultdict(set)
        for r in cand_amp_rows:
            org = orphaned_org_map.get(r["channel_id"])
            if org:
                cand_amp_org_pks[r["forwarded_from_id"]].add(org)

        def _cosine(a: set, b: set) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / (math.sqrt(len(a)) * math.sqrt(len(b)))

        def _jaccard(a: frozenset, b: frozenset) -> float:
            union = a | b
            return len(a & b) / len(union) if union else 0.0

        # ── Build candidate list ──────────────────────────────────────────
        candidates = []
        for cid in cand_ids:
            c = cand_channels.get(cid)
            if not c:
                continue
            amp_count: int = cand_map[cid]["amplifier_count"]
            lf = cand_map[cid]["last_forwarded"]
            fm = c.first_msg

            # A — Jaccard amplifier similarity
            score_a = round(amp_count / total_orphaned, 3) if total_orphaned else 0.0

            # B — Structural equivalence (cosine in + cosine out, equal weight)
            cos_in = math.sqrt(score_a)  # sqrt(amp_count / total_orphaned)
            cos_out = _cosine(vacancy_out_pks, cand_out_pks.get(cid, set()))
            score_b = round(0.5 * cos_in + 0.5 * cos_out, 3)

            # C — Brokerage role (Jaccard of organisation-pair sets)
            cand_org_pairs = frozenset(
                (s, a) for s in cand_src_org_pks.get(cid, set()) for a in cand_amp_org_pks.get(cid, set())
            )
            score_c: float | None = round(_jaccard(vacancy_org_pairs, cand_org_pairs), 3) if vacancy_org_pairs else None

            candidates.append(
                {
                    "pk": c.pk,
                    "title": c.title,
                    "url": c.get_absolute_url(),
                    "org_color": c.organization.color if c.organization else None,
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

        return JsonResponse(
            {
                "candidates": candidates,
                "orphaned_count": total_orphaned,
                "months_before": months_before,
                "months_after": months_after,
                "only_after_vacancy": only_after_vacancy,
            }
        )

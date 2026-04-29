import json
import re as _re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Count, Max, Min, Q, QuerySet, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import ListView, TemplateView
from django.views.static import serve as _static_serve

from webapp.paginator import DiggPaginator

from .models import Channel, Message, MessageReaction, Organization
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

    def get_queryset(self) -> QuerySet[Channel]:
        return (
            Channel.objects.interesting()
            .select_related("organization")
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
        return ctx


def _find_exports() -> list[dict]:
    """Return all available exports (named + default graph/), newest first."""
    exports: list[dict] = []

    def _read_summary(path: Path) -> dict:
        summary = path / "summary.json"
        if not summary.exists():
            return {}
        try:
            return json.loads(summary.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    # Named exports from BASE_DIR/exports/*/
    exports_root = Path(settings.BASE_DIR) / "exports"
    try:
        for item in sorted(exports_root.iterdir()):
            if not item.is_dir() or not (item / "index.html").exists():
                continue
            data = _read_summary(item)
            exports.append(
                {
                    "name": item.name,
                    "label": item.name,
                    "created_at": data.get("created_at"),
                    "nodes": data.get("nodes"),
                    "edges": data.get("edges"),
                    "path": item,
                    "url_prefix": f"/exports/{item.name}/",
                }
            )
    except (PermissionError, OSError):
        pass

    # Default graph/ export
    default_path = Path(settings.BASE_DIR) / settings.GRAPH_OUTPUT_DIR
    if (default_path / "index.html").exists():
        data = _read_summary(default_path)
        exports.append(
            {
                "name": "__default__",
                "label": "Default",
                "created_at": data.get("created_at"),
                "nodes": data.get("nodes"),
                "edges": data.get("edges"),
                "path": default_path,
                "url_prefix": f"/{settings.GRAPH_OUTPUT_DIR}/",
            }
        )

    exports.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return exports


def serve_export(request: HttpRequest, name: str, path: str = "") -> HttpResponse:
    """Serve static files from BASE_DIR/exports/{name}/ (development only)."""
    if not _re.match(r"^[\w\-]+$", name):
        raise Http404
    doc_root = Path(settings.BASE_DIR) / "exports" / name
    if not doc_root.is_dir():
        raise Http404
    return _static_serve(request, path or "index.html", document_root=str(doc_root))


class DataView(TemplateView):
    template_name = "webapp/data.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        docs_base = "https://github.com/giovabal/pulpit/blob/main/ANALYSIS.md"

        all_exports = _find_exports()

        requested = self.request.GET.get("export", "")
        current: dict | None = None
        if requested:
            current = next((e for e in all_exports if e["name"] == requested), None)
        if current is None and all_exports:
            current = all_exports[0]

        if current:
            graph_dir: Path = current["path"]
            prefix: str = current["url_prefix"]
        else:
            graph_dir = Path(settings.BASE_DIR) / settings.GRAPH_OUTPUT_DIR
            prefix = f"/{settings.GRAPH_OUTPUT_DIR}/"

        maps = []
        if (graph_dir / "graph.html").exists():
            maps.append(
                {
                    "title": "2D Network map",
                    "icon": "bi-map",
                    "description": "Interactive force-directed graph. Nodes are channels; edges represent forwards and mentions. Color encodes community membership.",
                    "url": f"{prefix}graph.html",
                    "action": "Open map",
                }
            )
        if (graph_dir / "graph3d.html").exists():
            maps.append(
                {
                    "title": "3D Network map",
                    "icon": "bi-box",
                    "description": "3D force-directed graph rendered with Three.js. Rotate, zoom, and pan with mouse. Click a node to inspect its connections.",
                    "url": f"{prefix}graph3d.html",
                    "action": "Open 3D map",
                }
            )

        tables = []
        if (graph_dir / "channel_table.html").exists():
            tables.append(
                {
                    "title": "Channels",
                    "icon": "bi-table",
                    "description": "One row per channel. Columns include degree, activity metrics, computed node measures (PageRank, Burt's constraint, …) and community assignments.",
                    "url": f"{prefix}channel_table.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#network-measures",
                }
            )
        if (graph_dir / "community_table.html").exists():
            tables.append(
                {
                    "title": "Community statistics",
                    "icon": "bi-diagram-3",
                    "description": "Structural metrics per detected community: size, internal/external edges, density, reciprocity, clustering, path length.",
                    "url": f"{prefix}community_table.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#community-detection-strategies",
                }
            )
        if (graph_dir / "network_table.html").exists():
            tables.append(
                {
                    "title": "Network statistics",
                    "icon": "bi-bar-chart",
                    "description": "Whole-network structural metrics: size, density, reciprocity, clustering, path length, diameter, modularity per strategy.",
                    "url": f"{prefix}network_table.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#whole-network-measures",
                }
            )

        compare_maps = []
        if (graph_dir / "graph_2.html").exists():
            compare_maps.append(
                {
                    "title": "2D Network map (comparison)",
                    "icon": "bi-map",
                    "description": "Interactive force-directed graph for the comparison dataset.",
                    "url": f"{prefix}graph_2.html",
                    "action": "Open map",
                }
            )
        if (graph_dir / "graph3d_2.html").exists():
            compare_maps.append(
                {
                    "title": "3D Network map (comparison)",
                    "icon": "bi-box",
                    "description": "3D force-directed graph for the comparison dataset.",
                    "url": f"{prefix}graph3d_2.html",
                    "action": "Open 3D map",
                }
            )

        compare_highlight = []
        if (graph_dir / "network_compare_table.html").exists():
            compare_highlight.append(
                {
                    "title": "Network comparison",
                    "icon": "bi-intersect",
                    "description": "Side-by-side whole-network metrics for the two datasets.",
                    "url": f"{prefix}network_compare_table.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#whole-network-measures",
                }
            )

        compare_tables = []
        if (graph_dir / "channel_table_2.html").exists():
            compare_tables.append(
                {
                    "title": "Channels (comparison)",
                    "icon": "bi-table",
                    "description": "Per-channel measures and community assignments for the comparison dataset.",
                    "url": f"{prefix}channel_table_2.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#network-measures",
                }
            )
        if (graph_dir / "community_table_2.html").exists():
            compare_tables.append(
                {
                    "title": "Community statistics (comparison)",
                    "icon": "bi-diagram-3",
                    "description": "Structural metrics per community for the comparison dataset.",
                    "url": f"{prefix}community_table_2.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#community-detection-strategies",
                }
            )
        if (graph_dir / "network_table_2.html").exists():
            compare_tables.append(
                {
                    "title": "Network statistics (comparison)",
                    "icon": "bi-bar-chart",
                    "description": "Whole-network structural metrics for the comparison dataset.",
                    "url": f"{prefix}network_table_2.html",
                    "action": "Open table",
                    "docs_url": f"{docs_base}#whole-network-measures",
                }
            )

        ctx["all_exports"] = all_exports
        ctx["current_export"] = current
        ctx["maps"] = maps
        ctx["tables"] = tables
        ctx["compare_highlight"] = compare_highlight
        ctx["compare_maps"] = compare_maps
        ctx["compare_tables"] = compare_tables
        ctx["graph_available"] = bool(maps or tables or compare_highlight or compare_maps or compare_tables)
        return ctx


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

        context_data.update(
            {
                "selected_channel": ch,
                "summary": summary,
                "panels": panels,
                "is_interesting": is_interesting,
                "top_reactions": top_reactions,
            }
        )
        return context_data

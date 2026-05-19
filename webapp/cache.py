"""Cache helpers for slow webapp pages.

Home page ecosystem summary:
  * 5 sequential aggregates that each scan most of the Message table (channel
    count, total messages, date range, subscriber sum, distinct forward-edges,
    reply count). Cold-render cost is 200–500 ms on a real corpus.
  * Cached under :data:`HOME_SUMMARY_CACHE_KEY` for
    :data:`HOME_SUMMARY_CACHE_TIMEOUT` seconds.
  * Invalidated at the start of every ``crawl_channels`` run via
    :func:`invalidate_home_summary_cache` so freshly fetched data shows up
    on the next home-page hit.

Cache backend: :file:`webapp_engine/settings.py` configures a
``FileBasedCache`` so the management-command process (which writes the
data) and the runserver/gunicorn process (which renders the page) share
the same cache; an in-memory backend wouldn't survive the process boundary.
"""

from django.core.cache import cache
from django.db.models import Count, Max, Min, Q, Sum

from webapp.models import Channel, Message, MessageReply
from webapp.utils.dates import fmt_date

HOME_SUMMARY_CACHE_KEY = "pulpit:home:summary"
HOME_SUMMARY_CACHE_TIMEOUT = 3600  # 1 hour


def compute_home_summary() -> list[dict]:
    """Build the 5 ecosystem-stat cards shown on the home page.

    Called on a cache miss (cold first hit after a crawl) and never inside
    a request loop. Returns a list of presentation-ready dicts so the
    template can render without further DB access.
    """
    in_target_qs = Channel.objects.in_target()
    in_target_channels = in_target_qs.count()
    in_target_msgs = Message.objects.alive().filter(channel__in=in_target_qs.values("pk"))
    msg_agg = in_target_msgs.aggregate(
        total=Count("id"),
        earliest=Min("date"),
        latest=Max("date"),
        forwards=Count("id", filter=Q(forwarded_from__isnull=False)),
    )
    total_messages = msg_agg["total"] or 0
    total_forwards = msg_agg["forwards"] or 0
    total_subscribers = (
        in_target_qs.filter(participants_count__isnull=False).aggregate(total=Sum("participants_count"))["total"] or 0
    )
    total_forward_edges = (
        in_target_msgs.filter(forwarded_from__in=in_target_qs.values("pk"))
        .values("channel_id", "forwarded_from_id")
        .distinct()
        .count()
    )
    total_replies = MessageReply.objects.filter(
        parent_message__channel__in=in_target_qs.values("pk"), parent_message__is_lost=False
    ).count()
    return [
        {"icon": "bi-broadcast", "label": "Channels", "value": f"{in_target_channels:,}"},
        {
            "icon": "bi-chat-left-text",
            "label": "Messages collected",
            "value": f"{total_messages:,}",
            "secondary": [{"value": f"{total_replies:,}", "label": "replies"}],
        },
        {"icon": "bi-people", "label": "Total subscribers", "value": f"{total_subscribers:,}"},
        {
            "icon": "bi-calendar-range",
            "label": "Date range",
            "value": f"{fmt_date(msg_agg['earliest'])} – {fmt_date(msg_agg['latest'])}",
            "note": "first message - last message",
        },
        {
            "icon": "bi-forward",
            "label": "Forwards",
            "value": f"{total_forwards:,}",
            "note": "cross-channel amplifications",
            "secondary": [{"value": f"{total_forward_edges:,}", "label": "distinct connections"}],
        },
    ]


def get_home_summary() -> list[dict]:
    """Return the cached summary, computing on miss."""
    return cache.get_or_set(HOME_SUMMARY_CACHE_KEY, compute_home_summary, HOME_SUMMARY_CACHE_TIMEOUT)


def invalidate_home_summary_cache() -> None:
    """Drop the cached summary so the next render rebuilds from current data."""
    cache.delete(HOME_SUMMARY_CACHE_KEY)

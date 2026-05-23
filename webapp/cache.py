"""Cache helpers for slow webapp pages.

Home page ecosystem summary (two rows of cards):
  * Row 1 (5 cards): channels (with to_inspect count), messages (with replies),
    media (with per-type breakdown), total views (with subscribers), date range.
  * Row 2 (4 cards): forwards / mentions sent and received across the in-target
    set, with self / in-target / out-of-target splits — mirrors the channel
    detail engagement row.
  * ~10 sequential aggregates that each scan most of the Message and
    message_references tables. Cold-render cost is roughly 400-800 ms on a
    real corpus.
  * Cached under :data:`HOME_SUMMARY_CACHE_KEY` for
    :data:`HOME_SUMMARY_CACHE_TIMEOUT` seconds.
  * Invalidated at the start of every ``crawl_channels`` run via
    :func:`invalidate_home_summary_cache` so freshly fetched data shows up
    on the next home-page hit.
  * Aggregates do not honour ``Channel.out_of_target_after``: per-channel
    date caps would require joining Channel for every Message row, so home
    totals may diverge from the sum of per-channel detail-page totals when
    any in-target channel has ``out_of_target_after`` set.

Cache backend: :file:`webapp_engine/settings.py` configures a
``FileBasedCache`` so the management-command process (which writes the
data) and the runserver/gunicorn process (which renders the page) share
the same cache; an in-memory backend wouldn't survive the process boundary.
"""

from django.core.cache import cache
from django.db.models import Count, F, Max, Min, Q, Sum

from webapp.models import Channel, Message, MessageReply
from webapp.utils.dates import fmt_date

# Suffix bumped to :v2 when the return shape changed from list[dict] to
# list[list[dict]]; old entries become orphans and the FileBasedCache evicts
# them on its own schedule.
HOME_SUMMARY_CACHE_KEY = "pulpit:home:summary:v2"
HOME_SUMMARY_CACHE_TIMEOUT = 3600  # 1 hour


def _channels_phrase(prefix: str, count: int, kind: str) -> str:
    word = "channel" if count == 1 else "channels"
    return f"{prefix} <strong>{count:,}</strong> {kind} {word}"


def compute_home_summary() -> list[list[dict]]:
    """Build the two rows of ecosystem-stat cards shown on the home page.

    Called on a cache miss (cold first hit after a crawl) and never inside
    a request loop. Returns two card-row lists, ready for the template to
    render without further DB access.
    """
    in_target_qs = Channel.objects.in_target()
    in_target_pks = in_target_qs.values("pk")
    in_target_channels = in_target_qs.count()
    to_inspect_count = Channel.objects.filter(to_inspect=True).exclude(pk__in=in_target_pks).count()

    msgs = Message.objects.alive().filter(channel__in=in_target_pks)

    # Row 1 — single consolidated aggregate over the in-target Message set.
    media_known_types = ["photo", "video", "audio", "sticker"]
    msg_agg = msgs.aggregate(
        total=Count("id"),
        earliest=Min("date"),
        latest=Max("date"),
        views=Sum("views"),
        pictures=Count("id", filter=Q(media_type="photo")),
        videos=Count("id", filter=Q(media_type="video")),
        audio=Count("id", filter=Q(media_type="audio")),
        stickers=Count("id", filter=Q(media_type="sticker")),
        other=Count("id", filter=~Q(media_type__in=["", *media_known_types])),
    )
    total_messages = msg_agg["total"] or 0
    total_views = msg_agg["views"] or 0
    media_breakdown = [
        (msg_agg["pictures"], "picture", "pictures"),
        (msg_agg["videos"], "video", "videos"),
        (msg_agg["audio"], "audio", "audio"),
        (msg_agg["stickers"], "sticker", "stickers"),
        (msg_agg["other"], "other", "other"),
    ]
    total_media = sum(n for n, *_ in media_breakdown)
    total_subscribers = (
        in_target_qs.filter(participants_count__isnull=False).aggregate(total=Sum("participants_count"))["total"] or 0
    )
    total_replies = MessageReply.objects.filter(
        parent_message__channel__in=in_target_pks, parent_message__is_lost=False
    ).count()

    # Row 2 — forwards. Across the in-target set, every in-target-to-in-target
    # forward is one Message row counted both from the sender's perspective
    # (Forwards sent, in-target) and the receiver's (Forwards received), so the
    # two headline counts are numerically equal. The cards stay distinct because
    # their secondaries differ ("from N senders" vs "by N receivers"). Reuse the
    # row count rather than running a redundant query — same logic for mentions.
    fwd_in_target_filter = Q(forwarded_from__in=in_target_pks) & ~Q(forwarded_from=F("channel"))
    fwd_agg = msgs.aggregate(
        sent_in_target=Count("id", filter=fwd_in_target_filter),
        sent_self=Count("id", filter=Q(forwarded_from=F("channel"))),
        sent_oot=Count(
            "id",
            filter=Q(forwarded_from__isnull=False) & ~Q(forwarded_from__in=in_target_pks),
        ),
    )
    fwd_in_target_msgs = msgs.filter(fwd_in_target_filter)
    fwd_oot_msgs = msgs.filter(forwarded_from__isnull=False).exclude(forwarded_from__in=in_target_pks)
    fwd_sent_in_target_channels = fwd_in_target_msgs.values("forwarded_from").distinct().count()
    fwd_sent_oot_channels = fwd_oot_msgs.values("forwarded_from").distinct().count()
    fwd_received_channels = fwd_in_target_msgs.values("channel").distinct().count()

    # Row 2 — mentions (Message.references M2M, walked through the join table).
    refs_through = Message.references.through.objects
    base_refs = refs_through.filter(message__channel__in=in_target_pks, message__is_lost=False)
    ment_in_target_filter = Q(channel__in=in_target_pks) & ~Q(channel=F("message__channel"))
    ment_agg = base_refs.aggregate(
        sent_in_target=Count("id", filter=ment_in_target_filter),
        sent_self=Count("id", filter=Q(channel=F("message__channel"))),
        sent_oot=Count("id", filter=~Q(channel__in=in_target_pks)),
    )
    ment_in_target_refs = base_refs.filter(ment_in_target_filter)
    ment_oot_refs = base_refs.exclude(channel__in=in_target_pks)
    mentions_sent_in_target_channels = ment_in_target_refs.values("channel").distinct().count()
    mentions_sent_oot_channels = ment_oot_refs.values("channel").distinct().count()
    mentions_received_channels = ment_in_target_refs.values("message__channel").distinct().count()

    row1 = [
        {
            "icon": "bi-broadcast",
            "label": "Channels",
            "value": f"{in_target_channels:,}",
            "secondary": ([{"value": f"{to_inspect_count:,}", "label": "to inspect"}] if to_inspect_count else []),
        },
        {
            "icon": "bi-chat-left-text",
            "label": "Messages collected",
            "value": f"{total_messages:,}",
            "secondary": [
                {"value": f"{total_replies:,}", "label": "reply" if total_replies == 1 else "replies"},
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
        {
            "icon": "bi-eye",
            "label": "Total views",
            "value": f"{total_views:,}",
            "secondary": [{"value": f"{total_subscribers:,}", "label": "subscribers"}],
        },
        {
            "icon": "bi-calendar-range",
            "label": "Date range",
            "value": f"{fmt_date(msg_agg['earliest'])} – {fmt_date(msg_agg['latest'])}",
            "note": "first message - last message",
        },
    ]
    row2 = [
        {
            "icon": "bi-forward",
            "label": "Forwards sent",
            "value": f"{fwd_agg['sent_in_target']:,}",
            "note": _channels_phrase("from", fwd_sent_in_target_channels, "other in-target"),
            "secondary": [
                {"value": f"{fwd_agg['sent_self']:,}", "label": "self-forwards"},
                {
                    "value": f"{fwd_agg['sent_oot']:,}",
                    "label": _channels_phrase("from", fwd_sent_oot_channels, "non-in-target"),
                },
            ],
        },
        {
            "icon": "bi-at",
            "label": "Mentions sent",
            "value": f"{ment_agg['sent_in_target']:,}",
            "note": _channels_phrase("of", mentions_sent_in_target_channels, "other in-target"),
            "secondary": [
                {"value": f"{ment_agg['sent_self']:,}", "label": "self-mentions"},
                {
                    "value": f"{ment_agg['sent_oot']:,}",
                    "label": _channels_phrase("of", mentions_sent_oot_channels, "non-in-target"),
                },
            ],
        },
        {
            "icon": "bi-arrow-return-right",
            "label": "Forwards received",
            "value": f"{fwd_agg['sent_in_target']:,}",
            "note": _channels_phrase("by", fwd_received_channels, "other in-target"),
        },
        {
            "icon": "bi-chat-quote",
            "label": "Mentions received",
            "value": f"{ment_agg['sent_in_target']:,}",
            "note": _channels_phrase("by", mentions_received_channels, "other in-target"),
        },
    ]
    return [row1, row2]


def get_home_summary() -> list[list[dict]]:
    """Return the cached summary, computing on miss."""
    return cache.get_or_set(HOME_SUMMARY_CACHE_KEY, compute_home_summary, HOME_SUMMARY_CACHE_TIMEOUT)


def invalidate_home_summary_cache() -> None:
    """Drop the cached summary so the next render rebuilds from current data."""
    cache.delete(HOME_SUMMARY_CACHE_KEY)

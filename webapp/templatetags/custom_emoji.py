"""Draw Telegram custom emoji in post text and reaction pills (``webapp.models.emoji_models``).

``{{ post|message_html }}`` renders a message's text as ``linebreaks|urlize`` always did, with
each custom-emoji span — UTF-16 offsets, as Telegram reports them — replaced by the emoji's
stored file: an ``<img>`` (webp; masked to the text colour for ``text_color`` emoji), a
``<video>`` (webm), or a ``data-tgs-src`` element that ``webapp/js/custom_emoji.js`` turns
into a Lottie animation (TGS). A span whose emoji has no file keeps its fallback character,
and spans that do not fit the text leave it rendered as before. ``{% custom_emoji emoji %}``
draws one emoji on its own; ``{% reaction_pills post %}`` splits a message's ``"custom"``
reaction bucket into its custom emoji. Views prefetch ``custom_emoji_spans`` and
``custom_reactions`` with ``emoji__pack`` (``webapp.views._MESSAGE_LIST_PREFETCH``).
"""

from collections.abc import Iterable
from typing import Any

from django import template
from django.template.defaultfilters import linebreaks_filter, urlize
from django.utils.html import escape, format_html, linebreaks
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

#: ``data-play`` values: ``loop`` animates while on screen, ``hover`` only while hovered.
PLAY_MODES = ("loop", "hover")


def split_custom_emoji(text: str, spans: Iterable[Any]) -> list[tuple[str, Any]] | None:
    """Cut *text* at its custom-emoji spans: ``[(piece, span or None), …]``, or ``None`` if they don't fit.

    Telegram counts offsets in UTF-16 code units, so the text is sliced in its UTF-16 form; a
    span that overlaps another, runs past the end or splits a surrogate pair means the spans
    were not recorded against this text, and the caller renders it without them.
    """
    units = text.encode("utf-16-le")
    total = len(units) // 2
    pieces: list[tuple[str, Any]] = []
    cursor = 0
    try:
        for span in sorted(spans, key=lambda s: s.offset):
            start, end = span.offset, span.offset + span.length
            if span.length <= 0 or start < cursor or end > total:
                return None
            pieces.append((units[2 * cursor : 2 * start].decode("utf-16-le"), None))
            pieces.append((units[2 * start : 2 * end].decode("utf-16-le"), span))
            cursor = end
        pieces.append((units[2 * cursor :].decode("utf-16-le"), None))
    except UnicodeDecodeError:
        return None
    return pieces


def emoji_html(emoji: Any, fallback: str = "", play: str = "loop") -> SafeString:
    """The markup drawing *emoji*; its *fallback* text (else its ``alt``) when it has no file."""
    label = emoji.alt or fallback or "custom emoji"
    if emoji.is_unavailable or not emoji.file:
        return escape(fallback or emoji.alt)
    pack = emoji.pack.display_title if emoji.pack_id is not None and emoji.pack is not None else ""
    title = f"{label} · {pack}" if pack else label
    url = emoji.file.url
    play = play if play in PLAY_MODES else PLAY_MODES[0]
    kind = emoji.kind
    if kind == "lottie":
        tint = " custom-emoji--tint" if emoji.text_color else ""
        return format_html(
            '<span class="custom-emoji custom-emoji--tgs{}" data-tgs-src="{}" data-play="{}" role="img" '
            'aria-label="{}" title="{}">{}</span>',
            tint,
            url,
            play,
            label,
            title,
            fallback or emoji.alt,
        )
    if kind == "video":
        return format_html(
            '<video class="custom-emoji" src="{}" data-play="{}" loop muted playsinline preload="auto" '
            'aria-label="{}" title="{}"></video>',
            url,
            play,
            label,
            title,
        )
    if emoji.text_color:
        return format_html(
            '<span class="custom-emoji custom-emoji--mask" role="img" aria-label="{}" title="{}" '
            "style=\"--custom-emoji-src: url('{}')\"></span>",
            label,
            title,
            url,
        )
    return format_html(
        '<img class="custom-emoji" src="{}" alt="{}" title="{}" loading="lazy" decoding="async">', url, label, title
    )


@register.filter
def message_html(post: Any) -> SafeString:
    """*post*'s text as ``linebreaks|urlize`` renders it, with its custom emoji drawn in place."""
    text = post.message or ""
    spans = list(post.custom_emoji_spans.all()) if text else []
    pieces = split_custom_emoji(text, spans) if spans else None
    if pieces is None:
        return urlize(linebreaks_filter(text, autoescape=True), autoescape=True)
    # Each text piece is escaped and linkified on its own, so an emoji's markup never lands
    # inside a link; the paragraphs are cut afterwards, over the assembled markup.
    html = "".join(
        str(urlize(piece, autoescape=True)) if span is None else emoji_html(span.emoji, piece) for piece, span in pieces
    )
    return mark_safe(linebreaks(html))


@register.simple_tag
def custom_emoji(emoji: Any, play: str = "loop") -> SafeString:
    """``{% custom_emoji emoji play="hover" %}`` — one custom emoji on its own."""
    return emoji_html(emoji, play=play)


@register.simple_tag
def reaction_pills(post: Any) -> list[dict[str, Any]]:
    """``{% reaction_pills post as pills %}`` — ``[{"html", "count"}, …]`` in the stored reaction order.

    The ``"custom"`` bucket is replaced, at its place, by one pill per custom emoji with a
    stored file; what is left of it (emoji not downloaded or resolved, paid reactions,
    messages crawled before per-emoji counts were kept) stays a ``custom`` pill.
    """
    pills: list[dict[str, Any]] = []
    custom = list(post.custom_reactions.all())
    for reaction in post.reactions.all():
        if reaction.emoji != "custom":
            pills.append({"html": reaction.display_emoji, "count": reaction.count})
            continue
        shown = 0
        for item in custom:
            if item.emoji.file and not item.emoji.is_unavailable:
                pills.append({"html": emoji_html(item.emoji, play="hover"), "count": item.count})
                shown += item.count
        if reaction.count > shown:
            pills.append({"html": reaction.display_emoji, "count": reaction.count - shown})
    return pills

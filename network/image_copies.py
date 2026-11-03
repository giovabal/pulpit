"""Image copies: the same picture re-posted by another channel without a forward header.

The visual counterpart of :mod:`network.near_copies`. A channel that downloads a graphic and posts it
again — a poster with the local chapter's name swapped in, a training photo, a banner from a shared
"propaganda kit" — leaves no forward header, so the citation graph never sees it. With
``--image-copy-edges`` (off by default) such a post reads as a citation of the **earliest** in-scope post
showing the same image.

* **Unit = a post.** An album (one ``(channel, grouped_id)``) is one post, whatever its number of
  pictures, so a re-posted five-photo album counts once. Only posts carrying no forward header take
  part: forwards are already citations.
* **Same image** = the same Telegram photo id (a server-side re-post keeps it; distance 0), or perceptual
  hashes (pHash, :mod:`crawler.image_hash`) differing in at most ``--image-copy-distance`` of 64 bits
  (default 6 — re-encoding and resizing stay well inside it, distinct images sit around 32 apart).
  Hashes come from ``hash_media``; an image without one matches by photo id only.
* **Boilerplate**: an image a channel puts on at least ``IMAGE_BOILERPLATE_SHARE`` of its posts (a logo,
  a banner, a watermark template) is ignored for that channel.
* **Earliest origin**: each post points to the earliest post, by (date, id), that shows one of its images
  — in any channel, its own included (a *self-copy*, counted like a self-forward). Origins are searched
  over the channels' whole in-target history; only the copy must fall inside the date window.

Matching is exact: every pair of distinct hashes is compared (XOR + ``numpy.bitwise_count``, in chunks).
A match shows the same image appeared earlier in scope — not who made it, and not crops, mirror images or
text overlays beyond the distance.
"""

import collections
import datetime
from dataclasses import dataclass
from typing import Any

from django.db.models import Q
from django.utils import timezone

from network.parameters import FixedParameter

import numpy as np

#: Default largest pHash Hamming distance (of 64 bits) at which two images count as the same.
IMAGE_COPY_DISTANCE_DEFAULT = 6
#: An image on at least this share of a channel's image posts is that channel's boilerplate.
IMAGE_BOILERPLATE_SHARE = 0.2
#: Channels with fewer image posts keep every image (no boilerplate can be told apart).
IMAGE_BOILERPLATE_MIN_POSTS = 5
#: Rows per block of the all-pairs Hamming comparison (a block × all-hashes XOR matrix, ~100 MB at 50k hashes).
_CHUNK = 256

POST_RULE = (
    "an album (channel, grouped_id) is one post; only posts without a forward header take part; a post's "
    "date is its earliest message's"
)
MATCH_RULE = "same Telegram photo id (distance 0), or pHash Hamming distance ≤ --image-copy-distance"

_SOURCE = "network/image_copies.py"

#: The values fixed in this module (``PARAMETERS.md``); the distance is a run option.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Image copies: posts",
        value=POST_RULE,
        scope="image_copies",
        affects="What one image citation is: a re-posted album counts once, forwards never count.",
        source=f"{_SOURCE}: POST_RULE",
    ),
    FixedParameter(
        name="Image copies: matching",
        value=MATCH_RULE,
        scope="image_copies",
        affects="When two posts show the same image.",
        source=f"{_SOURCE}: MATCH_RULE",
        note="Perceptual hashing: Zauner (2010); meme tracking across communities: Zannettou et al. (2018).",
    ),
    FixedParameter(
        name="Image copies: boilerplate share",
        value=IMAGE_BOILERPLATE_SHARE,
        scope="image_copies",
        affects="An image on at least this share of a channel's image posts (logo, banner) is ignored for it.",
        source=f"{_SOURCE}: IMAGE_BOILERPLATE_SHARE",
    ),
    FixedParameter(
        name="Image copies: boilerplate minimum posts",
        value=IMAGE_BOILERPLATE_MIN_POSTS,
        scope="image_copies",
        affects="Channels with fewer image posts keep all their images.",
        source=f"{_SOURCE}: IMAGE_BOILERPLATE_MIN_POSTS",
    ),
)


@dataclass(frozen=True)
class ImageCopy:
    """One copy → origin link: the *copy* post re-posted an image of the earlier *origin* post. A post is
    identified by its first message's id."""

    copy_id: int
    copy_channel_id: int
    copy_date: datetime.datetime
    origin_id: int
    origin_channel_id: int
    origin_date: datetime.datetime
    distance: int
    #: Posts in scope showing the image (transitively): a picture shared by many channels is more likely
    #: a common meme than a copy of one specific post.
    cluster_size: int

    @property
    def is_self_copy(self) -> bool:
        return self.copy_channel_id == self.origin_channel_id

    @property
    def lag_hours(self) -> float:
        return (self.copy_date - self.origin_date).total_seconds() / 3600


def no_forward_header_q() -> Q:
    """Dated messages carrying no forward header of any kind — the header terms of
    :func:`network.near_copies.original_text_q` without its text requirement (an album sibling has none)."""
    from network.near_copies import _FORWARD_HEADER_NULLABLE_FIELDS

    q = Q(fwd_from_from_name="") & Q(date__isnull=False)
    for field in _FORWARD_HEADER_NULLABLE_FIELDS:
        q &= Q(**{f"{field}__isnull": True})
    return q


@dataclass
class _Post:
    post_id: int
    channel_id: int
    date: datetime.datetime
    images: set[int]


def _to_unsigned(values: list[int]) -> np.ndarray:
    return np.array([v & 0xFFFFFFFFFFFFFFFF for v in values], dtype=np.uint64)


def _neighbours(hashes: dict[int, int], distance: int) -> dict[int, list[tuple[int, int]]]:
    """``{photo id: [(other photo id, distance), …]}`` for every pair of distinct photo ids within ``distance``."""
    ids = list(hashes)
    out: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    if len(ids) < 2:
        return out
    values = _to_unsigned([hashes[i] for i in ids])
    for start in range(0, len(ids), _CHUNK):
        block = values[start : start + _CHUNK]
        rest = values[start:]
        dist = np.bitwise_count(block[:, None] ^ rest[None, :])
        rows, cols = np.nonzero(dist <= distance)
        for r, c in zip(rows.tolist(), cols.tolist(), strict=True):
            i, j = start + r, start + c
            if j <= i:
                continue
            d = int(dist[r, c])
            out[ids[i]].append((ids[j], d))
            out[ids[j]].append((ids[i], d))
    return out


def _strip_boilerplate(posts: list[_Post]) -> None:
    """Drop, per channel, the images on at least ``IMAGE_BOILERPLATE_SHARE`` of its posts (in place)."""
    per_channel: dict[int, list[_Post]] = collections.defaultdict(list)
    for post in posts:
        per_channel[post.channel_id].append(post)
    for channel_posts in per_channel.values():
        if len(channel_posts) < IMAGE_BOILERPLATE_MIN_POSTS:
            continue
        counts: collections.Counter[int] = collections.Counter()
        for post in channel_posts:
            counts.update(post.images)
        floor = max(2, int(np.ceil(IMAGE_BOILERPLATE_SHARE * len(channel_posts))))
        boilerplate = {image for image, c in counts.items() if c >= floor}
        if boilerplate:
            for post in channel_posts:
                post.images -= boilerplate


def find_image_copies(
    rows: "list[tuple[int, int, datetime.datetime, int | None, int]]",
    hashes: dict[int, int],
    *,
    distance: int = IMAGE_COPY_DISTANCE_DEFAULT,
) -> tuple[list[ImageCopy], list[_Post]]:
    """Image copies among ``rows`` of ``(message id, channel id, date, grouped_id, photo id)`` (one row per
    picture), ``hashes`` mapping photo id → pHash. Returns the links (sorted by copy date) and the posts."""
    if distance < 0 or distance > 64:
        raise ValueError(f"image-copy distance must be in [0, 64]; got {distance}")
    grouped: dict[tuple, _Post] = {}
    for message_id, channel_id, date, grouped_id, photo_id in rows:
        key = (channel_id, grouped_id) if grouped_id else ("m", message_id)
        post = grouped.get(key)
        if post is None:
            grouped[key] = _Post(message_id, channel_id, date, {photo_id})
        else:
            post.images.add(photo_id)
            if (date, message_id) < (post.date, post.post_id):
                post.post_id, post.date = message_id, date
    posts = list(grouped.values())
    _strip_boilerplate(posts)
    posts = [p for p in posts if p.images]
    order = sorted(range(len(posts)), key=lambda i: (posts[i].date, posts[i].post_id))
    rank = {i: r for r, i in enumerate(order)}
    posts_of: dict[int, list[int]] = collections.defaultdict(list)
    for i, post in enumerate(posts):
        for image in post.images:
            posts_of[image].append(i)
    neighbours = _neighbours({image: hashes[image] for image in posts_of if image in hashes}, distance)

    # Earliest post showing each image or one of its neighbours, with the distance of that match.
    earliest: dict[int, tuple[int, int]] = {}
    for image, holders in posts_of.items():
        best = (min(rank[i] for i in holders), 0)
        for other, d in neighbours.get(image, ()):
            candidate = (min(rank[i] for i in posts_of[other]), d)
            if candidate[0] < best[0]:
                best = candidate
        earliest[image] = best

    # Union-find over images (same post or matching hashes) for the cluster sizes.
    parent: dict[int, int] = {image: image for image in posts_of}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for image, others in neighbours.items():
        for other, _d in others:
            union(image, other)
    for post in posts:
        images = list(post.images)
        for other in images[1:]:
            union(images[0], other)
    cluster_posts: collections.Counter[int] = collections.Counter()
    for post in posts:
        cluster_posts[find(next(iter(post.images)))] += 1

    links: list[ImageCopy] = []
    for i, post in enumerate(posts):
        best: tuple[int, int] | None = None
        for image in post.images:
            candidate = earliest[image]
            if candidate[0] < rank[i] and (best is None or candidate < best):
                best = candidate
        if best is None:
            continue
        origin = posts[order[best[0]]]
        links.append(
            ImageCopy(
                copy_id=post.post_id,
                copy_channel_id=post.channel_id,
                copy_date=post.date,
                origin_id=origin.post_id,
                origin_channel_id=origin.channel_id,
                origin_date=origin.date,
                distance=best[1],
                cluster_size=cluster_posts[find(next(iter(post.images)))],
            )
        )
    links.sort(key=lambda link: (link.copy_date, link.copy_id))
    return links, posts


def _in_window(moment: datetime.datetime, start: datetime.date | None, end: datetime.date | None) -> bool:
    day = timezone.localdate(moment) if timezone.is_aware(moment) else moment.date()
    return (start is None or day >= start) and (end is None or day <= end)


def image_copies_for_channels(
    channel_ids: list[int],
    *,
    cutoff_q: Q,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    distance: int = IMAGE_COPY_DISTANCE_DEFAULT,
) -> dict[str, Any]:
    """Image copies among the alive, header-free picture posts of ``channel_ids`` passing ``cutoff_q``.

    Returns ``{"links": [ImageCopy…] (copies inside the window), "image_posts": {channel id: posts in the
    window}, "copied_posts": {channel id: posts in the window that copy another channel}}`` — the last two
    behind the ``VISUALORIGINALITY`` measure.
    """
    from webapp.models import ImageFingerprint, Message

    rows = list(
        Message.objects.alive()
        .filter(cutoff_q, no_forward_header_q(), channel_id__in=channel_ids, messagepicture__isnull=False)
        .values_list("id", "channel_id", "date", "grouped_id", "messagepicture__telegram_id")
        .distinct()
        .iterator(chunk_size=5000)
    )
    photo_ids = {row[4] for row in rows}
    hashes: dict[int, int] = {}
    photo_list = list(photo_ids)
    for start in range(0, len(photo_list), 500):
        hashes.update(
            ImageFingerprint.objects.filter(
                kind=ImageFingerprint.KIND_PICTURE, telegram_id__in=photo_list[start : start + 500]
            ).values_list("telegram_id", "phash")
        )
    links, posts = find_image_copies(rows, hashes, distance=distance)
    links = [link for link in links if _in_window(link.copy_date, start_date, end_date)]
    image_posts: collections.Counter[int] = collections.Counter(
        post.channel_id for post in posts if _in_window(post.date, start_date, end_date)
    )
    copied: collections.Counter[int] = collections.Counter(
        link.copy_channel_id for link in links if not link.is_self_copy
    )
    return {"links": links, "image_posts": dict(image_posts), "copied_posts": dict(copied), "hashed": len(hashes)}

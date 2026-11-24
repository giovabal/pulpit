"""Stored citation degrees: ``Channel.in_degree`` / ``Channel.out_degree``.

The single definition of the two columns, written by ``crawl_channels --in-degrees /
--out-degrees`` (Operations → *Refresh degrees*). Both count distinct **channels**, not
messages:

- an in-target channel's ``in_degree`` is the number of channels citing it and its
  ``out_degree`` the number of in-target channels it cites;
- an out-of-target channel cited by the in-target set gets the number of channels
  citing it as ``in_degree`` and ``0`` as ``out_degree``;
- any other channel still holding an earlier non-zero value is reset to ``0, 0``.

A citation is an alive message forwarding or mentioning (``t.me/`` link, @handle) the cited channel,
dated inside an in-target period of the citing channel (``channel_cutoff_q``); a
channel citing itself is not one. The citing channel counts whatever its state — lost,
private, or a type outside ``DEFAULT_CHANNEL_TYPES``: the stored ``in_degree`` is the
graph builder's dead-leaf gate (``DEAD_LEAF_MIN_CITING_CHANNELS``), and ``build_graph``
applies ``--channel-types`` / ``--include-lost`` / ``--include-private`` afterwards, so
the stored figure must cover every channel those options can bring back; a post by a
channel banned since is still a citation. Degrees are network-wide: neither
``--filter-labels`` nor ``--channel-types`` narrows them.
"""

from collections import Counter
from dataclasses import dataclass

from django.db.models import Exists, F, OuterRef, Q

from network.utils import channel_cutoff_q
from webapp.models import Channel, ChannelLabel, Message

#: Channels written per ``bulk_update`` batch.
DEGREE_BATCH_SIZE = 100


def ever_in_target_q() -> Q:
    """Q matching channels that hold at least one in-target label period (any time)."""
    return Q(Exists(ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True)))


def citation_ties(cited_pks: set[int]) -> set[tuple[int, int]]:
    """The ``(citing, cited)`` channel pairs whose cited side is in *cited_pks*.

    One pair however many in-period messages forward or mention the cited channel.
    The period gate admits only messages of channels holding an in-target label, so
    every citing side is an ever-in-target channel.
    """
    forwards = (
        Message.objects.alive()
        .filter(channel_cutoff_q(), forwarded_from_id__in=cited_pks)
        .exclude(channel_id=F("forwarded_from_id"))
        .values_list("channel_id", "forwarded_from_id")
        .distinct()
    )
    mentions = (
        Message.references.through.objects.filter(
            channel_cutoff_q("message__channel", "message__date"),
            channel_id__in=cited_pks,
            message__is_lost=False,
        )
        .exclude(message__channel_id=F("channel_id"))
        .values_list("message__channel_id", "channel_id")
        .distinct()
    )
    return set(forwards) | set(mentions)


def _cited_channel_pks() -> set[int]:
    """Every channel forwarded or mentioned by an alive in-period message."""
    forwarded = (
        Message.objects.alive()
        .filter(channel_cutoff_q(), forwarded_from__isnull=False)
        .values_list("forwarded_from_id", flat=True)
        .distinct()
    )
    mentioned = (
        Message.references.through.objects.filter(
            channel_cutoff_q("message__channel", "message__date"),
            message__is_lost=False,
        )
        .values_list("channel_id", flat=True)
        .distinct()
    )
    return set(forwarded) | set(mentioned)


@dataclass(frozen=True)
class DegreeUpdate:
    """Channels carrying their new ``in_degree`` / ``out_degree``, not yet saved.

    ``label`` names the batch for progress output, with a ``{total}`` placeholder.
    """

    label: str
    channels: list[Channel]


def degree_updates(*, in_target: bool = True, out_of_target: bool = True) -> list[DegreeUpdate]:
    """The degree changes to write, one batch per channel set (see the module docstring).

    ``in_target`` covers the ever-in-target channels; ``out_of_target`` the channels
    they cite and the reset of the ones no longer cited. Each pass leaves the other's
    channels untouched; a channel whose degrees were never computed stays ``NULL``
    unless one of the passes covers it.
    """
    in_target_pks = set(Channel.objects.filter(ever_in_target_q()).values_list("pk", flat=True))
    cited_pks = _cited_channel_pks() - in_target_pks
    updates: list[DegreeUpdate] = []

    if in_target and in_target_pks:
        ties = citation_ties(in_target_pks)
        cited_by: Counter[int] = Counter(cited for _, cited in ties)
        cites: Counter[int] = Counter(citing for citing, _ in ties)
        channels = list(Channel.objects.filter(pk__in=in_target_pks).only("pk", "in_degree", "out_degree"))
        for channel in channels:
            # Citation orientation (amplifier → source): incoming = cited by others.
            channel.in_degree = cited_by.get(channel.pk, 0)
            channel.out_degree = cites.get(channel.pk, 0)
        updates.append(DegreeUpdate("Refreshing degrees for {total} in-target channels", channels))

    if out_of_target and cited_pks:
        cited_by = Counter(cited for _, cited in citation_ties(cited_pks))
        channels = list(Channel.objects.filter(pk__in=cited_pks).only("pk", "in_degree", "out_degree"))
        for channel in channels:
            channel.in_degree = cited_by.get(channel.pk, 0)
            channel.out_degree = 0
        updates.append(DegreeUpdate("Refreshing citation degree for {total} referenced channels", channels))

    if out_of_target:
        # Out-of-target channels no in-period message cites any more — in-target labels
        # removed, citing messages purged or outside the periods. Never-computed NULLs
        # stay NULL; in-target channels belong to the in-target pass.
        stale = [
            channel
            for channel in Channel.objects.filter(Q(in_degree__gt=0) | Q(out_degree__gt=0)).only(
                "pk", "in_degree", "out_degree"
            )
            if channel.pk not in in_target_pks and channel.pk not in cited_pks
        ]
        for channel in stale:
            channel.in_degree = 0
            channel.out_degree = 0
        updates.append(DegreeUpdate("Resetting degrees for {total} channels no longer in target or cited", stale))

    return updates


def save_degrees(channels: list[Channel]) -> None:
    """Write the channels' ``in_degree`` / ``out_degree`` (nothing else) in batches."""
    Channel.objects.bulk_update(channels, ["in_degree", "out_degree"], batch_size=DEGREE_BATCH_SIZE)


def refresh_degrees(*, in_target: bool = True, out_of_target: bool = True) -> None:
    """Recompute and save the stored degrees (``crawl_channels`` without its progress output)."""
    for update in degree_updates(in_target=in_target, out_of_target=out_of_target):
        save_degrees(update.channels)

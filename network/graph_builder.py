import datetime
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Prefetch, Q, QuerySet
from django.utils import timezone

from network.utils import channel_cutoff_q, make_date_q
from webapp.models import Channel, ChannelLabel, LabelGroup, Message, ProfilePicture
from webapp.utils.channel_types import channel_type_filter
from webapp.utils.colors import hex_to_rgb

import networkx as nx


def channel_network_data(
    channel: Channel,
    default: dict | None = None,
    skip: frozenset[str] | set[str] = frozenset(),
    dead_leaves_color: str | None = None,
    resolved_label: "tuple[int, str, str] | None" = None,
    group_partitions: "dict[int, tuple[int, str]] | None" = None,
) -> dict:
    """Build the graph-node dict for a channel.

    Node colour comes from the channel's *resolved* in-target label in the
    **primary** group for the analysis window (``resolved_label`` =
    ``(label_id, name, color)``); channels with no in-target label in the
    primary group for the window — *dead-leaf* nodes, i.e. out-of-target
    channels an in-target channel forwarded from or mentioned via a ``t.me/``
    link — fall back to ``dead_leaves_color`` (or, when ``None``,
    ``settings.DEAD_LEAVES_COLOR``). ``group_partitions`` maps every *partition*
    group's pk → ``(label_id, label_color)`` resolved for the window, feeding the
    ``LABELGROUP<id>`` community strategies. The node keys ``organization`` /
    ``resolved_org_*`` keep their names for export back-compat but now hold the
    primary group's label.
    """
    default = default or {}
    leaf_color = dead_leaves_color or settings.DEAD_LEAVES_COLOR
    label_color = resolved_label[2] if resolved_label else None
    data: dict = {
        "pk": str(channel.pk),
        "id": channel.telegram_id,
        "label": channel.title,
        "communities": {},
        "color": ",".join(map(str, hex_to_rgb(label_color or leaf_color))),
        "organization": resolved_label[1] if resolved_label else "",
        "resolved_org_id": resolved_label[0] if resolved_label else None,
        "resolved_org_color": label_color,
        "group_partitions": group_partitions or {},
        "pic": channel.profile_picture.picture.url[1:]
        if channel.profile_picture and channel.profile_picture.picture
        else "",
        "url": channel.telegram_url,
        "activity_period": "" if "activity_period" in skip else channel.activity_period,
        "fans": channel.participants_count,
        "in_deg": channel.in_degree,
        "is_lost": channel.is_lost,
        "is_private": channel.is_private,
        "messages_count": 0 if "messages_count" in skip else channel.message_set.count(),
        "out_deg": channel.out_degree,
    }
    data.update(default)
    return data


def _channel_activity_bounds(
    channel_pks: list[int],
) -> dict[int, tuple[datetime.date | None, datetime.date | None]]:
    """Per-channel (earliest, latest) message *date* over all stored messages."""
    bounds: dict[int, tuple[datetime.date | None, datetime.date | None]] = {}
    rows = (
        Message.objects.filter(channel_id__in=channel_pks)
        .exclude(date__isnull=True)
        .values("channel_id")
        .annotate(min_date=Min("date"), max_date=Max("date"))
    )
    for row in rows:
        mn, mx = row["min_date"], row["max_date"]
        # localdate(): bucket into the TIME_ZONE calendar days the message filters
        # (make_date_q / channel_cutoff_q) use, so the clamps fed into
        # resolve_window_label agree with message-level period containment.
        bounds[row["channel_id"]] = (
            timezone.localdate(mn) if mn else None,
            timezone.localdate(mx) if mx else None,
        )
    return bounds


def _group_period_tuples(
    channel: Channel,
    group_id: int,
    *,
    in_target_only: bool,
) -> list[tuple[int, str, str, "datetime.date | None", "datetime.date | None"]]:
    """(label_id, label_name, label_color, start, end) for the channel's label periods in ``group_id``.

    With ``in_target_only`` only the channel's *in-target* labels count — used for
    the primary group, whose resolved label is the channel's in-target identity
    (node colour, "organization" column). Otherwise every label in the group is
    included, so a purely descriptive partition whose labels are all out-of-target
    (e.g. a "Nation" group) still resolves a window label and can colour the graph.
    Reads from prefetched ``channel_labels__label`` so it issues no query.
    """
    periods = []
    for channel_label in channel.channel_labels.all():
        label = channel_label.label
        if label.group_id == group_id and (label.is_in_target or not in_target_only):
            periods.append((label.id, label.name, label.color, channel_label.start, channel_label.end))
    return periods


def resolve_window_label(
    periods: list[tuple[int, str, str, "datetime.date | None", "datetime.date | None"]],
    window_start: datetime.date | None,
    window_end: datetime.date | None,
    channel_created: datetime.date | None,
    data_min: datetime.date | None,
    data_max: datetime.date | None,
) -> tuple[int, str, str] | None:
    """Pick the label whose period covers the most days inside the window.

    ``periods`` are the channel's label periods in one group (in-target only for
    the primary group, all labels otherwise). Tiebreak: the period that starts
    earliest. ``None`` bounds are clamped — a period start falls back to channel
    creation / earliest activity / window start; a period end to the window end /
    latest activity / today; an open analysis window to the channel's data range.
    Returns ``(label_id, label_name, label_color)`` or ``None`` when no period
    overlaps the window.
    """
    today = timezone.localdate()
    floor = channel_created or data_min or window_start or datetime.date.min
    w_lo = window_start or floor
    w_hi = window_end or data_max or today
    if w_hi < w_lo:
        w_hi = w_lo
    best_key: tuple[int, int] | None = None
    best_label: tuple[int, str, str] | None = None
    for label_id, label_name, label_color, p_start, p_end in periods:
        s = p_start or floor
        e = p_end or w_hi
        lo, hi = max(s, w_lo), min(e, w_hi)
        days = (hi - lo).days + 1 if hi >= lo else 0
        if days <= 0:
            continue
        key = (days, -s.toordinal())  # most days; tie -> earliest start
        if best_key is None or key > best_key:
            best_key, best_label = key, (label_id, label_name, label_color)
    return best_label


VALID_EDGE_WEIGHT_STRATEGIES = {"NONE", "TOTAL", "PARTIAL_MESSAGES", "PARTIAL_REFERENCES"}


def _filter_inactive_channels(
    channel_dict: dict[str, dict[str, Any]],
    graph: nx.DiGraph,
    channel_qs: QuerySet[Channel],
    messages_per_channel: dict,
) -> tuple[list[int], QuerySet[Channel]]:
    """Remove in-target channels with no activity in the date range from channel_dict and graph in-place.

    Dead-leaf nodes (out-of-target channels pulled in because an in-target channel
    cited them — identified by ``resolved_org_id is None``) are exempt: they have no
    in-target period, so the period-aware cutoff excludes all of their own messages
    and they would *always* be dropped here, before their incoming citation edges are
    even built. Their window relevance is whether they were cited *within* the window,
    which the degree-0 orphan sweep in ``build_graph`` decides once edges exist.
    """
    active_ids = set(messages_per_channel.keys())
    inactive = [
        cid
        for cid, cdata in channel_dict.items()
        if cdata["channel"].pk not in active_ids and cdata["data"].get("resolved_org_id") is not None
    ]
    for cid in inactive:
        graph.remove_node(cid)
        del channel_dict[cid]
    new_channel_ids = [int(cid) for cid in channel_dict]
    return new_channel_ids, channel_qs.filter(pk__in=new_channel_ids)


def _build_edge_list(
    forwarded_counts: dict,
    reference_counts: dict,
    referencing_counts: dict,
    messages_per_channel: dict,
    pk_to_str: dict[int, str],
    edge_weight_strategy: str,
    include_self_references: bool = False,
) -> list[list[str | float]]:
    """Compute weighted edge list from raw count dicts.

    Each row: ``[amplifier, cited, weight, weight_forwards, weight_mentions]``,
    matching the citation orientation the graph is built in (citing → cited).
    ``weight_forwards`` and ``weight_mentions`` are the raw forward/mention
    counts (before any normalisation), available for CSV export.
    """
    edge_list: list[list[str | float]] = []
    for amplifier_pk, source_pk in set(forwarded_counts.keys()) | set(reference_counts.keys()):
        if not include_self_references and amplifier_pk == source_pk:
            continue
        f_count = forwarded_counts.get((amplifier_pk, source_pk), 0)
        m_count = reference_counts.get((amplifier_pk, source_pk), 0)
        total = f_count + m_count
        if edge_weight_strategy == "NONE":
            weight = 1.0
        elif edge_weight_strategy == "TOTAL":
            weight = float(total)
        elif edge_weight_strategy == "PARTIAL_MESSAGES":
            message_count = messages_per_channel.get(amplifier_pk, 0)
            weight = total / message_count if message_count else 0.0
        else:  # PARTIAL_REFERENCES (default)
            ref_count = referencing_counts.get(amplifier_pk, 0)
            weight = total / ref_count if ref_count else 0.0
        if weight > 0:
            # Citation orientation: a forward of source's content by amplifier
            # produces an amplifier→source edge, mirroring the citing→cited
            # convention of scientometric PageRank/HITS. Measures that need
            # the opposite content-flow orientation (SIR spreading, trophic
            # level) reverse the graph internally.
            edge: list[str | float] = [pk_to_str[amplifier_pk], pk_to_str[source_pk]]
            edge.extend([weight, float(f_count), float(m_count)])
            edge_list.append(edge)
    return edge_list


def build_graph(
    draw_dead_leaves: bool = False,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    channel_types: list[str] | None = None,
    channel_sources: list[str] | None = None,
    edge_weight_strategy: str = "PARTIAL_REFERENCES",
    include_mentions: bool = True,
    include_self_references: bool = False,
    include_lost: bool = False,
    include_private: bool = False,
    dead_leaves_color: str | None = None,
) -> tuple[nx.DiGraph, dict[str, dict[str, Any]], list[list[str | float]], QuerySet[Channel]]:
    """Build a directed NetworkX graph from channels in the DB.

    Returns (graph, channel_dict, edge_list, channel_qs).
    Raises ValueError if no edges are found between channels.

    A *dead-leaf* node is an out-of-target channel that at least one in-target
    channel has forwarded from or mentioned via a ``t.me/`` link. Inclusion is
    gated by ``draw_dead_leaves``: the crawl counts every such forward/mention
    from the in-target set and stores the total in the out-of-target channel's
    ``in_degree``, so a non-zero in-degree is exactly the dead-leaf criterion.
    """
    # Node set: channels with an in-target period overlapping [start_date, end_date]
    # (the whole timeline when the window is open), plus dead leaves when requested.
    in_target_sub = ChannelLabel.objects.filter(channel=OuterRef("pk"), label__is_in_target=True)
    if end_date is not None:
        in_target_sub = in_target_sub.filter(Q(start__isnull=True) | Q(start__lte=end_date))
    if start_date is not None:
        in_target_sub = in_target_sub.filter(Q(end__isnull=True) | Q(end__gte=start_date))
    qs_filter = Q(Exists(in_target_sub))
    if draw_dead_leaves:
        # Dead-leaf criterion: an out-of-target channel cited (forwarded or
        # mentioned) at least once by some in-target channel. The cited count
        # lives in in_degree under the citation orientation (amplifier→source).
        qs_filter |= Q(in_degree__gt=0)
    channel_qs: QuerySet[Channel] = Channel.objects.filter(qs_filter, channel_type_filter(channel_types))
    if not include_private:
        channel_qs = channel_qs.exclude(is_private=True)
    if not include_lost:
        channel_qs = channel_qs.exclude(is_lost=True)
    channel_qs = channel_qs.prefetch_related(
        "channel_labels__label",
        Prefetch(
            "profilepicture_set",
            queryset=ProfilePicture.objects.order_by("-date")[:1],
            to_attr="_prefetched_profile_pics",
        ),
    )
    if channel_sources:
        channel_qs = channel_qs.filter(sources__key__in=channel_sources).distinct()

    # Resolve every partition group's window-label per node (feeds LABELGROUP<id> strategies); the
    # primary group additionally drives node colour and the "Label" export column (node attribute "organization").
    primary_group_id = LabelGroup.objects.filter(is_primary=True).values_list("pk", flat=True).first()
    partition_group_ids = list(LabelGroup.objects.filter(is_partition=True).values_list("pk", flat=True))
    # The primary group drives node colour and the "organization" column even when it is not itself a
    # partition group, so its window label must still be resolved; only partition groups, however, feed
    # group_partitions (the LABELGROUP<id> strategies). Resolve the union so a non-partition primary group
    # (or none) no longer silently leaves every node colourless / orphan-prunable.
    partition_id_set = set(partition_group_ids)
    resolve_group_ids = list(partition_group_ids)
    if primary_group_id is not None and primary_group_id not in partition_id_set:
        resolve_group_ids.append(primary_group_id)

    _skip = frozenset({"activity_period", "messages_count"})
    graph: nx.DiGraph = nx.DiGraph()
    channel_dict: dict[str, dict[str, Any]] = {}
    channels = list(channel_qs)
    activity_bounds = _channel_activity_bounds([channel.pk for channel in channels])
    for channel in channels:
        data_min, data_max = activity_bounds.get(channel.pk, (None, None))
        created = timezone.localdate(channel.date) if channel.date else None
        group_partitions: dict[int, tuple[int, str]] = {}
        resolved_label: tuple[int, str, str] | None = None
        for group_id in resolve_group_ids:
            # The primary group resolves the channel's in-target identity (node colour,
            # "organization" column), so it counts in-target labels only; descriptive
            # groups partition by every label they carry — including all-out-of-target
            # ones like a "Nation" group — so their LABELGROUP<id> colouring still works.
            is_primary = group_id == primary_group_id
            resolved = resolve_window_label(
                _group_period_tuples(channel, group_id, in_target_only=is_primary),
                start_date,
                end_date,
                created,
                data_min,
                data_max,
            )
            if resolved is not None:
                if group_id in partition_id_set:
                    group_partitions[group_id] = (resolved[0], resolved[2])  # (label_id, label_color)
                if is_primary:
                    resolved_label = resolved
        node_data = channel_network_data(
            channel,
            skip=_skip,
            dead_leaves_color=dead_leaves_color,
            resolved_label=resolved_label,
            group_partitions=group_partitions,
        )
        channel_dict[str(channel.pk)] = {"channel": channel, "data": node_data}
        graph.add_node(str(channel.pk), data=node_data)

    channel_ids = [int(channel_id) for channel_id in channel_dict]
    date_q = make_date_q(start_date, end_date)
    cutoff_q = channel_cutoff_q()
    references_through = Message.references.through

    messages_per_channel = {
        item["channel_id"]: item["total"]
        for item in Message.objects.alive()
        .filter(date_q, cutoff_q, channel_id__in=channel_ids)
        .values("channel_id")
        .annotate(total=Count("id"))
    }

    if start_date or end_date:
        channel_ids, channel_qs = _filter_inactive_channels(channel_dict, graph, channel_qs, messages_per_channel)

    forwarded_counts = {
        (item["channel_id"], item["forwarded_from_id"]): item["total"]
        for item in Message.objects.alive()
        .filter(date_q, cutoff_q, channel_id__in=channel_ids, forwarded_from_id__in=channel_ids)
        .values("channel_id", "forwarded_from_id")
        .annotate(total=Count("id"))
    }

    reference_counts = (
        {
            (item["message__channel_id"], item["channel_id"]): item["total"]
            for item in references_through.objects.filter(
                channel_cutoff_q("message__channel", "message__date"),
                make_date_q(start_date, end_date, field="message__date"),
                message__is_lost=False,
                channel_id__in=channel_ids,
                message__channel_id__in=channel_ids,
            )
            .exclude(message__forwarded_from=F("channel"))
            .values("message__channel_id", "channel_id")
            .annotate(total=Count("id"))
        }
        if include_mentions
        else {}
    )

    referencing_counts = {}
    if edge_weight_strategy == "PARTIAL_REFERENCES":
        has_reference_subq = references_through.objects.filter(message=OuterRef("pk"))
        ref_filter = (
            Q(forwarded_from_id__isnull=False) | Q(Exists(has_reference_subq))
            if include_mentions
            else Q(forwarded_from_id__isnull=False)
        )
        referencing_counts = {
            item["channel_id"]: item["total"]
            for item in Message.objects.alive()
            .filter(date_q, cutoff_q, channel_id__in=channel_ids)
            .filter(ref_filter)
            .values("channel_id")
            .annotate(total=Count("id"))
        }

    pk_to_str: dict[int, str] = {data["channel"].pk: cid for cid, data in channel_dict.items()}
    edge_list = _build_edge_list(
        forwarded_counts,
        reference_counts,
        referencing_counts,
        messages_per_channel,
        pk_to_str,
        edge_weight_strategy,
        include_self_references=include_self_references,
    )

    if not edge_list:
        raise ValueError("There are no relationships between channels.")

    max_weight = max(edge[2] for edge in edge_list)
    for edge in edge_list:
        graph.add_edge(
            edge[0],
            edge[1],
            weight=10 * edge[2] / max_weight if max_weight else 0.0,
            # Un-rescaled tie weight (before the ×10/max normalisation): portable across
            # exports and used for the displayed In-/Out-strength node measures.
            weight_raw=float(edge[2]),
            weight_forwards=edge[3],
            weight_mentions=edge[4],
        )

    # Remove org-less nodes that ended up with no edges. Two ways they arise:
    # dead leaves earned their slot via the all-time, period-blind
    # ``Channel.in_degree`` but edge construction is period-aware
    # (``channel_cutoff_q``), so a leaf cited solely outside those periods — or
    # inside a restricted analysis window with no citations — keeps no edge; and an
    # in-target channel whose open-start attribution matches any window can still
    # resolve to no label when it was created after the window end
    # (``resolve_window_label`` clamps the open start to the creation date).
    # ``_filter_inactive_channels`` deliberately exempts org-less nodes on the
    # promise that this sweep decides their fate, so it must run regardless of
    # ``draw_dead_leaves`` — gating it on the flag left the second kind hanging as
    # isolated grey ghosts precisely when dead leaves were *off*. In-target nodes
    # (``resolved_org_id`` set) are kept even when isolated — they are subjects of
    # the analysis.
    orphaned = [
        cid
        for cid in list(channel_dict)
        if graph.degree(cid) == 0 and channel_dict[cid]["data"].get("resolved_org_id") is None
    ]
    for cid in orphaned:
        graph.remove_node(cid)
        del channel_dict[cid]
    channel_qs = channel_qs.filter(pk__in=[int(cid) for cid in channel_dict])

    return graph, channel_dict, edge_list, channel_qs

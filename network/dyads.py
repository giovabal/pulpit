"""The dyadic export bundle (``--dyadic-export``): the citation network as data for network-modelling tools.

Pulpit's own statistics are descriptive or permutation-tested; models that explain tie formation —
exponential random graph models, stochastic actor-oriented models, relational event models — live in
dedicated R and Python packages. This module writes ``dyads/`` at the export root with what they need,
read from the very graph and messages the export was computed on:

* ``actors.csv`` — every node with its partition labels and covariates;
* ``edgelist.csv`` — every tie with its raw counts (ERGM, QAP);
* ``events.csv`` — every citation event between two nodes, timestamped (relational event models);
* ``dyads.csv`` — the MRQAP dyad table, when ``--mrqap`` is on;
* ``waves/`` — one adjacency matrix per timeline period and a presence table, when ``--timeline-step``
  is on without ``--timeline-window`` (stochastic actor-oriented models; overlapping sliding windows are
  not panel waves);
* ``README.md`` — the file dictionary.

``events.csv`` lists the forwards and mentions through :func:`network.graph_builder.forward_messages_qs` /
:func:`~network.graph_builder.reference_rows_qs` — the querysets ``build_graph`` aggregates — and the
near-copies the graph was built with, keeping only those on an edge of the graph: one event per counted
citation, so its per-pair counts equal the edge's ``weight_forwards`` / ``weight_mentions`` /
``weight_copies``.
"""

import csv
import datetime
import os
from typing import Any

from network.graph_builder import forward_messages_qs, reference_rows_qs
from network.mrqap import Design
from network.parameters import FixedParameter
from network.utils import GraphData, citation_count, dead_leaf_ids

import networkx as nx

DYADS_DIR = "dyads"

WAVE_ACTOR_RULE = (
    "waves cover the observed channels (dead leaves excluded) of every timeline period's graph; a channel absent "
    "from a period's graph is marked absent in waves/presence.csv and has an empty row and column that period"
)
EVENT_RULE = (
    "one row per forward, mention and near-copy counted on an edge of the exported graph, at the citing "
    "message's timestamp (UTC)"
)

_SOURCE = "network/dyads.py"

#: The rules fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Dyadic export: events",
        value=EVENT_RULE,
        scope="dyads",
        affects="Which citations events.csv lists; its per-pair counts equal the graph's raw edge counts.",
        source=f"{_SOURCE}: EVENT_RULE",
    ),
    FixedParameter(
        name="Dyadic export: wave actors",
        value=WAVE_ACTOR_RULE,
        scope="dyads",
        affects="Which channels the per-period adjacency matrices span and how a channel absent in a period is coded.",
        source=f"{_SOURCE}: WAVE_ACTOR_RULE",
    ),
)

#: One timeline period's network for the waves: its key, its observed node ids and its ties between them.
type Wave = tuple[str, list[str], list[tuple[str, str]]]


def wave_of(period_key: str, graph: nx.DiGraph) -> Wave:
    """The :data:`Wave` of one period graph (observed nodes, self-loops dropped)."""
    dead = dead_leaf_ids(graph)
    nodes = sorted(n for n in graph if n not in dead)
    present = set(nodes)
    ties = sorted((u, v) for u, v in graph.edges() if u != v and u in present and v in present)
    return str(period_key), nodes, ties


def _write_csv(path: str, header: list[str], rows: list[list[Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _iso(moment: datetime.datetime | None) -> str:
    if moment is None:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone(datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def citation_events(
    graph: nx.DiGraph,
    *,
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    environment_depth: int | None,
    include_mentions: bool,
) -> list[list[Any]]:
    """``[sender, receiver, timestamp, type, message_id]`` for every citation counted on an edge of ``graph``,
    sorted by time (then message id)."""
    channel_ids = [int(n) for n in graph]
    edges = {(int(u), int(v)) for u, v in graph.edges()}
    events: list[tuple[datetime.datetime | None, int, int, int, str]] = []
    for sender, receiver, date, message_id in (
        forward_messages_qs(channel_ids, start_date, end_date, environment_depth)
        .values_list("channel_id", "forwarded_from_id", "date", "id")
        .iterator(chunk_size=5000)
    ):
        if (sender, receiver) in edges:
            events.append((date, message_id, sender, receiver, "forward"))
    if include_mentions:
        for sender, receiver, date, message_id in (
            reference_rows_qs(channel_ids, start_date, end_date, environment_depth)
            .values_list("message__channel_id", "channel_id", "message__date", "message_id")
            .iterator(chunk_size=5000)
        ):
            if (sender, receiver) in edges:
                events.append((date, message_id, sender, receiver, "mention"))
    for link in graph.graph.get("near_copies") or []:
        if (link.copy_channel_id, link.origin_channel_id) in edges:
            events.append((link.copy_date, link.copy_id, link.copy_channel_id, link.origin_channel_id, "copy"))
    epoch = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    events.sort(key=lambda e: (e[0] or epoch, e[1]))
    return [[sender, receiver, _iso(date), kind, message_id] for date, message_id, sender, receiver, kind in events]


def _group_names() -> dict[int, str]:
    from webapp.models import LabelGroup

    return dict(LabelGroup.objects.filter(is_partition=True).order_by("-is_primary", "name").values_list("pk", "name"))


def _actor_rows(graph: nx.DiGraph, graph_data: GraphData) -> tuple[list[str], list[list[Any]]]:
    from webapp.models import Channel, Label

    groups = _group_names()
    dead = dead_leaf_ids(graph)
    node_info = {node["id"]: node for node in graph_data["nodes"]}
    label_ids = {
        resolved[0]
        for n in graph
        for resolved in ((graph.nodes[n].get("data") or {}).get("group_partitions") or {}).values()
        if resolved
    }
    label_names = dict(Label.objects.filter(pk__in=label_ids).values_list("pk", "name"))
    types = {str(c.pk): c.channel_type for c in Channel.objects.filter(pk__in=[int(n) for n in graph])}
    header = [
        "id",
        "title",
        "url",
        *groups.values(),
        "observed",
        "dead_leaf",
        "environment_depth",
        "messages",
        "subscribers",
        "activity_period",
        "is_lost",
        "type",
    ]
    rows = []
    for n in sorted(graph, key=int):
        data = graph.nodes[n].get("data") or {}
        partitions = data.get("group_partitions") or {}
        info = node_info.get(n, {})
        rows.append(
            [
                n,
                info.get("label") or data.get("label") or "",
                info.get("url") or data.get("url") or "",
                *(label_names.get((partitions.get(gid) or (None,))[0], "") for gid in groups),
                int(n not in dead),
                int(n in dead),
                data.get("environment_depth"),
                info.get("messages_count"),
                info.get("fans"),
                info.get("activity_period") or "",
                int(bool(info.get("is_lost"))),
                types.get(n, ""),
            ]
        )
    return header, rows


def _edge_rows(graph: nx.DiGraph) -> list[list[Any]]:
    return [
        [
            u,
            v,
            citation_count(data),
            int(round(float(data.get("weight_forwards") or 0))),
            int(round(float(data.get("weight_mentions") or 0))),
            int(round(float(data.get("weight_copies") or 0))),
            data.get("weight_raw", data.get("weight")),
        ]
        for u, v, data in sorted(graph.edges(data=True), key=lambda e: (int(e[0]), int(e[1])))
    ]


def _dyad_rows(design: Design) -> tuple[list[str], list[list[Any]]]:
    header = ["sender", "receiver", "tie", "log_citations", *design.keys]
    actors = design.actors
    rows = [
        [
            actors[i],
            actors[j],
            int(design.dependents["tie"][k]),
            round(float(design.dependents["log_citations"][k]), 6),
            *(round(float(x), 6) for x in design.predictors[k]),
        ]
        for k, (i, j) in enumerate(zip(design.rows.tolist(), design.cols.tolist(), strict=True))
    ]
    return header, rows


def _write_waves(directory: str, waves: list[Wave]) -> None:
    os.makedirs(directory, exist_ok=True)
    actors = sorted({n for _key, nodes, _ties in waves for n in nodes}, key=int)
    keys = [key for key, _nodes, _ties in waves]
    presence = {key: set(nodes) for key, nodes, _ties in waves}
    _write_csv(
        os.path.join(directory, "presence.csv"),
        ["actor", *keys],
        [[a, *(int(a in presence[k]) for k in keys)] for a in actors],
    )
    index = {a: i for i, a in enumerate(actors)}
    for key, _nodes, ties in waves:
        matrix = [[0] * len(actors) for _ in actors]
        for u, v in ties:
            matrix[index[u]][index[v]] = 1
        _write_csv(
            os.path.join(directory, f"wave_{key}.csv"),
            ["actor", *actors],
            [[a, *row] for a, row in zip(actors, matrix, strict=True)],
        )


_README = """# Dyadic export

The citation network of this export as data for network-modelling tools. Ids are Pulpit channel ids,
the `id` column of `actors.csv` (and of `nodes.csv` / `edges.csv` when `--csv` is on). Ties point from
the citing channel to the cited one: a forward or mention of j by i is a tie i → j.

| File | Content |
| :-- | :-- |
| `actors.csv` | Every node: title, URL, its label in each partition label group, `observed` (1 = its own messages were read; 0 = a dead leaf, cited only), environment depth, messages in the window, subscribers, activity period, lost flag, channel type |
| `edgelist.csv` | Every tie: `citations` = `forwards` + `mentions` + `copies` (raw counts), `weight` = the `--edge-weight-strategy` tie weight |
| `events.csv` | One row per citation counted on a tie, in time order: `sender`, `receiver`, `timestamp` (UTC), `type` (forward / mention / copy), `message_id`. Its per-pair counts equal `edgelist.csv` |
{dyads_row}{waves_row}
Typical uses:

- **ERGM** (R `statnet`/`ergm`, valued ERGM via `ergm.count`): build the network from `edgelist.csv`, attach `actors.csv` as vertex attributes. Restrict to `observed == 1` senders — a dead leaf's own citations were never read.
- **Relational event models** (R `goldfish`, `relevent`, `rem`; `eventnet`): `events.csv` is the event sequence, `actors.csv` the node set and covariates.
- **QAP / MRQAP** in R (`sna::netlm`, `sna::netlogit`): `dyads.csv` holds the dependent variables and predictors of Pulpit's own MRQAP, one row per ordered pair of actors.
- **Stochastic actor-oriented models** (R `RSiena`): each `waves/wave_<period>.csv` is one observation; `waves/presence.csv` says which actors exist in each wave — channels that join or leave enter `sienaCompositionChange`, or their absent rows can be coded as structural zeros.

Every tie is a one-degree attribution (Telegram credits a forward to its origin): model the ties as citations, not as paths along which content travelled. See `docs/dyadic-models.md` in the Pulpit repository.
"""


def write_dyadic_bundle(
    root: str,
    graph: nx.DiGraph,
    graph_data: GraphData,
    *,
    start_date: datetime.date | None,
    end_date: datetime.date | None,
    environment_depth: int | None,
    include_mentions: bool,
    design: "Design | None" = None,
    waves: "list[Wave] | None" = None,
    waves_skipped: bool = False,
) -> str:
    """Write ``dyads/`` under ``root`` (module docstring) and return its path."""
    directory = os.path.join(root, DYADS_DIR)
    os.makedirs(directory, exist_ok=True)
    header, rows = _actor_rows(graph, graph_data)
    _write_csv(os.path.join(directory, "actors.csv"), header, rows)
    _write_csv(
        os.path.join(directory, "edgelist.csv"),
        ["sender", "receiver", "citations", "forwards", "mentions", "copies", "weight"],
        _edge_rows(graph),
    )
    _write_csv(
        os.path.join(directory, "events.csv"),
        ["sender", "receiver", "timestamp", "type", "message_id"],
        citation_events(
            graph,
            start_date=start_date,
            end_date=end_date,
            environment_depth=environment_depth,
            include_mentions=include_mentions,
        ),
    )
    dyads_row = waves_row = ""
    if design is not None:
        header, rows = _dyad_rows(design)
        _write_csv(os.path.join(directory, "dyads.csv"), header, rows)
        dyads_row = (
            "| `dyads.csv` | One row per ordered pair of MRQAP actors: `tie`, `log_citations` and every predictor "
            "of the regression (`same_labelgroup<id>`, `reverse_tie`, sender/receiver activity and audience) |\n"
        )
    if waves:
        _write_waves(os.path.join(directory, "waves"), waves)
        waves_row = (
            "| `waves/wave_<period>.csv` | Binary adjacency of each timeline period over the union of the periods' "
            "observed channels (row = citing, column = cited) |\n"
            "| `waves/presence.csv` | 1 when the channel is part of that period's graph, 0 when not |\n"
        )
    elif waves_skipped:
        waves_row = (
            "\nNo `waves/`: the timeline uses overlapping sliding windows (`--timeline-window`), which would count "
            "the same tie in several waves. Re-run with a tumbling `--timeline-step` for panel waves.\n"
        )
    with open(os.path.join(directory, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(_README.format(dyads_row=dyads_row, waves_row=waves_row))
    return directory

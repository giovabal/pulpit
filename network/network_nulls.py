"""Significance of the whole-network statistics against random graphs (the ``SIGNIFICANCE`` stat group).

A whole-network statistic says little on its own: a sparse citation graph has low clustering, a
heavy-tailed one a high centralisation, whatever its organisation. Each statistic the random graphs do
not hold fixed is therefore set against three baselines, each a random graph with the same channels:

* **configuration** — :func:`network.robustness.null_model.rewire_strength_preserving`: every channel's
  in/out-degree exactly, its in/out-strength approximately, the wiring random. A deviation is structure
  beyond the degree sequence: reciprocity, triadic closure, degree mixing, component structure, how
  concentrated prestige is.
* **reciprocal** — :func:`network.robustness.null_model.rewire_reciprocity_preserving`: the same, and
  also every channel's reciprocated degree, so reciprocity is held fixed. A clustering or centralisation
  deviation that survives it is not explained by mutual citation alone (Squartini & Garlaschelli 2011).
* **random digraph** — the same number of ties placed uniformly at random, each from an observed
  channel (dead leaves never cite: their own citations are outside the analysis) to any other channel,
  with the observed tie weights shuffled onto them. The only baseline for the statistics the two
  rewirings hold fixed — the degree coefficients of variation and the degree centralisations — and a
  coarse reference for the rest (Erdős & Rényi 1959's G(n, m), restricted to the observation boundary).

Each test reports the null mean, the z-score and the two-sided add-one empirical p
(:func:`network.robustness.null_model.empirical_p`). A statistic a null holds fixed is reported as such,
not as a p of 1. The observed values are recomputed here with the very functions applied to the null
graphs, so the comparison never mixes two definitions.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from network.measures import compute_hits, pagerank_scores
from network.parameters import FixedParameter
from network.robustness.null_model import (
    empirical_p,
    rewire_reciprocity_preserving,
    rewire_strength_preserving,
    z_score,
)
from network.utils import without_self_loops

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

#: Random graphs per baseline; the smallest two-sided p is 2/(K+1).
NETWORK_NULL_SAMPLES = 100
#: Seed of the random graphs (each baseline draws from its own stream, seeded by this and its position).
NETWORK_NULL_SEED = 42
#: Above this many possible (sender, receiver) pairs the random digraph is drawn by rejection sampling
#: instead of one draw without replacement over all pairs.
_DIRECT_SAMPLING_PAIRS = 5_000_000

NULL_MODELS: tuple[str, ...] = ("configuration", "reciprocal", "random")
NULL_LABELS: dict[str, str] = {
    "configuration": "vs configuration",
    "reciprocal": "vs reciprocal",
    "random": "vs random digraph",
}
_DEGREE_FIXED = frozenset(
    {
        "in_degree_cv",
        "out_degree_cv",
        "centralization.in_degree_centrality",
        "centralization.out_degree_centrality",
    }
)
#: The statistics each baseline holds fixed by construction (reported as fixed, never tested).
FIXED_BY_NULL: dict[str, frozenset[str]] = {
    "configuration": _DEGREE_FIXED,
    "reciprocal": _DEGREE_FIXED | {"reciprocity"},
    "random": frozenset(),
}
#: Centrality measures whose centralisation is recomputed on every random graph (the others are not
#: centralised; see ``CENTRALITY_MEASURE_KEYS``).
TESTED_CENTRALIZATIONS: frozenset[str] = frozenset(
    {"pagerank", "hits_hub", "hits_authority", "in_degree_centrality", "out_degree_centrality"}
)
TESTED_STATISTICS_RULE = (
    "reciprocity and average clustering (PATHS); transitivity and in/out-degree CV (COHESION); largest WCC and "
    "SCC fraction (COMPONENTS); the four degree assortativities (DEGCORRELATION); the centralisation of PageRank, "
    "HITS and in/out-degree centrality (CENTRALIZATION) — each only when its group is selected"
)
RANDOM_DIGRAPH_RULE = (
    "as many inter-channel ties as observed, drawn uniformly without replacement among (observed channel → any "
    "other channel) pairs; the observed tie weights shuffled onto them; self-loops kept as observed"
)

_SOURCE = "network/network_nulls.py"

#: The values fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Network significance: random graphs per baseline",
        value=NETWORK_NULL_SAMPLES,
        scope="network_significance",
        affects="Random graphs behind each z-score and p of the whole-network statistics; the smallest "
        "two-sided p is 2/(K+1).",
        source=f"{_SOURCE}: NETWORK_NULL_SAMPLES",
        note="Add-one Monte-Carlo p-values (Phipson & Smyth 2010).",
    ),
    FixedParameter(
        name="Network significance: seed",
        value=NETWORK_NULL_SEED,
        scope="network_significance",
        affects="Seeds the random graphs (one stream per baseline), so every z and p is reproducible.",
        source=f"{_SOURCE}: NETWORK_NULL_SEED",
    ),
    FixedParameter(
        name="Network significance: statistics tested",
        value=TESTED_STATISTICS_RULE,
        scope="network_significance",
        affects="Path lengths, efficiency and algebraic connectivity stay descriptive: expensive on every random "
        "graph, and shape descriptors of the citation topology rather than claims.",
        source=f"{_SOURCE}: TESTED_STATISTICS_RULE",
    ),
    FixedParameter(
        name="Network significance: statistics a baseline holds fixed",
        value={key: sorted(value) for key, value in FIXED_BY_NULL.items()},
        scope="network_significance",
        affects="Reported as held fixed instead of tested: degree-preserving rewiring cannot move a degree "
        "statistic, nor the reciprocal null the reciprocity.",
        source=f"{_SOURCE}: FIXED_BY_NULL",
    ),
    FixedParameter(
        name="Network significance: random digraph",
        value=RANDOM_DIGRAPH_RULE,
        scope="network_significance",
        affects="The baseline of the degree statistics: a G(n, m) random digraph that respects the observation "
        "boundary (dead leaves never cite).",
        source=f"{_SOURCE}: RANDOM_DIGRAPH_RULE",
        note="Erdős & Rényi (1959).",
    ),
)

type StatisticsFn = Callable[[nx.DiGraph, frozenset[str], "frozenset[str] | None"], dict[str, Any]]
type CentralizationFn = Callable[[list[float]], "float | None"]


def _light_copy(graph: nx.DiGraph) -> nx.DiGraph:
    """``graph``'s nodes and weighted edges only — what the rewirings need, without the node payloads."""
    light = nx.DiGraph()
    light.add_nodes_from(graph.nodes())
    light.add_weighted_edges_from((u, v, float(data.get("weight", 1.0))) for u, v, data in graph.edges(data=True))
    return light


def random_boundary_digraph(graph: nx.DiGraph, dead: frozenset[str], rng: np.random.Generator) -> nx.DiGraph:
    """A G(n, m) random digraph on ``graph``'s nodes that respects the observation boundary (module docstring)."""
    nodes = list(graph.nodes())
    n = len(nodes)
    position = {node: i for i, node in enumerate(nodes)}
    senders = np.array([position[node] for node in nodes if node not in dead], dtype=np.int64)
    weights = np.array([float(d.get("weight", 1.0)) for u, v, d in graph.edges(data=True) if u != v])
    rng.shuffle(weights)
    random_graph = nx.DiGraph()
    random_graph.add_nodes_from(nodes)
    random_graph.add_weighted_edges_from(
        (u, v, float(d.get("weight", 1.0))) for u, v, d in graph.edges(data=True) if u == v
    )
    possible = int(senders.size) * (n - 1)
    m = min(int(weights.size), possible)
    if m == 0:
        return random_graph
    if possible <= _DIRECT_SAMPLING_PAIRS:
        picks = rng.choice(possible, size=m, replace=False)
        sender_pos = senders[picks // (n - 1)]
        offset = picks % (n - 1)
        receiver_pos = offset + (offset >= sender_pos)
        pairs = list(zip(sender_pos.tolist(), receiver_pos.tolist(), strict=True))
    else:
        chosen: set[tuple[int, int]] = set()
        while len(chosen) < m:
            draw = m - len(chosen)
            sender_pos = senders[rng.integers(0, senders.size, size=draw)]
            receiver_pos = rng.integers(0, n, size=draw)
            chosen.update((u, v) for u, v in zip(sender_pos.tolist(), receiver_pos.tolist(), strict=True) if u != v)
        pairs = list(chosen)[:m]
    random_graph.add_weighted_edges_from(
        (nodes[u], nodes[v], float(w)) for (u, v), w in zip(pairs, weights[:m].tolist(), strict=True)
    )
    return random_graph


def _centrality_values(graph: nx.DiGraph, key: str, dead: frozenset[str]) -> list[float] | None:
    """The values of one centrality measure on ``graph``, as the measure computes them (dead leaves censored
    where the measure censors them); ``None`` when it cannot be computed."""
    loop_free = without_self_loops(graph)
    try:
        if key == "pagerank":
            values = pagerank_scores(graph)
        elif key in ("hits_hub", "hits_authority"):
            hubs, authorities = compute_hits(loop_free)
            values = hubs if key == "hits_hub" else authorities
        elif key == "in_degree_centrality":
            values = nx.in_degree_centrality(loop_free)
        elif key == "out_degree_centrality":
            values = nx.out_degree_centrality(loop_free)
        else:
            return None
    except Exception as exc:  # noqa: BLE001 — a diverging power iteration on one random graph skips that draw
        logger.debug("centralisation of %s unavailable on a random graph: %s", key, exc)
        return None
    if key in ("hits_hub", "out_degree_centrality"):
        return [value for node, value in values.items() if node not in dead]
    return list(values.values())


def _flatten(ties: dict[str, Any]) -> dict[str, float | None]:
    flat: dict[str, float | None] = {}
    for key in ("reciprocity", "avg_clustering", "transitivity", "in_degree_cv", "out_degree_cv"):
        flat[key] = ties.get(key)
    for key in ("wcc_fraction", "scc_fraction"):
        flat[key] = ties.get(key)
    for key, value in (ties.get("assortativity") or {}).items():
        flat[f"assortativity.{key}"] = value
    return flat


def _all_statistics(
    graph: nx.DiGraph,
    dead: frozenset[str],
    selected_groups: "frozenset[str] | None",
    centrality_keys: list[str],
    statistics: StatisticsFn,
    centralization: CentralizationFn,
) -> dict[str, float | None]:
    values = _flatten(statistics(graph, dead, selected_groups))
    for key in centrality_keys:
        scores = _centrality_values(graph, key, dead)
        values[f"centralization.{key}"] = centralization(scores) if scores is not None else None
    return values


@contextmanager
def _quiet_hits() -> Iterator[None]:
    hits_logger = logging.getLogger("network.measures._centrality")
    previous = hits_logger.level
    hits_logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        hits_logger.setLevel(previous)


def _draw(
    light: nx.DiGraph,
    dead: frozenset[str],
    selected_groups: "frozenset[str] | None",
    keys: list[str],
    statistics: StatisticsFn,
    centralization: CentralizationFn,
    samples: int,
    seed: int,
    tested: dict[str, float | None],
    draws: dict[str, dict[str, list[float]]],
) -> None:
    """Fill ``draws[null][statistic]`` with the statistics of ``samples`` random graphs per baseline."""
    for index, null in enumerate(NULL_MODELS):
        rng = np.random.default_rng([seed, index])
        for _ in range(samples):
            if null == "configuration":
                random_graph = rewire_strength_preserving(light, weight="weight", rng=rng)
            elif null == "reciprocal":
                random_graph = rewire_reciprocity_preserving(light, weight="weight", rng=rng)
            else:
                random_graph = random_boundary_digraph(light, dead, rng)
            values = _all_statistics(random_graph, dead, selected_groups, keys, statistics, centralization)
            for key in tested:
                if key in FIXED_BY_NULL[null]:
                    continue
                value = values.get(key)
                if value is not None and np.isfinite(value):
                    draws[null][key].append(float(value))


def network_significance(
    graph: nx.DiGraph,
    dead: frozenset[str],
    *,
    statistics: StatisticsFn,
    centralization: CentralizationFn,
    selected_groups: "frozenset[str] | None",
    centrality_keys: list[str],
    samples: int = NETWORK_NULL_SAMPLES,
    seed: int = NETWORK_NULL_SEED,
) -> dict[str, dict[str, dict[str, Any]]]:
    """``{statistic: {baseline: {"mean", "z", "p"} | {"fixed": True}}}`` for the whole-network statistics.

    ``statistics`` is :func:`network.community_stats.tie_statistics` and ``centralization`` the centralisation
    index the network table reports (passed in so this module needs no import of ``community_stats``).
    ``centrality_keys`` are the selected centrality measures in :data:`TESTED_CENTRALIZATIONS`. Statistic keys
    are flat: ``reciprocity``, ``assortativity.in_out``, ``centralization.pagerank``, … Empty when the graph
    is too small to randomise (fewer than three channels or two inter-channel ties).
    """
    keys = [key for key in centrality_keys if key in TESTED_CENTRALIZATIONS]
    light = _light_copy(graph)
    if light.number_of_nodes() < 3 or sum(1 for u, v in light.edges() if u != v) < 2 or samples <= 0:
        return {}
    observed = _all_statistics(light, dead, selected_groups, keys, statistics, centralization)
    tested = {key: value for key, value in observed.items() if value is not None}
    draws: dict[str, dict[str, list[float]]] = {null: {key: [] for key in tested} for null in NULL_MODELS}
    # HITS warns when its power iteration stops short; on hundreds of random graphs that would flood the log
    # with warnings about graphs nobody looks at, so they are silenced for the null draws only.
    with _quiet_hits():
        _draw(light, dead, selected_groups, keys, statistics, centralization, samples, seed, tested, draws)

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for key, value in tested.items():
        per_null: dict[str, dict[str, Any]] = {}
        for null in NULL_MODELS:
            if key in FIXED_BY_NULL[null]:
                per_null[null] = {"fixed": True}
                continue
            sample = draws[null][key]
            if not sample:
                per_null[null] = {"mean": None, "z": None, "p": None}
                continue
            z, mean, _sd = z_score(value, sample)
            per_null[null] = {
                "mean": round(mean, 6),
                "z": round(z, 2) if np.isfinite(z) else None,
                "p": round(empirical_p(value, sample), 4),
            }
        result[key] = per_null
    return result

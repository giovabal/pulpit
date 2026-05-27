"""Removal-order strategies for network robustness analysis.

A *removal order* is a list of node IDs ordered from "first to remove" to
"last to remove".  Strategies are partitioned into:

- **Random** — uniform shuffle, averaged over `n_random_runs` in the runner.
- **Static** — rank the nodes once on the full backbone and remove them in
  that fixed order.  One centrality pass per attack.
- **Dynamic** — recompute the ranking on the residual graph after every
  removal (``_dyn`` suffix).  Much more aggressive and much costlier.

Tie-breaking is deterministic (ascending node ID) so non-random strategies
are reproducible without an ``rng``.  Most strategies sort *descending* by
score; Burt's constraint sorts *ascending* (low constraint = broker).

A single registry — :data:`STRATEGY_SPECS` — drives the available
strategies, their human labels, score functions, and sort direction.
``bridging`` is the one parameterised strategy: it accepts an optional
community basis as ``bridging(<strategy>)`` (case-insensitive, defaults to
``leiden_directed``); the named strategy must also be present in the
runner's partitions dict.

References:
    Albert, R., Jeong, H. & Barabási, A.-L. (2000). Error and attack
        tolerance of complex networks. *Nature* 406(6794), 378-382.
        https://doi.org/10.1038/35019019
    Holme, P., Kim, B. J., Yoon, C. N. & Han, S. K. (2002). Attack
        vulnerability of complex networks. *Phys. Rev. E* 65(5), 056109.
        https://doi.org/10.1103/PhysRevE.65.056109
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from math import isnan
from typing import Any, Literal

from network.measures import compute_betweenness, compute_hits
from network.measures._base import compute_neighbour_community_participation
from network.measures._centrality import proximity_distances
from network.measures._spreading import _run_sir

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

# ── Spec registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategySpec:
    """Describes a removal strategy.

    ``label``           human-readable name (used by HTML / XLSX renderers)
    ``score_fn``        ``(g: nx.DiGraph) -> dict[node, float]``; ignored for
                        ``"random"``
    ``inverse``         when True, sort *ascending* — used for measures where
                        low values flag critical nodes (e.g. Burt's constraint)
    ``kind``            ``"random"``, ``"static"``, or ``"dynamic"``
    """

    label: str
    score_fn: Callable[[nx.DiGraph], dict[Any, float]] | None
    inverse: bool = False
    kind: Literal["random", "static", "dynamic"] = "static"


# ── Score functions ─────────────────────────────────────────────────────────
# Each scorer returns a {node: float} dict.  All are pure: they take a graph
# and return scores without mutating it.


def _in_strength(g: nx.DiGraph) -> dict[Any, float]:
    return dict(g.in_degree(weight="weight"))


def _out_strength(g: nx.DiGraph) -> dict[Any, float]:
    return dict(g.out_degree(weight="weight"))


def _safe_pagerank(g: nx.DiGraph) -> dict[Any, float]:
    # Power iteration can fail on adversarial residual graphs; fall back to
    # in-strength as a structural proxy so the attack loop never aborts.
    try:
        return nx.pagerank(g)
    except nx.PowerIterationFailedConvergence:
        return _in_strength(g)


def _hits_hub(g: nx.DiGraph) -> dict[Any, float]:
    # Weighted HITS (shared with the HITS measure) so the attack ranks by the same
    # tie-strength-aware scores. Degenerate residual graphs can still misbehave;
    # catch broadly and fall back to out-strength as a structural proxy.
    try:
        hubs, _ = compute_hits(g)
        return hubs
    except Exception:  # noqa: BLE001 - logged before falling back to structural proxy
        logger.warning("HITS hub failed; using out-strength proxy", exc_info=True)
        return _out_strength(g)


def _hits_authority(g: nx.DiGraph) -> dict[Any, float]:
    try:
        _, auth = compute_hits(g)
        return auth
    except Exception:  # noqa: BLE001 - logged before falling back to structural proxy
        logger.warning("HITS authority failed; using in-strength proxy", exc_info=True)
        return _in_strength(g)


def _harmonic(g: nx.DiGraph) -> dict[Any, float]:
    # Weighted over distance = 1/weight (Opsahl 2010), matching the harmonic measure.
    n = g.number_of_nodes()
    norm = (n - 1) if n > 1 else 1
    gd = proximity_distances(g)
    return {nid: v / norm for nid, v in nx.harmonic_centrality(gd, distance="distance").items()}


def _burt_constraint(g: nx.DiGraph) -> dict[Any, float]:
    # Low constraint = structural-hole broker.  Sort direction reversed via the
    # ``inverse`` flag on the StrategySpec.  Isolated nodes get NaN from
    # NetworkX; we coerce to +infinity so they sort last under ascending order
    # (treated as "not a broker").
    out: dict[Any, float] = {}
    for nid, val in nx.constraint(g, weight="weight").items():
        out[nid] = float("inf") if val is None or isnan(val) else val
    return out


_BRIDGING_RE = re.compile(r"^bridging(?:\((\w+)\))?$", re.IGNORECASE)


def _bridging_with_partition(g: nx.DiGraph, partition: dict[Any, Any]) -> dict[Any, float]:
    """Community bridging = betweenness × participation coefficient of the
    community distribution among the node's weighted neighbours.

    This is the community-participation brokerage measure, *not* the Bridging
    Centrality of Hwang et al. (2008).  Both pieces come from shared helpers —
    ``compute_betweenness`` and ``compute_neighbour_community_participation`` — so
    the formula stays in lock-step with
    :func:`network.measures._centrality.apply_community_bridging`.
    """
    betweenness = compute_betweenness(g)
    participation = compute_neighbour_community_participation(g, partition)
    return {node: betweenness.get(node, 0.0) * participation.get(node, 0.0) for node in g.nodes()}


def _spreading_scores(g: nx.DiGraph, *, runs: int = 200, rng: np.random.Generator | None = None) -> dict[Any, float]:
    """Per-node SIR spreading efficiency — mean fraction infected when each
    node seeds the cascade.  Reuses :func:`network.measures._spreading._run_sir`.

    Cost: O(runs × N × mean outbreak size) per call.  Used as an attack
    strategy, this runs once per ranking computation — heavy but feasible
    on moderately-sized backbones.
    """
    if rng is None:
        rng = np.random.default_rng(42)
    n = g.number_of_nodes()
    if n <= 1:
        return dict.fromkeys(g.nodes(), 0.0)
    # Transmission probability = weight / max_weight (scale-independent; the raw
    # weight is rescaled to max 10 by build_graph, which would saturate min(w, 1)).
    edge_weights = [d.get("weight", 1.0) for _, _, d in g.edges(data=True)]
    max_weight = max(edge_weights) if edge_weights else 1.0
    adj: dict[Any, list[tuple[Any, float]]] = {
        nid: [(s, min(d.get("weight", 1.0) / max_weight, 1.0)) for s, d in g[nid].items()] for nid in g.nodes()
    }
    norm = n - 1
    scores: dict[Any, float] = {}
    for nid in g.nodes():
        total = sum(_run_sir(adj, nid, rng) for _ in range(runs))
        scores[nid] = (total / runs - 1) / norm
    return scores


# ── Registry ────────────────────────────────────────────────────────────────


STRATEGY_SPECS: dict[str, StrategySpec] = {
    # Baseline
    "random": StrategySpec("Random failure", None, kind="random"),
    # Degree
    "in_strength": StrategySpec("In-strength", _in_strength),
    "out_strength": StrategySpec("Out-strength", _out_strength),
    # Prestige
    "pagerank": StrategySpec("PageRank", _safe_pagerank),
    "hits_hub": StrategySpec("HITS hub", _hits_hub),
    "hits_authority": StrategySpec("HITS authority", _hits_authority),
    # Reach
    "harmonic": StrategySpec("Harmonic centrality", _harmonic),
    # Brokerage
    "betweenness": StrategySpec("Betweenness", compute_betweenness),
    "burt_constraint": StrategySpec("Burt's constraint (low = broker)", _burt_constraint, inverse=True),
    # bridging is parameterised; the "bridging" key here is a placeholder for
    # the registry (label / kind) — the score function is invoked separately
    # via _bridging_with_partition because it needs the chosen partition.  This
    # is community bridging (Guimerà-Amaral participation), not Hwang's Bridging
    # Centrality, which has no robustness-attack counterpart.
    "bridging": StrategySpec("Community bridging", None),
    # Dynamical — score_fn is None: ``removal_order`` special-cases "spreading"
    # so it can thread the shared rng into the (stochastic) SIR scorer.
    "spreading": StrategySpec("Spreading efficiency (SIR)", None),
    # Dynamic variants
    "in_strength_dyn": StrategySpec("In-strength (dyn)", _in_strength, kind="dynamic"),
    "out_strength_dyn": StrategySpec("Out-strength (dyn)", _out_strength, kind="dynamic"),
    "pagerank_dyn": StrategySpec("PageRank (dyn)", _safe_pagerank, kind="dynamic"),
    "hits_hub_dyn": StrategySpec("HITS hub (dyn)", _hits_hub, kind="dynamic"),
    "hits_authority_dyn": StrategySpec("HITS authority (dyn)", _hits_authority, kind="dynamic"),
    "betweenness_dyn": StrategySpec("Betweenness (dyn)", compute_betweenness, kind="dynamic"),
}

DEFAULT_STRATEGIES: list[str] = ["random", "in_strength", "out_strength", "pagerank", "betweenness"]

# Derived sets so existing imports keep working.
STATIC_STRATEGIES: frozenset[str] = frozenset(name for name, spec in STRATEGY_SPECS.items() if spec.kind != "dynamic")
DYNAMIC_STRATEGIES: frozenset[str] = frozenset(name for name, spec in STRATEGY_SPECS.items() if spec.kind == "dynamic")
ALL_STRATEGIES: list[str] = list(STRATEGY_SPECS.keys())


# ── Strategy-name parsing / validation ──────────────────────────────────────


def parse_strategy(name: str) -> tuple[str, str | None]:
    """Normalise a strategy token to ``(canonical_name, bridging_partition_key)``.

    Bare strategy names normalise to lowercase: ``"PageRank"`` → ``("pagerank", None)``.
    Bridging accepts an optional partition: ``"bridging(LEIDEN)"`` →
    ``("bridging", "leiden")``; bare ``"bridging"`` →
    ``("bridging", "leiden_directed")`` (the default basis, since the directed
    Leiden variant respects citation direction — closer to what a brokerage
    attack on a directed citation network is asking).

    Raises ``ValueError`` for unknown names.
    """
    raw = name.strip()
    m = _BRIDGING_RE.match(raw)
    if m:
        return ("bridging", (m.group(1) or "leiden_directed").lower())
    canonical = raw.lower()
    if canonical not in STRATEGY_SPECS:
        raise ValueError(
            f"unknown attack strategy {name!r}; choose from {sorted(STRATEGY_SPECS.keys())} "
            f"or bridging(<community-strategy>)"
        )
    return (canonical, None)


def strategy_label(name: str, partition_key: str | None = None) -> str:
    """Human-readable label, including the partition basis for bridging."""
    base = STRATEGY_SPECS[name].label
    if name == "bridging" and partition_key:
        return f"{base} ({partition_key})"
    return base


# ── Removal order ───────────────────────────────────────────────────────────


def removal_order(
    G: nx.DiGraph,
    strategy: str,
    *,
    rng: np.random.Generator | None = None,
    partitions: dict[str, dict[Any, Any]] | None = None,
) -> list[Any]:
    """Compute the node-removal order for *G* under *strategy*.

    See :data:`STRATEGY_SPECS` for the available strategies.  Tie-breaking is
    deterministic (ascending by node ID).  Empty graph returns ``[]``.

    ``rng`` is consulted for ``"random"`` and ``"spreading"`` (the stochastic
    SIR scorer); all other strategies are deterministic.  ``partitions`` (a dict
    ``{strategy_name: {node: community_id}}``) is required only for
    ``"bridging"`` / ``"bridging(...)"``.

    Worst-case dynamic complexity (|V| = N, |E| = m):
        ``in_strength_dyn`` / ``out_strength_dyn``   O(N · (N + m))
        ``pagerank_dyn`` / ``hits_*_dyn``                   O(N · power-iter)
        ``betweenness_dyn``                                 O(N² · m)
    """
    canonical, bridging_key = parse_strategy(strategy)

    if G.number_of_nodes() == 0:
        return []

    if canonical == "random":
        return _random_order(G, rng)

    if canonical == "bridging":
        if partitions is None or bridging_key not in partitions:
            raise ValueError(
                f"bridging strategy needs partition {bridging_key!r} in --community-strategies; "
                f"available: {sorted((partitions or {}).keys())}"
            )
        scores = _bridging_with_partition(G, partitions[bridging_key])
        return _sort_by_scores(G, scores, inverse=False)

    spec = STRATEGY_SPECS[canonical]
    if spec.kind == "dynamic":
        return _dynamic_order(G, spec)
    if canonical == "spreading":
        # The only static scorer that consumes randomness: thread the shared rng
        # through so the ranking honours the run's seed. Every other static scorer
        # is deterministic and ignores rng; without an rng the SIR scorer falls
        # back to its own fixed seed.
        scores = _spreading_scores(G, rng=rng)
        return _sort_by_scores(G, scores, inverse=spec.inverse)
    if spec.score_fn is None:
        raise ValueError(f"strategy {canonical!r} has no score function and isn't a recognised special case")
    scores = spec.score_fn(G)
    return _sort_by_scores(G, scores, inverse=spec.inverse)


def _random_order(G: nx.DiGraph, rng: np.random.Generator | None) -> list[Any]:
    if rng is None:
        rng = np.random.default_rng()
    nodes = list(G.nodes())
    indices = rng.permutation(len(nodes))
    return [nodes[i] for i in indices]


def _sort_by_scores(G: nx.DiGraph, scores: dict[Any, float], *, inverse: bool) -> list[Any]:
    # Descending by score (or ascending if ``inverse``), ascending by node ID for ties.
    if inverse:
        return sorted(G.nodes(), key=lambda n: (scores.get(n, float("inf")), n))
    return sorted(G.nodes(), key=lambda n: (-scores.get(n, 0.0), n))


def _dynamic_order(G: nx.DiGraph, spec: StrategySpec) -> list[Any]:
    score_fn = spec.score_fn
    if score_fn is None:
        raise ValueError(f"dynamic strategy {spec.label!r} has no score function")
    g = G.copy()
    order: list[Any] = []
    while g.number_of_nodes() > 0:
        scores = score_fn(g)
        if not scores:
            order.extend(sorted(g.nodes()))
            break
        if spec.inverse:
            nid = min(g.nodes(), key=lambda n: (scores.get(n, float("inf")), n))
        else:
            nid = min(g.nodes(), key=lambda n: (-scores.get(n, 0.0), n))
        order.append(nid)
        g.remove_node(nid)
    return order

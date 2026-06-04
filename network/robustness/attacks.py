"""Removal-order strategies for network robustness analysis.

A *removal order* is a list of node IDs ordered from "first to remove" to
"last to remove".  Strategies are partitioned into:

- **Random** — uniform shuffle, averaged over `n_random_runs` in the runner.
- **Static** — rank the nodes once on the full backbone and remove them in
  that fixed order.  One centrality pass per attack.
- **Dynamic** — recompute the ranking on the residual graph after every
  removal (``_dyn`` suffix).  Much more aggressive and much costlier.

Tie-breaking is deterministic (ascending node ID) so non-random strategies
are reproducible without an ``rng``.  All current strategies sort *descending*
by score; the ``inverse`` flag on :class:`StrategySpec` exists for future
strategies whose low values flag the critical nodes.

A single registry — :data:`STRATEGY_SPECS` — drives the available
strategies, their human labels, score functions, and sort direction.

References:
    Albert, R., Jeong, H. & Barabási, A.-L. (2000). Error and attack
        tolerance of complex networks. *Nature* 406(6794), 378-382.
        https://doi.org/10.1038/35019019
    Holme, P., Kim, B. J., Yoon, C. N. & Han, S. K. (2002). Attack
        vulnerability of complex networks. *Phys. Rev. E* 65(5), 056109.
        https://doi.org/10.1103/PhysRevE.65.056109
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import networkx as nx
import numpy as np

# ── Spec registry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategySpec:
    """Describes a removal strategy.

    ``label``           human-readable name (used by HTML / XLSX renderers)
    ``score_fn``        ``(g: nx.DiGraph) -> dict[node, float]``; ignored for
                        ``"random"``
    ``inverse``         when True, sort *ascending* — used for measures where
                        low values flag critical nodes
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


# ── Registry ────────────────────────────────────────────────────────────────


STRATEGY_SPECS: dict[str, StrategySpec] = {
    # Baseline
    "random": StrategySpec("Random failure", None, kind="random"),
    # Degree
    "in_strength": StrategySpec("In-strength", _in_strength),
    "out_strength": StrategySpec("Out-strength", _out_strength),
    # Prestige
    "pagerank": StrategySpec("PageRank", _safe_pagerank),
    # Dynamic variants
    "in_strength_dyn": StrategySpec("In-strength (dyn)", _in_strength, kind="dynamic"),
    "out_strength_dyn": StrategySpec("Out-strength (dyn)", _out_strength, kind="dynamic"),
    "pagerank_dyn": StrategySpec("PageRank (dyn)", _safe_pagerank, kind="dynamic"),
}

DEFAULT_STRATEGIES: list[str] = ["random", "in_strength", "out_strength", "pagerank"]

# Derived sets so existing imports keep working.
STATIC_STRATEGIES: frozenset[str] = frozenset(name for name, spec in STRATEGY_SPECS.items() if spec.kind != "dynamic")
DYNAMIC_STRATEGIES: frozenset[str] = frozenset(name for name, spec in STRATEGY_SPECS.items() if spec.kind == "dynamic")
ALL_STRATEGIES: list[str] = list(STRATEGY_SPECS.keys())


# ── Strategy-name parsing / validation ──────────────────────────────────────


def parse_strategy(name: str) -> str:
    """Normalise a strategy token to its canonical lowercase name.

    ``"PageRank"`` → ``"pagerank"``.  Raises ``ValueError`` for unknown names.
    """
    canonical = name.strip().lower()
    if canonical not in STRATEGY_SPECS:
        raise ValueError(f"unknown attack strategy {name!r}; choose from {sorted(STRATEGY_SPECS.keys())}")
    return canonical


def strategy_label(name: str) -> str:
    """Human-readable label for a strategy."""
    return STRATEGY_SPECS[name].label


# ── Removal order ───────────────────────────────────────────────────────────


def removal_order(
    G: nx.DiGraph,
    strategy: str,
    *,
    rng: np.random.Generator | None = None,
) -> list[Any]:
    """Compute the node-removal order for *G* under *strategy*.

    See :data:`STRATEGY_SPECS` for the available strategies.  Tie-breaking is
    deterministic (ascending by node ID).  Empty graph returns ``[]``.

    ``rng`` is consulted only for ``"random"``; all other strategies are
    deterministic.

    Worst-case dynamic complexity (|V| = N, |E| = m):
        ``in_strength_dyn`` / ``out_strength_dyn``   O(N · (N + m))
        ``pagerank_dyn``                             O(N · power-iter)
    """
    canonical = parse_strategy(strategy)

    if G.number_of_nodes() == 0:
        return []

    if canonical == "random":
        return _random_order(G, rng)

    spec = STRATEGY_SPECS[canonical]
    if spec.kind == "dynamic":
        return _dynamic_order(G, spec)
    if spec.score_fn is None:
        raise ValueError(f"strategy {canonical!r} has no score function")
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

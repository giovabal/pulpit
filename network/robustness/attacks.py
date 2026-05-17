"""Removal-order strategies for network robustness analysis.

A *removal order* is a list of node IDs ordered from "first to remove" to
"last to remove".  Two families of strategies:

- **Static** strategies rank the nodes once and remove them in that fixed
  order.  Cheap: a single centrality pass.
- **Dynamic** strategies recompute the ranking on the residual graph after
  every removal — a much more aggressive (and costlier) attack model.
  Dynamic variants carry the ``_dyn`` suffix.

Tie-breaking is deterministic (ascending node ID) so non-random strategies
are reproducible without an ``rng``.  Only ``"random"`` consults ``rng``.

Centrality computation is delegated to existing wrappers where one exists
(``network.measures.compute_betweenness``) and to ``networkx`` directly
otherwise, so the robustness module never duplicates centrality logic.

References:
    Albert, R., Jeong, H. & Barabási, A.-L. (2000). Error and attack
        tolerance of complex networks. *Nature* 406(6794), 378-382.
        https://doi.org/10.1038/35019019
    Holme, P., Kim, B. J., Yoon, C. N. & Han, S. K. (2002). Attack
        vulnerability of complex networks. *Phys. Rev. E* 65(5), 056109.
        https://doi.org/10.1103/PhysRevE.65.056109
"""

from collections.abc import Callable
from typing import Any

from network.measures import compute_betweenness

import networkx as nx
import numpy as np

STATIC_STRATEGIES: frozenset[str] = frozenset(
    {
        "random",
        "in_strength",
        "out_strength",
        "pagerank",
        "betweenness",
    }
)

DYNAMIC_STRATEGIES: frozenset[str] = frozenset(
    {
        "in_strength_dyn",
        "pagerank_dyn",
        "betweenness_dyn",
    }
)

ALL_STRATEGIES: list[str] = [
    "random",
    "in_strength",
    "out_strength",
    "pagerank",
    "betweenness",
    "in_strength_dyn",
    "pagerank_dyn",
    "betweenness_dyn",
]


def removal_order(
    G: nx.DiGraph,
    strategy: str,
    *,
    rng: np.random.Generator | None = None,
) -> list[Any]:
    """Compute the node-removal order for *G* under *strategy*.

    Static strategies — one-shot ranking; ``rng`` consulted only for
    ``"random"``:
        ``"random"``        uniform shuffle
        ``"in_strength"``   decreasing weighted in-degree
        ``"out_strength"``  decreasing weighted out-degree
        ``"pagerank"``      decreasing PageRank
        ``"betweenness"``   decreasing weighted betweenness centrality

    Dynamic strategies — re-rank after every deletion:
        ``"in_strength_dyn"``  recomputed weighted in-degree
        ``"pagerank_dyn"``     recomputed PageRank
        ``"betweenness_dyn"``  recomputed weighted betweenness

    Tie-breaking is deterministic (ascending by node ID).  Empty graph
    returns ``[]``.  Worst-case dynamic complexity (|V| = N, |E| = m):

        ``in_strength_dyn``   O(N · (N + m))
        ``pagerank_dyn``      O(N · pagerank-iteration)
        ``betweenness_dyn``   O(N² · m)  — keep this off for large graphs
    """
    if strategy not in STATIC_STRATEGIES and strategy not in DYNAMIC_STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(STATIC_STRATEGIES | DYNAMIC_STRATEGIES)}; got {strategy!r}")

    if G.number_of_nodes() == 0:
        return []

    if strategy == "random":
        return _random_order(G, rng)
    if strategy in STATIC_STRATEGIES:
        return _static_order(G, strategy)
    return _dynamic_order(G, strategy)


# ── static ───────────────────────────────────────────────────────────────────


def _random_order(G: nx.DiGraph, rng: np.random.Generator | None) -> list[Any]:
    if rng is None:
        rng = np.random.default_rng()
    nodes = list(G.nodes())
    indices = rng.permutation(len(nodes))
    return [nodes[i] for i in indices]


def _static_order(G: nx.DiGraph, strategy: str) -> list[Any]:
    scores = _static_scores(G, strategy)
    return sorted(G.nodes(), key=lambda n: (-scores.get(n, 0.0), n))


def _static_scores(G: nx.DiGraph, strategy: str) -> dict[Any, float]:
    if strategy == "in_strength":
        return dict(G.in_degree(weight="weight"))
    if strategy == "out_strength":
        return dict(G.out_degree(weight="weight"))
    if strategy == "pagerank":
        return _safe_pagerank(G)
    if strategy == "betweenness":
        return compute_betweenness(G)
    raise ValueError(f"unsupported static strategy: {strategy!r}")


def _safe_pagerank(G: nx.DiGraph) -> dict[Any, float]:
    # Power iteration can fail on adversarial residual graphs; fall back to
    # in-strength as a structural proxy so the attack loop never aborts.
    try:
        return nx.pagerank(G)
    except nx.PowerIterationFailedConvergence:
        return dict(G.in_degree(weight="weight"))


# ── dynamic ──────────────────────────────────────────────────────────────────


_DYNAMIC_SCORE_FNS: dict[str, Callable[[nx.DiGraph], dict[Any, float]]] = {
    "in_strength_dyn": lambda g: dict(g.in_degree(weight="weight")),
    "pagerank_dyn": _safe_pagerank,
    "betweenness_dyn": compute_betweenness,
}


def _dynamic_order(G: nx.DiGraph, strategy: str) -> list[Any]:
    score_fn = _DYNAMIC_SCORE_FNS[strategy]
    g = G.copy()
    order: list[Any] = []
    while g.number_of_nodes() > 0:
        scores = score_fn(g)
        if not scores:
            order.extend(sorted(g.nodes()))
            break
        nid = min(g.nodes(), key=lambda n: (-scores.get(n, 0.0), n))
        order.append(nid)
        g.remove_node(nid)
    return order

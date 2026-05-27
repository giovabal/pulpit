"""Robustness metrics for directed weighted graphs.

Three families of metrics:

1. **Attack curves** — :func:`attack_curve` returns the residual normalised
   size ``S(q)`` for ``q = 0, 1, …, N`` after removing the ``q`` first nodes
   of a given order, with three choices of *size*:

       ``"WCC"``   fraction of nodes in the largest residual weakly-connected component
       ``"SCC"``   fraction of nodes in the largest residual strongly-connected component
       ``"REACH"`` fraction of ordered pairs still connected by a directed path

   ``S`` is normalised by the *original* node count ``N`` so that
   ``R = (1/N) Σ_{q=1..N} S(q)`` (:func:`r_index`) ranges between 0 (immediate
   collapse) and ≈ 0.5 (random failure of a resilient network).  This is the
   weighted extension of Schneider et al. 2011 used by Bellingeri,
   Cassi & Vincenzi 2014.

2. **Critical threshold** — :func:`critical_threshold` returns the fraction
   of removed nodes at which ``S(f)`` first drops below ``drop_to`` times its
   initial value.

3. **Weighted global efficiency** — :func:`weighted_global_efficiency`
   computes Latora-Marchiori (PRL 2001) global efficiency on the largest SCC
   with edge distance ``d_ij = 1 / w_ij``.  Use it as a pre/post-attack
   indicator complementing the residual-size curves.

References:
    Schneider, C. M., Moreira, A. A., Andrade, J. S., Havlin, S. & Herrmann,
        H. J. (2011). Mitigation of malicious attacks on networks. *PNAS*
        108(10), 3838-3841. https://doi.org/10.1073/pnas.1009440108
    Bellingeri, M., Cassi, D. & Vincenzi, S. (2014). Efficiency of attack
        strategies on complex model and real-world networks. *Physica A* 414,
        174-180. https://doi.org/10.1016/j.physa.2014.06.079
    Latora, V. & Marchiori, M. (2001). Efficient behavior of small-world
        networks. *Phys. Rev. Lett.* 87(19), 198701.
        https://doi.org/10.1103/PhysRevLett.87.198701
"""

from typing import Any, Literal

import networkx as nx
import numpy as np

type ResidualMetric = Literal["WCC", "SCC", "REACH"]
_VALID_METRICS: frozenset[str] = frozenset({"WCC", "SCC", "REACH"})


def attack_curve(
    G: nx.DiGraph,
    removal_order: list[Any],
    metric: ResidualMetric = "WCC",
    *,
    reach_sample: int | None = 500,
    rng: np.random.Generator | None = None,
) -> list[float]:
    """Residual-size curve ``S(q)`` for ``q = 0, 1, …, len(removal_order)``.

    For ``metric="REACH"`` on graphs larger than ``reach_sample``, the
    reachable-pair count is estimated from a uniform random sample of
    ``reach_sample`` sources drawn from the *current* graph at every step
    (sampling per step keeps the estimator unbiased).  ``reach_sample=None``
    forces exact computation regardless of graph size.  ``rng`` controls the
    sampling and is allocated lazily (only when ``metric="REACH"`` and
    sampling actually kicks in).

    Nodes in ``removal_order`` that are not (or no longer) in the graph are
    silently skipped; the returned curve always has length
    ``len(removal_order) + 1``.  ``S`` is always normalised by the original
    node count ``N``, so a node removed but already absent still produces a
    curve point and ``S`` decays monotonically over the run.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}; got {metric!r}")

    n0 = G.number_of_nodes()
    if n0 == 0:
        return [0.0]

    if metric == "REACH" and rng is None:
        rng = np.random.default_rng()

    g = G.copy()

    def _step() -> float:
        if metric == "WCC":
            return _wcc_size(g, n0)
        if metric == "SCC":
            return _scc_size(g, n0)
        return _reach_size(g, n0, reach_sample, rng)

    curve: list[float] = [_step()]
    for nid in removal_order:
        if g.has_node(nid):
            g.remove_node(nid)
        curve.append(_step())
    return curve


def r_index(curve: list[float]) -> float:
    """Robustness ``R = (1/N) · Σ_{q=1..N} S(q)`` (Schneider et al. 2011).

    Expects a curve of length ``N + 1`` as produced by :func:`attack_curve`;
    ``S(0)`` is *excluded* from the sum.  Returns 0 for an empty or
    single-point curve.
    """
    if len(curve) <= 1:
        return 0.0
    n = len(curve) - 1
    return float(sum(curve[1:]) / n)


def critical_threshold(curve: list[float], drop_to: float = 0.05) -> float | None:
    """First fraction ``f_c = q / N`` at which ``S(q)`` drops below
    ``drop_to × S(0)``.  Returns ``None`` if the threshold is never reached or
    if the initial size is zero.
    """
    if not curve or curve[0] <= 0:
        return None
    n = len(curve) - 1
    if n <= 0:
        return None
    threshold = drop_to * curve[0]
    for q, s in enumerate(curve):
        if s < threshold:
            return q / n
    return None


def weighted_global_efficiency(
    G: nx.DiGraph,
    *,
    weight: str = "weight",
    nodes: set[Any] | None = None,
) -> float:
    """Weighted Latora-Marchiori efficiency of the largest SCC of *G*.

    Edge distance is ``d = 1 / w``; pair efficiency is ``1 / d`` (equal to
    the edge weight when the directed path has length 1).  When *nodes* is
    given the restriction happens *before* the SCC search.  Returns 0 if the
    SCC has fewer than two nodes.

    This is **not** the whole-graph "Global Efficiency" reported in the
    network-statistics table (:func:`network.community_stats._network_summary`),
    which is *unweighted* and averaged over *all* ordered pairs (unreachable
    pairs contributing 0).  This robustness variant is *weighted* (``1/w``) and
    restricted to the largest strongly-connected core, so it is a relative
    core-cohesion indicator (pre-attack vs post-attack), not a probability and
    not comparable to that table's value.  Unlike the unweighted form (which
    lives in ``[0, 1]``) it can exceed 1 when edge weights are above 1.
    """
    g = G.subgraph(nodes) if nodes is not None else G
    if g.number_of_nodes() < 2:
        return 0.0

    sccs = nx.strongly_connected_components(g)
    largest = max(sccs, key=len, default=set())
    if len(largest) < 2:
        return 0.0

    scc = g.subgraph(largest)
    n_scc = len(largest)

    def _dist(_u: Any, _v: Any, data: dict) -> float:
        w = data.get(weight, 0.0)
        return float("inf") if w <= 0 else 1.0 / w

    total_inv = 0.0
    for source in largest:
        lengths = nx.single_source_dijkstra_path_length(scc, source, weight=_dist)
        for target, d in lengths.items():
            if target != source and d > 0:
                total_inv += 1.0 / d
    return float(total_inv / (n_scc * (n_scc - 1)))


# ── private helpers ──────────────────────────────────────────────────────────


def _wcc_size(g: nx.DiGraph, n0: int) -> float:
    if g.number_of_nodes() == 0:
        return 0.0
    return max((len(c) for c in nx.weakly_connected_components(g)), default=0) / n0


def _scc_size(g: nx.DiGraph, n0: int) -> float:
    if g.number_of_nodes() == 0:
        return 0.0
    return max((len(c) for c in nx.strongly_connected_components(g)), default=0) / n0


def _reach_size(
    g: nx.DiGraph,
    n0: int,
    sample: int | None,
    rng: np.random.Generator,
) -> float:
    nq = g.number_of_nodes()
    if nq == 0 or n0 <= 1:
        return 0.0
    nodes = list(g.nodes())
    if sample is None or nq <= sample:
        sources = nodes
        scale = 1.0
    else:
        indices = rng.choice(nq, size=sample, replace=False)
        sources = [nodes[i] for i in indices]
        scale = nq / sample
    pair_total = sum(len(nx.descendants(g, s)) for s in sources)
    return (pair_total * scale) / (n0 * (n0 - 1))

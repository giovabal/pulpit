"""Robustness metrics for directed weighted graphs.

Four families of metrics:

1. **Attack curves** — :func:`attack_curve` returns the residual normalised
   size ``S(q)`` for ``q = 0, 1, …, N`` after removing the ``q`` first nodes
   of a given order, with four choices of *size*:

       ``"WCC"``      fraction of nodes in the largest residual weakly-connected component
       ``"SCC"``      fraction of nodes in the largest residual strongly-connected component
       ``"REACH"``    fraction of ordered pairs still connected by a directed path
       ``"STRENGTH"`` fraction of the graph's total edge weight carried by the
                      heaviest residual weakly-connected component

   The node-counting metrics are normalised by the *original* node count ``N``
   so that ``R = (1/N) Σ_{q=1..N} S(q)`` (:func:`r_index`) ranges between 0
   (immediate collapse) and ≈ 0.5 (random failure of a resilient network)
   — the Schneider et al. 2011 framework.  ``STRENGTH`` is normalised by the
   original *total edge weight* instead: it is the weighted-damage measure of
   Bellingeri & Cassi 2018 (the weight of the largest connected cluster), which
   catches attacks that leave the component *large* but gut the citation weight
   it carries — damage the unweighted sizes cannot see (Bellingeri, Cassi &
   Vincenzi 2014).

2. **Critical threshold** — :func:`critical_threshold` returns the fraction
   of removed nodes at which ``S(f)`` first drops below ``drop_to`` times its
   initial value.

3. **Weighted global efficiency** — :func:`weighted_global_efficiency`
   computes Latora-Marchiori (PRL 2001) global efficiency on the largest SCC
   with edge distance ``d_ij = 1 / w_ij``; :func:`efficiency_curve` samples it
   along a removal order on a coarse grid (it costs an all-pairs Dijkstra per
   evaluation, so a per-removal curve is prohibitive).

4. **One-shot residuals** — :func:`residual_sizes` evaluates all four sizes
   once after a block removal, the building block of the ban-wave scenarios
   in :mod:`network.robustness.scenarios`.

References:
    Schneider, C. M., Moreira, A. A., Andrade, J. S., Havlin, S. & Herrmann,
        H. J. (2011). Mitigation of malicious attacks on networks. *PNAS*
        108(10), 3838-3841. https://doi.org/10.1073/pnas.1009440108
    Bellingeri, M., Cassi, D. & Vincenzi, S. (2014). Efficiency of attack
        strategies on complex model and real-world networks. *Physica A* 414,
        174-180. https://doi.org/10.1016/j.physa.2014.06.079
    Bellingeri, M. & Cassi, D. (2018). Robustness of weighted networks.
        *Physica A* 489, 47-55. https://doi.org/10.1016/j.physa.2017.07.020
    Latora, V. & Marchiori, M. (2001). Efficient behavior of small-world
        networks. *Phys. Rev. Lett.* 87(19), 198701.
        https://doi.org/10.1103/PhysRevLett.87.198701
"""

from collections.abc import Iterable
from typing import Any, Literal

import networkx as nx
import numpy as np

type ResidualMetric = Literal["WCC", "SCC", "REACH", "STRENGTH"]
_VALID_METRICS: frozenset[str] = frozenset({"WCC", "SCC", "REACH", "STRENGTH"})


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
    ``len(removal_order) + 1``.  ``S`` is always normalised against the
    original graph (node count ``N`` for the node-counting metrics, total
    edge weight for ``"STRENGTH"``), so a node removed but already absent
    still produces a curve point and ``S`` decays monotonically over the run.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}; got {metric!r}")

    n0 = G.number_of_nodes()
    if n0 == 0:
        return [0.0]
    w0 = G.size(weight="weight") if metric == "STRENGTH" else 0.0

    if metric == "REACH" and rng is None:
        rng = np.random.default_rng()

    g = G.copy()

    def _step() -> float:
        if metric == "WCC":
            return _wcc_size(g, n0)
        if metric == "SCC":
            return _scc_size(g, n0)
        if metric == "STRENGTH":
            return _strength_size(g, w0)
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


def residual_sizes(
    G: nx.DiGraph,
    remove: Iterable[Any],
    *,
    reach_sample: int | None = 500,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """One-shot residual sizes after removing the *remove* nodes from *G*.

    Same normalisations as :func:`attack_curve` (node counts against the
    original ``N``, surviving strength against the original total edge
    weight), evaluated once on the residual graph instead of per removal —
    the building block of the ban-wave scenarios.  Keys are the lowercase
    metric names: ``"wcc"``, ``"scc"``, ``"reach"``, ``"strength"``.  Nodes
    in *remove* that are not in the graph are silently skipped; *G* is never
    mutated.
    """
    n0 = G.number_of_nodes()
    if n0 == 0:
        return {"wcc": 0.0, "scc": 0.0, "reach": 0.0, "strength": 0.0}
    w0 = G.size(weight="weight")
    if rng is None:
        rng = np.random.default_rng()
    g = G.copy()
    g.remove_nodes_from([nid for nid in remove if g.has_node(nid)])
    return component_sizes(g, n0=n0, w0=w0, reach_sample=reach_sample, rng=rng)


def component_sizes(
    g: nx.DiGraph,
    *,
    n0: int,
    w0: float,
    reach_sample: int | None = 500,
    rng: np.random.Generator | None = None,
) -> dict[str, float]:
    """The four residual sizes of *g*, normalised against *external* ``n0``/``w0``.

    Unlike :func:`residual_sizes` (which removes nodes from a graph and
    normalises against that same graph), this evaluates the four sizes of an
    already-built graph *g* against a caller-supplied node count ``n0`` and
    total edge weight ``w0``.  That lets a *predicted* residual (a pre-wave
    graph with the banned block removed) and an *observed* residual (the
    post-wave graph restricted to the survivors) be normalised against the
    same pre-wave baseline, so the two are directly comparable — the building
    block of :mod:`network.robustness.replay`.  Keys are the lowercase metric
    names ``"wcc"`` / ``"scc"`` / ``"reach"`` / ``"strength"``.
    """
    if rng is None:
        rng = np.random.default_rng()
    return {
        "wcc": _wcc_size(g, n0),
        "scc": _scc_size(g, n0),
        "reach": _reach_size(g, n0, reach_sample, rng),
        "strength": _strength_size(g, w0),
    }


def efficiency_curve(
    G: nx.DiGraph,
    removal_order: list[Any],
    *,
    weight: str = "weight",
    n_points: int = 20,
) -> tuple[list[float], list[float]]:
    """Weighted global efficiency along *removal_order*, sampled on a coarse grid.

    :func:`weighted_global_efficiency` costs an all-pairs Dijkstra over the
    largest SCC, so evaluating it after every removal (as the residual-size
    curves do) is prohibitive.  Instead it is evaluated at ``n_points + 1``
    approximately evenly spaced removal counts, always including ``q = 0``
    and ``q = N``.  Returns ``(fractions, values)`` where ``fractions[i]`` is
    the fraction of nodes removed at evaluation point *i*.  Efficiency is the
    weighted damage indicator of Bellingeri, Cassi & Vincenzi (2014): it
    weighs *how well* the surviving core is knit rather than how many nodes
    remain, so it can degrade sharply while the residual-size curves still
    look healthy.
    """
    n = len(removal_order)
    if n == 0 or G.number_of_nodes() == 0:
        return [0.0], [weighted_global_efficiency(G, weight=weight)]
    grid = sorted({round(i * n / n_points) for i in range(n_points + 1)})
    g = G.copy()
    fractions: list[float] = []
    values: list[float] = []
    next_i = 0
    for q in range(n + 1):
        if next_i < len(grid) and q == grid[next_i]:
            fractions.append(q / n)
            values.append(weighted_global_efficiency(g, weight=weight))
            next_i += 1
        if q < n:
            nid = removal_order[q]
            if g.has_node(nid):
                g.remove_node(nid)
    return fractions, values


# ── private helpers ──────────────────────────────────────────────────────────


def _wcc_size(g: nx.DiGraph, n0: int) -> float:
    if g.number_of_nodes() == 0:
        return 0.0
    return max((len(c) for c in nx.weakly_connected_components(g)), default=0) / n0


def _scc_size(g: nx.DiGraph, n0: int) -> float:
    if g.number_of_nodes() == 0:
        return 0.0
    return max((len(c) for c in nx.strongly_connected_components(g)), default=0) / n0


def _strength_size(g: nx.DiGraph, w0: float) -> float:
    # Weight of the heaviest residual WCC over the original total weight.
    # "Heaviest" (not "largest by nodes") keeps the curve monotone: every
    # residual component is a subgraph of a pre-removal component, so the
    # max internal weight can only decrease.
    if w0 <= 0 or g.number_of_edges() == 0:
        return 0.0
    best = 0.0
    for comp in nx.weakly_connected_components(g):
        tw = g.subgraph(comp).size(weight="weight")
        if tw > best:
            best = tw
    return best / w0


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

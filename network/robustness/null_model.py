"""Null model for the robustness battery — a directed weighted configuration model.

This implements the *strength-preserving* null: a randomised graph that keeps
each node's in/out **degree** sequence exactly and its in/out **strength**
sequence (approximately), while randomising the topology. It supersedes the
earlier weight-shuffle null, which merely permuted the weight multiset over a
*fixed* topology and so preserved no structural constraint beyond the wiring
itself — leaving deviations attributable only to weight placement.

It is built in two stages (see :func:`rewire_strength_preserving`):
    1. **Maslov–Sneppen directed edge swaps** — randomise which pairs are
       connected while preserving the exact in/out degree sequence.
    2. **Iterative proportional fitting** (Sinkhorn) — rescale the rewired weights
       back onto the observed in/out strength sequence.

**What this null preserves**
    - per-node in- and out-degree (exactly),
    - per-node in- and out-strength (approximately, via IPF),
    - total number of edges and total edge weight.

**What it randomises**
    - the topology (which pairs are connected, beyond the degree sequence),
    - clustering, reciprocity, motifs, and weight–topology coupling.

So a deviation between the observed R and the null R reflects higher-order
structure, not the degree/strength sequences the attack strategies already
rank on.

The companion :func:`z_score` helper turns ``(R_observed, [R_null_1, …,
R_null_K])`` into a standard ``(z, μ_null, σ_null)`` triple, with
``ddof=1`` sample standard deviation since the K simulations are a sample
of the null distribution.  :func:`empirical_p` reports the same comparison
without the normality assumption the z-score smuggles in: a two-sided
add-one Monte-Carlo p-value (North, Curtis & Sham 2002; Phipson & Smyth
2010), whose resolution floor ``2/(K+1)`` makes the certainty K draws can
actually support explicit.

References:
    Maslov, S. & Sneppen, K. (2002). Specificity and stability in topology
        of protein networks. *Science* 296(5569), 910-913.
        https://doi.org/10.1126/science.1065103
    Serrano, M. Á. & Boguñá, M. (2005). Weighted configuration model.
        *AIP Conference Proceedings* 776, 101-107.
        https://doi.org/10.1063/1.1985381
    North, B. V., Curtis, D. & Sham, P. C. (2002). A note on the calculation
        of empirical P values from Monte Carlo procedures. *American Journal
        of Human Genetics* 71(2), 439-441. https://doi.org/10.1086/341527
    Phipson, B. & Smyth, G. K. (2010). Permutation P-values should never be
        zero: calculating exact P-values when permutations are randomly
        drawn. *Statistical Applications in Genetics and Molecular Biology*
        9(1), Article 39. https://doi.org/10.2202/1544-6115.1585
"""

from collections.abc import Iterator

import networkx as nx
import numpy as np

_IPF_ITERATIONS = 50


def rewire_strength_preserving(
    G: nx.DiGraph,
    *,
    weight: str = "weight",
    n_swaps: int | None = None,
    rng: np.random.Generator | None = None,
) -> nx.DiGraph:
    """Return a randomised copy of *G* that preserves the in/out degree sequence
    exactly and the in/out strength sequence approximately — a directed weighted
    configuration-model null.

    Two stages:

    1. **Maslov–Sneppen directed edge swaps** (2002): repeatedly pick two edges
       ``(a→b)`` and ``(c→d)`` and rewire them to ``(a→d)`` and ``(c→b)`` whenever
       that creates no self-loop or duplicate edge, carrying each edge's weight
       with it. This preserves the exact in- and out-degree sequence while
       randomising *which* pairs are connected. ``n_swaps`` is the number of swap
       *attempts* and defaults to ``10 · |E|``.
    2. **Iterative proportional fitting** (Sinkhorn): alternately rescale every
       node's out-edges to its observed out-strength and in-edges to its observed
       in-strength, for ``_IPF_ITERATIONS`` rounds. Because the degree sequence
       is preserved the system is feasible, so the rewired weights converge onto
       G's strength sequence (and hence its total weight).

    The result shares G's degree *and* strength sequences but not its wiring, so a
    robustness deviation from this null reflects higher-order structure rather than
    the strength sequence the attack strategies already rank on.

    Graphs with fewer than two edges are returned as a plain copy. The input graph
    is never mutated.
    """
    H = G.copy()
    m = H.number_of_edges()
    if m < 2:
        return H

    if rng is None:
        rng = np.random.default_rng()
    if n_swaps is None:
        n_swaps = 10 * m

    # ── Stage 1: degree-preserving edge swaps ─────────────────────────────────
    edges = list(H.edges())
    draws = rng.integers(0, m, size=2 * n_swaps)
    for k in range(n_swaps):
        i, j = int(draws[2 * k]), int(draws[2 * k + 1])
        if i == j:
            continue
        a, b = edges[i]
        c, d = edges[j]
        # Skip swaps that share an endpoint (no-op) or would make a self-loop or
        # a parallel edge.
        if a == c or b == d or a == d or c == b:
            continue
        if H.has_edge(a, d) or H.has_edge(c, b):
            continue
        w_ab = H.edges[a, b][weight]
        w_cd = H.edges[c, d][weight]
        H.remove_edge(a, b)
        H.remove_edge(c, d)
        H.add_edge(a, d, **{weight: w_ab})
        H.add_edge(c, b, **{weight: w_cd})
        edges[i] = (a, d)
        edges[j] = (c, b)

    # ── Stage 2: IPF rescaling onto the observed strength sequence ────────────
    target_out = dict(G.out_degree(weight=weight))
    target_in = dict(G.in_degree(weight=weight))
    for _ in range(_IPF_ITERATIONS):
        cur_out = dict(H.out_degree(weight=weight))
        for u in H.nodes():
            cur, tgt = cur_out.get(u, 0.0), target_out.get(u, 0.0)
            if cur > 0 and tgt > 0:
                scale = tgt / cur
                for _, v in H.out_edges(u):
                    H.edges[u, v][weight] *= scale
        cur_in = dict(H.in_degree(weight=weight))
        for v in H.nodes():
            cur, tgt = cur_in.get(v, 0.0), target_in.get(v, 0.0)
            if cur > 0 and tgt > 0:
                scale = tgt / cur
                for u, _ in H.in_edges(v):
                    H.edges[u, v][weight] *= scale
    return H


def null_distribution(
    G: nx.DiGraph,
    n_simulations: int = 20,
    *,
    rng: np.random.Generator | None = None,
    n_swaps: int | None = None,
) -> Iterator[nx.DiGraph]:
    """Yield *n_simulations* independent rewired copies of *G*.

    Streams to keep peak memory at O(|G|): callers should consume each
    rewired graph (compute its attack curves, harvest R values, …) before
    moving on to the next.  All simulations share the same *rng*, so a
    fixed seed makes the whole sequence reproducible.
    """
    if n_simulations <= 0:
        return
    if rng is None:
        rng = np.random.default_rng()
    for _ in range(n_simulations):
        yield rewire_strength_preserving(G, weight="weight", n_swaps=n_swaps, rng=rng)


def empirical_p(observed: float, null_samples: list[float]) -> float:
    """Two-sided add-one empirical p-value of *observed* against *null_samples*.

    Follows the Monte-Carlo convention of North, Curtis & Sham (2002) /
    Phipson & Smyth (2010): the observed value counts as one member of the
    null distribution, so each tail is ``(b + 1) / (K + 1)`` with ``b`` the
    number of null samples at least as extreme in that direction, and the
    two-sided p doubles the smaller tail (capped at 1).  The +1 keeps the
    p-value from ever reaching zero — with K draws the smallest reportable
    two-sided value is ``2 / (K + 1)``, which is the honest resolution of
    the simulation (K = 20 bottoms out at ≈ 0.095; publication-grade claims
    at α = 0.05 need K ≥ 79).

    Unlike :func:`z_score` this makes no normality assumption and stays
    defined when the null distribution has zero variance (all draws equal):
    an observed value sitting inside the degenerate null gets p = 1, one
    outside it gets the resolution floor.  Returns ``nan`` for an empty
    sample list.
    """
    if not null_samples:
        return float("nan")
    arr = np.asarray(null_samples, dtype=float)
    k = arr.size
    p_low = (float((arr <= observed).sum()) + 1.0) / (k + 1.0)
    p_high = (float((arr >= observed).sum()) + 1.0) / (k + 1.0)
    return min(1.0, 2.0 * min(p_low, p_high))


def z_score(observed: float, null_samples: list[float]) -> tuple[float, float, float]:
    """Return ``(z, μ_null, σ_null)`` for ``z = (observed − μ) / σ``.

    Uses the sample standard deviation (``ddof=1``) since the *null_samples*
    are a sample of the null distribution, not the full population.  ``z``
    is ``nan`` when there are no samples or when σ is zero (e.g. a
    degenerate null where every simulation produced the same R).  An empty
    sample list returns ``(nan, nan, nan)``.
    """
    if not null_samples:
        return (float("nan"), float("nan"), float("nan"))
    arr = np.asarray(null_samples, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    if std == 0.0:
        return (float("nan"), mean, std)
    return ((observed - mean) / std, mean, std)

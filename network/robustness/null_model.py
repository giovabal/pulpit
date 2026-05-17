"""Null model for the robustness battery — weight-rewiring on a fixed topology.

The ideal null model would be a *directed weighted configuration model* that
preserves each node's ``(s_in, s_out)`` strength sequence.  This module
implements the cheaper and more commonly used *weight-shuffling* variant:
the graph topology and the *multiset* of edge weights are preserved, but
weights are randomly permuted among the existing edges via pairwise swaps.

**What this null preserves**
    - graph topology (the same pairs are connected),
    - total number of edges and total sum of weights,
    - the multiset of edge weights,
    - per-node binary in- and out-degree.

**What this null does NOT preserve** (documented limitations)
    - per-node in-strength / out-strength,
    - reciprocity (the (u, v) and (v, u) weights are reshuffled independently),
    - clustering coefficient,
    - higher-order motifs and assortativity patterns.

In other words: any deviation between the observed R and the null R can be
attributed only to the *distribution of weights across edges*, not to the
underlying topology or to richer correlations.  When you need a stricter
null, use a per-node strength-preserving sampler (e.g. Maslov-Sneppen style
edge-swap with weight reassignment); this module is the minimum acceptable
baseline as discussed in the project's robustness-analysis brief.

The companion :func:`z_score` helper turns ``(R_observed, [R_null_1, …,
R_null_K])`` into a standard ``(z, μ_null, σ_null)`` triple, with
``ddof=1`` sample standard deviation since the K simulations are a sample
of the null distribution.

References:
    Serrano, M. Á. & Boguñá, M. (2005). Weighted configuration model.
        *AIP Conference Proceedings* 776, 101-107.
        https://doi.org/10.1063/1.1985381
    Maslov, S. & Sneppen, K. (2002). Specificity and stability in topology
        of protein networks. *Science* 296(5569), 910-913.
        https://doi.org/10.1126/science.1065103
"""

from collections.abc import Iterator

import networkx as nx
import numpy as np


def rewire_weights(
    G: nx.DiGraph,
    *,
    weight: str = "weight",
    n_swaps: int | None = None,
    rng: np.random.Generator | None = None,
) -> nx.DiGraph:
    """Return a copy of *G* whose edge weights have been pairwise-swapped.

    Topology is preserved (the same ``(u, v)`` pairs carry an edge); only
    the weights are reshuffled.  ``n_swaps`` is the number of swap *attempts*
    and defaults to ``10 * |E|``.  Each attempt draws two random edge
    indices uniformly; identity swaps (the same index picked twice) are
    silent no-ops, which happens at expected rate ``1/|E|`` so well above
    99% of attempts move weights for any non-trivial graph.

    Graphs with fewer than two edges are returned as a plain copy (nothing
    to swap).  The input graph is never mutated.
    """
    H = G.copy()
    m = H.number_of_edges()
    if m < 2:
        return H

    if rng is None:
        rng = np.random.default_rng()
    if n_swaps is None:
        n_swaps = 10 * m

    edges = list(H.edges())
    weights = np.array([H.edges[u, v].get(weight, 0.0) for u, v in edges], dtype=float)

    idx = rng.integers(0, m, size=2 * n_swaps)
    for i in range(n_swaps):
        a, b = int(idx[2 * i]), int(idx[2 * i + 1])
        if a != b:
            weights[a], weights[b] = weights[b], weights[a]

    for k, (u, v) in enumerate(edges):
        H.edges[u, v][weight] = float(weights[k])
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
        yield rewire_weights(G, weight="weight", n_swaps=n_swaps, rng=rng)


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

"""Null models for the robustness battery — directed weighted configuration models.

Two nulls are offered, both randomised graphs that keep each node's in/out
**degree** sequence exactly and its in/out **strength** sequence
(approximately) while randomising the topology.  They supersede the earlier
weight-shuffle null, which merely permuted the weight multiset over a *fixed*
topology and so preserved no structural constraint beyond the wiring itself.

**``"configuration"``** (:func:`rewire_strength_preserving`) — the default.
Two stages:
    1. **Maslov–Sneppen directed edge swaps** — randomise which pairs are
       connected while preserving the exact in/out degree sequence.
    2. **Iterative proportional fitting** (Sinkhorn) — rescale the rewired weights
       back onto the observed in/out strength sequence.

**``"reciprocal"``** (:func:`rewire_reciprocity_preserving`) — the
reciprocity-preserving variant.  Identical, except the stage-1 swaps run
*within dyad classes*: reciprocated pairs (``a⇄b``) are swapped only against
other reciprocated pairs (as whole dyads), and single edges only against other
single edges under a constraint that forbids creating or destroying a
reciprocal tie.  It therefore also holds each node's **reciprocated degree**
fixed and the network's global reciprocity constant — the Squartini &
Garlaschelli (2011) reciprocal-configuration-model constraint, realised by
degree-preserving rewiring rather than analytically.  Choose it when mutual
citation (echo-chamber cores) is itself the structure under test, so that a
significant deviation cannot be explained away as "the network merely has
reciprocated dyads".

**What both nulls preserve**
    - per-node in- and out-degree (exactly),
    - per-node in- and out-strength (approximately, via IPF),
    - total number of edges and total edge weight.
    ``"reciprocal"`` additionally preserves per-node reciprocated degree and
    global reciprocity (exactly).

**What ``"configuration"`` randomises** (and ``"reciprocal"`` keeps of it)
    - the topology (which pairs are connected, beyond the degree sequence),
    - clustering, reciprocity, motifs, and weight–topology coupling —
      ``"reciprocal"`` retains reciprocity while still randomising the rest.

So a deviation between the observed R and the null R reflects higher-order
structure, not the degree/strength sequences the attack strategies already
rank on (nor reciprocity, under the ``"reciprocal"`` null).

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
    Squartini, T. & Garlaschelli, D. (2011). Analytical maximum-likelihood
        method to detect patterns in real networks. *New Journal of Physics*
        13, 083001. https://doi.org/10.1088/1367-2630/13/8/083001
    North, B. V., Curtis, D. & Sham, P. C. (2002). A note on the calculation
        of empirical P values from Monte Carlo procedures. *American Journal
        of Human Genetics* 71(2), 439-441. https://doi.org/10.1086/341527
    Phipson, B. & Smyth, G. K. (2010). Permutation P-values should never be
        zero: calculating exact P-values when permutations are randomly
        drawn. *Statistical Applications in Genetics and Molecular Biology*
        9(1), Article 39. https://doi.org/10.2202/1544-6115.1585
"""

from collections.abc import Iterator
from typing import Literal

import networkx as nx
import numpy as np

type NullModel = Literal["configuration", "reciprocal"]
_VALID_NULL_MODELS: frozenset[str] = frozenset({"configuration", "reciprocal"})

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
    _ipf_rescale(H, G, weight)
    return H


def rewire_reciprocity_preserving(
    G: nx.DiGraph,
    *,
    weight: str = "weight",
    n_swaps: int | None = None,
    rng: np.random.Generator | None = None,
) -> nx.DiGraph:
    """Return a randomised copy of *G* that additionally preserves reciprocity.

    Same two-stage recipe as :func:`rewire_strength_preserving`, but the stage-1
    Maslov–Sneppen swaps run *within dyad classes* so the reciprocity structure
    is invariant:

    * **Reciprocated dyads** (``a⇄b``) are swapped as whole units against other
      reciprocated dyads: ``{a⇄b}, {c⇄d} → {a⇄d}, {b⇄c}``, carrying each node's
      outgoing weight with it.  The result stays reciprocated on both new pairs.
    * **Single edges** (``a→b`` with no ``b→a``) are swapped against other single
      edges ``a→d``/``c→b`` only when neither reverse edge (``d→a``, ``b→c``)
      exists — so a single tie can never become reciprocated, nor vice versa.

    This holds each node's reciprocated in/out degree fixed on top of its total
    in/out degree, hence global reciprocity is exactly preserved (the
    reciprocal-configuration-model constraint of Squartini & Garlaschelli 2011,
    realised by rewiring).  ``n_swaps`` defaults to ``10·|E|`` swap *attempts*,
    split across the two classes in proportion to their edge counts.  The input
    graph is never mutated; graphs with fewer than two edges are returned as a
    plain copy.
    """
    H = G.copy()
    m = H.number_of_edges()
    if m < 2:
        return H
    if rng is None:
        rng = np.random.default_rng()
    if n_swaps is None:
        n_swaps = 10 * m

    # Partition the directed edges into reciprocated dyads (each unordered pair
    # once) and single edges.
    dyads: list[tuple] = []
    singles: list[tuple] = []
    seen_dyad: set = set()
    for u, v in H.edges():
        if H.has_edge(v, u):
            key = (u, v) if u <= v else (v, u)
            if key not in seen_dyad:
                seen_dyad.add(key)
                dyads.append(key)
        else:
            singles.append((u, v))

    # ── Stage 1: dyad-class-preserving swaps ──────────────────────────────────
    total = len(dyads) + len(singles)
    if total > 0:
        dyad_attempts = round(n_swaps * len(dyads) / total)
        _swap_dyads(H, dyads, dyad_attempts, weight, rng)
        _swap_singles(H, singles, n_swaps - dyad_attempts, weight, rng)

    # ── Stage 2: IPF rescaling onto the observed strength sequence ────────────
    _ipf_rescale(H, G, weight)
    return H


def _swap_dyads(H: nx.DiGraph, dyads: list[tuple], attempts: int, weight: str, rng: np.random.Generator) -> None:
    if len(dyads) < 2 or attempts <= 0:
        return
    draws = rng.integers(0, len(dyads), size=2 * attempts)
    for k in range(attempts):
        i, j = int(draws[2 * k]), int(draws[2 * k + 1])
        if i == j:
            continue
        a, b = dyads[i]
        c, d = dyads[j]
        if len({a, b, c, d}) < 4:
            continue
        # New dyads {a,d} and {b,c}: reject if either already has an edge in
        # any direction (would collide or merge dyads).
        if H.has_edge(a, d) or H.has_edge(d, a) or H.has_edge(b, c) or H.has_edge(c, b):
            continue
        w_ab, w_ba = H.edges[a, b][weight], H.edges[b, a][weight]
        w_cd, w_dc = H.edges[c, d][weight], H.edges[d, c][weight]
        H.remove_edge(a, b)
        H.remove_edge(b, a)
        H.remove_edge(c, d)
        H.remove_edge(d, c)
        # Carry each node's *outgoing* weight to its new out-edge.
        H.add_edge(a, d, **{weight: w_ab})
        H.add_edge(d, a, **{weight: w_dc})
        H.add_edge(b, c, **{weight: w_ba})
        H.add_edge(c, b, **{weight: w_cd})
        dyads[i] = (a, d) if a <= d else (d, a)
        dyads[j] = (b, c) if b <= c else (c, b)


def _swap_singles(H: nx.DiGraph, singles: list[tuple], attempts: int, weight: str, rng: np.random.Generator) -> None:
    if len(singles) < 2 or attempts <= 0:
        return
    draws = rng.integers(0, len(singles), size=2 * attempts)
    for k in range(attempts):
        i, j = int(draws[2 * k]), int(draws[2 * k + 1])
        if i == j:
            continue
        a, b = singles[i]
        c, d = singles[j]
        if a == c or b == d or a == d or c == b:
            continue
        # Target edges must be free, and their reverses must be absent so the
        # swap never turns a single tie into a reciprocated one.
        if H.has_edge(a, d) or H.has_edge(c, b) or H.has_edge(d, a) or H.has_edge(b, c):
            continue
        w_ab = H.edges[a, b][weight]
        w_cd = H.edges[c, d][weight]
        H.remove_edge(a, b)
        H.remove_edge(c, d)
        H.add_edge(a, d, **{weight: w_ab})
        H.add_edge(c, b, **{weight: w_cd})
        singles[i] = (a, d)
        singles[j] = (c, b)


def _ipf_rescale(H: nx.DiGraph, G: nx.DiGraph, weight: str) -> None:
    """Iterative proportional fitting: rescale H's weights onto G's in/out strength."""
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


def null_distribution(
    G: nx.DiGraph,
    n_simulations: int = 20,
    *,
    rng: np.random.Generator | None = None,
    n_swaps: int | None = None,
    model: NullModel = "configuration",
) -> Iterator[nx.DiGraph]:
    """Yield *n_simulations* independent rewired copies of *G*.

    *model* selects the null: ``"configuration"`` (default, degree/strength
    preserving) or ``"reciprocal"`` (additionally reciprocity-preserving).

    Streams to keep peak memory at O(|G|): callers should consume each
    rewired graph (compute its attack curves, harvest R values, …) before
    moving on to the next.  All simulations share the same *rng*, so a
    fixed seed makes the whole sequence reproducible.
    """
    if n_simulations <= 0:
        return
    if model not in _VALID_NULL_MODELS:
        raise ValueError(f"model must be one of {sorted(_VALID_NULL_MODELS)}; got {model!r}")
    if rng is None:
        rng = np.random.default_rng()
    rewire = rewire_reciprocity_preserving if model == "reciprocal" else rewire_strength_preserving
    for _ in range(n_simulations):
        yield rewire(G, weight="weight", n_swaps=n_swaps, rng=rng)


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


def bh_adjust(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), order-preserving.

    Standard step-up FDR control (Benjamini & Hochberg 1995): ``q_(i) = min``
    over ``j ≥ i`` of ``p_(j) · m / j``, capped at 1.  The robustness runner
    applies it across the whole (strategy × metric) grid of empirical
    p-values, so each reported q accounts for how many attack/metric cells
    were tested at once — the same correction the vacancy analysis already
    uses across its candidate list.  ``nan`` inputs are carried through
    unchanged (a strategy with no null variance has no p to adjust) and are
    excluded from the test count ``m``.

    Reference:
        Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery
        rate: a practical and powerful approach to multiple testing. *JRSS B*
        57(1), 289-300. https://doi.org/10.1111/j.2517-6161.1995.tb02031.x
    """
    finite = [i for i, p in enumerate(pvals) if not np.isnan(p)]
    m = len(finite)
    adjusted = list(pvals)
    if m == 0:
        return adjusted
    order = sorted(finite, key=lambda i: pvals[i])
    running_min = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running_min = min(running_min, pvals[i] * m / (rank + 1))
        adjusted[i] = running_min
    return adjusted


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

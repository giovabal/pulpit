import logging
from math import isnan

from network.measures._base import apply_measure, compute_neighbour_community_participation
from network.utils import GraphData, to_undirected_sum

import networkx as nx
import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import lsqr

logger = logging.getLogger(__name__)


def apply_pagerank(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add the PageRank score to each node.

    Channels the network's own key players treat as authoritative: a node's score
    aggregates the PageRank of the channels that forward or mention it, each
    amplifier's vote split proportionally to the edge weight it dedicates to that
    source. The citation orientation ``build_graph`` writes (amplifier→source,
    citing→cited) is exactly the orientation Brin & Page defined PageRank on —
    incoming edges are *received* citations, so the standard fixed-point

        ``PR(v) = (1 - α)/N + α · Σ_u PR(u) · w(u→v) / Σ_w w(u→w)``

    propagates prestige toward sources without any orientation tricks. NetworkX's
    ``nx.pagerank`` is used with its defaults (``α = 0.85`` damping, dangling
    nodes redistributed uniformly, edge weight = ``"weight"``); the random walk
    is scale-invariant to ``build_graph``'s global max-10 rescaling. See
    `docs/network-measures.md#pagerank` for the prose write-up.

    Refs: Brin & Page 1998, *Computer Networks* 30(1–7); Page, Brin, Motwani &
    Winograd 1999, "The PageRank citation ranking", Stanford TR.
    """
    key = "pagerank"
    try:
        pagerank_values: dict[str, float] = nx.pagerank(graph)
    except Exception as exc:  # noqa: BLE001
        # PageRank rarely fails, but power iteration can diverge on adversarial /
        # degenerate graphs; degrade gracefully rather than aborting the whole
        # export (parity with the HITS handler below).
        logger.warning("PageRank could not be computed (%s); skipping score", exc)
        return []
    for node in graph_data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]
    return [(key, "PageRank")]


def compute_hits(
    graph: nx.DiGraph, *, max_iter: int = 100, tol: float = 1.0e-8
) -> tuple[dict[str, float], dict[str, float]]:
    """Weighted HITS hub & authority scores (Kleinberg 1999, weighted variant).

    Computes HITS on the *weighted* adjacency ``A`` (``A[u,v] = w(u→v)``) by power
    iteration:

        ``a = Aᵀ h``   (authority of v = Σ_u w(u→v) · hub(u))
        ``h = A a``    (hub of v       = Σ_u w(v→u) · authority(u))

    iterated to convergence (each vector rescaled by its max per step) and finally
    normalised so each vector sums to 1 — matching ``nx.hits(normalized=True)``,
    which is also weight-aware on this NetworkX version (it builds the adjacency
    via ``nx.adjacency_matrix`` with its default ``weight="weight"``). The reason
    Pulpit keeps its own implementation is twofold: ``nx.hits`` is backed by SciPy
    SVDS, which raises ``ArpackNoConvergence`` on degenerate residual graphs (lone
    self-loops, near-empty backbones) that show up during robustness attacks; and
    the same routine is reused by ``robustness.attacks`` so the attack ranking and
    the measure cannot drift if NetworkX changes its internals.

    Returns ``(hubs, authorities)`` keyed by node id; ``({}, {})`` for an empty
    graph.
    """
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}, {}
    a_mat = nx.to_scipy_sparse_array(graph, nodelist=nodes, weight="weight", dtype=float, format="csr")
    at_mat = a_mat.T.tocsr()
    hub = np.full(n, 1.0 / n)
    for _ in range(max_iter):
        auth = at_mat @ hub
        auth_max = auth.max() if auth.size else 0.0
        if auth_max > 0:
            auth = auth / auth_max
        new_hub = a_mat @ auth
        hub_max = new_hub.max() if new_hub.size else 0.0
        if hub_max > 0:
            new_hub = new_hub / hub_max
        if float(np.abs(new_hub - hub).sum()) < tol:
            hub = new_hub
            break
        hub = new_hub
    auth = at_mat @ hub
    hub_sum = float(hub.sum())
    auth_sum = float(auth.sum())
    if hub_sum > 0:
        hub = hub / hub_sum
    if auth_sum > 0:
        auth = auth / auth_sum
    return (
        {nid: float(v) for nid, v in zip(nodes, hub, strict=True)},
        {nid: float(v) for nid, v in zip(nodes, auth, strict=True)},
    )


def apply_hits(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add weighted HITS hub and authority scores to each node."""
    try:
        hubs, authorities = compute_hits(graph)
    except Exception as exc:  # noqa: BLE001
        # Degrade gracefully on degenerate graphs (e.g. a lone self-referencing
        # channel) instead of aborting the whole export.
        logger.warning("HITS could not be computed (%s); skipping hub/authority scores", exc)
        return []
    for node in graph_data["nodes"]:
        node["hits_hub"] = hubs.get(node["id"], 0.0)
        node["hits_authority"] = authorities.get(node["id"], 0.0)
    return [("hits_hub", "HITS Hub"), ("hits_authority", "HITS Authority")]


def proximity_distances(graph: nx.DiGraph) -> nx.DiGraph:
    """Return a copy of *graph* with a ``distance`` edge attribute = ``1 / weight``.

    Our ``weight`` is tie *strength* (``build_graph`` sets it to
    ``10 · total / normalizer / max``, so higher = stronger), but every NetworkX
    shortest-path routine *minimises* the distance attribute. Passing strength
    straight through would route paths *around* the strongest ties, inverting any
    distance-based measure (the lightly-trafficked node would score as the broker /
    the closest). Inverting strength to a proximity distance ``1 / weight``
    (Brandes 2001; Opsahl, Agneessens & Skvoretz 2010) makes heavily-forwarded
    edges *short*, so betweenness and harmonic centrality both agree on
    what "close" means. Done on a copy so the source graph's ``weight`` attribute —
    which the null-model rewiring permutes — is never touched.
    """
    g = graph.copy()
    for _u, _v, data in g.edges(data=True):
        w = data.get("weight", 1.0)
        data["distance"] = (1.0 / w) if w > 0 else float("inf")
    return g


def compute_betweenness(graph: nx.DiGraph) -> dict[str, float]:
    """Compute betweenness centrality with tie strength mapped to proximity.

    Computed over the ``distance = 1 / weight`` projection (see
    :func:`proximity_distances`) so the nodes brokering real flow score highest.
    """
    return nx.betweenness_centrality(proximity_distances(graph), weight="distance")


def apply_betweenness_centrality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add betweenness centrality to each node.

    If ``betweenness`` is provided (pre-computed via ``compute_betweenness``),
    the nx call is skipped, allowing the caller to share one computation with
    ``apply_bridging_centrality``.
    """
    values = betweenness if betweenness is not None else compute_betweenness(graph)
    return apply_measure(graph_data, values, "betweenness", "Betweenness Centrality")


def apply_in_degree_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Freeman-normalised in-degree centrality to each node.

    The canonical degree centrality of a directed graph: ``C_in(v) = deg_in(v) / (n − 1)``,
    where ``deg_in(v)`` is the number of *distinct* predecessors of ``v`` and ``n − 1`` is the
    maximum achievable on a star graph. ``build_graph`` writes edges amplifier→source, so
    the in-degree counts how many distinct channels cite this one — the audience / prestige
    side of the prestige↔expansiveness pair (Wasserman & Faust 1994 §5).

    Unweighted by design: ``nx.in_degree_centrality`` discards edge weights and counts
    distinct predecessors, mirroring Freeman's (1978) original definition. The weighted
    counterpart — the in-strength ``in_deg = Σ_u w(u→v)`` — is reported separately by
    :func:`apply_base_node_measures` and answers a different question (intensity, not
    breadth). The unweighted measure is the one fed to Freeman centralisation in
    ``network/community_stats.py`` because the star bound is exact for it; the in-strength
    has no comparable theoretical maximum and is excluded there. See
    `docs/network-measures.md#in-degree-centrality` for the prose write-up.

    Refs: Freeman 1978, *Social Networks* 1(3); Wasserman & Faust 1994 §5.
    """
    return apply_measure(graph_data, nx.in_degree_centrality(graph), "in_degree_centrality", "In-degree Centrality")


def apply_out_degree_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Freeman-normalised out-degree centrality to each node.

    The directed counterpart to :func:`apply_in_degree_centrality`:
    ``C_out(v) = deg_out(v) / (n − 1)``, where ``deg_out(v)`` is the number of *distinct*
    successors of ``v`` and ``n − 1`` is the maximum achievable on a star graph. ``build_graph``
    writes edges amplifier→source, so out-degree counts how many distinct channels ``v`` cites
    or forwards — the *expansiveness* / curatorial-breadth side of the prestige↔expansiveness
    pair (Wasserman & Faust 1994 §5).

    Unweighted by design: ``nx.out_degree_centrality`` discards edge weights and counts distinct
    successors, mirroring Freeman's (1978) original definition. The weighted counterpart — the
    out-strength ``out_deg = Σ_w w(v→w)`` — is reported separately by
    :func:`apply_base_node_measures` and answers a different question (intensity of citing
    activity, not breadth). The unweighted measure is the one fed to Freeman centralisation in
    ``network/community_stats.py`` because the star bound is exact for it; the out-strength has
    no comparable theoretical maximum and is excluded there. See
    `docs/network-measures.md#out-degree-centrality` for the prose write-up.

    Refs: Freeman 1978, *Social Networks* 1(3); Wasserman & Faust 1994 §5.
    """
    return apply_measure(graph_data, nx.out_degree_centrality(graph), "out_degree_centrality", "Out-degree Centrality")


def apply_harmonic_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add harmonic centrality to each node, weighted by tie strength.

    Harmonic centrality (Marchiori & Latora 2000; Rochat 2009; Boldi & Vigna 2014):
    ``C_H(u) = Σ_{v ≠ u} 1/d(v, u)``, divided by ``n − 1`` to report the mean
    reciprocal distance. Unreachable pairs contribute 0 (not infinity, as in
    classical closeness), which is why harmonic is the right reach measure on the
    sparse, partially disconnected citation graphs Pulpit builds (Boldi & Vigna 2014).

    Direction. ``nx.harmonic_centrality`` sums distances *to* a node, not *from* it
    (it computes ``Σ_v 1/d(v, u)``, the in-coming reciprocal distances). Pulpit keeps
    the graph in its as-built amplifier→source orientation — the same convention as
    PageRank, HITS, betweenness and bridging — so on this citing→cited graph the score
    measures *how easily the rest of the network reaches u* via short citation chains.
    Functionally it is a closeness-style prestige index: the multi-hop generalisation
    of in-degree (which counts only direct citers). (``BURTCONSTRAINT`` is excluded
    from this list because ``nx.constraint`` symmetrises direction internally — see
    :func:`apply_burt_constraint`.)

    Weighting. Computed over the ``distance = 1 / weight`` projection (Opsahl,
    Agneessens & Skvoretz 2010) so heavily-forwarded edges are *short* — shared with
    betweenness and the matching robustness attack scorer. Because a weighted distance
    can fall below 1 (when an edge weight exceeds 1), the normalised score is **not
    bounded to [0, 1]**; interpret it relatively, not as a fraction.

    See ``docs/network-measures.md#harmonic-centrality`` for the prose write-up.
    """
    n = graph.number_of_nodes()
    norm = (n - 1) if n > 1 else 1
    g = proximity_distances(graph)
    values = {nid: v / norm for nid, v in nx.harmonic_centrality(g, distance="distance").items()}
    return apply_measure(graph_data, values, "harmonic_centrality", "Harmonic Centrality")


def apply_community_bridging(
    graph_data: GraphData,
    graph: nx.DiGraph,
    strategy_key: str,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add community bridging (betweenness × neighbour-community participation coefficient) to each node.

    For each node, the participation coefficient (Guimerà & Amaral 2005) of its neighbours'
    community distribution — weighted by edge strength — measures how evenly the node's ties
    spread across communities (0 = every neighbour in one community, →1 = evenly split across
    many). Multiplying it by betweenness (Freeman 1977) surfaces nodes that are both
    structurally central and span communities. The participation coefficient is bounded in
    ``[0, 1]``, so the product stays on betweenness' scale.

    The *product* is a project composite: both factors are standard (Freeman 1977 betweenness;
    Guimerà & Amaral 2005 participation), but their multiplication is not itself a single named
    published index — read it as "central *and* spanning", not as a canonical centrality.

    This is *not* the Bridging Centrality of Hwang et al. (2008) — see
    :func:`apply_bridging_centrality` for that. This measure asks "broker between *detected
    communities*" (and so needs a community partition); the Hwang measure asks "bridge between
    *high-degree regions*" (a purely degree-based, partition-free quantity). They are kept
    separate on purpose.

    If ``betweenness`` is provided (pre-computed via ``compute_betweenness``), the nx call
    is skipped, allowing the caller to share one computation with ``apply_betweenness_centrality``.
    """
    betweenness = betweenness if betweenness is not None else compute_betweenness(graph)
    community_map: dict[str, str] = {
        node_id: node_data["communities"][strategy_key]
        for node_id, node_data in graph.nodes(data="data")
        if node_data and strategy_key in (node_data.get("communities") or {})
    }
    participation = compute_neighbour_community_participation(graph, community_map)
    values = {nid: betweenness.get(nid, 0.0) * participation.get(nid, 0.0) for nid in graph.nodes()}
    return apply_measure(graph_data, values, "community_bridging", "Community Bridging")


def compute_bridging_coefficient(graph: nx.DiGraph) -> dict[str, float]:
    """Bridging coefficient of each node (Hwang et al. 2008).

    The bridging coefficient measures how well a node sits *between* high-degree regions of
    the graph — independent of how globally central it is:

        ``Ψ(v) = (1 / d(v)) / Σ_{i ∈ N(v)} (1 / d(i))``

    where ``d(v)`` is the **undirected** degree of ``v`` (the number of distinct neighbours,
    counting a node reached by both an incoming and an outgoing edge once) and ``N(v)`` its
    neighbour set. Direction is dropped on purpose: the coefficient is a topological-position
    quantity, so a citation either way makes two channels neighbours, mirroring Hwang's
    original undirected, unweighted definition. A node scores high when it has *few* links of
    its own yet those links reach *high-degree* nodes — the small ``1/d(i)`` terms shrink the
    denominator — i.e. it is the narrow waist between otherwise busy regions.

    Isolated nodes (``d(v) = 0``) get ``0.0``: they bridge nothing. Every neighbour ``i`` of a
    non-isolated node necessarily has ``d(i) ≥ 1``, so the denominator is always positive there.
    """
    neighbours: dict[str, set] = {
        node: (set(graph.predecessors(node)) | set(graph.successors(node))) - {node} for node in graph.nodes()
    }
    degree: dict[str, int] = {node: len(nbrs) for node, nbrs in neighbours.items()}
    coefficient: dict[str, float] = {}
    for node, nbrs in neighbours.items():
        d = degree[node]
        if d == 0:
            coefficient[node] = 0.0
            continue
        denom = sum(1.0 / degree[i] for i in nbrs if degree[i] > 0)
        coefficient[node] = (1.0 / d) / denom if denom > 0 else 0.0
    return coefficient


def apply_bridging_centrality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add Bridging Centrality (Hwang et al. 2008) to each node.

    Bridging centrality is the product of betweenness centrality and the *bridging coefficient*
    (:func:`compute_bridging_coefficient`):

        ``C_bridge(v) = betweenness(v) × Ψ(v)``

    Betweenness alone surfaces nodes on many shortest paths; the bridging coefficient
    up-weights those whose links sit *between* high-degree regions rather than inside one
    dense cluster. Their product (Hwang, Kim, Ramanathan & Zhang, *Bridging Centrality: Graph
    Mining from Element Level to Group Level*, KDD 2008) isolates the true topological
    bridges — nodes whose removal most fragments global connectivity.

    Unlike :func:`apply_community_bridging` (betweenness × neighbour-community participation),
    this needs no community partition: the bridging coefficient is purely degree-based, so the
    two measures answer different questions — "bridge between dense regions" (here) vs. "broker
    between detected communities" (there).

    Betweenness uses the project's weighted, directed convention (:func:`compute_betweenness`,
    tie strength mapped to proximity) for parity with the standalone betweenness measure; the
    bridging coefficient follows Hwang's original undirected, unweighted degree. If
    ``betweenness`` is supplied, the nx computation is skipped so the caller can share one
    betweenness across measures.
    """
    betweenness = betweenness if betweenness is not None else compute_betweenness(graph)
    coefficient = compute_bridging_coefficient(graph)
    values = {nid: betweenness.get(nid, 0.0) * coefficient.get(nid, 0.0) for nid in graph.nodes()}
    return apply_measure(graph_data, values, "bridging_centrality", "Bridging Centrality")


def apply_burt_constraint(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Burt's constraint to each node. Isolated nodes receive None (undefined).

    Burt's constraint (Burt 1992 *Structural Holes*; Burt 2004 *AJS* 110(2)):

        ``c(v) = Σ_{w ∈ N(v)\\{v}} (p_vw + Σ_q p_vq · p_qw)²``

    where ``p_xy = mutual_weight(x, y) / Σ_k mutual_weight(x, k)`` is x's normalised
    investment in y. The dyadic term ``ℓ(v, w)`` combines *direct* investment in w
    with *indirect* investment via shared neighbours q; the total is small when
    ego's contacts are mutually disjoint (the structural-hole / broker regime) and
    large when they cite each other (the embedded / redundant regime). Typical
    range is [0, 1]; the theoretical upper bound is ≈ 1.125, occasionally reached
    by perfectly redundant ego-networks (Burt 1992 ch. 2; Borgatti 1997).

    **Direction.** ``nx.constraint`` symmetrises the directed graph internally:
    the mutual weight of (u, v) is ``w(u→v) + w(v→u)`` and ``N(v) =
    predecessors(v) ∪ successors(v)``. This is the academically correct treatment
    of Burt's framework — structural holes are about ego's *contacts*, not the
    citation direction — and makes constraint **direction-invariant**, unlike
    PageRank, HITS, betweenness, harmonic and the bridging measures. Robustness
    attacks (:mod:`network.robustness.attacks`) sort *ascending* on the same
    score (low constraint = broker) via the ``inverse=True`` flag.

    Edge weights still matter: pass-through ``weight="weight"`` means
    ``--edge-weight-strategy`` affects rankings via the row-normalised mutual
    weight.

    See ``docs/network-measures.md#burts-constraint`` for the prose write-up.
    """
    key = "burt_constraint"
    values: dict[str, float] = nx.constraint(graph, weight="weight")
    for node in graph_data["nodes"]:
        val = values.get(node["id"])
        node[key] = None if (val is None or isnan(val)) else round(val, 6)
    return [(key, "Burt's Constraint")]


def apply_local_clustering(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Fagiolo (2007) directed local clustering coefficient to each node.

    ``nx.clustering`` on a ``DiGraph`` implements Fagiolo's "total" directed clustering:
    ``c^D(u) = T^D(u) / [2 · (d^tot · (d^tot − 1) − 2 d^↔)]``, the count of directed
    triangles through ``u`` summed over the four pattern types (cycle, middleman,
    in-triangle, out-triangle) divided by the maximum allowed by ``u``'s degree
    configuration. Score is in ``[0, 1]``; 0 for isolated nodes and for nodes with
    total degree < 2 (no triangle geometrically possible). Called *without* a
    ``weight=`` argument, so it is unweighted — ``--edge-weight-strategy`` does not
    affect the ranking. The formula sums all 8 directed triangle orientations
    symmetrically, so the score is also direction-invariant (same value on ``G`` and
    ``G.reverse()``).
    """
    return apply_measure(graph_data, nx.clustering(graph), "local_clustering", "Local Clustering")


def apply_coreness(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add the k-core coreness number (the deepest k-core a node belongs to) to each node.

    Computed on the symmetrised, self-loop-free graph (``to_undirected_sum`` then drop
    self-loops), matching the convention of the KCORE community strategy
    (:func:`network.community.detect_kcore`). ``nx.core_number`` is unweighted, so coreness
    is a topological depth, not a tie-strength quantity. High coreness = embedded in the
    densely interconnected nucleus; low = a peripheral amplifier shed in the first peeling
    rounds. Coreness is a robust predictor of spreading influence (Kitsak et al. 2010), often
    outperforming degree and betweenness, and is well-behaved on the sparse, partially
    disconnected graphs typical of Telegram ecosystems.
    """
    undirected = to_undirected_sum(graph)
    undirected.remove_edges_from(nx.selfloop_edges(undirected))
    values = {nid: float(core) for nid, core in nx.core_number(undirected).items()}
    return apply_measure(graph_data, values, "coreness", "K-core Coreness")


def apply_trophic_level(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add the hierarchical trophic level to each node (MacKay, Johnson & Sansom 2020).

    Solves the Laplacian system ``(diag(u) − (W + Wᵀ)) h = (w_in − w_out)``, where ``W`` is
    the weighted adjacency, ``w_in`` / ``w_out`` are the weighted in-/out-strength and
    ``u = w_in + w_out``. This *hierarchical-levels* formulation (MacKay, Johnson & Sansom,
    "How directed is a directed network?", *Royal Society Open Science* 7(9), 2020) is always finite — unlike
    the classic Levine 1980 trophic level, which diverges on graphs without basal nodes — so
    it is defined on the cyclic citation graphs Pulpit builds. The system is consistent
    (``Σ(w_in − w_out) = 0``) but singular per connected component, so it is solved by
    least squares and each weakly-connected component is shifted to a minimum of 0.

    ``build_graph`` orients edges amplifier→source (citation convention), but MacKay's
    formulation treats edges as energy/information flow — w_in is "what reaches the node",
    w_out is "what leaves it" — so the Laplacian is solved on the *reversed* graph (edges
    source→amplifier). That way pure originators (w_in = 0 in the flow graph) anchor each
    component at level 0 and terminal amplifiers (w_out = 0) sit at the top, matching the
    intuitive Telegram-diffusion reading and complementing CONTENTORIGINALITY, which
    measures the same producer↔redistributor axis from message content rather than link
    structure. The level is scale-invariant to a global edge-weight rescaling.
    """
    nodes = list(graph.nodes())
    if not nodes:
        return apply_measure(graph_data, {}, "trophic_level", "Trophic Level")
    flow_graph = graph.reverse(copy=False)
    w = nx.to_scipy_sparse_array(flow_graph, nodelist=nodes, weight="weight", dtype=float, format="csr")
    w_in = np.asarray(w.sum(axis=0)).ravel()
    w_out = np.asarray(w.sum(axis=1)).ravel()
    laplacian = (diags(w_in + w_out) - (w + w.T)).tocsr()
    levels = lsqr(laplacian, w_in - w_out)[0]
    # Levels are only defined up to an additive constant per component; pin each weakly
    # connected component to a minimum of 0 so sources read as 0 and the scale is comparable.
    index = {nid: i for i, nid in enumerate(nodes)}
    for component in nx.weakly_connected_components(flow_graph):
        idxs = [index[nid] for nid in component]
        shift = min(levels[i] for i in idxs)
        for i in idxs:
            levels[i] -= shift
    values = {nid: round(float(levels[i]), 6) for i, nid in enumerate(nodes)}
    return apply_measure(graph_data, values, "trophic_level", "Trophic Level")


# Guimerà & Amaral (2005) within-module-degree-z / participation-coefficient role thresholds.
_GA_Z_HUB = 2.5


def _ga_role(z: float, participation: float) -> str:
    """Map a (within-module z-score, participation coefficient) pair to one of the seven
    Guimerà & Amaral (2005) node roles."""
    if z < _GA_Z_HUB:  # non-hub
        if participation <= 0.05:
            return "Ultra-peripheral"
        if participation <= 0.62:
            return "Peripheral"
        if participation <= 0.80:
            return "Connector"
        return "Kinless"
    # hub
    if participation <= 0.30:
        return "Provincial hub"
    if participation <= 0.75:
        return "Connector hub"
    return "Kinless hub"


def apply_module_role(graph_data: GraphData, graph: nx.DiGraph, strategy_key: str) -> list[tuple[str, str]]:
    """Add the Guimerà & Amaral (2005) within-module role to each node, relative to the
    community partition named by ``strategy_key``.

    Two quantities, both measured against the node's own community (module):

    * **within-module degree z-score** ``z`` — how many more (or fewer) intra-module
      neighbours the node has than its module's average, z-scored within the module; high
      ``z`` marks a hub *inside* its own community. Emitted as the sortable numeric measure
      ``within_module_z``.
    * **participation coefficient** ``P`` (Guimerà & Amaral 2005, the same helper that backs
      community bridging) — how evenly the node's ties spread across communities.

    The (z, P) pair maps to one of seven canonical roles (ultra-peripheral, peripheral,
    connector, kinless; and provincial / connector / kinless hub), written as the categorical
    node attribute ``module_role``. Together they answer "within-community kingpin or
    cross-community connector?" — the embeddedness-versus-brokerage distinction, read off the
    community partitions Pulpit already produces. Within-module degree counts distinct
    same-module neighbours (predecessors ∪ successors), following the undirected, unweighted
    neighbour convention of the bridging coefficient. Nodes with no community assignment
    (e.g. dead leaves) receive ``None``.
    """
    community_map: dict[str, str] = {
        node_id: node_data["communities"][strategy_key]
        for node_id, node_data in graph.nodes(data="data")
        if node_data and strategy_key in (node_data.get("communities") or {})
    }
    module_degree: dict[str, int] = {}
    for node in graph.nodes():
        module = community_map.get(node)
        if module is None:
            continue
        neighbours = (set(graph.predecessors(node)) | set(graph.successors(node))) - {node}
        module_degree[node] = sum(1 for nb in neighbours if community_map.get(nb) == module)

    by_module: dict[str, list[int]] = {}
    for node, deg in module_degree.items():
        by_module.setdefault(community_map[node], []).append(deg)
    module_stats: dict[str, tuple[float, float]] = {
        m: (float(np.mean(degs)), float(np.std(degs))) for m, degs in by_module.items()
    }
    participation = compute_neighbour_community_participation(graph, community_map)

    for node in graph_data["nodes"]:
        nid = node["id"]
        if nid not in module_degree:
            node["within_module_z"] = None
            node["module_role"] = None
            continue
        mean, std = module_stats[community_map[nid]]
        z = (module_degree[nid] - mean) / std if std > 0 else 0.0
        node["within_module_z"] = round(z, 4)
        node["module_role"] = _ga_role(z, participation.get(nid, 0.0))
    return [("within_module_z", "Within-module z")]


# Collective Influence ball radius (Morone & Makse 2015). ℓ = 2 is the value used
# throughout their paper: large enough to see beyond the immediate neighbourhood,
# small enough to stay local and cheap. The optimal-percolation ranking is
# insensitive to ℓ in the small-ℓ regime, so it is fixed rather than exposed as a flag.
_CI_RADIUS = 2


def apply_collective_influence(
    graph_data: GraphData, graph: nx.DiGraph, radius: int = _CI_RADIUS
) -> list[tuple[str, str]]:
    """Add the Collective Influence score to each node (Morone & Makse 2015, *Nature*).

    Collective Influence is the optimal-percolation measure of a node's importance to
    global connectivity:

        ``CI_ℓ(i) = (k_i − 1) · Σ_{j ∈ ∂Ball(i, ℓ)} (k_j − 1)``

    where ``k`` is the degree, ``Ball(i, ℓ)`` is the set of nodes within shortest-path
    distance ``ℓ`` of ``i`` and ``∂Ball(i, ℓ)`` is its *frontier* (nodes at distance
    *exactly* ``ℓ``). A node scores high only when it has many links *and* sits ``ℓ`` hops
    from many other well-connected nodes — the signature of a node whose removal most
    fragments the giant component. Morone & Makse show the ranking identifies the minimal
    set of structurally critical spreaders better than degree, k-core, PageRank or
    betweenness; it is the per-node companion to Pulpit's robustness attacks (the optimal
    dismantling order) and complements CORENESS (a depth label) and SPREADING (a per-node
    cascade average).

    Computed on the symmetrised, self-loop-free, **unweighted** projection
    (``to_undirected_sum`` then drop self-loops), matching CORENESS — so the score is
    direction-invariant and ``--edge-weight-strategy`` does not affect the ranking. Degree-0
    and degree-1 nodes score 0 (the ``k_i − 1`` factor vanishes), as do nodes whose
    distance-``ℓ`` frontier is empty. The raw values are unbounded and have no star-based
    maximum, so the score is read **ordinally** (to rank channels) and is excluded from
    Freeman centralisation — like CORENESS and TROPHICLEVEL.

    Refs: Morone, F. & Makse, H.A. (2015) "Influence maximization in complex networks
    through optimal percolation", *Nature* 524(7563):65–68.
    """
    undirected = to_undirected_sum(graph)
    undirected.remove_edges_from(nx.selfloop_edges(undirected))
    adjacency: dict[str, set] = {node: set(undirected.neighbors(node)) for node in undirected.nodes()}
    degree: dict[str, int] = {node: len(nbrs) for node, nbrs in adjacency.items()}

    values: dict[str, float] = {}
    for node in undirected.nodes():
        k_minus_1 = degree[node] - 1
        if k_minus_1 <= 0:
            values[node] = 0.0
            continue
        # Expand BFS shells to obtain the frontier at distance == radius exactly.
        visited = {node}
        frontier = {node}
        for _ in range(radius):
            nxt: set = set()
            for u in frontier:
                nxt |= adjacency[u]
            nxt -= visited
            visited |= nxt
            frontier = nxt
            if not frontier:
                break
        ball_sum = sum(degree[j] - 1 for j in frontier)
        values[node] = float(k_minus_1 * ball_sum)
    return apply_measure(graph_data, values, "collective_influence", "Collective Influence")


# Gould & Fernandez (1989) brokerage roles. Each directed 2-path i→v→j (the broker v is
# cited by i and itself cites j) is classified by the group memberships of i, v, j into
# one of five mutually exclusive, exhaustive roles. Ordered (key, display) — the list order
# is also the tie-break priority for the dominant-role label.
_GF_ROLES: tuple[tuple[str, str], ...] = (
    ("brokerage_coordinator", "Coordinator"),
    ("brokerage_gatekeeper", "Gatekeeper"),
    ("brokerage_representative", "Representative"),
    ("brokerage_consultant", "Consultant"),
    ("brokerage_liaison", "Liaison"),
)
_GF_ROLE_KEYS: tuple[str, ...] = tuple(k for k, _ in _GF_ROLES)


def _gf_role_of(gi: str, gv: str, gj: str) -> str:
    """Classify a directed 2-path i→v→j by the groups of its endpoints (i ≠ j assumed).

    Returns the node-attribute key of the broker role of *v* (Gould & Fernandez 1989):

    * **Coordinator** ``w_I`` — i, v, j all in v's group (within-group broker).
    * **Consultant** ``w_O`` — i and j share a group that is *not* v's (itinerant broker
      mediating two members of another group).
    * **Gatekeeper** ``b_IO`` — i is outside, v and j share v's group (controls inflow into
      the broker's own group).
    * **Representative** ``b_OI`` — i and v share v's group, j is outside (controls outflow
      from the broker's own group).
    * **Liaison** ``b_O`` — i, v, j all in different groups (broker between two foreign groups).
    """
    if gi == gv == gj:
        return "brokerage_coordinator"
    if gi == gj:  # gv differs → two members of one foreign group
        return "brokerage_consultant"
    if gv == gj:  # gi differs, v & j together → inflow gatekeeper
        return "brokerage_gatekeeper"
    if gi == gv:  # j differs, i & v together → outflow representative
        return "brokerage_representative"
    return "brokerage_liaison"


def apply_gould_fernandez(graph_data: GraphData, graph: nx.DiGraph, strategy_key: str) -> list[tuple[str, str]]:
    """Add the Gould & Fernandez (1989) brokerage-role census to each node.

    A channel ``v`` *brokers* a directed 2-path ``i → v → j`` (``i`` cites ``v`` and ``v``
    cites ``j``, with ``i ≠ j``). Each such ordered 2-path is classified by the group
    memberships — taken from the partition named by ``strategy_key`` — of ``i``, ``v`` and
    ``j`` into one of the five mutually exclusive Gould–Fernandez roles (coordinator,
    gatekeeper, representative, consultant, liaison; see :func:`_gf_role_of`). The census
    answers *what kind of broker is this channel* — a question Burt's constraint (redundancy)
    and community bridging (brokerage intensity) cannot: with the **Organization** partition
    a gatekeeper controls what enters a faction, a representative what leaves it, a liaison
    bridges two factions it belongs to neither of.

    Emits, per node:

    * ``brokerage_total`` — the count of all brokered 2-paths (the only value returned as a
      sortable numeric measure column);
    * ``brokerage_role`` — the categorical *dominant* role label (the role with the most
      2-paths, list-order tie-break; ``None`` when the node brokers nothing or has no group),
      which rides alongside ``brokerage_total`` exactly as ``module_role`` rides alongside
      ``within_module_z``;
    * the five raw role counts (``brokerage_coordinator`` … ``brokerage_liaison``) — written
      onto the node for the channels.json payload, the CSV, and the GEXF/GraphML exports, but
      not surfaced as table columns.

    Only 2-paths whose three endpoints all carry a group membership are counted; a node with
    no group assignment (e.g. a dead leaf) receives ``None`` for every field. **Unweighted**
    (paths are counted, not weighted) and computed in the as-built citation orientation —
    matching the other brokerage measures (betweenness, community bridging, bridging
    centrality), so a citation chain ``i → v → j`` is the brokered transaction. The raw
    counts have no star-based maximum, so ``brokerage_total`` is excluded from Freeman
    centralisation (like coreness/trophic), and the dominant-role label is biased toward
    whichever role has the most structural opportunity (largest groups) — read it as a quick
    descriptor and the five counts as the rigorous census.

    Refs: Gould, R.V. & Fernandez, R.M. (1989) "Structures of mediation: A formal approach to
    brokerage in transaction networks", *Sociological Methodology* 19:89–126.
    """
    community_map: dict[str, str] = {
        node_id: node_data["communities"][strategy_key]
        for node_id, node_data in graph.nodes(data="data")
        if node_data and strategy_key in (node_data.get("communities") or {})
    }

    counts: dict[str, dict[str, int]] = {}
    for v in graph.nodes():
        gv = community_map.get(v)
        if gv is None:
            continue
        role_counts = dict.fromkeys(_GF_ROLE_KEYS, 0)
        preds = [(p, community_map.get(p)) for p in graph.predecessors(v) if p != v]
        succs = [(s, community_map.get(s)) for s in graph.successors(v) if s != v]
        for i, gi in preds:
            if gi is None:
                continue
            for j, gj in succs:
                if gj is None or j == i:
                    continue
                role_counts[_gf_role_of(gi, gv, gj)] += 1
        counts[v] = role_counts

    for node in graph_data["nodes"]:
        nid = node["id"]
        role_counts = counts.get(nid)
        if role_counts is None:
            node["brokerage_total"] = None
            node["brokerage_role"] = None
            for key in _GF_ROLE_KEYS:
                node[key] = None
            continue
        total = sum(role_counts.values())
        for key in _GF_ROLE_KEYS:
            node[key] = role_counts[key]
        node["brokerage_total"] = total
        dominant = None
        best = 0
        for key, display in _GF_ROLES:
            if role_counts[key] > best:
                best = role_counts[key]
                dominant = display
        node["brokerage_role"] = dominant
    return [("brokerage_total", "Brokerage")]

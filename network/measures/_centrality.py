import logging
from math import isnan

from network.measures._base import apply_measure, compute_neighbour_community_participation
from network.utils import GraphData, to_undirected_sum

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)


def apply_pagerank(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add PageRank score to each node."""
    key = "pagerank"
    try:
        pagerank_values: dict[str, float] = nx.pagerank(graph)
    except Exception as exc:  # noqa: BLE001
        # PageRank rarely fails, but power iteration can diverge on adversarial /
        # degenerate graphs; degrade gracefully rather than aborting the whole
        # export (parity with the HITS and Katz handlers below).
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

    NetworkX's ``hits`` ignores edge weights — it treats the graph as binary — so
    its scores disagree with every other prestige measure here (PageRank, Katz, …)
    which all use tie strength. This computes HITS on the *weighted* adjacency by
    power iteration:

        ``a = Aᵀ h``   (authority of v = Σ_u w(u→v) · hub(u))
        ``h = A a``    (hub of v       = Σ_u w(v→u) · authority(u))

    iterated to convergence (each vector rescaled by its max per step, as NetworkX
    does) and finally normalised so each vector sums to 1 (matching
    ``nx.hits(normalized=True)``). Returns ``(hubs, authorities)`` keyed by node id;
    ``({}, {})`` for an empty graph.
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
    edges *short*, so betweenness, closeness and harmonic centrality all agree on
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
    """Add normalized in-degree centrality to each node."""
    return apply_measure(graph_data, nx.in_degree_centrality(graph), "in_degree_centrality", "In-degree Centrality")


def apply_out_degree_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add normalized out-degree centrality to each node."""
    return apply_measure(graph_data, nx.out_degree_centrality(graph), "out_degree_centrality", "Out-degree Centrality")


def apply_harmonic_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add harmonic centrality to each node, weighted by tie strength.

    Computed over the ``distance = 1 / weight`` projection (Opsahl, Agneessens &
    Skvoretz 2010) for consistency with betweenness/closeness, then divided by
    ``n − 1`` to report the mean reciprocal distance to the other nodes
    (unreachable nodes contribute 0). Because the weighted distance can be below 1,
    this no longer lies in ``[0, 1]`` — interpret it relatively, not as a fraction.
    """
    n = graph.number_of_nodes()
    norm = (n - 1) if n > 1 else 1
    g = proximity_distances(graph)
    values = {nid: v / norm for nid, v in nx.harmonic_centrality(g, distance="distance").items()}
    return apply_measure(graph_data, values, "harmonic_centrality", "Harmonic Centrality")


def katz_alpha(graph: nx.DiGraph, *, margin: float = 0.9, default: float = 0.1) -> float:
    """Return a Katz ``alpha`` guaranteed to be below ``1 / spectral_radius``.

    Katz centrality only converges — and only yields non-negative scores — for
    ``alpha < 1/λ_max``. ``build_graph`` rescales edge weights (max → 10), which
    inflates ``λ_max`` well past the NetworkX default ``alpha=0.1``, so power
    iteration diverges and the numpy solver silently returns invalid (negative)
    scores. We bound ``λ_max`` by ``min`` of the largest weighted out-/in-degree
    (a Perron-Frobenius/Gershgorin upper bound — O(N), needs no eigensolver and
    is independent of the weight scale) and back off by ``margin``.
    """
    if graph.number_of_edges() == 0:
        return default
    out_max = max((w for _, w in graph.out_degree(weight="weight")), default=0.0)
    in_max = max((w for _, w in graph.in_degree(weight="weight")), default=0.0)
    bound = min(out_max, in_max)
    return margin / bound if bound > 0 else default


def apply_katz_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Katz centrality to each node."""
    alpha = katz_alpha(graph)
    try:
        values: dict[str, float] = nx.katz_centrality(graph, alpha=alpha, weight="weight")
    except nx.PowerIterationFailedConvergence:
        logger.warning("Katz centrality failed to converge; retrying with numpy solver")
        try:
            values = nx.katz_centrality_numpy(graph, alpha=alpha, weight="weight")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Katz centrality numpy fallback also failed: %s", exc)
            return []
    return apply_measure(graph_data, values, "katz_centrality", "Katz Centrality")


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


def apply_flow_betweenness_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add random-walk (current-flow) betweenness centrality to each node.

    Uses ``networkx.current_flow_betweenness_centrality`` (Newman 2005), which models
    information as a random walk rather than routing it along shortest paths.  Each node's
    score reflects how often it lies on a random walk between any two other nodes,
    integrating over *all* paths weighted by their probability — not just the shortest one.

    The directed graph is symmetrised to undirected before computation (consistent with the
    random-walk assumption that current flows in both directions along any edge).  Edge
    weights are preserved.  Because the algorithm requires a connected graph, nodes outside
    the largest weakly-connected component receive 0.0; a warning is logged when this occurs.
    """
    key = "flow_betweenness"
    ugraph = to_undirected_sum(graph)

    if not nx.is_connected(ugraph):
        logger.warning(
            "flow_betweenness: graph is not connected — computing on the largest component; all other nodes receive 0.0"
        )
        largest_cc = max(nx.connected_components(ugraph), key=len)
        subgraph = ugraph.subgraph(largest_cc)
    else:
        subgraph = ugraph

    try:
        values: dict[str, float] = nx.current_flow_betweenness_centrality(subgraph, weight="weight")
    except (nx.NetworkXError, nx.NetworkXAlgorithmError, ZeroDivisionError) as exc:
        logger.warning("flow_betweenness: computation failed (%s)", exc)
        return []

    return apply_measure(graph_data, values, key, "Flow Betweenness")


def apply_burt_constraint(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Burt's constraint to each node. Isolated nodes receive None (undefined)."""
    key = "burt_constraint"
    # Use edge weights so constraint reflects tie strength, consistent with the
    # other structural measures (betweenness, Katz, …) which all pass weight.
    values: dict[str, float] = nx.constraint(graph, weight="weight")
    for node in graph_data["nodes"]:
        val = values.get(node["id"])
        node[key] = None if (val is None or isnan(val)) else round(val, 6)
    return [(key, "Burt's Constraint")]


def apply_closeness_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add closeness centrality to each node, weighted by tie strength.

    Uses the Wasserman-Faust improved formula (NetworkX default), which handles partially
    disconnected graphs correctly: nodes that cannot reach any other node receive 0.0.
    Computed over the ``distance = 1 / weight`` projection (Opsahl, Agneessens & Skvoretz
    2010) for consistency with betweenness/harmonic; because the weighted distance can be
    below 1 the value may exceed 1, so interpret it relatively rather than as a fraction.
    """
    g = proximity_distances(graph)
    return apply_measure(
        graph_data, nx.closeness_centrality(g, distance="distance"), "closeness_centrality", "Closeness Centrality"
    )


def apply_local_clustering(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add directed local clustering coefficient to each node (Fagiolo 2007).

    Counts the fraction of directed triangles through the node relative to all possible
    directed triads.  Nodes with total degree < 2 receive 0.0.
    """
    return apply_measure(graph_data, nx.clustering(graph), "local_clustering", "Local Clustering")


def apply_ego_network_density(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add ego network density to each node.

    For each node, the density of the directed subgraph induced by its immediate neighbours
    (predecessors ∪ successors, ego excluded) is computed as:

        actual directed edges among alters / (k × (k − 1))

    where k is the number of alters.  A value near 1 means every neighbour is connected to
    every other — the node is embedded in a cohesive echo chamber or mutual-citation clique.
    A value near 0 means the neighbours are largely disconnected from one another — the node
    acts as a hub or structural bridge between otherwise separate sources.

    ``None`` is returned for nodes with fewer than two neighbours (density is undefined when
    fewer than two alters exist).
    """
    key = "ego_network_density"
    for node in graph_data["nodes"]:
        node_id = node["id"]
        neighbors = (set(graph.predecessors(node_id)) | set(graph.successors(node_id))) - {node_id}
        if len(neighbors) < 2:
            node[key] = None
        else:
            node[key] = round(nx.density(graph.subgraph(neighbors)), 6)
    return [(key, "Ego Network Density")]

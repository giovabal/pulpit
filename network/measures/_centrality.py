import logging
from math import isnan

from network.measures._base import apply_measure, compute_neighbour_community_entropy
from network.utils import GraphData

import networkx as nx

logger = logging.getLogger(__name__)


def apply_pagerank(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add PageRank score to each node."""
    key = "pagerank"
    pagerank_values: dict[str, float] = nx.pagerank(graph)
    for node in graph_data["nodes"]:
        if node["id"] in pagerank_values:
            node[key] = pagerank_values[node["id"]]
    return [(key, "PageRank")]


def apply_hits(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add HITS hub and authority scores to each node."""
    try:
        hubs, authorities = nx.hits(graph)
    except Exception as exc:  # noqa: BLE001
        # nx.hits is backed by SciPy SVDS, which raises ValueError / ArpackError
        # (not just PowerIterationFailedConvergence) on single-node or otherwise
        # degenerate graphs — e.g. a lone self-referencing channel. Degrade
        # gracefully instead of aborting the whole export.
        logger.warning("HITS could not be computed (%s); skipping hub/authority scores", exc)
        return []
    for node in graph_data["nodes"]:
        node["hits_hub"] = hubs.get(node["id"], 0.0)
        node["hits_authority"] = authorities.get(node["id"], 0.0)
    return [("hits_hub", "HITS Hub"), ("hits_authority", "HITS Authority")]


def compute_betweenness(graph: nx.DiGraph) -> dict[str, float]:
    """Compute betweenness centrality and return the raw values dict."""
    return nx.betweenness_centrality(graph, weight="weight")


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
    """Add normalized harmonic centrality to each node."""
    n = graph.number_of_nodes()
    norm = (n - 1) if n > 1 else 1
    values = {nid: v / norm for nid, v in nx.harmonic_centrality(graph).items()}
    return apply_measure(graph_data, values, "harmonic_centrality", "Harmonic Centrality")


def apply_katz_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add Katz centrality to each node."""
    try:
        values: dict[str, float] = nx.katz_centrality(graph, weight="weight")
    except nx.PowerIterationFailedConvergence:
        logger.warning("Katz centrality failed to converge; retrying with numpy solver")
        try:
            values = nx.katz_centrality_numpy(graph, weight="weight")
        except Exception as exc:
            logger.warning("Katz centrality numpy fallback also failed: %s", exc)
            return []
    return apply_measure(graph_data, values, "katz_centrality", "Katz Centrality")


def apply_bridging_centrality(
    graph_data: GraphData,
    graph: nx.DiGraph,
    strategy_key: str,
    betweenness: "dict[str, float] | None" = None,
) -> list[tuple[str, str]]:
    """Add bridging centrality (betweenness × neighbor-community Shannon entropy) to each node.

    For each node, the Shannon entropy is computed over the community distribution of its
    neighbours weighted by edge strength. Nodes that connect many distinct communities score
    high on entropy; multiplying by betweenness surfaces nodes that are both structurally
    central and community-diverse.

    If ``betweenness`` is provided (pre-computed via ``compute_betweenness``), the nx call
    is skipped, allowing the caller to share one computation with ``apply_betweenness_centrality``.
    """
    betweenness = betweenness if betweenness is not None else compute_betweenness(graph)
    community_map: dict[str, str] = {
        node_id: node_data["communities"][strategy_key]
        for node_id, node_data in graph.nodes(data="data")
        if node_data and strategy_key in (node_data.get("communities") or {})
    }
    entropies = compute_neighbour_community_entropy(graph, community_map)
    values = {nid: betweenness.get(nid, 0.0) * entropies.get(nid, 0.0) for nid in graph.nodes()}
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
    ugraph = graph.to_undirected()

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
    values: dict[str, float] = nx.constraint(graph)
    for node in graph_data["nodes"]:
        val = values.get(node["id"])
        node[key] = None if (val is None or isnan(val)) else round(val, 6)
    return [(key, "Burt's Constraint")]


def apply_closeness_centrality(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add closeness centrality to each node.

    Uses the Wasserman-Faust improved formula (NetworkX default), which handles partially
    disconnected graphs correctly: nodes that cannot reach any other node receive 0.0.
    """
    return apply_measure(graph_data, nx.closeness_centrality(graph), "closeness_centrality", "Closeness Centrality")


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

import logging
from math import isnan

from network.measures._base import apply_measure, compute_neighbour_community_participation
from network.utils import GraphData

import networkx as nx
import numpy as np

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
    Pulpit keeps its own implementation is that ``nx.hits`` is backed by SciPy
    SVDS, which raises ``ArpackNoConvergence`` on degenerate residual graphs (lone
    self-loops, near-empty backbones).

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
    PageRank and HITS.

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
    * **participation coefficient** ``P`` (Guimerà & Amaral 2005) — how evenly the node's ties
      spread across communities.

    The (z, P) pair maps to one of seven canonical roles (ultra-peripheral, peripheral,
    connector, kinless; and provincial / connector / kinless hub), written as the categorical
    node attribute ``module_role``. Together they answer "within-community kingpin or
    cross-community connector?" — the embeddedness-versus-brokerage distinction, read off the
    community partitions Pulpit already produces. Within-module degree counts distinct
    same-module neighbours (predecessors ∪ successors), following the undirected, unweighted
    neighbour convention. Nodes with no community assignment (e.g. dead leaves) receive
    ``None``.
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

import logging
from math import isnan

from network.measures._base import PARTICIPATION_WEIGHT, apply_measure, compute_neighbour_community_participation
from network.parameters import FixedParameter
from network.utils import GraphData, dead_leaf_ids, without_self_loops

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

# ── Fixed parameters ──────────────────────────────────────────────────────────────────────────────
# Values the measures below rely on, NetworkX defaults included, named here and passed explicitly so
# PARAMETERS.md reads them from the very constants the computation uses.

#: PageRank damping factor α (NetworkX default).
PAGERANK_ALPHA = 0.85
#: PageRank power-iteration cap (NetworkX default); a run that has not converged by then skips the score.
PAGERANK_MAX_ITER = 100
#: PageRank convergence tolerance (NetworkX default): iteration stops once the L1 change is below N · tol.
PAGERANK_TOL = 1.0e-6
#: Edge attribute the PageRank walk is weighted by (the run's edge weight, ×10/max rescaled).
PAGERANK_WEIGHT = "weight"
#: PageRank teleport distribution: ``None`` = uniform over all nodes (NetworkX default).
PAGERANK_PERSONALIZATION = None
#: PageRank dangling-node redistribution: ``None`` = the teleport distribution, i.e. uniform (NetworkX default).
PAGERANK_DANGLING = None
#: HITS power-iteration cap; the last iterate is used (with a logged warning) if it has not converged by then.
#: NetworkX's 100 is too few on sparse citation graphs whose leading eigenvalues sit close together (a 2,000-node
#: graph with dead leaves needed ~300); an iteration is one sparse matrix-vector product, so the cap is generous.
HITS_MAX_ITER = 1000
#: HITS convergence tolerance: iteration stops once the L1 change of the max-scaled hub vector is below it.
HITS_TOL = 1.0e-8
#: Edge attribute the HITS adjacency is weighted by (the run's edge weight).
HITS_WEIGHT = "weight"
#: Edge attribute Burt's constraint weighs ties by (the run's edge weight).
BURT_CONSTRAINT_WEIGHT = "weight"
#: Decimal places Burt's constraint is reported to.
BURT_CONSTRAINT_DECIMALS = 6
#: Edge attribute the local clustering coefficient weighs triangles by: ``None`` = unweighted.
LOCAL_CLUSTERING_WEIGHT = None
#: Decimal places node reciprocity is reported to.
RECIPROCITY_DECIMALS = 4
# Guimerà & Amaral (2005) within-module-degree-z / participation-coefficient role thresholds.
#: Within-module z-score at or above which a node is a hub.
GA_Z_HUB = 2.5
#: Non-hub participation upper bounds: ultra-peripheral ≤ 0.05 < peripheral ≤ 0.62 < connector ≤ 0.80 < kinless.
GA_P_ULTRA_PERIPHERAL = 0.05
GA_P_PERIPHERAL = 0.62
GA_P_CONNECTOR = 0.80
#: Hub participation upper bounds: provincial hub ≤ 0.30 < connector hub ≤ 0.75 < kinless hub.
GA_P_PROVINCIAL_HUB = 0.30
GA_P_CONNECTOR_HUB = 0.75
#: Delta degrees of freedom of the within-module degree standard deviation: 0 = population SD (NumPy default).
MODULE_Z_STD_DDOF = 0
#: Decimal places the within-module z-score and participation coefficient are reported to (roles use exact values).
MODULE_ROLE_DECIMALS = 4


def _censor_dead_leaves(graph: nx.DiGraph, values: dict) -> dict:
    """``values`` with every dead leaf (:func:`network.utils.dead_leaf_ids`) set to ``None``.

    A dead leaf is drawn only because a monitored channel cited it; its own messages — and so its outgoing
    citations — are never read. A measure built on a channel's outgoing ties would score it 0 (out-degree, hub,
    reciprocity) or from its incoming side alone (Burt's constraint, clustering): a boundary artefact, not a
    finding, so the value is reported as undefined instead.
    """
    dead = dead_leaf_ids(graph)
    if not dead:
        return values
    return {node: (None if node in dead else value) for node, value in values.items()}


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
    ``nx.pagerank`` is called with its default settings passed explicitly
    (``PAGERANK_ALPHA`` = 0.85 damping, uniform teleport, dangling nodes
    redistributed uniformly, edge weight = ``"weight"``); the random walk
    is scale-invariant to ``build_graph``'s global max-10 rescaling. Self-loops
    (``--self-references``) are left out: a channel's citation of itself is no
    vote of prestige. See `docs/network-measures.md#pagerank` for the prose write-up.

    Refs: Brin & Page 1998, *Computer Networks* 30(1–7); Page, Brin, Motwani &
    Winograd 1999, "The PageRank citation ranking", Stanford TR.
    """
    key = "pagerank"
    try:
        pagerank_values: dict[str, float] = nx.pagerank(
            without_self_loops(graph),
            alpha=PAGERANK_ALPHA,
            personalization=PAGERANK_PERSONALIZATION,
            max_iter=PAGERANK_MAX_ITER,
            tol=PAGERANK_TOL,
            weight=PAGERANK_WEIGHT,
            dangling=PAGERANK_DANGLING,
        )
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
    graph: nx.DiGraph, *, max_iter: int = HITS_MAX_ITER, tol: float = HITS_TOL
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
    graph. A warning is logged when ``max_iter`` passes without convergence (the
    last iterate is then used).
    """
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}, {}
    a_mat = nx.to_scipy_sparse_array(graph, nodelist=nodes, weight=HITS_WEIGHT, dtype=float, format="csr")
    at_mat = a_mat.T.tocsr()
    hub = np.full(n, 1.0 / n)
    converged = False
    change = float("nan")
    for _ in range(max_iter):
        auth = at_mat @ hub
        auth_max = auth.max() if auth.size else 0.0
        if auth_max > 0:
            auth = auth / auth_max
        new_hub = a_mat @ auth
        hub_max = new_hub.max() if new_hub.size else 0.0
        if hub_max > 0:
            new_hub = new_hub / hub_max
        change = float(np.abs(new_hub - hub).sum())
        hub = new_hub
        if change < tol:
            converged = True
            break
    if not converged and graph.number_of_edges():
        logger.warning(
            "HITS did not converge in %d iterations (last L1 change %.3g > tolerance %.1g); "
            "using the last iterate — read small hub/authority differences with care",
            max_iter,
            change,
            tol,
        )
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
    """Add weighted HITS hub and authority scores to each node.

    Computed without self-loops (a channel citing itself is neither its own hub nor its own authority); the
    hub score of a dead leaf is ``None`` — its outgoing citations are outside the analysis (see
    :func:`_censor_dead_leaves`).
    """
    try:
        hubs, authorities = compute_hits(without_self_loops(graph), max_iter=HITS_MAX_ITER, tol=HITS_TOL)
    except Exception as exc:  # noqa: BLE001
        # Degrade gracefully on degenerate graphs (e.g. a lone self-referencing
        # channel) instead of aborting the whole export.
        logger.warning("HITS could not be computed (%s); skipping hub/authority scores", exc)
        return []
    dead = dead_leaf_ids(graph)
    for node in graph_data["nodes"]:
        node["hits_hub"] = None if node["id"] in dead else hubs.get(node["id"], 0.0)
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

    Self-loops are left out (a channel citing itself is not one of its citers), so the star bound
    stays exact.

    Refs: Freeman 1978, *Social Networks* 1(3); Wasserman & Faust 1994 §5.
    """
    values = nx.in_degree_centrality(without_self_loops(graph))
    return apply_measure(graph_data, values, "in_degree_centrality", "In-degree Centrality")


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

    Self-loops are left out; a dead leaf gets ``None`` — its own citations are outside the analysis, so
    its out-degree is unobserved, not zero (:func:`_censor_dead_leaves`).

    Refs: Freeman 1978, *Social Networks* 1(3); Wasserman & Faust 1994 §5.
    """
    values = _censor_dead_leaves(graph, nx.out_degree_centrality(without_self_loops(graph)))
    return apply_measure(graph_data, values, "out_degree_centrality", "Out-degree Centrality", default=None)


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

    Self-loops are left out — with them a channel would count as its own contact
    (raising a triangle's 1.125 to 1.5). A dead leaf gets ``None``: its ego network is
    only seen from the citing side (:func:`_censor_dead_leaves`).

    See ``docs/network-measures.md#burts-constraint`` for the prose write-up.
    """
    key = "burt_constraint"
    values: dict[str, float] = _censor_dead_leaves(
        graph, nx.constraint(without_self_loops(graph), weight=BURT_CONSTRAINT_WEIGHT)
    )
    for node in graph_data["nodes"]:
        val = values.get(node["id"])
        node[key] = None if (val is None or isnan(val)) else round(val, BURT_CONSTRAINT_DECIMALS)
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
    ``G.reverse()``). A dead leaf gets ``None``: the triangles its own citations would
    close are outside the analysis (:func:`_censor_dead_leaves`).
    """
    # float(): nx.clustering yields int 0 for nodes with degree < 2 and float
    # elsewhere; mixed types corrupt GEXF/GraphML attribute typing on export.
    values = {node: float(value) for node, value in nx.clustering(graph, weight=LOCAL_CLUSTERING_WEIGHT).items()}
    return apply_measure(
        graph_data, _censor_dead_leaves(graph, values), "local_clustering", "Local Clustering", default=None
    )


def apply_reciprocity(graph_data: GraphData, graph: nx.DiGraph) -> list[tuple[str, str]]:
    """Add node-level reciprocity: the share of a channel's citation partners that are mutual.

    ``r(v) = 2 · |pred(v) ∩ succ(v)| / (|pred(v)| + |succ(v)|)``, self-loops excluded —
    the node-level counterpart of the whole-network *Reciprocity* statistic and of the
    per-community reciprocity column. Purely dyadic, so fully consistent with the
    one-degree attribution model: a reciprocated pair is two channels that each cite
    the other — a mutual-amplification relationship rather than one-way audience.

    Range [0, 1]; ``None`` for isolated nodes (no partners → undefined, matching Burt's
    constraint's convention) and for dead leaves, whose return citations are outside the
    analysis (:func:`_censor_dead_leaves`). **Unweighted by design**, like the Freeman degree
    centralities: mutuality is about *whether* a return tie exists, not how heavy it
    is, so the ranking is invariant to ``--edge-weight-strategy``. Direction-invariant
    (predecessors and successors swap under ``G.reverse()``, the overlap does not).

    Hand-rolled rather than ``nx.reciprocity``, which raises on the isolated in-target
    nodes Pulpit deliberately keeps in the graph and counts self-loops as reciprocated.

    Refs: Garlaschelli & Loffredo 2004, *PRL* 93(26); Squartini, Picciolo, Ruzzenenti
    & Garlaschelli 2013, *Sci. Rep.* 3:2729 (weighted extension, not implemented);
    Wasserman & Faust 1994 ch. 13 (dyad census).
    """
    values: dict[str, float | None] = {}
    for node in graph.nodes():
        pred = set(graph.predecessors(node)) - {node}
        succ = set(graph.successors(node)) - {node}
        total = len(pred) + len(succ)
        values[node] = round(2 * len(pred & succ) / total, RECIPROCITY_DECIMALS) if total else None
    return apply_measure(graph_data, _censor_dead_leaves(graph, values), "reciprocity", "Reciprocity", default=None)


def _ga_role(z: float, participation: float) -> str:
    """Map a (within-module z-score, participation coefficient) pair to one of the seven
    Guimerà & Amaral (2005) node roles."""
    if z < GA_Z_HUB:  # non-hub
        if participation <= GA_P_ULTRA_PERIPHERAL:
            return "Ultra-peripheral"
        if participation <= GA_P_PERIPHERAL:
            return "Peripheral"
        if participation <= GA_P_CONNECTOR:
            return "Connector"
        return "Kinless"
    # hub
    if participation <= GA_P_PROVINCIAL_HUB:
        return "Provincial hub"
    if participation <= GA_P_CONNECTOR_HUB:
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
      spread across communities: 0 = every tie inside one community, → 1 = ties spread evenly
      across many. Emitted as the sortable numeric measure ``participation`` — the continuous
      cross-community bridging score the seven role labels quantise. Like ``z`` it counts
      distinct neighbours, unweighted: Guimerà & Amaral's definition, on which the role
      thresholds were calibrated. A weighted variant — each neighbour's tie weight summed over
      both directions — is emitted alongside as ``participation_weighted`` for reading the
      intensity of bridging; it does not drive the role.

    The (z, P) pair maps to one of seven canonical roles (ultra-peripheral, peripheral,
    connector, kinless; and provincial / connector / kinless hub), written as the categorical
    node attribute ``module_role``. Together they answer "within-community kingpin or
    cross-community connector?" — the embeddedness-versus-brokerage distinction, read off the
    community partitions Pulpit already produces. Within-module degree counts distinct
    same-module neighbours (predecessors ∪ successors), following the undirected, unweighted
    neighbour convention. Nodes with no community assignment (e.g. dead leaves under a
    label-group basis) and nodes with no neighbour at all receive ``None`` — an isolated
    channel holds no position inside or across modules — and isolated nodes are left out of
    their module's degree mean and standard deviation.
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
        if not neighbours:
            continue  # isolated: no role, and kept out of its module's degree statistics
        module_degree[node] = sum(1 for nb in neighbours if community_map.get(nb) == module)

    by_module: dict[str, list[int]] = {}
    for node, deg in module_degree.items():
        by_module.setdefault(community_map[node], []).append(deg)
    module_stats: dict[str, tuple[float, float]] = {
        m: (float(np.mean(degs)), float(np.std(degs, ddof=MODULE_Z_STD_DDOF))) for m, degs in by_module.items()
    }
    participation = compute_neighbour_community_participation(graph, community_map)
    participation_weighted = compute_neighbour_community_participation(
        graph, community_map, weight=PARTICIPATION_WEIGHT
    )

    for node in graph_data["nodes"]:
        nid = node["id"]
        if nid not in module_degree:
            node["within_module_z"] = None
            node["participation"] = None
            node["participation_weighted"] = None
            node["module_role"] = None
            continue
        mean, std = module_stats[community_map[nid]]
        z = (module_degree[nid] - mean) / std if std > 0 else 0.0
        p = participation.get(nid, 0.0)
        node["within_module_z"] = round(z, MODULE_ROLE_DECIMALS)
        node["participation"] = round(p, MODULE_ROLE_DECIMALS)
        node["participation_weighted"] = round(participation_weighted.get(nid, 0.0), MODULE_ROLE_DECIMALS)
        node["module_role"] = _ga_role(z, p)
    return [
        ("within_module_z", "Within-module z"),
        ("participation", "Participation Coefficient"),
        ("participation_weighted", "Participation (weighted)"),
    ]


_SOURCE = "network/measures/_centrality.py"
_NX_DEFAULT = "NetworkX default, passed explicitly."


def _hits_parameters() -> tuple[FixedParameter, ...]:
    """The HITS settings, once per HITS measure token: hub and authority come from one computation."""
    return tuple(
        parameter
        for scope in ("measure:HITSHUB", "measure:HITSAUTH")
        for parameter in (
            FixedParameter(
                name="HITS maximum iterations",
                value=HITS_MAX_ITER,
                scope=scope,
                affects="Caps the power iteration; a graph that has not converged by then keeps the last "
                "iterate's hub and authority scores.",
                source=f"{_SOURCE}: HITS_MAX_ITER",
                note="Power iteration from a uniform hub vector; scores normalised to sum to 1, as nx.hits.",
            ),
            FixedParameter(
                name="HITS convergence tolerance",
                value=HITS_TOL,
                scope=scope,
                affects="Iteration stops once the L1 change of the max-scaled hub vector falls below this; "
                "a looser value stops earlier with less precise scores.",
                source=f"{_SOURCE}: HITS_TOL",
            ),
            FixedParameter(
                name="HITS edge weight",
                value=HITS_WEIGHT,
                scope=scope,
                affects="Hub and authority scores weigh each citation by this edge attribute, the run's edge "
                "weight, so they follow --edge-weight-strategy.",
                source=f"{_SOURCE}: HITS_WEIGHT",
                note="Weighted HITS (Kleinberg 1999, weighted variant).",
            ),
        )
    )


#: Rule of the measures that read the graph without self-loops (``without_self_loops``).
SELF_LOOP_RULE = "self-citations (--self-references) are removed before the measure is computed"
#: Rule of the measures left undefined on dead leaves (``_censor_dead_leaves``).
DEAD_LEAF_RULE = "None on dead leaves (their own outgoing citations are outside the analysis)"
_SELF_LOOP_FREE_MEASURES = ("PAGERANK", "HITSHUB", "HITSAUTH", "INDEGCENTRALITY", "OUTDEGCENTRALITY", "BURTCONSTRAINT")
_DEAD_LEAF_CENSORED_MEASURES = ("OUTDEGCENTRALITY", "HITSHUB", "BURTCONSTRAINT", "LOCALCLUSTERING", "RECIPROCITY")


def _rule_parameters() -> tuple[FixedParameter, ...]:
    """The self-loop and dead-leaf rules, once per measure they apply to."""
    return tuple(
        FixedParameter(
            name="Self-citations",
            value=SELF_LOOP_RULE,
            scope=f"measure:{token}",
            affects="A channel citing itself is not a vote of prestige nor a contact of its own, so the measure "
            "ignores those self-loops even when --self-references keeps them in the graph.",
            source=f"{_SOURCE}: SELF_LOOP_RULE",
        )
        for token in _SELF_LOOP_FREE_MEASURES
    ) + tuple(
        FixedParameter(
            name="Dead leaves",
            value=DEAD_LEAF_RULE,
            scope=f"measure:{token}",
            affects="A dead leaf is drawn only because a monitored channel cited it; the measure needs the "
            "channel's own citations, which are never read, so it is reported as undefined rather than 0.",
            source=f"{_SOURCE}: DEAD_LEAF_RULE",
        )
        for token in _DEAD_LEAF_CENSORED_MEASURES
    )


#: The values fixed in this module that shape the structural measures (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    *_rule_parameters(),
    FixedParameter(
        name="PageRank damping factor α",
        value=PAGERANK_ALPHA,
        scope="measure:PAGERANK",
        affects="Probability the random walk follows a citation rather than teleporting; higher values give "
        "more weight to the citation structure and less to the uniform teleport.",
        source=f"{_SOURCE}: PAGERANK_ALPHA",
        note=f"{_NX_DEFAULT} Brin & Page 1998.",
    ),
    FixedParameter(
        name="PageRank maximum iterations",
        value=PAGERANK_MAX_ITER,
        scope="measure:PAGERANK",
        affects="Caps the power iteration; a graph that has not converged by then gets no PageRank score.",
        source=f"{_SOURCE}: PAGERANK_MAX_ITER",
        note=_NX_DEFAULT,
    ),
    FixedParameter(
        name="PageRank convergence tolerance",
        value=PAGERANK_TOL,
        scope="measure:PAGERANK",
        affects="Iteration stops once the L1 change of the score vector falls below N times this value; a "
        "looser value stops earlier with less precise scores.",
        source=f"{_SOURCE}: PAGERANK_TOL",
        note=_NX_DEFAULT,
    ),
    FixedParameter(
        name="PageRank edge weight",
        value=PAGERANK_WEIGHT,
        scope="measure:PAGERANK",
        affects="Each channel's vote is split across the channels it cites in proportion to this edge "
        "attribute, the run's edge weight. PageRank re-normalises each channel's outgoing weights, so TOTAL, "
        "PARTIAL_MESSAGES and PARTIAL_REFERENCES (which scale a channel's ties by one constant) give the same "
        "ranking; only NONE differs.",
        source=f"{_SOURCE}: PAGERANK_WEIGHT",
        note=_NX_DEFAULT,
    ),
    FixedParameter(
        name="PageRank teleport distribution",
        value=PAGERANK_PERSONALIZATION,
        scope="measure:PAGERANK",
        affects="None teleports uniformly to every node; a personalisation vector would bias the scores "
        "toward the channels it favours.",
        source=f"{_SOURCE}: PAGERANK_PERSONALIZATION",
        note=_NX_DEFAULT,
    ),
    FixedParameter(
        name="PageRank dangling-node redistribution",
        value=PAGERANK_DANGLING,
        scope="measure:PAGERANK",
        affects="None sends the score of channels citing no one (dangling nodes) back through the teleport "
        "distribution, i.e. uniformly.",
        source=f"{_SOURCE}: PAGERANK_DANGLING",
        note=_NX_DEFAULT,
    ),
    *_hits_parameters(),
    FixedParameter(
        name="Burt's constraint edge weight",
        value=BURT_CONSTRAINT_WEIGHT,
        scope="measure:BURTCONSTRAINT",
        affects="Ties are weighed by this edge attribute (mutual weight w(u→v) + w(v→u)), so the constraint "
        "follows --edge-weight-strategy; None would make it unweighted.",
        source=f"{_SOURCE}: BURT_CONSTRAINT_WEIGHT",
        note="Burt 1992; nx.constraint symmetrises direction internally.",
    ),
    FixedParameter(
        name="Burt's constraint decimals",
        value=BURT_CONSTRAINT_DECIMALS,
        scope="measure:BURTCONSTRAINT",
        affects="Decimal places Burt's constraint is reported to; channels equal at this precision tie.",
        source=f"{_SOURCE}: BURT_CONSTRAINT_DECIMALS",
    ),
    FixedParameter(
        name="Local clustering edge weight",
        value=LOCAL_CLUSTERING_WEIGHT,
        scope="measure:LOCALCLUSTERING",
        affects="None counts triangles unweighted, so the coefficient ignores --edge-weight-strategy; an "
        "attribute name would switch to the weighted (geometric-mean) clustering.",
        source=f"{_SOURCE}: LOCAL_CLUSTERING_WEIGHT",
        note="Fagiolo 2007 directed clustering; NetworkX default, passed explicitly.",
    ),
    FixedParameter(
        name="Reciprocity decimals",
        value=RECIPROCITY_DECIMALS,
        scope="measure:RECIPROCITY",
        affects="Decimal places node reciprocity is reported to; channels equal at this precision tie.",
        source=f"{_SOURCE}: RECIPROCITY_DECIMALS",
    ),
    FixedParameter(
        name="Hub threshold (within-module z)",
        value=GA_Z_HUB,
        scope="measure:MODULEROLE",
        affects="Nodes whose within-module degree z-score reaches this are hubs (provincial / connector / "
        "kinless hub); below it they take a non-hub role.",
        source=f"{_SOURCE}: GA_Z_HUB",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Ultra-peripheral participation bound",
        value=GA_P_ULTRA_PERIPHERAL,
        scope="measure:MODULEROLE",
        affects="A non-hub with participation at or below this is ultra-peripheral; above it, peripheral or beyond.",
        source=f"{_SOURCE}: GA_P_ULTRA_PERIPHERAL",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Peripheral participation bound",
        value=GA_P_PERIPHERAL,
        scope="measure:MODULEROLE",
        affects="A non-hub with participation at or below this (and above the ultra-peripheral bound) is "
        "peripheral; above it, a connector or kinless.",
        source=f"{_SOURCE}: GA_P_PERIPHERAL",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Connector participation bound",
        value=GA_P_CONNECTOR,
        scope="measure:MODULEROLE",
        affects="A non-hub with participation at or below this (and above the peripheral bound) is a "
        "connector; above it, kinless.",
        source=f"{_SOURCE}: GA_P_CONNECTOR",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Provincial-hub participation bound",
        value=GA_P_PROVINCIAL_HUB,
        scope="measure:MODULEROLE",
        affects="A hub with participation at or below this is a provincial hub; above it, a connector or kinless hub.",
        source=f"{_SOURCE}: GA_P_PROVINCIAL_HUB",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Connector-hub participation bound",
        value=GA_P_CONNECTOR_HUB,
        scope="measure:MODULEROLE",
        affects="A hub with participation at or below this (and above the provincial-hub bound) is a "
        "connector hub; above it, a kinless hub.",
        source=f"{_SOURCE}: GA_P_CONNECTOR_HUB",
        note="Guimerà & Amaral 2005.",
    ),
    FixedParameter(
        name="Within-module z-score SD degrees of freedom",
        value=MODULE_Z_STD_DDOF,
        scope="measure:MODULEROLE",
        affects="The within-module degree is z-scored against the module's population standard deviation "
        "(ddof 0); ddof 1 would use the sample SD, shrinking every z-score and so the set of hubs.",
        source=f"{_SOURCE}: MODULE_Z_STD_DDOF",
        note="NumPy default, passed explicitly.",
    ),
    FixedParameter(
        name="Module-role decimals",
        value=MODULE_ROLE_DECIMALS,
        scope="measure:MODULEROLE",
        affects="Decimal places the within-module z-score and participation coefficient are reported to; "
        "the role labels are assigned from the exact values.",
        source=f"{_SOURCE}: MODULE_ROLE_DECIMALS",
    ),
)

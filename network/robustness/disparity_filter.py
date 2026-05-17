"""Disparity-filter backbone extraction (Serrano, Boguñá & Vespignani 2009).

For each node, the significance of an incident edge with normalised weight
``p = w / s`` and ``k`` total edges in that direction is ``α = (1 - p)^(k - 1)``.
An edge is *surprising* when α is below a chosen threshold (typically 0.05):
it carries more of the node's total weight than would be expected if the
weights were uniformly distributed across the node's connections.

For directed graphs the test is applied independently to the in- and
out-edge distributions of the endpoints; an edge survives if it passes from
either side, i.e. ``min(α_in, α_out) < threshold``.

Nodes with a single edge in a given direction have no distribution to test
against; their incident edge gets ``α = 0`` from that side and is kept by
convention.  This is the standard "keep the single edge" rule used in the
backbone-extraction literature: discarding the only incident edge of a node
would isolate it from the network entirely.

Reference:
    Serrano, M. Á., Boguñá, M., & Vespignani, A. (2009). Extracting the
    multiscale backbone of complex weighted networks. *PNAS* 106(16),
    6483-6488. https://doi.org/10.1073/pnas.0808904106
"""

from typing import Any

import networkx as nx


def disparity_filter(
    G: nx.DiGraph,
    alpha: float = 0.05,
    weight: str = "weight",
) -> nx.DiGraph:
    """Return the directed backbone of *G* per Serrano et al. 2009.

    An edge ``(u, v)`` is kept when ``min(α_in, α_out) < alpha``, where α_in is
    the significance against ``v``'s incoming-edge distribution and α_out the
    significance against ``u``'s outgoing-edge distribution.  Edges incident on
    a node with a single edge in the relevant direction get ``α = 0`` (kept)
    from that side.

    ``alpha`` must lie in ``(0, 1]``.  Node attributes are preserved; isolated
    nodes that result from the filtering are kept so the backbone shares the
    same vertex set as *G*.  Edge attributes are preserved on retained edges.
    """
    if not (0 < alpha <= 1):
        raise ValueError(f"alpha must be in (0, 1]; got {alpha!r}")

    backbone = G.__class__()
    backbone.add_nodes_from(G.nodes(data=True))
    for (u, v), (a_in, a_out) in compute_alpha_values(G, weight=weight).items():
        if min(a_in, a_out) < alpha:
            backbone.add_edge(u, v, **G.edges[u, v])
    return backbone


def compute_alpha_values(
    G: nx.DiGraph,
    weight: str = "weight",
) -> dict[tuple[Any, Any], tuple[float, float]]:
    """Per-edge ``{(u, v): (alpha_in, alpha_out)}`` disparity scores.

    ``alpha_in`` tests the edge against ``v``'s incoming-weight distribution;
    ``alpha_out`` tests it against ``u``'s outgoing-weight distribution.
    Either side returns ``0.0`` when the corresponding node has a single edge
    in that direction (no statistical test possible — kept by convention).
    """
    out_degree = dict(G.out_degree())
    in_degree = dict(G.in_degree())
    out_strength = dict(G.out_degree(weight=weight))
    in_strength = dict(G.in_degree(weight=weight))

    result: dict[tuple[Any, Any], tuple[float, float]] = {}
    for u, v, data in G.edges(data=True):
        w = data.get(weight, 0.0)

        k_out, s_out = out_degree[u], out_strength[u]
        if k_out <= 1 or s_out <= 0:
            a_out = 0.0
        else:
            p = w / s_out
            a_out = (1.0 - p) ** (k_out - 1) if p < 1.0 else 0.0

        k_in, s_in = in_degree[v], in_strength[v]
        if k_in <= 1 or s_in <= 0:
            a_in = 0.0
        else:
            q = w / s_in
            a_in = (1.0 - q) ** (k_in - 1) if q < 1.0 else 0.0

        result[(u, v)] = (a_in, a_out)
    return result

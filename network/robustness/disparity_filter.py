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

When **every edge carries the same weight** (``--edge-weight-strategy NONE``,
or a ``TOTAL`` graph whose ties are all single citations) the filter carries no
information: each edge of a degree-``k`` node gets ``α = (1 − 1/k)^(k−1)``,
which is ≥ 1/e ≈ 0.37 for every ``k ≥ 2``, so any ``α < 0.37`` keeps only the
edges of degree-1 endpoints and the "backbone" collapses to a near-empty graph
for purely combinatorial reasons.  :func:`disparity_filter` therefore logs a
warning and returns an unfiltered copy in that case (:func:`has_uniform_weights`
lets callers detect and report it).

Reference:
    Serrano, M. Á., Boguñá, M., & Vespignani, A. (2009). Extracting the
    multiscale backbone of complex weighted networks. *PNAS* 106(16),
    6483-6488. https://doi.org/10.1073/pnas.0808904106
"""

import logging
import math
from typing import Any

from network.parameters import FixedParameter

import networkx as nx

logger = logging.getLogger(__name__)

# Relative / absolute tolerance under which two edge weights count as equal for the uniform-weight
# check (:func:`has_uniform_weights`) — loose enough that a float round-off in the ×10/max rescale
# cannot hide a uniform graph.
UNIFORM_WEIGHT_REL_TOL = 1e-9
UNIFORM_WEIGHT_ABS_TOL = 1e-12

_SOURCE = "network/robustness/disparity_filter.py"


def _uniform_tolerance_parameters(scope: str) -> tuple[FixedParameter, ...]:
    return (
        FixedParameter(
            name="Disparity filter: uniform-weight relative tolerance",
            value=UNIFORM_WEIGHT_REL_TOL,
            scope=scope,
            affects="Edge weights equal within this relative tolerance count as uniform; on a uniform graph the "
            "disparity test is uninformative and the backbone is skipped (the full graph is used).",
            source=f"{_SOURCE}: UNIFORM_WEIGHT_REL_TOL",
        ),
        FixedParameter(
            name="Disparity filter: uniform-weight absolute tolerance",
            value=UNIFORM_WEIGHT_ABS_TOL,
            scope=scope,
            affects="Absolute companion of the relative tolerance, for weights near zero.",
            source=f"{_SOURCE}: UNIFORM_WEIGHT_ABS_TOL",
        ),
    )


#: The values fixed in this module (``PARAMETERS.md``).  The filter serves both the robustness
#: backbone and the community-detection backbone, so each scope lists them; the threshold α is a run
#: option (``--robustness-alpha`` / ``--community-backbone-alpha``), not listed here.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = _uniform_tolerance_parameters(
    "robustness"
) + _uniform_tolerance_parameters("community_backbone")


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

    When every edge carries the same weight (:func:`has_uniform_weights`) the
    test is uninformative — it would keep only degree-1 endpoints' edges — so a
    warning is logged and an unfiltered copy of *G* is returned instead.
    """
    if not (0 < alpha <= 1):
        raise ValueError(f"alpha must be in (0, 1]; got {alpha!r}")

    if has_uniform_weights(G, weight=weight):
        logger.warning(
            "Disparity filter skipped (α=%g): all %d edges carry the same weight, so the backbone test "
            "carries no information (it would keep only the edges of degree-1 endpoints). Using the full "
            "graph — pick a weighted --edge-weight-strategy (TOTAL / PARTIAL_*) for a meaningful backbone.",
            alpha,
            G.number_of_edges(),
        )
        return G.copy()

    backbone = G.__class__()
    backbone.add_nodes_from(G.nodes(data=True))
    for (u, v), (a_in, a_out) in compute_alpha_values(G, weight=weight).items():
        if min(a_in, a_out) < alpha:
            backbone.add_edge(u, v, **G.edges[u, v])
    return backbone


def has_uniform_weights(G: nx.DiGraph, weight: str = "weight") -> bool:
    """Whether *G* has at least two edges and every edge carries the same *weight*.

    The disparity filter is uninformative on such a graph (see the module docstring); with fewer
    than two edges there is nothing to filter either way (a lone edge is always kept), so that case
    is not flagged.  Weights are compared with a relative tolerance so a float round-off in the
    ×10/max rescale cannot hide a uniform graph.  A missing attribute counts as ``1.0``, matching
    ``G.degree(weight=…)``.
    """
    if G.number_of_edges() < 2:
        return False
    first: float | None = None
    for _, _, data in G.edges(data=True):
        w = float(data.get(weight, 1.0))
        if first is None:
            first = w
        elif not math.isclose(w, first, rel_tol=UNIFORM_WEIGHT_REL_TOL, abs_tol=UNIFORM_WEIGHT_ABS_TOL):
            return False
    return True


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

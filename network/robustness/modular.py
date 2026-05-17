"""Modular (intra-/inter-community) edge-survival curves.

For a given removal order and a community partition, this module tracks
how the share of *intra*-community edges and *inter*-community edges in
the residual graph evolves over the attack.  Combined with the
residual-size curves from :mod:`network.robustness.metrics`, the modular
curves answer a second-order question: does an attack disproportionately
strip cross-community ties (decoupling sub-ecosystems) or intra-community
ties (eroding cohesion)?

Curves are normalised to their q = 0 baseline: ``intra[q] = intra_q /
intra_0`` and ``inter[q] = inter_q / inter_0``.  The ratio ``intra / inter``
is returned per step too; ``None`` whenever ``inter_q == 0`` (mathematically
undefined — emitting ``None`` keeps the resulting JSON payload free of
non-finite floats).
"""

from typing import Any

import networkx as nx


def modular_robustness_curves(
    G: nx.DiGraph,
    removal_order: list[Any],
    partition: dict[Any, Any],
) -> dict[str, list[float | None]]:
    """Intra/inter-community edge-survival curves along *removal_order*.

    *G* is the directed graph (never mutated).  *removal_order* is a list
    of node IDs to remove one at a time; nodes not (or no longer) present
    are silently skipped.  *partition* is a ``{node_id: community_id}``
    mapping; edges incident on a node missing from *partition* count as
    **inter** (an unassigned node has no community to match).

    Returns ``{"intra": [...], "inter": [...], "ratio": [...]}``, each of
    length ``len(removal_order) + 1``.  ``intra[q]`` / ``inter[q]`` are
    fractions of their q = 0 baseline; ``0.0`` when the baseline is itself
    zero (e.g. ``intra`` on a partition where no edge stays within a
    community).  ``ratio[q]`` is ``intra_q / inter_q``, or ``None`` when no
    inter-community edges remain.

    Update cost is O(degree) per removal: each removed node enumerates its
    own incident edges and reclassifies them — there is no full O(|E|)
    rescan per step.  Total cost is O(|E| + N).
    """
    g = G.copy()

    def _is_intra(u: Any, v: Any) -> bool:
        cu = partition.get(u)
        cv = partition.get(v)
        return cu is not None and cv is not None and cu == cv

    intra_0 = sum(1 for u, v in g.edges() if _is_intra(u, v))
    inter_0 = g.number_of_edges() - intra_0

    intra_q = intra_0
    inter_q = inter_0

    def _frac(q: int, base: int) -> float:
        return q / base if base > 0 else 0.0

    def _ratio(i_q: int, e_q: int) -> float | None:
        return i_q / e_q if e_q > 0 else None

    intra: list[float | None] = [_frac(intra_q, intra_0)]
    inter: list[float | None] = [_frac(inter_q, inter_0)]
    ratio: list[float | None] = [_ratio(intra_q, inter_q)]

    for nid in removal_order:
        if g.has_node(nid):
            # Enumerate each incident edge once: out-edges (covering the
            # self-loop if any) plus in-edges minus the self-loop we
            # already accounted for.
            for _, v in g.out_edges(nid):
                if _is_intra(nid, v):
                    intra_q -= 1
                else:
                    inter_q -= 1
            for u, _ in g.in_edges(nid):
                if u == nid:
                    continue
                if _is_intra(u, nid):
                    intra_q -= 1
                else:
                    inter_q -= 1
            g.remove_node(nid)
        intra.append(_frac(intra_q, intra_0))
        inter.append(_frac(inter_q, inter_0))
        ratio.append(_ratio(intra_q, inter_q))

    return {"intra": intra, "inter": inter, "ratio": ratio}

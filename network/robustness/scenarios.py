"""Ban-wave scenarios — block removal of whole communities or label groups.

The attack curves remove channels one at a time, but real moderation on
Telegram has repeatedly removed *groups* of channels at once — the January
2021 wave against US far-right channels being the canonical example
(deplatforming lineage: Rogers 2020).  A *ban-wave scenario* models that
directly: for every community of a partition, remove the whole block in one
step and measure what is left of the network, next to the damage that
removing the *same number* of channels uniformly at random would cause (the
``random`` strategy's mean curve evaluated at the same removal count).

The equal-q random baseline is the point of the exercise.  A block whose
residual ``S`` falls far *below* the baseline is a load-bearing sub-ecosystem:
banning it damages the network far beyond what its size alone explains.  A
block at or above the baseline is structurally replaceable in place, however
large it is.  This is the scenario counterpart of module-based attack
analysis; because Pulpit's partitions include the analyst's own label groups,
"what if every channel of organisation O disappears?" is a first-class query.

Reference:
    Rogers, R. (2020). Deplatforming: Following extreme Internet celebrities
        to Telegram and alternative social media. *European Journal of
        Communication* 35(3), 213-229. https://doi.org/10.1177/0267323120922066
"""

from typing import Any

from network.robustness.metrics import residual_sizes

import networkx as nx
import numpy as np

_BAN_WAVE_METRICS: tuple[str, ...] = ("wcc", "scc", "reach", "strength")


def ban_wave_rows(
    G: nx.DiGraph,
    partition: dict[Any, Any],
    random_curves: dict[str, list[float]],
    *,
    reach_sample: int | None = 500,
    rng: np.random.Generator | None = None,
    min_block_size: int = 2,
) -> list[dict[str, Any]]:
    """One scenario row per community of *partition* with ≥ *min_block_size* members in *G*.

    *random_curves* maps a lowercase metric name to the random strategy's mean
    residual-size curve (index = number of nodes removed) — the equal-q
    baseline each block is compared against.

    Each row carries ``community`` (the stringified community id), ``n`` (block
    size within *G*), ``fraction`` (block share of the node set), the four
    one-shot residual sizes ``s_wcc`` / ``s_scc`` / ``s_reach`` /
    ``s_strength`` after removing the whole block, and the matching baselines
    ``random_wcc`` / … (``None`` when the corresponding curve is absent or too
    short).  Rows are sorted by block size descending, community id ascending.
    Blocks covering the entire graph are skipped — removing everything says
    nothing about structure.
    """
    n0 = G.number_of_nodes()
    if n0 == 0:
        return []

    blocks: dict[Any, list[Any]] = {}
    for node in G.nodes():
        cid = partition.get(node)
        if cid is not None:
            blocks.setdefault(cid, []).append(node)

    rows: list[dict[str, Any]] = []
    for cid, members in blocks.items():
        q = len(members)
        if q < min_block_size or q >= n0:
            continue
        sizes = residual_sizes(G, members, reach_sample=reach_sample, rng=rng)
        row: dict[str, Any] = {"community": str(cid), "n": q, "fraction": q / n0}
        for m in _BAN_WAVE_METRICS:
            row[f"s_{m}"] = sizes[m]
            curve = random_curves.get(m)
            row[f"random_{m}"] = curve[q] if curve and q < len(curve) else None
        rows.append(row)

    rows.sort(key=lambda r: (-r["n"], r["community"]))
    return rows

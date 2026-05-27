from typing import Any

from network.measures._base import apply_measure
from network.utils import GraphData

import networkx as nx
import numpy as np

_SIR_GAMMA = 0.3  # recovery probability per step; mean infectious period ≈ 3 steps


def sir_ever_infected(
    adj: dict[Any, list[tuple[Any, float]]],
    seed: Any,
    rng: np.random.Generator,
    *,
    universe: "set | None" = None,
) -> set:
    """Single SIR run seeded at *seed*; return the set of nodes ever infected (incl. seed).

    *adj* maps each node to ``[(successor, transmission_prob), …]``. *universe* is the
    susceptible pool and defaults to the keys of *adj*. Recovery probability per step is
    ``_SIR_GAMMA``. Generic over node type (str ids or int PKs) so the per-channel
    spreading measure, the robustness spreading attack, and the vacancy cascade-overlap
    score all share one transmission model.
    """
    susceptible = (set(adj) if universe is None else set(universe)) - {seed}
    infected = {seed}
    ever = {seed}

    while infected:
        infected_list = list(infected)

        # Recovery: batch draw for all currently infected nodes
        newly_recovered = {
            n for n, r in zip(infected_list, rng.random(len(infected_list)) < _SIR_GAMMA, strict=True) if r
        }

        # Transmission: for each infected node, batch-draw against its out-edges
        newly_infected: set = set()
        for node in infected_list:
            neighbors = adj.get(node, ())
            if not neighbors:
                continue
            succs = [s for s, _ in neighbors]
            weights = np.array([w for _, w in neighbors])
            hits = rng.random(len(succs)) < weights
            for succ, hit in zip(succs, hits, strict=True):
                if hit and succ in susceptible:
                    newly_infected.add(succ)

        susceptible -= newly_infected
        infected = (infected | newly_infected) - newly_recovered
        ever |= newly_infected

    return ever


def _run_sir(
    adj: dict[str, list[tuple[str, float]]],
    seed: str,
    rng: np.random.Generator,
) -> int:
    """Single SIR run seeded at *seed*. Returns the number of nodes ever infected, including the seed."""
    return len(sir_ever_infected(adj, seed, rng))


def apply_spreading_efficiency(
    graph_data: GraphData,
    graph: nx.DiGraph,
    runs: int = 200,
) -> list[tuple[str, str]]:
    """SIR spreading efficiency: mean fraction of nodes infected when each node seeds the process.

    Each node is used as the sole initial infective in ``runs`` independent Monte Carlo
    SIR simulations.  Transmission probability along edge (i→j) is the edge weight
    *normalised by the maximum edge weight* (so the strongest tie transmits with
    probability 1 and the rest in proportion).  This keeps the probability scale-
    independent — the raw ``weight`` is rescaled to max 10 by ``build_graph``, which
    would otherwise saturate ``min(weight, 1.0)`` to near-certain transmission on most
    edges.  Recovery probability per step is ``_SIR_GAMMA``.  The result is normalised to
    [0, 1] by dividing by (N − 1), so 1.0 means the seed eventually infects every other
    node on average.

    Caveat: the weight->transmission-probability mapping is a heuristic — there is no
    canonical way to turn citation frequency into an infection probability, and tying the
    single strongest edge in the graph to certain transmission is a modelling choice. Read
    Spreading Efficiency *ordinally* (to rank channels by reach) rather than as a calibrated
    probability; absolute values shift with the mapping and the ``runs`` / ``_SIR_GAMMA`` knobs.
    """
    key = "spreading_efficiency"
    n = graph.number_of_nodes()
    if n <= 1:
        for node in graph_data["nodes"]:
            node[key] = 0.0
        return [(key, "Spreading Efficiency")]

    # Pre-build adjacency lists with transmission probabilities = weight / max_weight.
    edge_weights = [data.get("weight", 1.0) for _, _, data in graph.edges(data=True)]
    max_weight = max(edge_weights) if edge_weights else 1.0
    adj: dict[str, list[tuple[str, float]]] = {
        node_id: [(succ, min(data.get("weight", 1.0) / max_weight, 1.0)) for succ, data in graph[node_id].items()]
        for node_id in graph.nodes()
    }

    rng = np.random.default_rng(42)
    results: dict[str, float] = {}
    norm = n - 1

    for node_id in graph.nodes():
        total_infected = sum(_run_sir(adj, node_id, rng) for _ in range(runs))
        # Subtract 1 per run to exclude the seed itself from the spreading count
        results[node_id] = round((total_infected / runs - 1) / norm, 6)

    return apply_measure(graph_data, results, key, "Spreading Efficiency")

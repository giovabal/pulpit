import logging

from network.utils import GraphData

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

_SIR_GAMMA = 0.3  # recovery probability per step; mean infectious period ≈ 3 steps


def _run_sir(
    adj: dict[str, list[tuple[str, float]]],
    seed: str,
    rng: np.random.Generator,
) -> int:
    """Single SIR run seeded at *seed*. Returns the number of nodes ever infected, including the seed."""
    susceptible = set(adj) - {seed}
    infected = {seed}
    ever_infected = 1

    while infected:
        infected_list = list(infected)

        # Recovery: batch draw for all currently infected nodes
        newly_recovered = {
            n for n, r in zip(infected_list, rng.random(len(infected_list)) < _SIR_GAMMA, strict=True) if r
        }

        # Transmission: for each infected node, batch-draw against its out-edges
        newly_infected: set[str] = set()
        for node in infected_list:
            neighbors = adj[node]
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
        ever_infected += len(newly_infected)

    return ever_infected


def apply_spreading_efficiency(
    graph_data: GraphData,
    graph: nx.DiGraph,
    runs: int = 200,
) -> list[tuple[str, str]]:
    """SIR spreading efficiency: mean fraction of nodes infected when each node seeds the process.

    Each node is used as the sole initial infective in ``runs`` independent Monte Carlo
    SIR simulations.  Transmission probability along edge (i→j) equals the edge weight,
    clipped to [0, 1].  Recovery probability per step is ``_SIR_GAMMA``.  The result is
    normalised to [0, 1] by dividing by (N − 1), so 1.0 means the seed eventually infects
    every other node on average.
    """
    key = "spreading_efficiency"
    n = graph.number_of_nodes()
    if n <= 1:
        for node in graph_data["nodes"]:
            node[key] = 0.0
        return [(key, "Spreading Efficiency")]

    # Pre-build adjacency lists with weights clipped to [0, 1]
    adj: dict[str, list[tuple[str, float]]] = {
        node_id: [(succ, min(data.get("weight", 1.0), 1.0)) for succ, data in graph[node_id].items()]
        for node_id in graph.nodes()
    }

    rng = np.random.default_rng(42)
    results: dict[str, float] = {}
    norm = n - 1

    for node_id in graph.nodes():
        total_infected = sum(_run_sir(adj, node_id, rng) for _ in range(runs))
        # Subtract 1 per run to exclude the seed itself from the spreading count
        results[node_id] = round((total_infected / runs - 1) / norm, 6)

    for node in graph_data["nodes"]:
        node[key] = results.get(node["id"], 0.0)

    return [(key, "Spreading Efficiency")]

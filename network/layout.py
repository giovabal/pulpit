import networkx as nx
from pyforceatlas2 import ForceAtlas2


def compute_layout(graph: nx.DiGraph, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* and return a position dict keyed by node pk."""
    forceatlas2 = ForceAtlas2(
        outbound_attraction_distribution=True,
        edge_weight_influence=1.0,
        lin_log_mode=True,
        jitter_tolerance=1.0,
        barnes_hut_optimize=True,
        barnes_hut_theta=1.2,
        scaling_ratio=2.0,
        strong_gravity_mode=False,
        gravity=1.0,
        verbose=False,
    )
    return forceatlas2.forceatlas2_networkx_layout(graph, pos=None, iterations=iterations)

import networkx as nx
from fa2 import ForceAtlas2

LAYOUT_HORIZONTAL = "HORIZONTAL"
LAYOUT_VERTICAL = "VERTICAL"


def rotate_positions(positions: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Rotate all positions 90° clockwise: (x, y) → (y, -x)."""
    return {key: (y, -x) for key, (x, y) in positions.items()}


def kamada_kawai_positions(graph: nx.DiGraph) -> dict:
    """Return initial node positions via Kamada-Kawai."""
    return nx.kamada_kawai_layout(graph, weight="weight")


def forceatlas2_positions(graph: nx.DiGraph, initial_pos: dict, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* starting from *initial_pos*."""
    forceatlas2 = ForceAtlas2(
        outboundAttractionDistribution=True,
        edgeWeightInfluence=1.0,
        linLogMode=True,
        jitterTolerance=1.0,
        barnesHutOptimize=True,
        barnesHutTheta=1.2,
        scalingRatio=2.0,
        strongGravityMode=False,
        gravity=1.0,
        verbose=False,
    )
    return forceatlas2.forceatlas2_networkx_layout(graph.to_undirected(), pos=initial_pos, iterations=iterations)


def compute_layout(graph: nx.DiGraph, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run Kamada-Kawai then ForceAtlas2 on *graph*; return positions keyed by node pk."""
    return forceatlas2_positions(graph, kamada_kawai_positions(graph), iterations)

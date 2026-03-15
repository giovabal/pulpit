import networkx as nx

LAYOUT_HORIZONTAL = "HORIZONTAL"
LAYOUT_VERTICAL = "VERTICAL"


def rotate_positions(positions: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Rotate all positions 90° clockwise: (x, y) → (y, -x)."""
    return {key: (y, -x) for key, (x, y) in positions.items()}


def compute_layout(graph: nx.DiGraph, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* and return a position dict keyed by node pk."""
    raw = nx.forceatlas2_layout(
        graph,
        max_iter=iterations,
        distributed_action=True,
        jitter_tolerance=1.0,
        scaling_ratio=2.0,
        strong_gravity=False,
        gravity=1.0,
        weight="weight",
    )
    return {node: (float(pos[0]), float(pos[1])) for node, pos in raw.items()}

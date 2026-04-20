import warnings

import networkx as nx
import numpy as np
from fa2 import ForceAtlas2

LAYOUT_HORIZONTAL = "HORIZONTAL"
LAYOUT_VERTICAL = "VERTICAL"


def _build_forceatlas2(dim: int = 2) -> ForceAtlas2:
    """Return a ForceAtlas2 instance with standard settings for 2D or 3D layout.

    Barnes-Hut optimisation is enabled for 2D only; it is 2D-specific and
    must be disabled for the 3D back-end.
    """
    return ForceAtlas2(
        outboundAttractionDistribution=True,
        edgeWeightInfluence=1.0,
        linLogMode=True,
        jitterTolerance=1.0,
        barnesHutOptimize=dim == 2,
        barnesHutTheta=1.2,
        scalingRatio=2.0,
        strongGravityMode=False,
        gravity=1.0,
        verbose=False,
        dim=dim,
    )


def rotate_positions(positions: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Rotate all positions 90° clockwise: (x, y) → (y, -x)."""
    return {key: (y, -x) for key, (x, y) in positions.items()}


def kamada_kawai_positions(graph: nx.DiGraph) -> dict:
    """Return initial node positions via Kamada-Kawai."""
    return nx.kamada_kawai_layout(graph, weight="weight")


def forceatlas2_positions(graph: nx.DiGraph, initial_pos: dict, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* starting from *initial_pos*."""
    return _build_forceatlas2(dim=2).forceatlas2_networkx_layout(
        graph.to_undirected(), pos=initial_pos, iterations=iterations
    )


def compute_layout(graph: nx.DiGraph, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run Kamada-Kawai then ForceAtlas2 on *graph*; return positions keyed by node pk."""
    return forceatlas2_positions(graph, kamada_kawai_positions(graph), iterations)


def kamada_kawai_positions_3d(graph: nx.DiGraph) -> dict:
    """Return initial 3D node positions via Kamada-Kawai.

    Suppress the benign divide-by-zero RuntimeWarning that networkx emits when
    two nodes share the same initial position (the layout still converges correctly).
    """
    with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return nx.kamada_kawai_layout(graph, weight="weight", dim=3)


def forceatlas2_positions_3d(
    graph: nx.DiGraph, initial_pos: dict, iterations: int = 10
) -> dict[str, tuple[float, float, float]]:
    """Run ForceAtlas2 in 3D on *graph* starting from *initial_pos*.

    Barnes-Hut optimisation is disabled because it is 2D-only; the vectorised
    O(n²) back-end is used instead.
    """
    return _build_forceatlas2(dim=3).forceatlas2_networkx_layout(
        graph.to_undirected(), pos=initial_pos, iterations=iterations
    )


def compute_layout_3d(graph: nx.DiGraph, iterations: int = 10) -> dict[str, tuple[float, float, float]]:
    """Run Kamada-Kawai then ForceAtlas2 in 3D on *graph*; return 3D positions keyed by node id."""
    return forceatlas2_positions_3d(graph, kamada_kawai_positions_3d(graph), iterations)

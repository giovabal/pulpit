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


# Four axis-aligned rotation matrices (row-vector convention: v @ R.T).
_ROTATIONS: list[np.ndarray] = [
    np.array([[1, 0], [0, 1]], dtype=float),  # 0°
    np.array([[0, 1], [-1, 0]], dtype=float),  # 90° clockwise
    np.array([[-1, 0], [0, -1]], dtype=float),  # 180°
    np.array([[0, -1], [1, 0]], dtype=float),  # 270° clockwise
]


def align_to_reference(
    positions: dict[str, tuple[float, float]],
    reference_positions: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Return *positions* rotated to best match *reference_positions*.

    Tests the four axis-aligned rotations (0°, 90°, 180°, 270°) on the nodes
    present in both dicts and picks the rotation that minimises mean squared
    distance to the reference.  When no common nodes exist the input is
    returned unchanged.
    """
    common = list(set(positions) & set(reference_positions))
    if not common:
        return positions

    ref_pts = np.array([reference_positions[k] for k in common])  # (m, 2)
    our_pts = np.array([positions[k] for k in common])  # (m, 2)

    best_R = _ROTATIONS[0]
    best_msd = float("inf")
    for R in _ROTATIONS:
        msd = float(np.mean(np.sum((our_pts @ R.T - ref_pts) ** 2, axis=1)))
        if msd < best_msd:
            best_msd, best_R = msd, R

    if best_R is _ROTATIONS[0]:
        return positions  # identity — nothing to do

    all_pts = np.array(list(positions.values())) @ best_R.T
    return dict(zip(positions.keys(), (tuple(row) for row in all_pts.tolist()), strict=False))


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


EXTRA_LAYOUT_CHOICES = {"CIRCULAR", "SPECTRAL", "SPRING"}

_EXTRA_LAYOUT_SCALE = 500.0


def circular_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Place nodes equally spaced on a circle."""
    return nx.circular_layout(graph, scale=_EXTRA_LAYOUT_SCALE)


def spectral_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Place nodes using the two smallest Laplacian eigenvectors.

    Falls back to spring layout if the eigensolver fails (e.g. disconnected graph).
    """
    try:
        return nx.spectral_layout(graph, scale=_EXTRA_LAYOUT_SCALE)
    except Exception:
        return spring_positions(graph)


def spring_positions(graph: nx.DiGraph, iterations: int = 200) -> dict[str, tuple[float, float]]:
    """Place nodes with the Fruchterman-Reingold force-directed algorithm."""
    return nx.spring_layout(graph, scale=_EXTRA_LAYOUT_SCALE, iterations=iterations, seed=42)


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

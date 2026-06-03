import warnings

import networkx as nx
import numpy as np
from fa2 import ForceAtlas2

try:
    import umap as _umap_lib

    HAS_UMAP = True
except ImportError:
    HAS_UMAP = False

LAYOUT_HORIZONTAL = "HORIZONTAL"
LAYOUT_VERTICAL = "VERTICAL"

EXTRA_LAYOUT_CHOICES_2D = {"FA2", "CIRCULAR", "KAMADA_KAWAI", "COMMUNITY_SHELL", "TSNE", "UMAP", "HYPERBOLIC"}
EXTRA_LAYOUT_CHOICES_3D = {"FA2", "SPECTRAL", "SPRING", "KAMADA_KAWAI", "TSNE", "UMAP"}

FA2_ITERATIONS_DEFAULT = "7x"
FA2_ITERATIONS_FLOOR = 100


def resolve_iterations(value: str | int | None, num_nodes: int) -> int:
    """Resolve ``fa2_iterations`` to a concrete iteration count.

    Accepted forms:
      * integer or numeric string (``5000``, ``"5000"``) — used verbatim.
      * multiplier-of-N form (``"7x"``, ``"2.5x"``) — returns ``N × num_nodes``.

    Empty / ``None`` falls back to :data:`FA2_ITERATIONS_DEFAULT`. The result
    is floored at :data:`FA2_ITERATIONS_FLOOR` so a tiny graph never gets a
    pathologically short FA2 run.
    """
    if value is None:
        value = FA2_ITERATIONS_DEFAULT
    s = str(value).strip().lower()
    if not s:
        s = FA2_ITERATIONS_DEFAULT
    if s.endswith("x"):
        multiplier = float(s[:-1])
        iterations = int(multiplier * num_nodes)
    else:
        iterations = int(float(s))
    return max(FA2_ITERATIONS_FLOOR, iterations)


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
    return dict(zip(positions.keys(), (tuple(row) for row in all_pts.tolist()), strict=True))


def _kk_distance_graph(graph: nx.DiGraph) -> nx.DiGraph:
    """Copy of *graph* whose edge ``weight`` is inverted (1/w).

    ``nx.kamada_kawai_layout`` reads ``weight`` as a target *distance*, so passing
    the raw weight would place strongly-tied nodes *farther* apart — the opposite
    of the intent (more forwards/mentions ⇒ closer) and the opposite of what the
    ForceAtlas2 pass this seeds expects. Inverting makes a strong tie a short edge.
    """
    inverted = graph.copy()
    for _, _, data in inverted.edges(data=True):
        weight = data.get("weight", 1.0)
        data["weight"] = 1.0 / weight if weight else 1.0
    return inverted


def kamada_kawai_positions(graph: nx.DiGraph) -> dict:
    """Return initial node positions via Kamada-Kawai."""
    return nx.kamada_kawai_layout(_kk_distance_graph(graph), weight="weight")


def forceatlas2_positions(graph: nx.DiGraph, initial_pos: dict, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* starting from *initial_pos*."""
    return _build_forceatlas2(dim=2).forceatlas2_networkx_layout(
        graph.to_undirected(), pos=initial_pos, iterations=iterations
    )


_EXTRA_LAYOUT_SCALE = 500.0


# ── Private helpers ──────────────────────────────────────────────────────────


def _laplacian_features(graph: nx.DiGraph, k: int = 10) -> tuple[list, np.ndarray]:
    """Return (nodes_list, feature_matrix) using the k smallest non-trivial
    normalised Laplacian eigenvectors of the undirected symmetrisation."""
    nodes = list(graph.nodes())
    n = len(nodes)
    k = min(k, max(n - 2, 1))
    G_und = graph.to_undirected()
    A = nx.to_numpy_array(G_und, nodelist=nodes, weight="weight")
    deg = A.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    D_inv_sqrt = np.diag(d_inv_sqrt)
    L_norm = np.eye(n) - D_inv_sqrt @ A @ D_inv_sqrt
    eigenvalues, eigenvectors = np.linalg.eigh(L_norm)
    # skip eigenvector 0 (constant, eigenvalue ≈ 0)
    features = eigenvectors[:, 1 : k + 1]
    return nodes, features


def _scale_embedding(arr: np.ndarray, scale: float = 500.0) -> np.ndarray:
    """Scale embedding to fit within [-scale, scale] on each axis."""
    maxval = np.abs(arr).max()
    if maxval > 0:
        arr = arr / maxval * scale
    return arr


def _shortest_path_matrix(graph: nx.DiGraph) -> tuple[list, np.ndarray]:
    """Return (nodes_list, distance_matrix) of all-pairs shortest-path lengths.

    Uses the undirected symmetrisation.  Unreachable pairs are assigned
    distance n (graph order) so UMAP treats disconnected components as
    maximally far apart rather than encountering inf.
    """
    nodes = list(graph.nodes())
    n = len(nodes)
    node_idx = {node: i for i, node in enumerate(nodes)}
    G_und = graph.to_undirected()
    dist = np.full((n, n), float(n), dtype=float)
    np.fill_diagonal(dist, 0.0)
    for source, lengths in nx.all_pairs_shortest_path_length(G_und):
        i = node_idx[source]
        for target, length in lengths.items():
            dist[i, node_idx[target]] = float(length)
    return nodes, dist


# ── 2D extra layouts ─────────────────────────────────────────────────────────


def circular_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Place nodes equally spaced on a circle."""
    return nx.circular_layout(graph, scale=_EXTRA_LAYOUT_SCALE)


def community_shell_positions(
    graph: nx.DiGraph,
    strategy_results: "dict[str, tuple]",
) -> dict[str, tuple[float, float]]:
    """Place nodes in concentric shells, one shell per community.

    Largest community occupies the outermost shell; remaining communities fill
    progressively inner shells.  Falls back to a plain shell layout when no
    community data is available.

    *strategy_results* has the shape returned by ``_compute_communities``:
    ``{strategy_key: (community_map, palette)}`` keyed by the parameter-suffixed partition key
    (``StrategyInstance.key``) where *community_map* is ``{node_id: community_label}``.
    """
    preferred = ["leiden", "leiden_directed", "labelpropagation"]
    community_map: dict | None = None
    for key in preferred:
        if key in strategy_results:
            community_map, _ = strategy_results[key]
            break
    if community_map is None and strategy_results:
        community_map, _ = next(iter(strategy_results.values()))
    if community_map is None:
        return nx.shell_layout(graph, scale=_EXTRA_LAYOUT_SCALE)

    groups: dict[str, list] = {}
    for node in graph.nodes():
        cid = community_map.get(node, "__none__")
        groups.setdefault(cid, []).append(node)
    nlist = sorted(groups.values(), key=len, reverse=True)
    return nx.shell_layout(graph, nlist=nlist, scale=_EXTRA_LAYOUT_SCALE)


def tsne_positions_2d(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """2D t-SNE embedding via the top Laplacian eigenvectors.

    Van der Maaten & Hinton 2008.  Uses ``random_state=42`` for
    reproducibility; perplexity is clamped to a safe range.
    """
    from sklearn.manifold import TSNE

    nodes, features = _laplacian_features(graph)
    n = len(nodes)
    if n < 4:
        return kamada_kawai_positions(graph)
    perplexity = min(30, max(5, n // 4), n - 1)
    embedding = TSNE(n_components=2, random_state=42, perplexity=perplexity).fit_transform(features)
    embedding = _scale_embedding(embedding)
    return {node: (float(embedding[i, 0]), float(embedding[i, 1])) for i, node in enumerate(nodes)}


def umap_positions_2d(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """2D UMAP embedding on the all-pairs shortest-path distance matrix.

    McInnes et al. 2018.  Using precomputed graph distances (not Laplacian
    eigenvectors) gives a perspective complementary to t-SNE: UMAP sees raw
    topological distances, so nodes that are many hops apart are pushed far
    apart globally — not just locally separated by cluster membership.
    Falls back to t-SNE when umap-learn is unavailable.
    """
    if not HAS_UMAP:
        return tsne_positions_2d(graph)
    nodes, dist = _shortest_path_matrix(graph)
    n = len(nodes)
    # Need n >= 5: UMAP's spectral init fails with "k >= N" on smaller graphs.
    if n < 5:
        return kamada_kawai_positions(graph)
    n_neighbors = min(15, n - 1)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="umap")
        embedding = _umap_lib.UMAP(
            n_components=2, random_state=42, n_neighbors=n_neighbors, metric="precomputed"
        ).fit_transform(dist)
    embedding = _scale_embedding(embedding)
    return {node: (float(embedding[i, 0]), float(embedding[i, 1])) for i, node in enumerate(nodes)}


def hyperbolic_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Pseudo-hyperbolic (Poincaré-disk) layout.

    Approximates hyperbolic embedding (Krioukov et al. 2010; Boguña et al.
    2010 Mercator) without external dependencies: angular positions come from
    a 2D spring seed and radial positions are derived from log-scaled total
    degree — hubs land near the centre, peripheral channels at the edge,
    reproducing the key visual property of the Poincaré disk.
    """
    nodes = list(graph.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: (0.0, 0.0)}

    seed_pos = nx.spring_layout(graph.to_undirected(), seed=42)
    degrees = dict(graph.degree())
    max_deg = max(degrees.values()) if degrees else 1

    result: dict[str, tuple[float, float]] = {}
    for node in nodes:
        sx, sy = seed_pos.get(node, (0.0, 0.0))
        angle = float(np.arctan2(sy, sx))
        deg = degrees.get(node, 0)
        r_frac = 1.0 - float(np.log1p(deg) / np.log1p(max(max_deg, 1)))
        r = r_frac * _EXTRA_LAYOUT_SCALE
        result[node] = (r * float(np.cos(angle)), r * float(np.sin(angle)))
    return result


# ── 3D extra layouts ─────────────────────────────────────────────────────────


def spectral_positions(graph: nx.DiGraph) -> dict[str, tuple[float, float, float]]:
    """Place nodes using the three smallest Laplacian eigenvectors (3D).

    Falls back to spring layout if the eigensolver fails (e.g. disconnected graph).
    """
    try:
        return nx.spectral_layout(graph, scale=_EXTRA_LAYOUT_SCALE, dim=3)
    except Exception:
        return spring_positions(graph)


def spring_positions(graph: nx.DiGraph, iterations: int = 200) -> dict[str, tuple[float, float, float]]:
    """Place nodes with the Fruchterman-Reingold force-directed algorithm in 3D."""
    return nx.spring_layout(graph, scale=_EXTRA_LAYOUT_SCALE, iterations=iterations, seed=42, dim=3)


def tsne_positions_3d(graph: nx.DiGraph) -> dict[str, tuple[float, float, float]]:
    """3D t-SNE embedding via the top Laplacian eigenvectors.

    Van der Maaten & Hinton 2008.
    """
    from sklearn.manifold import TSNE

    nodes, features = _laplacian_features(graph)
    n = len(nodes)
    # Need n >= 5: _laplacian_features yields only n-2 columns for small graphs,
    # and sklearn's PCA-init t-SNE requires n_components (3) <= n_features.
    if n < 5:
        return kamada_kawai_positions_3d(graph)
    perplexity = min(30, max(5, n // 4), n - 1)
    embedding = TSNE(n_components=3, random_state=42, perplexity=perplexity).fit_transform(features)
    embedding = _scale_embedding(embedding)
    return {
        node: (float(embedding[i, 0]), float(embedding[i, 1]), float(embedding[i, 2])) for i, node in enumerate(nodes)
    }


def umap_positions_3d(graph: nx.DiGraph) -> dict[str, tuple[float, float, float]]:
    """3D UMAP embedding on the all-pairs shortest-path distance matrix.

    McInnes et al. 2018.  Falls back to 3D t-SNE when umap-learn is unavailable.
    """
    if not HAS_UMAP:
        return tsne_positions_3d(graph)
    nodes, dist = _shortest_path_matrix(graph)
    n = len(nodes)
    # Need n >= 5: UMAP's spectral init fails with "k >= N" on smaller graphs.
    if n < 5:
        return kamada_kawai_positions_3d(graph)
    n_neighbors = min(15, n - 1)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="umap")
        embedding = _umap_lib.UMAP(
            n_components=3, random_state=42, n_neighbors=n_neighbors, metric="precomputed"
        ).fit_transform(dist)
    embedding = _scale_embedding(embedding)
    return {
        node: (float(embedding[i, 0]), float(embedding[i, 1]), float(embedding[i, 2])) for i, node in enumerate(nodes)
    }


# ── Primary 3D pipeline ──────────────────────────────────────────────────────


def kamada_kawai_positions_3d(graph: nx.DiGraph) -> dict:
    """Return initial 3D node positions via Kamada-Kawai.

    Suppress the benign divide-by-zero RuntimeWarning that networkx emits when
    two nodes share the same initial position (the layout still converges correctly).
    """
    with np.errstate(divide="ignore", invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return nx.kamada_kawai_layout(_kk_distance_graph(graph), weight="weight", dim=3)


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

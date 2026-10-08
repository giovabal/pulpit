import warnings

from network.parameters import FixedParameter
from network.utils import to_undirected_sum

import networkx as nx
import numpy as np
from fa2 import ForceAtlas2

try:
    # umap probes for Tensorflow (for the optional ParametricUMAP) at import and
    # emits an ImportWarning when it is absent. We never use ParametricUMAP, and
    # the warning is unfilterable from settings under the test runner (which
    # resets warning filters), so suppress it at the import site.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ImportWarning)
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

# ── Fixed layout parameters ──────────────────────────────────────────────────
# Every value below shapes a layout and is declared in FIXED_PARAMETERS (PARAMETERS.md). The fa2 /
# networkx / scikit-learn / umap-learn defaults the code used to rely on implicitly are named here
# with the library's own value and passed explicitly, so the map is computed from the same values
# the document lists.

# ForceAtlas2 settings shared by the 2D and 3D passes (main and coordination maps).
FA2_OUTBOUND_ATTRACTION_DISTRIBUTION = True
FA2_LINLOG_MODE = True
FA2_EDGE_WEIGHT_INFLUENCE = 1.0
FA2_JITTER_TOLERANCE = 1.0
FA2_BARNES_HUT_THETA = 1.2
FA2_SCALING_RATIO = 2.0
FA2_STRONG_GRAVITY_MODE = False
FA2_GRAVITY = 1.0
# fa2 library defaults, made explicit.
FA2_ADJUST_SIZES = False
FA2_NORMALIZE_EDGE_WEIGHTS = False
FA2_INVERTED_EDGE_WEIGHTS_MODE = False
FA2_BACKEND = "auto"
# Barnes-Hut repulsion approximation: 2D only — it is 2D-specific and must be off for the 3D back-end.
FA2_BARNES_HUT_2D = True
FA2_BARNES_HUT_3D = False
# Edge attribute ForceAtlas2 reads as the attraction weight: the graph's edge weight (the ×10/max
# rescale of --edge-weight-strategy), so an edge pulls its endpoints together in proportion to its
# weight (raised to FA2_EDGE_WEIGHT_INFLUENCE). The pass runs on the W+Wᵀ projection
# (network.utils.to_undirected_sum), so a mutual tie pulls with both directions' weights summed.
FA2_WEIGHT_ATTR = "weight"

# Kamada-Kawai seed layout. The target distance of an edge is 1/weight (a strong tie is a short
# edge); an edge without a positive weight gets KK_ZERO_WEIGHT_LENGTH. KK_SCALE is networkx's default
# output scale — the coordinate range ForceAtlas2 starts from. networkx starts the 2D pass from a
# circular layout (deterministic) and the 3D pass from uniform-random positions drawn with
# KK_SEED_3D, so both are reproducible.
KK_SCALE = 1
KK_ZERO_WEIGHT_LENGTH = 1.0
KK_SEED_3D = 42

# Extra layouts (``--layouts-2d`` / ``--layouts-3d``).
EXTRA_LAYOUT_SEED = 42  # t-SNE / UMAP random_state and the spring-layout seeds
EXTRA_LAYOUT_WEIGHT_ATTR = "weight"  # edge weight read by the spring, spectral and Laplacian-feature layouts
LAPLACIAN_FEATURES_K = 10  # Laplacian eigenvectors fed to t-SNE
TSNE_PERPLEXITY_MAX = 30
TSNE_PERPLEXITY_MIN = 5
TSNE_NODES_PER_PERPLEXITY = 4  # perplexity = min(MAX, max(MIN, n // 4), n − 1)
TSNE_EARLY_EXAGGERATION = 12.0
TSNE_LEARNING_RATE = "auto"
TSNE_MAX_ITER = 1000
TSNE_N_ITER_WITHOUT_PROGRESS = 300
TSNE_MIN_GRAD_NORM = 1e-7
TSNE_METRIC = "euclidean"
TSNE_INIT = "pca"
TSNE_METHOD = "barnes_hut"
TSNE_ANGLE = 0.5
UMAP_METRIC = "precomputed"  # all-pairs undirected shortest-path lengths (unreachable pairs at distance n)
UMAP_N_NEIGHBORS_MAX = 15  # n_neighbors = min(MAX, n − 1)
UMAP_MIN_DIST = 0.1
UMAP_SPREAD = 1.0
UMAP_LEARNING_RATE = 1.0
UMAP_N_EPOCHS: int | None = None
UMAP_INIT = "spectral"
SPRING_3D_ITERATIONS = 200
HYPERBOLIC_SPRING_ITERATIONS = 50
SPRING_K: float | None = None
SPRING_THRESHOLD = 1e-4
SPRING_METHOD = "auto"
SPRING_GRAVITY = 1.0
# The partition that defines the COMMUNITY_SHELL rings: the first of these strategy keys present,
# else the first partition computed.
COMMUNITY_SHELL_PREFERENCE: tuple[str, ...] = ("leiden", "leiden_directed", "consensus", "louvain")
# Coordinate range (± this) the extra layouts are scaled to.
_EXTRA_LAYOUT_SCALE = 500.0

_SOURCE = "network/layout.py"


def _entry(name: str, value: object, scope: str, constant: str, affects: str, note: str = "") -> FixedParameter:
    return FixedParameter(
        name=name, value=value, scope=scope, affects=affects, source=f"{_SOURCE}: {constant}", note=note
    )


def _kamada_kawai_parameters(scope: str, *, seed_3d: bool) -> list[FixedParameter]:
    """The Kamada-Kawai settings — the seed of the main ForceAtlas2 map and the KAMADA_KAWAI extra layout."""
    params = [
        _entry(
            "Kamada-Kawai output scale",
            KK_SCALE,
            scope,
            "KK_SCALE",
            "Coordinate range of the Kamada-Kawai placement (the positions ForceAtlas2 starts from).",
            note="networkx default, passed explicitly.",
        ),
        _entry(
            "Kamada-Kawai length of a zero-weight edge",
            KK_ZERO_WEIGHT_LENGTH,
            scope,
            "KK_ZERO_WEIGHT_LENGTH",
            "Kamada-Kawai lays nodes out at shortest-path distances over edge length 1/weight (a strong tie is "
            "a short edge); an edge without a positive weight gets this length instead.",
            note="networkx measures the shortest paths on the directed graph and gives unreachable pairs a "
            "target distance of 1e6.",
        ),
    ]
    if seed_3d:
        params.append(
            _entry(
                "Kamada-Kawai 3D starting-position seed",
                KK_SEED_3D,
                scope,
                "KK_SEED_3D",
                "Seeds the uniform-random positions the 3D Kamada-Kawai pass starts from, so the 3D maps (and "
                "the 3D KAMADA_KAWAI layout) come out the same on every run.",
                note="networkx's own starting layout for 3D, seeded (the 2D pass starts from a circle).",
            )
        )
    return params


def _map_layout_parameters(scope: str, dim: int) -> list[FixedParameter]:
    """The main map layout (``layout_2d`` / ``layout_3d``): ForceAtlas2 seeded by Kamada-Kawai.

    The coordination maps run the same pipeline with the same settings.
    """
    params = [
        _entry(
            "ForceAtlas2 minimum iterations",
            FA2_ITERATIONS_FLOOR,
            scope,
            "FA2_ITERATIONS_FLOOR",
            "The resolved --fa2-iterations count is raised to at least this many iterations, so a tiny graph "
            "never gets a pathologically short run.",
        ),
        _entry(
            "ForceAtlas2 LinLog mode",
            FA2_LINLOG_MODE,
            scope,
            "FA2_LINLOG_MODE",
            "Logarithmic instead of linear attraction: hubs no longer drag the periphery onto themselves and "
            "communities come out as tighter, better-separated clusters.",
            note="Designed for scale-free networks — docs/graph-layouts.md.",
        ),
        _entry(
            "ForceAtlas2 outbound attraction distribution",
            FA2_OUTBOUND_ATTRACTION_DISTRIBUTION,
            scope,
            "FA2_OUTBOUND_ATTRACTION_DISTRIBUTION",
            "Divides each node's attraction by its degree-based mass (Gephi's 'Dissuade Hubs'), pushing hubs "
            "toward the borders with their satellites around them.",
        ),
        _entry(
            "ForceAtlas2 scaling ratio",
            FA2_SCALING_RATIO,
            scope,
            "FA2_SCALING_RATIO",
            "Strength of the node-node repulsion; larger values spread the layout out.",
        ),
        _entry(
            "ForceAtlas2 gravity",
            FA2_GRAVITY,
            scope,
            "FA2_GRAVITY",
            "Pull toward the centre that keeps disconnected components from drifting away.",
        ),
        _entry(
            "ForceAtlas2 strong gravity mode",
            FA2_STRONG_GRAVITY_MODE,
            scope,
            "FA2_STRONG_GRAVITY_MODE",
            "Off: the standard ForceAtlas2 gravity is used, not the strong-gravity variant.",
        ),
        _entry(
            "ForceAtlas2 Barnes-Hut approximation",
            FA2_BARNES_HUT_2D if dim == 2 else FA2_BARNES_HUT_3D,
            scope,
            "FA2_BARNES_HUT_2D" if dim == 2 else "FA2_BARNES_HUT_3D",
            "Whether repulsion is approximated by the Barnes-Hut quadtree (O(n log n)) rather than computed "
            "exactly over every node pair; the approximation is 2D-only.",
        ),
        _entry(
            "ForceAtlas2 Barnes-Hut θ",
            FA2_BARNES_HUT_THETA,
            scope,
            "FA2_BARNES_HUT_THETA",
            "Accuracy of the Barnes-Hut approximation (lower = more exact, slower); only used when it is on.",
        ),
        _entry(
            "ForceAtlas2 jitter tolerance",
            FA2_JITTER_TOLERANCE,
            scope,
            "FA2_JITTER_TOLERANCE",
            "How much node oscillation the adaptive speed tolerates: higher converges faster but less precisely.",
        ),
        _entry(
            "ForceAtlas2 edge-weight attribute",
            FA2_WEIGHT_ATTR,
            scope,
            "FA2_WEIGHT_ATTR",
            "Each edge pulls its endpoints together in proportion to this attribute — the run's edge weight "
            "(--edge-weight-strategy, rescaled to a maximum of 10), with a mutual tie's two directions summed.",
            note="fa2's own default is None (unweighted); Pulpit passes the weight, as Gephi's ForceAtlas2 does.",
        ),
        _entry(
            "ForceAtlas2 edge-weight influence",
            FA2_EDGE_WEIGHT_INFLUENCE,
            scope,
            "FA2_EDGE_WEIGHT_INFLUENCE",
            "Exponent applied to edge weights in the attraction; with the unweighted pass every weight is 1, "
            "so it has no effect.",
        ),
        _entry(
            "ForceAtlas2 node-size anti-collision",
            FA2_ADJUST_SIZES,
            scope,
            "FA2_ADJUST_SIZES",
            "Off: nodes are points, so the layout does not push apart overlapping nodes.",
            note="fa2 default, passed explicitly.",
        ),
        _entry(
            "ForceAtlas2 edge-weight normalisation",
            FA2_NORMALIZE_EDGE_WEIGHTS,
            scope,
            "FA2_NORMALIZE_EDGE_WEIGHTS",
            "Off: edge weights are not min-max rescaled before the attraction.",
            note="fa2 default, passed explicitly.",
        ),
        _entry(
            "ForceAtlas2 inverted edge weights",
            FA2_INVERTED_EDGE_WEIGHTS_MODE,
            scope,
            "FA2_INVERTED_EDGE_WEIGHTS_MODE",
            "Off: edge weights are not inverted (1/w) before the attraction.",
            note="fa2 default, passed explicitly.",
        ),
        _entry(
            "ForceAtlas2 force back-end",
            FA2_BACKEND,
            scope,
            "FA2_BACKEND",
            "Which fa2 force implementation runs: 'auto' uses the compiled Cython loop (Barnes-Hut honoured) "
            "and falls back to the NumPy vectorised back-end, which ignores Barnes-Hut, when fa2 is not "
            "compiled.",
            note="fa2 default, passed explicitly.",
        ),
    ]
    return params + _kamada_kawai_parameters(scope, seed_3d=dim == 3)


def _extra_layout_parameters() -> list[FixedParameter]:
    """The extra layouts (``--layouts-2d`` / ``--layouts-3d``), one ``layout:<TOKEN>`` scope per layout.

    A setting shared by several layouts is declared once per token (same name and source).
    """
    params: list[FixedParameter] = []

    def shared(tokens: tuple[str, ...], *args, **kwargs) -> None:
        name, value, constant, affects = args
        params.extend(_entry(name, value, f"layout:{t}", constant, affects, **kwargs) for t in tokens)

    shared(
        ("CIRCULAR", "COMMUNITY_SHELL", "HYPERBOLIC", "SPECTRAL", "SPRING", "TSNE", "UMAP"),
        "Extra layouts: coordinate scale",
        _EXTRA_LAYOUT_SCALE,
        "_EXTRA_LAYOUT_SCALE",
        "The extra layout's positions are scaled to span ± this (the HYPERBOLIC disk radius).",
    )
    shared(
        ("HYPERBOLIC", "SPRING", "TSNE", "UMAP"),
        "Extra layouts: random seed",
        EXTRA_LAYOUT_SEED,
        "EXTRA_LAYOUT_SEED",
        "random_state of t-SNE and UMAP and seed of the spring layouts (SPRING, and the spring layout whose "
        "angles place the HYPERBOLIC nodes), so these layouts are reproducible.",
    )
    shared(
        ("HYPERBOLIC", "SPECTRAL", "SPRING", "TSNE"),
        "Extra layouts: edge-weight attribute",
        EXTRA_LAYOUT_WEIGHT_ATTR,
        "EXTRA_LAYOUT_WEIGHT_ATTR",
        "Edge attribute read as tie strength by the spring and spectral layouts and by the Laplacian "
        "features behind t-SNE.",
        note="networkx default, passed explicitly.",
    )
    shared(
        ("COMMUNITY_SHELL",),
        "COMMUNITY_SHELL: partition preference",
        COMMUNITY_SHELL_PREFERENCE,
        "COMMUNITY_SHELL_PREFERENCE",
        "The partition whose communities form the concentric shells (largest outermost): the first of these "
        "strategy keys computed in the run, else the first partition.",
    )
    params.extend(_kamada_kawai_parameters("layout:KAMADA_KAWAI", seed_3d=True))
    tsne = (
        (
            "t-SNE: Laplacian eigenvectors",
            LAPLACIAN_FEATURES_K,
            "LAPLACIAN_FEATURES_K",
            "Number of smallest non-trivial normalised-Laplacian eigenvectors fed to t-SNE as node features "
            "(capped at n − 2).",
            "",
        ),
        (
            "t-SNE: maximum perplexity",
            TSNE_PERPLEXITY_MAX,
            "TSNE_PERPLEXITY_MAX",
            "Upper bound of the perplexity min(maximum, max(minimum, n // nodes-per-unit), n − 1).",
            "",
        ),
        (
            "t-SNE: minimum perplexity",
            TSNE_PERPLEXITY_MIN,
            "TSNE_PERPLEXITY_MIN",
            "Lower bound of the perplexity (before the n − 1 cap).",
            "",
        ),
        (
            "t-SNE: nodes per unit of perplexity",
            TSNE_NODES_PER_PERPLEXITY,
            "TSNE_NODES_PER_PERPLEXITY",
            "Between its bounds the perplexity grows as n // this.",
            "",
        ),
        (
            "t-SNE: early exaggeration",
            TSNE_EARLY_EXAGGERATION,
            "TSNE_EARLY_EXAGGERATION",
            "How tightly clusters form in the early optimisation phase.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: learning rate",
            TSNE_LEARNING_RATE,
            "TSNE_LEARNING_RATE",
            "Gradient step size ('auto' scales it with the sample size).",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: maximum iterations",
            TSNE_MAX_ITER,
            "TSNE_MAX_ITER",
            "Upper bound on the optimisation iterations.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: iterations without progress",
            TSNE_N_ITER_WITHOUT_PROGRESS,
            "TSNE_N_ITER_WITHOUT_PROGRESS",
            "The optimisation stops after this many iterations without improvement.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: minimum gradient norm",
            TSNE_MIN_GRAD_NORM,
            "TSNE_MIN_GRAD_NORM",
            "The optimisation stops when the gradient norm falls below this.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: feature metric",
            TSNE_METRIC,
            "TSNE_METRIC",
            "Distance between the nodes' Laplacian feature vectors.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: initialisation",
            TSNE_INIT,
            "TSNE_INIT",
            "Starting embedding of the optimisation.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: gradient method",
            TSNE_METHOD,
            "TSNE_METHOD",
            "Barnes-Hut approximation of the t-SNE gradient instead of the exact O(n²) one.",
            "scikit-learn default, passed explicitly.",
        ),
        (
            "t-SNE: Barnes-Hut angle",
            TSNE_ANGLE,
            "TSNE_ANGLE",
            "Accuracy/speed trade-off of the Barnes-Hut gradient.",
            "scikit-learn default, passed explicitly.",
        ),
    )
    for name, value, constant, affects, note in tsne:
        params.append(_entry(name, value, "layout:TSNE", constant, affects, note=note))
    umap = (
        (
            "UMAP: input metric",
            UMAP_METRIC,
            "UMAP_METRIC",
            "UMAP embeds the all-pairs undirected shortest-path distances; unreachable pairs are placed at distance "
            "n (the node count) rather than infinity.",
            "",
        ),
        (
            "UMAP: maximum neighbours",
            UMAP_N_NEIGHBORS_MAX,
            "UMAP_N_NEIGHBORS_MAX",
            "Size of the local neighbourhood UMAP preserves: min(this, n − 1).",
            "",
        ),
        (
            "UMAP: minimum distance",
            UMAP_MIN_DIST,
            "UMAP_MIN_DIST",
            "How tightly UMAP packs points that are neighbours.",
            "umap-learn default, passed explicitly.",
        ),
        (
            "UMAP: spread",
            UMAP_SPREAD,
            "UMAP_SPREAD",
            "Scale of the embedded points, together with the minimum distance.",
            "umap-learn default, passed explicitly.",
        ),
        (
            "UMAP: learning rate",
            UMAP_LEARNING_RATE,
            "UMAP_LEARNING_RATE",
            "Initial step size of the embedding optimisation.",
            "umap-learn default, passed explicitly.",
        ),
        (
            "UMAP: training epochs",
            UMAP_N_EPOCHS,
            "UMAP_N_EPOCHS",
            "None lets umap-learn pick the number of epochs from the data size.",
            "umap-learn default, passed explicitly.",
        ),
        (
            "UMAP: initialisation",
            UMAP_INIT,
            "UMAP_INIT",
            "Starting embedding of the optimisation.",
            "umap-learn default, passed explicitly.",
        ),
    )
    for name, value, constant, affects, note in umap:
        params.append(_entry(name, value, "layout:UMAP", constant, affects, note=note))
    params.append(
        _entry(
            "HYPERBOLIC: spring-seed iterations",
            HYPERBOLIC_SPRING_ITERATIONS,
            "layout:HYPERBOLIC",
            "HYPERBOLIC_SPRING_ITERATIONS",
            "Iterations of the spring layout whose angles place the nodes around the Poincaré disk.",
            note="networkx default, passed explicitly.",
        )
    )
    params.append(
        _entry(
            "SPRING: iterations",
            SPRING_3D_ITERATIONS,
            "layout:SPRING",
            "SPRING_3D_ITERATIONS",
            "Iterations of the 3D Fruchterman-Reingold layout.",
        )
    )
    shared(
        ("HYPERBOLIC", "SPRING"),
        "Spring layouts: optimal distance k",
        SPRING_K,
        "SPRING_K",
        "None lets networkx use 1/√n as the optimal node spacing.",
        note="networkx default, passed explicitly.",
    )
    shared(
        ("HYPERBOLIC", "SPRING"),
        "Spring layouts: convergence threshold",
        SPRING_THRESHOLD,
        "SPRING_THRESHOLD",
        "The spring layout stops early when the per-node displacement falls below this.",
        note="networkx default, passed explicitly.",
    )
    shared(
        ("HYPERBOLIC", "SPRING"),
        "Spring layouts: method",
        SPRING_METHOD,
        "SPRING_METHOD",
        "'auto' runs the force method below 500 nodes and the energy method from 500 nodes up.",
        note="networkx default, passed explicitly.",
    )
    shared(
        ("HYPERBOLIC", "SPRING"),
        "Spring layouts: gravity",
        SPRING_GRAVITY,
        "SPRING_GRAVITY",
        "Pull toward the centre used by the energy method (graphs of 500+ nodes).",
        note="networkx default, passed explicitly.",
    )
    return params


#: The values fixed in this module (``PARAMETERS.md``): the main map layout under ``layout_2d`` /
#: ``layout_3d``, each extra layout under ``layout:<TOKEN>`` (tokens of EXTRA_LAYOUT_CHOICES_2D/3D).
#: The ForceAtlas2 iteration count, the extra-layout selection and the map orientation are run
#: options (``--fa2-iterations``, ``--layouts-2d`` / ``--layouts-3d``, ``--vertical-layout``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = tuple(
    _map_layout_parameters("layout_2d", 2) + _map_layout_parameters("layout_3d", 3) + _extra_layout_parameters()
)


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
        outboundAttractionDistribution=FA2_OUTBOUND_ATTRACTION_DISTRIBUTION,
        linLogMode=FA2_LINLOG_MODE,
        adjustSizes=FA2_ADJUST_SIZES,
        edgeWeightInfluence=FA2_EDGE_WEIGHT_INFLUENCE,
        normalizeEdgeWeights=FA2_NORMALIZE_EDGE_WEIGHTS,
        invertedEdgeWeightsMode=FA2_INVERTED_EDGE_WEIGHTS_MODE,
        jitterTolerance=FA2_JITTER_TOLERANCE,
        barnesHutOptimize=FA2_BARNES_HUT_2D if dim == 2 else FA2_BARNES_HUT_3D,
        barnesHutTheta=FA2_BARNES_HUT_THETA,
        scalingRatio=FA2_SCALING_RATIO,
        strongGravityMode=FA2_STRONG_GRAVITY_MODE,
        gravity=FA2_GRAVITY,
        backend=FA2_BACKEND,
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
        data["weight"] = 1.0 / weight if weight else KK_ZERO_WEIGHT_LENGTH
    return inverted


def kamada_kawai_positions(graph: nx.DiGraph) -> dict:
    """Return initial node positions via Kamada-Kawai.

    Starts from networkx's own 2D choice, a circular layout, passed explicitly.
    """
    kk_graph = _kk_distance_graph(graph)
    return nx.kamada_kawai_layout(kk_graph, pos=nx.circular_layout(kk_graph), weight="weight", scale=KK_SCALE)


def _fa2_graph(graph: nx.DiGraph) -> nx.Graph:
    """The undirected graph ForceAtlas2 lays out: the W+Wᵀ projection of ``FA2_WEIGHT_ATTR``.

    ``DiGraph.to_undirected()`` would keep one direction's weight of a mutual tie, chosen by edge
    insertion order; summing both gives the tie its full weight.
    """
    return to_undirected_sum(graph, weight=FA2_WEIGHT_ATTR)


def forceatlas2_positions(graph: nx.DiGraph, initial_pos: dict, iterations: int = 10) -> dict[str, tuple[float, float]]:
    """Run ForceAtlas2 on *graph* starting from *initial_pos*."""
    return _build_forceatlas2(dim=2).forceatlas2_networkx_layout(
        _fa2_graph(graph), pos=initial_pos, iterations=iterations, weight_attr=FA2_WEIGHT_ATTR
    )


# ── Private helpers ──────────────────────────────────────────────────────────


def _laplacian_features(graph: nx.DiGraph, k: int = LAPLACIAN_FEATURES_K) -> tuple[list, np.ndarray]:
    """Return (nodes_list, feature_matrix) using the k smallest non-trivial
    normalised Laplacian eigenvectors of the undirected symmetrisation."""
    nodes = list(graph.nodes())
    n = len(nodes)
    k = min(k, max(n - 2, 1))
    G_und = graph.to_undirected()
    A = nx.to_numpy_array(G_und, nodelist=nodes, weight=EXTRA_LAYOUT_WEIGHT_ATTR)
    deg = A.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        d_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    D_inv_sqrt = np.diag(d_inv_sqrt)
    L_norm = np.eye(n) - D_inv_sqrt @ A @ D_inv_sqrt
    _eigenvalues, eigenvectors = np.linalg.eigh(L_norm)
    # skip eigenvector 0 (constant, eigenvalue ≈ 0)
    features = eigenvectors[:, 1 : k + 1]
    return nodes, features


def _scale_embedding(arr: np.ndarray, scale: float = _EXTRA_LAYOUT_SCALE) -> np.ndarray:
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


def _tsne(dim: int, n: int):
    """t-SNE estimator with the module's fixed settings; perplexity clamped to a safe range for *n* nodes."""
    from sklearn.manifold import TSNE

    perplexity = min(TSNE_PERPLEXITY_MAX, max(TSNE_PERPLEXITY_MIN, n // TSNE_NODES_PER_PERPLEXITY), n - 1)
    return TSNE(
        n_components=dim,
        perplexity=perplexity,
        early_exaggeration=TSNE_EARLY_EXAGGERATION,
        learning_rate=TSNE_LEARNING_RATE,
        max_iter=TSNE_MAX_ITER,
        n_iter_without_progress=TSNE_N_ITER_WITHOUT_PROGRESS,
        min_grad_norm=TSNE_MIN_GRAD_NORM,
        metric=TSNE_METRIC,
        init=TSNE_INIT,
        random_state=EXTRA_LAYOUT_SEED,
        method=TSNE_METHOD,
        angle=TSNE_ANGLE,
    )


def _umap(dim: int, n: int):
    """UMAP estimator on a precomputed distance matrix with the module's fixed settings."""
    return _umap_lib.UMAP(
        n_neighbors=min(UMAP_N_NEIGHBORS_MAX, n - 1),
        n_components=dim,
        metric=UMAP_METRIC,
        n_epochs=UMAP_N_EPOCHS,
        learning_rate=UMAP_LEARNING_RATE,
        init=UMAP_INIT,
        min_dist=UMAP_MIN_DIST,
        spread=UMAP_SPREAD,
        random_state=EXTRA_LAYOUT_SEED,
    )


def _spring(graph: nx.Graph, *, dim: int, iterations: int, scale: float = 1) -> dict:
    """Fruchterman-Reingold (``nx.spring_layout``) with the module's fixed settings."""
    return nx.spring_layout(
        graph,
        k=SPRING_K,
        iterations=iterations,
        threshold=SPRING_THRESHOLD,
        weight=EXTRA_LAYOUT_WEIGHT_ATTR,
        scale=scale,
        dim=dim,
        seed=EXTRA_LAYOUT_SEED,
        method=SPRING_METHOD,
        gravity=SPRING_GRAVITY,
    )


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
    community_map: dict | None = None
    for key in COMMUNITY_SHELL_PREFERENCE:
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
    nodes, features = _laplacian_features(graph)
    n = len(nodes)
    if n < 4:
        return kamada_kawai_positions(graph)
    embedding = _tsne(2, n).fit_transform(features)
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
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="umap")
        embedding = _umap(2, n).fit_transform(dist)
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

    seed_pos = _spring(graph.to_undirected(), dim=2, iterations=HYPERBOLIC_SPRING_ITERATIONS)
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
        return nx.spectral_layout(graph, weight=EXTRA_LAYOUT_WEIGHT_ATTR, scale=_EXTRA_LAYOUT_SCALE, dim=3)
    except Exception:
        return spring_positions(graph)


def spring_positions(
    graph: nx.DiGraph, iterations: int = SPRING_3D_ITERATIONS
) -> dict[str, tuple[float, float, float]]:
    """Place nodes with the Fruchterman-Reingold force-directed algorithm in 3D."""
    return _spring(graph, dim=3, iterations=iterations, scale=_EXTRA_LAYOUT_SCALE)


def tsne_positions_3d(graph: nx.DiGraph) -> dict[str, tuple[float, float, float]]:
    """3D t-SNE embedding via the top Laplacian eigenvectors.

    Van der Maaten & Hinton 2008.
    """
    nodes, features = _laplacian_features(graph)
    n = len(nodes)
    # Need n >= 5: _laplacian_features yields only n-2 columns for small graphs,
    # and sklearn's PCA-init t-SNE requires n_components (3) <= n_features.
    if n < 5:
        return kamada_kawai_positions_3d(graph)
    embedding = _tsne(3, n).fit_transform(features)
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
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="umap")
        embedding = _umap(3, n).fit_transform(dist)
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
        kk_graph = _kk_distance_graph(graph)
        start = nx.random_layout(kk_graph, dim=3, seed=KK_SEED_3D)
        return nx.kamada_kawai_layout(kk_graph, pos=start, weight="weight", scale=KK_SCALE, dim=3)


def forceatlas2_positions_3d(
    graph: nx.DiGraph, initial_pos: dict, iterations: int = 10
) -> dict[str, tuple[float, float, float]]:
    """Run ForceAtlas2 in 3D on *graph* starting from *initial_pos*.

    Barnes-Hut optimisation is disabled because it is 2D-only; the vectorised
    O(n²) back-end is used instead.
    """
    return _build_forceatlas2(dim=3).forceatlas2_networkx_layout(
        _fa2_graph(graph), pos=initial_pos, iterations=iterations, weight_attr=FA2_WEIGHT_ATTR
    )

import re

VALID_MEASURES: frozenset[str] = frozenset(
    {
        "PAGERANK",
        "HITSHUB",
        "HITSAUTH",
        "BETWEENNESS",
        "FLOWBETWEENNESS",
        "INDEGCENTRALITY",
        "OUTDEGCENTRALITY",
        "HARMONICCENTRALITY",
        "KATZ",
        "CLOSENESS",
        "BURTCONSTRAINT",
        "AMPLIFICATION",
        "CONTENTORIGINALITY",
        "SPREADING",
        "EGODENSITY",
    }
)

_BRIDGING_RE = re.compile(r"^BRIDGING(?:\(([A-Z]+)\))?$")
_BRIDGING_DEFAULT_STRATEGY = "LEIDEN"

ALL_MEASURES: list[str] = [*sorted(VALID_MEASURES), "BRIDGING"]

VALID_NETWORK_STAT_GROUPS: frozenset[str] = frozenset(
    {
        "SIZE",
        "PATHS",
        "COHESION",
        "COMPONENTS",
        "DEGCORRELATION",
        "CENTRALIZATION",
        "CONTENT",
    }
)
ALL_NETWORK_STAT_GROUPS: list[str] = sorted(VALID_NETWORK_STAT_GROUPS)

ALL_STRATEGIES: list[str] = [
    "ORGANIZATION",
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM_COARSE",
    "LEIDEN_CPM_FINE",
    "LOUVAIN",
    "KCORE",
    "INFOMAP",
    "INFOMAP_MEMORY",
    "MCL",
    "WALKTRAP",
    "WEAKCC",
    "STRONGCC",
]

# Dispatch table: (settings key, progress label, apply function name)
# HITS and BRIDGING are handled separately because they have non-standard signatures.
MEASURE_STEPS: list[tuple[str, str, str]] = [
    ("PAGERANK", "pagerank", "apply_pagerank"),
    ("BETWEENNESS", "betweenness centrality", "apply_betweenness_centrality"),
    ("FLOWBETWEENNESS", "flow betweenness centrality", "apply_flow_betweenness_centrality"),
    ("INDEGCENTRALITY", "in-degree centrality", "apply_in_degree_centrality"),
    ("OUTDEGCENTRALITY", "out-degree centrality", "apply_out_degree_centrality"),
    ("HARMONICCENTRALITY", "harmonic centrality", "apply_harmonic_centrality"),
    ("KATZ", "Katz centrality", "apply_katz_centrality"),
    ("CLOSENESS", "closeness centrality", "apply_closeness_centrality"),
    ("BURTCONSTRAINT", "Burt's constraint", "apply_burt_constraint"),
    ("EGODENSITY", "ego network density", "apply_ego_network_density"),
]


def is_valid_measure(token: str) -> bool:
    return token in VALID_MEASURES or bool(_BRIDGING_RE.match(token))


def find_bridging_token(network_measures: list[str]) -> str | None:
    return next((m for m in network_measures if _BRIDGING_RE.match(m)), None)


def bridging_strategy(token: str) -> str:
    """Return the community strategy encoded in a BRIDGING token (defaults to LEIDEN)."""
    m = _BRIDGING_RE.match(token)
    return (m.group(1) or _BRIDGING_DEFAULT_STRATEGY) if m else _BRIDGING_DEFAULT_STRATEGY

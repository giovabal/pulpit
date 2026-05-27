import re

VALID_MEASURES: frozenset[str] = frozenset(
    {
        "PAGERANK",
        "HITSHUB",
        "HITSAUTH",
        "BETWEENNESS",
        "BRIDGINGCENTRALITY",
        "INDEGCENTRALITY",
        "OUTDEGCENTRALITY",
        "HARMONICCENTRALITY",
        "BURTCONSTRAINT",
        "AMPLIFICATION",
        "CONTENTORIGINALITY",
        "DIFFUSIONLAG",
        "SPREADING",
        "LOCALCLUSTERING",
        "CORENESS",
        "TROPHICLEVEL",
        "MODULEROLE",
    }
)

# [A-Z_]+ — underscore required so multi-word strategies like LEIDEN_DIRECTED
# or LEIDEN_CPM_COARSE can be passed as a bridging basis.  Defaults to
# LEIDEN_DIRECTED because the directed null model respects citation direction,
# matching what a brokerage-flavoured measure on a directed graph is asking.
_BRIDGING_RE = re.compile(r"^BRIDGING(?:\(([A-Z_]+)\))?$")
_BRIDGING_DEFAULT_STRATEGY = "LEIDEN_DIRECTED"

ALL_MEASURES: list[str] = [*sorted(VALID_MEASURES), "BRIDGING"]

# Node-attribute keys that are genuine centrality indices — the only measures for
# which a Freeman-style centralization (score concentration around the max) is
# meaningful. Excludes audience/activity attributes (fans, messages_count),
# local coefficients (burt_constraint, local_clustering), positional/structural
# coordinates with no star-based maximum (coreness, trophic_level, within_module_z),
# and behavioural metrics (amplification_factor, content_originality,
# diffusion_lag, spreading_efficiency). The weighted in/out *strength* columns
# (in_deg, out_deg) are also excluded: strength has no star-based theoretical
# maximum, so the generic (n−1)·C_max normaliser is too loose to be a useful
# Freeman approximation. The unweighted, normalised in_degree_centrality /
# out_degree_centrality (for which the star bound is exact) stay in.
CENTRALITY_MEASURE_KEYS: frozenset[str] = frozenset(
    {
        "pagerank",
        "hits_hub",
        "hits_authority",
        "betweenness",
        "in_degree_centrality",
        "out_degree_centrality",
        "harmonic_centrality",
        "bridging_centrality",
        "community_bridging",
    }
)

# Node-attribute keys that describe how a channel *behaves* (originate vs amplify,
# fast vs slow, narrow vs wide) plus its audience/activity volume — the feature set
# for the behavioural-equivalence matrix. Each is included only when actually computed.
BEHAVIOURAL_MEASURE_KEYS: frozenset[str] = frozenset(
    {
        "amplification_factor",
        "content_originality",
        "diffusion_lag",
        "spreading_efficiency",
        "fans",
        "messages_count",
    }
)

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
    "LABELPROPAGATION",
    "KCORE",
    "INFOMAP",
    "INFOMAP_MEMORY",
    "MCL",
    "WALKTRAP",
    "WEAKCC",
    "STRONGCC",
]

# Dispatch table: (settings key, progress label, apply function name)
# HITS, BRIDGINGCENTRALITY (Hwang, shares betweenness), BRIDGING (community bridging) and
# MODULEROLE (Guimerà-Amaral role) are handled separately: the last two need a community
# partition basis, and all have non-standard signatures.
MEASURE_STEPS: list[tuple[str, str, str]] = [
    ("PAGERANK", "pagerank", "apply_pagerank"),
    ("BETWEENNESS", "betweenness centrality", "apply_betweenness_centrality"),
    ("INDEGCENTRALITY", "in-degree centrality", "apply_in_degree_centrality"),
    ("OUTDEGCENTRALITY", "out-degree centrality", "apply_out_degree_centrality"),
    ("HARMONICCENTRALITY", "harmonic centrality", "apply_harmonic_centrality"),
    ("BURTCONSTRAINT", "Burt's constraint", "apply_burt_constraint"),
    ("LOCALCLUSTERING", "local clustering", "apply_local_clustering"),
    ("CORENESS", "k-core coreness", "apply_coreness"),
    ("TROPHICLEVEL", "trophic level", "apply_trophic_level"),
]


def is_valid_measure(token: str) -> bool:
    return token in VALID_MEASURES or bool(_BRIDGING_RE.match(token))


def find_bridging_token(network_measures: list[str]) -> str | None:
    return next((m for m in network_measures if _BRIDGING_RE.match(m)), None)


def bridging_strategy(token: str) -> str:
    """Return the community strategy encoded in a BRIDGING token (defaults to LEIDEN_DIRECTED)."""
    m = _BRIDGING_RE.match(token)
    return (m.group(1) or _BRIDGING_DEFAULT_STRATEGY) if m else _BRIDGING_DEFAULT_STRATEGY

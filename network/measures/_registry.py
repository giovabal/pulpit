import re

from network.tokens import (
    TokenInstance,
    TokenParam,
    TokenSpec,
    base_keys_for,
    canonical_key,
    parse_tokens,
)

# Back-compat aliases: measures were the first user of the generic token machinery, so the
# ``Measure*`` names are kept as thin aliases of the shared ``Token*`` primitives.
MeasureParam = TokenParam
MeasureSpec = TokenSpec

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
        "COLLECTIVEINFLUENCE",
        "TROPHICLEVEL",
        "MODULEROLE",
        "BROKERAGEROLES",
    }
)

# [A-Z_]+ — underscore required so multi-word strategies like LEIDEN_DIRECTED
# or LEIDEN_CPM can be passed as a bridging basis.  Defaults to
# LEIDEN_DIRECTED because the directed null model respects citation direction,
# matching what a brokerage-flavoured measure on a directed graph is asking.
_BRIDGING_RE = re.compile(r"^BRIDGING(?:\(([A-Z_]+)\))?$")
_BRIDGING_DEFAULT_STRATEGY = "LEIDEN_DIRECTED"

ALL_MEASURES: list[str] = [*sorted(VALID_MEASURES), "BRIDGING"]

# Node-attribute keys that are genuine centrality indices — the only measures for
# which a Freeman-style centralization (score concentration around the max) is
# meaningful. Excludes audience/activity attributes (fans, messages_count),
# local coefficients (burt_constraint, local_clustering), positional/structural
# coordinates with no star-based maximum (coreness, collective_influence,
# trophic_level, within_module_z, brokerage_total), and behavioural metrics
# (amplification_factor, content_originality,
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

# Community-strategy names offered as a measure "basis" (BRIDGING / MODULEROLE / BROKERAGEROLES).
# Must mirror community.VALID_STRATEGIES — a guard test enforces it. Kept here (rather than imported
# from network.community) so importing measures stays free of the heavy igraph/leidenalg/infomap deps.
ALL_STRATEGIES: list[str] = [
    "ORGANIZATION",
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM",
    "LABELPROPAGATION",
    "KCORE",
    "INFOMAP",
    "INFOMAP_MEMORY",
    "MCL",
    "WALKTRAP",
    "STRONGCC",
]

# Dispatch table: (settings key, progress label, apply function name)
# HITS, BRIDGINGCENTRALITY (Hwang, shares betweenness), BRIDGING (community bridging) and
# MODULEROLE / BROKERAGEROLES (Guimerà-Amaral role; Gould-Fernandez brokerage census) are
# handled separately: the partition-based ones need a community basis, and all have
# non-standard signatures.
MEASURE_STEPS: list[tuple[str, str, str]] = [
    ("PAGERANK", "pagerank", "apply_pagerank"),
    ("BETWEENNESS", "betweenness centrality", "apply_betweenness_centrality"),
    ("INDEGCENTRALITY", "in-degree centrality", "apply_in_degree_centrality"),
    ("OUTDEGCENTRALITY", "out-degree centrality", "apply_out_degree_centrality"),
    ("HARMONICCENTRALITY", "harmonic centrality", "apply_harmonic_centrality"),
    ("BURTCONSTRAINT", "Burt's constraint", "apply_burt_constraint"),
    ("LOCALCLUSTERING", "local clustering", "apply_local_clustering"),
    ("CORENESS", "k-core coreness", "apply_coreness"),
    ("COLLECTIVEINFLUENCE", "collective influence", "apply_collective_influence"),
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


# ── Parameterised measures & measure instances ────────────────────────────────
#
# A handful of measures take tunable parameters and may therefore be requested *more than once*
# with different settings (e.g. SPREADING(runs=200) alongside SPREADING(runs=2000)). The rest are
# drop-once. The generic machinery in ``network.tokens`` turns the comma-separated ``--measures``
# value into an ordered list of MeasureInstance objects, each carrying its own resolved parameters;
# every instance maps to a distinct, parameter-suffixed set of node-attribute keys so two instances
# of the same measure never overwrite each other's column.

# Gould-Fernandez brokerage role-count node keys (the categorical census companions of the
# numeric ``brokerage_total`` measure). Mirrors ``_GF_ROLE_KEYS`` in ``_centrality`` and
# ``_GF_COUNT_KEYS`` in ``exporter``; kept here as the source of truth for the aux-key inventory.
_GF_COUNT_KEYS: tuple[str, ...] = (
    "brokerage_coordinator",
    "brokerage_gatekeeper",
    "brokerage_representative",
    "brokerage_consultant",
    "brokerage_liaison",
)
_GF_COUNT_LABELS: tuple[str, ...] = ("Coordinator", "Gatekeeper", "Representative", "Consultant", "Liaison")


def _basis_param(default: str) -> MeasureParam:
    return MeasureParam(
        "basis",
        "enum",
        default,
        choices=tuple(ALL_STRATEGIES),
        label="Community basis",
        help="Community partition the measure is read against; must also be in --community-strategies.",
    )


# The five parameterised measures, in canonical display order. Everything else is drop-once.
PARAMETERISED_MEASURES: dict[str, MeasureSpec] = {
    "SPREADING": MeasureSpec(
        "SPREADING",
        "Spreading Efficiency",
        params=(MeasureParam("runs", "int", 200, minimum=1, label="Runs", help="Monte-Carlo SIR runs per node."),),
        primary_keys=("spreading_efficiency",),
    ),
    "DIFFUSIONLAG": MeasureSpec(
        "DIFFUSIONLAG",
        "Diffusion Lag",
        params=(
            MeasureParam(
                "window",
                "int",
                30,
                minimum=0,
                label="Window (days)",
                help="Reaction window in days; 0 disables the window.",
            ),
        ),
        primary_keys=("diffusion_lag",),
    ),
    "BRIDGING": MeasureSpec(
        "BRIDGING",
        "Community Bridging",
        params=(_basis_param(_BRIDGING_DEFAULT_STRATEGY),),
        primary_keys=("community_bridging",),
    ),
    "MODULEROLE": MeasureSpec(
        "MODULEROLE",
        "Module Role",
        params=(_basis_param(""),),
        primary_keys=("within_module_z",),
        aux_keys=("module_role",),
    ),
    "BROKERAGEROLES": MeasureSpec(
        "BROKERAGEROLES",
        "Brokerage Roles",
        params=(_basis_param(""),),
        primary_keys=("brokerage_total",),
        aux_keys=("brokerage_role", *_GF_COUNT_KEYS),
    ),
}

# Base node-attribute keys owned by a parameterised measure (primary + aux), longest first so
# canonical_measure_key strips the most specific base before a shorter prefix can match.
_PARAM_BASE_KEYS: tuple[str, ...] = base_keys_for(PARAMETERISED_MEASURES)


class MeasureInstance(TokenInstance):
    """One requested measure with its resolved parameters.

    Thin :class:`~network.tokens.TokenInstance` subclass that keeps the ``measure`` accessor used
    throughout the pipeline and resolves its :class:`MeasureSpec` from ``PARAMETERISED_MEASURES``.
    """

    @property
    def measure(self) -> str:
        return self.name

    @property
    def spec(self) -> "MeasureSpec | None":
        return PARAMETERISED_MEASURES.get(self.name)


KNOWN_MEASURE_TOKENS: frozenset[str] = VALID_MEASURES | {"BRIDGING"}


def parse_measures(
    tokens: list[str],
    *,
    defaults: dict[str, dict[str, object]] | None = None,
) -> list[MeasureInstance]:
    """Parse ``--measures`` tokens into an ordered, de-duplicated list of MeasureInstance.

    ``ALL`` expands to every measure with default parameters. ``defaults`` supplies per-measure
    parameter overrides for omitted values (the command passes the global ``--spreading-runs`` /
    ``--diffusion-window`` so a bare ``SPREADING`` uses them).

    Raises ``ValueError`` on an unknown measure, an unknown/ill-typed/out-of-range parameter,
    parameters on a drop-once measure, a repeated drop-once measure, or two instances of the same
    measure with identical parameters.
    """
    return parse_tokens(
        tokens,
        registry=PARAMETERISED_MEASURES,
        known_tokens=KNOWN_MEASURE_TOKENS,
        all_tokens=ALL_MEASURES,
        instance_cls=MeasureInstance,
        defaults=defaults,
        noun="measure",
    )


def canonical_measure_key(key: str) -> str:
    """Strip a parameter suffix back to the base measure key (``spreading_efficiency_runs_200``
    → ``spreading_efficiency``). Non-parameterised keys are returned unchanged."""
    return canonical_key(key, _PARAM_BASE_KEYS)


def role_companions(primary_key: str) -> "dict | None":
    """Categorical companion columns for a role-measure's numeric key (suffix-aware).

    Given ``within_module_z[...suffix]`` or ``brokerage_total[...suffix]``, return the matching
    ``module_role`` / ``brokerage_role`` (and brokerage count) keys carrying the *same* suffix,
    so each instance's companions are disambiguated alongside its numeric column. Returns
    ``None`` for any other key.
    """
    base = canonical_measure_key(primary_key)
    suffix = primary_key[len(base) :]
    if base == "within_module_z":
        return {"role_key": "module_role" + suffix, "role_label": "Module role", "count_keys": [], "count_labels": []}
    if base == "brokerage_total":
        return {
            "role_key": "brokerage_role" + suffix,
            "role_label": "Brokerage role",
            "count_keys": [k + suffix for k in _GF_COUNT_KEYS],
            "count_labels": list(_GF_COUNT_LABELS),
        }
    return None

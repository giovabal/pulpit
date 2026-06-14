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
        "INDEGCENTRALITY",
        "OUTDEGCENTRALITY",
        "BURTCONSTRAINT",
        "AMPLIFICATION",
        "CONTENTORIGINALITY",
        "DIFFUSIONLAG",
        "LOCALCLUSTERING",
        "MODULEROLE",
    }
)

ALL_MEASURES: list[str] = sorted(VALID_MEASURES)

# Node-attribute keys that are genuine centrality indices — the only measures for
# which a Freeman-style centralization (score concentration around the max) is
# meaningful. Excludes audience/activity attributes (fans, messages_count), local
# coefficients (burt_constraint, local_clustering), the within-module z-score
# (within_module_z, no star-based maximum), and behavioural metrics
# (amplification_factor, content_originality, diffusion_lag). The weighted in/out
# *strength* columns (in_deg, out_deg) are also excluded: strength has no
# star-based theoretical maximum, so the generic (n−1)·C_max normaliser is too
# loose to be a useful Freeman approximation. The unweighted, normalised
# in_degree_centrality / out_degree_centrality (for which the star bound is exact)
# stay in.
CENTRALITY_MEASURE_KEYS: frozenset[str] = frozenset(
    {
        "pagerank",
        "hits_hub",
        "hits_authority",
        "in_degree_centrality",
        "out_degree_centrality",
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

# Static community-strategy names offered as a measure "basis" (MODULEROLE). Must mirror
# community.VALID_STRATEGIES — a guard test enforces it. Kept here (rather than imported
# from network.community) so importing measures stays free of the heavy igraph/leidenalg deps.
# The dynamic ``LABELGROUP<id>`` metadata partitions are also valid bases but, being DB-keyed,
# are not enumerated here — the ``basis`` param is free-form (``str``) and validated against the
# actually-selected --community-strategies at compute time.
ALL_STRATEGIES: list[str] = [
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM",
    "LOUVAIN",
    "LABELPROPAGATION",
    "KCORE",
    "SBM",
]

# Dispatch table: (settings key, progress label, apply function name)
# HITS and MODULEROLE (Guimerà-Amaral within-module role) are handled separately: the
# partition-based MODULEROLE needs a community basis, and both have non-standard signatures.
MEASURE_STEPS: list[tuple[str, str, str]] = [
    ("PAGERANK", "pagerank", "apply_pagerank"),
    ("INDEGCENTRALITY", "in-degree centrality", "apply_in_degree_centrality"),
    ("OUTDEGCENTRALITY", "out-degree centrality", "apply_out_degree_centrality"),
    ("BURTCONSTRAINT", "Burt's constraint", "apply_burt_constraint"),
    ("LOCALCLUSTERING", "local clustering", "apply_local_clustering"),
]


def is_valid_measure(token: str) -> bool:
    return token in VALID_MEASURES


# ── Parameterised measures & measure instances ────────────────────────────────
#
# A handful of measures take tunable parameters and may therefore be requested *more than once*
# with different settings (e.g. DIFFUSIONLAG(window=30) alongside DIFFUSIONLAG(window=90)). The
# rest are drop-once. The generic machinery in ``network.tokens`` turns the comma-separated
# ``--measures`` value into an ordered list of MeasureInstance objects, each carrying its own
# resolved parameters; every instance maps to a distinct, parameter-suffixed set of
# node-attribute keys so two instances of the same measure never overwrite each other's column.


def _basis_param(default: str) -> MeasureParam:
    return MeasureParam(
        "basis",
        "str",
        default,
        choices=tuple(ALL_STRATEGIES),  # UI hint only (str is not enum-validated); LABELGROUP<id> also valid
        label="Community basis",
        help="Community partition the measure is read against (a strategy name or LABELGROUP<id>); "
        "must also be in --community-strategies.",
    )


# The parameterised measures, in canonical display order. Everything else is drop-once.
PARAMETERISED_MEASURES: dict[str, MeasureSpec] = {
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
    "MODULEROLE": MeasureSpec(
        "MODULEROLE",
        "Module Role",
        params=(_basis_param(""),),
        primary_keys=("within_module_z",),
        aux_keys=("module_role",),
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


KNOWN_MEASURE_TOKENS: frozenset[str] = VALID_MEASURES


def parse_measures(
    tokens: list[str],
    *,
    defaults: dict[str, dict[str, object]] | None = None,
) -> list[MeasureInstance]:
    """Parse ``--measures`` tokens into an ordered, de-duplicated list of MeasureInstance.

    ``ALL`` expands to every measure with default parameters. ``defaults`` supplies per-measure
    parameter overrides for omitted values (the command passes the global ``--diffusion-window``
    so a bare ``DIFFUSIONLAG`` uses it).

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
    """Strip a parameter suffix back to the base measure key (``within_module_z_basis_leiden``
    → ``within_module_z``). Non-parameterised keys are returned unchanged."""
    return canonical_key(key, _PARAM_BASE_KEYS)


def role_companions(primary_key: str) -> "dict | None":
    """Categorical companion columns for a role-measure's numeric key (suffix-aware).

    Given ``within_module_z[...suffix]``, return the matching ``module_role`` key carrying the
    *same* suffix, so each instance's companion is disambiguated alongside its numeric column.
    Returns ``None`` for any other key.
    """
    base = canonical_measure_key(primary_key)
    suffix = primary_key[len(base) :]
    if base == "within_module_z":
        return {"role_key": "module_role" + suffix, "role_label": "Module role", "count_keys": [], "count_labels": []}
    return None

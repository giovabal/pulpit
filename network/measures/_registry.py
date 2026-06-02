import re
from dataclasses import dataclass

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

ALL_STRATEGIES: list[str] = [
    "ORGANIZATION",
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM_COARSE",
    "LEIDEN_CPM_FINE",
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
# A handful of measures take tunable parameters and may therefore be requested
# *more than once* with different settings (e.g. SPREADING(runs=200) alongside
# SPREADING(runs=2000)). The rest are drop-once. The model below turns the
# comma-separated ``--measures`` value into an ordered list of MeasureInstance
# objects, each carrying its own resolved parameters; every instance maps to a
# distinct, parameter-suffixed set of node-attribute keys so two instances of the
# same measure never overwrite each other's column.
#
# Token grammar (keyword args in parentheses; the historical positional
# ``BRIDGING(LEIDEN_DIRECTED)`` form is still accepted):
#     PAGERANK                      # drop-once, no params
#     SPREADING(runs=2000)          # keyword
#     DIFFUSIONLAG(window=60)
#     BRIDGING(basis=LEIDEN)        # keyword
#     BRIDGING(LEIDEN)              # legacy positional → basis=LEIDEN

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


@dataclass(frozen=True)
class MeasureParam:
    """One tunable parameter of a measure.

    ``kind`` is ``"int"``, ``"float"`` or ``"enum"``. ``default`` is used when the token
    omits the parameter (the command may override numeric defaults from the global
    ``--spreading-runs`` / ``--diffusion-window`` flags). An empty-string default on an
    ``enum`` means "auto-resolve at compute time" (the MODULEROLE / BROKERAGEROLES basis).
    ``choices`` lists the valid enum values (uppercase, matching ``ALL_STRATEGIES``).
    """

    name: str
    kind: str
    default: object
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    label: str = ""
    help: str = ""


@dataclass(frozen=True)
class MeasureSpec:
    """Declarative description of a parameterised measure.

    ``primary_keys`` are the numeric node-attribute keys that land in ``measures_labels``
    (sortable table columns); ``aux_keys`` are categorical / count companions written onto
    the node but surfaced separately (e.g. ``module_role``, the brokerage role counts).
    Both are the *base* keys — the per-instance parameter suffix is appended at compute time.
    """

    key: str
    label: str
    params: tuple[MeasureParam, ...] = ()
    primary_keys: tuple[str, ...] = ()
    aux_keys: tuple[str, ...] = ()


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
_PARAM_BASE_KEYS: tuple[str, ...] = tuple(
    sorted(
        {bk for spec in PARAMETERISED_MEASURES.values() for bk in (*spec.primary_keys, *spec.aux_keys)},
        key=len,
        reverse=True,
    )
)


def _coerce_value(param: MeasureParam, raw: str) -> object:
    """Validate and convert a raw token value for ``param``. Raises ValueError on bad input."""
    raw = raw.strip()
    if param.kind == "enum":
        val = raw.upper()
        if val not in param.choices:
            raise ValueError(f"{param.name}={raw!r} is not a valid community strategy. Choose from {param.choices}.")
        return val
    if param.kind in ("int", "float"):
        try:
            num = int(raw) if param.kind == "int" else float(raw)
        except ValueError as exc:
            raise ValueError(f"{param.name}={raw!r} is not a valid {param.kind}.") from exc
        if param.minimum is not None and num < param.minimum:
            raise ValueError(f"{param.name}={num} is below the minimum {param.minimum}.")
        if param.maximum is not None and num > param.maximum:
            raise ValueError(f"{param.name}={num} is above the maximum {param.maximum}.")
        return num
    raise ValueError(f"Unknown parameter kind {param.kind!r}.")


# Case-insensitive: the CLI/config path upper-cases the whole token (see _parse_csv), so a
# keyword like ``runs=2000`` arrives as ``RUNS=2000``; the measure name and parameter names are
# normalised (upper / lower) after the match so either spelling round-trips.
_TOKEN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z_]*)\s*(?:\(\s*(.*?)\s*\))?\s*$")


@dataclass(frozen=True)
class MeasureInstance:
    """One requested measure with its resolved parameters.

    ``params`` is an ordered tuple of ``(name, value)`` pairs (spec order), making the
    instance hashable so duplicates can be detected. Drop-once measures carry ``()``.
    """

    measure: str
    params: tuple[tuple[str, object], ...] = ()

    @property
    def params_dict(self) -> dict[str, object]:
        return dict(self.params)

    @property
    def spec(self) -> "MeasureSpec | None":
        return PARAMETERISED_MEASURES.get(self.measure)

    def _visible_params(self) -> list[tuple[str, object]]:
        # Skip empty/auto values (e.g. an unresolved MODULEROLE basis) — they neither appear in
        # the token nor contribute to the suffix.
        return [(k, v) for k, v in self.params if v not in (None, "")]

    def token(self) -> str:
        vis = self._visible_params()
        if not vis:
            return self.measure
        return f"{self.measure}(" + ",".join(f"{k}={v}" for k, v in vis) + ")"

    def suffix(self) -> str:
        """Parameter suffix appended to every node key this instance writes (``""`` if none)."""
        vis = self._visible_params()
        if not vis:
            return ""
        return "_" + "_".join(f"{k}_{str(v).lower()}" for k, v in vis)

    def label_annotation(self) -> str:
        """Human-readable parameter annotation for table/column labels, e.g. `` (runs=2000)``."""
        vis = self._visible_params()
        if not vis:
            return ""
        parts = [f"{k}={str(v).lower() if isinstance(v, str) else v}" for k, v in vis]
        return " (" + ", ".join(parts) + ")"

    def key_for(self, base_key: str) -> str:
        return base_key + self.suffix()

    def resolved_with(self, **overrides: object) -> "MeasureInstance":
        """Return a copy with some parameter values replaced (used to pin an auto-resolved basis)."""
        merged = dict(self.params)
        merged.update(overrides)
        spec = self.spec
        order = [p.name for p in spec.params] if spec else list(merged)
        return MeasureInstance(self.measure, tuple((k, merged[k]) for k in order if k in merged))


KNOWN_MEASURE_TOKENS: frozenset[str] = VALID_MEASURES | {"BRIDGING"}


def parse_measures(
    tokens: list[str],
    *,
    defaults: dict[str, dict[str, object]] | None = None,
) -> list[MeasureInstance]:
    """Parse ``--measures`` tokens into an ordered, de-duplicated list of MeasureInstance.

    ``ALL`` expands to every measure with default parameters. ``defaults`` supplies
    per-measure parameter overrides for omitted values (the command passes the global
    ``--spreading-runs`` / ``--diffusion-window`` so a bare ``SPREADING`` uses them).

    Raises ``ValueError`` on an unknown measure, an unknown/ill-typed/out-of-range parameter,
    parameters on a drop-once measure, a repeated drop-once measure, or two instances of the
    same measure with identical parameters.
    """
    defaults = defaults or {}
    if any(t.strip().upper() == "ALL" for t in tokens):
        tokens = list(ALL_MEASURES)

    instances: list[MeasureInstance] = []
    seen: set[MeasureInstance] = set()
    for raw_token in tokens:
        token = raw_token.strip()
        if not token:
            continue
        m = _TOKEN_RE.match(token)
        if not m:
            raise ValueError(f"Could not parse measure token {raw_token!r}.")
        measure, argstr = m.group(1).upper(), (m.group(2) or "").strip()
        if measure not in KNOWN_MEASURE_TOKENS:
            valid = sorted(KNOWN_MEASURE_TOKENS) + ["ALL"]
            raise ValueError(f"Unknown measure {measure!r}. Choose from {valid}.")

        spec = PARAMETERISED_MEASURES.get(measure)
        if argstr and spec is None:
            raise ValueError(f"Measure {measure} takes no parameters, but got {argstr!r}.")

        if spec is None:
            instance = MeasureInstance(measure)
        else:
            values: dict[str, object] = {p.name: p.default for p in spec.params}
            values.update(defaults.get(measure, {}))
            for i, piece in enumerate([p for p in argstr.split(",") if p.strip()]):
                if "=" in piece:
                    name, raw = piece.split("=", 1)
                    name = name.strip().lower()  # tolerate the CLI/config upper-casing of tokens
                    param = next((p for p in spec.params if p.name == name), None)
                    if param is None:
                        raise ValueError(
                            f"{measure} has no parameter {name!r}. Valid: {[p.name for p in spec.params]}."
                        )
                else:  # positional → map to the i-th declared parameter (legacy BRIDGING(STRATEGY))
                    if i >= len(spec.params):
                        raise ValueError(f"{measure} accepts {len(spec.params)} positional parameter(s).")
                    param, raw = spec.params[i], piece
                values[param.name] = _coerce_value(param, str(raw))
            instance = MeasureInstance(measure, tuple((p.name, values[p.name]) for p in spec.params))

        if instance in seen:
            if spec is None:
                raise ValueError(f"Measure {measure} is listed more than once.")
            raise ValueError(f"Measure {instance.token()} is listed more than once with identical parameters.")
        seen.add(instance)
        instances.append(instance)
    return instances


def canonical_measure_key(key: str) -> str:
    """Strip a parameter suffix back to the base measure key (``spreading_efficiency_runs_200``
    → ``spreading_efficiency``). Non-parameterised keys are returned unchanged."""
    for base in _PARAM_BASE_KEYS:
        if key == base or key.startswith(base + "_"):
            return base
    return key


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

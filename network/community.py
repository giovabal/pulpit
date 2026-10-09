import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from itertools import combinations
from typing import Any

from django.utils.text import slugify

from network.parameters import FixedParameter
from network.tokens import TokenInstance, TokenParam, TokenSpec, base_keys_for, canonical_key, parse_tokens
from network.utils import tie_weight_key, to_undirected_sum
from webapp.models import Label, LabelGroup
from webapp.utils.colors import (
    DEFAULT_FALLBACK_COLOR,
    ColorTuple,
    expand_colors,
    palette_colors,
    parse_color,
    rgb_avg,
    rgb_to_hex,
)

import igraph as ig
import leidenalg
import networkx as nx

# Canonical ordered list of community-strategy names. Mirrors measures.ALL_STRATEGIES (which feeds
# the measure "basis" choices); a guard test keeps the two in sync. LEIDEN_CPM is a single
# parameterised strategy (its resolution γ is per-instance and it may be requested more than once).
# CONSENSUS is derived from
# the other selected strategies' partitions (dispatched after them; see detect_consensus).
ALL_STRATEGIES: list[str] = [
    "LEIDEN",
    "LEIDEN_DIRECTED",
    "LEIDEN_CPM",
    "LEIDEN_TEMPORAL",
    "LOUVAIN",
    "KCORE",
    "SBM",
    "SBM_ASSORTATIVE",
    "CONSENSUS",
]

# Strategies the ``ALL`` token does NOT expand to. LEIDEN_TEMPORAL hard-requires a year timeline
# (``--timeline-step year``), so folding it into ALL would break every non-timeline ``ALL`` run;
# it must be requested explicitly.
EXCLUDED_FROM_ALL: frozenset[str] = frozenset({"LEIDEN_TEMPORAL"})
# Every static strategy is an algorithm; the only *metadata* partitions are the dynamic, DB-keyed
# ``LABELGROUP<id>`` strategies (one per partition LabelGroup). ``is_metadata_strategy`` distinguishes them.
COMMUNITY_ALGORITHMS: frozenset[str] = frozenset(ALL_STRATEGIES)
VALID_STRATEGIES: frozenset[str] = frozenset(ALL_STRATEGIES)

_LABELGROUP_RE = re.compile(r"^LABELGROUP(\d+)$")


def labelgroup_id(strategy_name: str) -> int | None:
    """The LabelGroup pk a ``LABELGROUP<id>`` strategy token selects, or ``None`` for algorithms."""
    match = _LABELGROUP_RE.match(strategy_name.upper())
    return int(match.group(1)) if match else None


def is_metadata_strategy(strategy_name: str) -> bool:
    """Whether a strategy is a manual ``LABELGROUP<id>`` partition rather than an algorithm."""
    return labelgroup_id(strategy_name) is not None


def labelgroup_strategy_tokens() -> list[str]:
    """``LABELGROUP<id>`` tokens for every partition LabelGroup, in pk order (DB lookup)."""
    return [f"LABELGROUP{pk}" for pk in LabelGroup.objects.filter(is_partition=True).values_list("pk", flat=True)]


def labelgroup_display_labels() -> dict[str, str]:
    """Map each partition LabelGroup's lowercase ``labelgroup<id>`` partition key to its display name.

    Injected into the static viewer as ``window.STRATEGY_LABELS`` so a label-group colour-by option
    shows the analyst's group name (e.g. "Region") rather than the title-cased key ("Labelgroup3").
    The key matches ``StrategyInstance.key`` for a ``LABELGROUP<id>`` token (``name.lower()``).
    """
    return {
        f"labelgroup{pk}": name for pk, name in LabelGroup.objects.filter(is_partition=True).values_list("pk", "name")
    }


# Tag appended to a label group's name wherever it is offered as a community/strategy *option* outside
# its own picker — the MODULEROLE basis select, the table / CSV / GEXF export columns, and the viewer's
# colour-by selector (mirrored by ``strategy_label`` in webapp_engine/map/js/labels.js). Inside the
# Operations "Label groups" fieldset the bare name is shown, since the context is already unambiguous.
CUSTOM_LABEL_SUFFIX = " [custom label]"


def custom_label_display(name: str) -> str:
    """A label-group name tagged as a manual ("custom") partition, for display outside its own picker."""
    return f"{name}{CUSTOM_LABEL_SUFFIX}"


# Strategies whose partition is optimised (or computed) on the UNDIRECTED projection
# of the citation graph. Their reported modularity should use the undirected null
# model (k_i·k_j / 2m), matching what they actually optimised — not the directed
# null model (k_out_i·k_in_j / m). Keys are the lowercased community keys.
# Everything else (leiden_directed, organization) is reported with directed
# modularity, the form it was built against.
# Keys are *canonical* (parameter-suffix-stripped) strategy keys — membership is tested via
# canonical_strategy_key(), so every LEIDEN_CPM instance (whatever its resolution) is covered.
# CONSENSUS is optimised on the (undirected) co-assignment graph, not the citation graph;
# its modularity is reported against the undirected projection, the closest null. LEIDEN_TEMPORAL
# and SBM_ASSORTATIVE are both fitted on the undirected W+Wᵀ projection (per-year slices for the
# former), so they report against the undirected null too.
UNDIRECTED_BASIS_STRATEGIES: frozenset[str] = frozenset(
    {"leiden", "leiden_cpm", "leiden_temporal", "louvain", "kcore", "sbm_assortative", "consensus"}
)

# Human-readable labels for the strategy keys above — mirrors STRATEGY_LABELS in
# webapp_engine/map/js/labels.js so the same display text shows up in browser
# pages and in the server-side Operations panel.
COMMUNITY_STRATEGY_LABELS: dict[str, str] = {
    "LEIDEN": "Leiden",
    "LEIDEN_DIRECTED": "Leiden directed",
    "LEIDEN_CPM": "Leiden CPM",
    "LEIDEN_TEMPORAL": "Leiden temporal",
    "LOUVAIN": "Louvain",
    "KCORE": "K-core",
    "SBM": "Stochastic block model",
    "SBM_ASSORTATIVE": "Assortative SBM",
    "CONSENSUS": "Consensus",
}


def consensus_eligible(strategy_name: str) -> bool:
    """Whether a strategy's partition may feed consensus aggregation (the CONSENSUS strategy
    and the consensus-matrix balloon plot alike).

    Eligible = a genuine algorithmic community detection *of the graph under analysis*: not a
    manual ``LABELGROUP<id>`` partition, not the KCORE shell decomposition (a connectivity
    hierarchy, not a community detection), not CONSENSUS itself (a derived partition must not
    feed its own input — nor double-count in the matrix it summarises), and not LEIDEN_TEMPORAL
    (its full-range column is a plurality summary across timeline slices and its per-year
    partitions are deliberately coupled to neighbouring years — neither is an independent
    detection of the graph being aggregated). Mirrored by ``_consensusExcluded`` in
    webapp_engine/map/js/consensus_matrix.js.
    """
    name = strategy_name.upper()
    return name not in {"KCORE", "CONSENSUS", "LEIDEN_TEMPORAL"} and not is_metadata_strategy(name)


# ── Parameterised community strategies & strategy instances ────────────────────
#
# Most strategies are parameter-free, but LEIDEN_CPM takes a tunable knob and may be requested more
# than once with different settings — e.g. LEIDEN_CPM(resolution=0.01) alongside
# LEIDEN_CPM(resolution=0.05). The shared token machinery (network.tokens) turns the comma-separated
# --community-strategies value into an ordered list of StrategyInstance objects; each instance maps to
# a distinct, parameter-suffixed partition key (``StrategyInstance.key``) so two instances of one
# strategy never overwrite each other's communities[...] entry. This mirrors the measures system.

StrategyParam = TokenParam
StrategySpec = TokenSpec

# LEIDEN_CPM / LEIDEN_TEMPORAL take no fixed default γ: an omitted ``resolution`` (empty default, the
# token machinery's "auto") resolves at compute time to the weighted edge density of the graph CPM
# runs on — CPM at the Reichardt–Bornholdt Erdős–Rényi null (see cpm_density_resolution).
SBM_DEFAULT_MODE = "NESTED"
#: Edge-covariate model of an SBM token that omits ``weights``: empty = the binary (unweighted) fit.
SBM_DEFAULT_WEIGHTS = ""
#: Refinement of an SBM / SBM_ASSORTATIVE token that omits ``refine``: empty = the single point estimate.
SBM_DEFAULT_REFINE = ""
CONSENSUS_DEFAULT_THRESHOLD = 0.5
# Coupling ω of a LEIDEN_TEMPORAL token that omits ``interslice``: ω is relative — a multiple of the mean tie weight
# of the year slices (temporal_interslice_weight) — so 1.0 makes an identity link as strong as an average tie,
# whatever --edge-weight-strategy's units. Higher ω = smoother, more persistent communities across years, lower ω =
# each year re-partitioned nearly independently.
TEMPORAL_DEFAULT_INTERSLICE = 1.0

# Base key of the per-channel SBM assignment-confidence companion column written by
# SBM(refine=MCMC); the per-instance parameter suffix is appended at compute time
# (sbm_mode_nested_refine_mcmc → sbm_confidence_mode_nested_refine_mcmc).
SBM_CONFIDENCE_BASE_KEY = "sbm_confidence"

PARAMETERISED_STRATEGIES: dict[str, StrategySpec] = {
    "LEIDEN_CPM": StrategySpec(
        "LEIDEN_CPM",
        "Leiden CPM",
        params=(
            StrategyParam(
                "resolution",
                "float",
                "",
                minimum=0.0,
                label="Resolution γ",
                help="CPM resolution: a community is stable when its internal edge density exceeds γ. "
                "Empty (or auto) = the network's own weighted edge density, so communities are groups "
                "denser than the network as a whole (Reichardt & Bornholdt 2006) — unaffected by a uniform "
                "rescale of the weights. An explicit γ is an absolute density on the raw (un-rescaled) tie "
                "weights, in the units of --edge-weight-strategy: a binary edge density under NONE, a "
                "citation-share density under PARTIAL_*, a citation-count density under TOTAL. "
                "Lower = fewer, larger communities; higher = more, smaller ones.",
            ),
        ),
        primary_keys=("leiden_cpm",),
    ),
    "SBM": StrategySpec(
        "SBM",
        "Stochastic block model",
        params=(
            StrategyParam(
                "mode",
                "enum",
                SBM_DEFAULT_MODE,
                choices=("FLAT", "NESTED"),
                label="Mode",
                help="NESTED = nested SBM (Peixoto 2017), partition taken at the finest level — better "
                "model selection on large graphs. FLAT = single-level SBM. May be added once per mode.",
            ),
            StrategyParam(
                "weights",
                "enum",
                SBM_DEFAULT_WEIGHTS,
                choices=("POISSON", "EXPONENTIAL"),
                label="Weights",
                help="Edge-covariate model for a weighted SBM fit (Peixoto 2018). Empty = binary fit on the "
                "bare citation structure (the historical behaviour, invariant to --edge-weight-strategy). "
                "POISSON models weights as discrete counts — pair with --edge-weight-strategy TOTAL; "
                "EXPONENTIAL models them as positive reals — pair with the ratio-valued PARTIAL_* strategies.",
            ),
            StrategyParam(
                "refine",
                "enum",
                SBM_DEFAULT_REFINE,
                choices=("MCMC",),
                label="Refine",
                help="Empty = single minimum-description-length fit. MCMC equilibrates the fit and samples "
                "the posterior (Peixoto 2014; 2021), reporting each channel's most probable block plus a "
                "per-channel assignment-confidence column (share of posterior samples agreeing).",
            ),
        ),
        primary_keys=("sbm",),
        aux_keys=(SBM_CONFIDENCE_BASE_KEY,),
    ),
    "LEIDEN_TEMPORAL": StrategySpec(
        "LEIDEN_TEMPORAL",
        "Leiden temporal",
        params=(
            StrategyParam(
                "resolution",
                "float",
                "",
                minimum=0.0,
                label="Resolution γ",
                help="CPM resolution of each year slice, as in LEIDEN_CPM. Empty (or auto) = each slice's own "
                "weighted edge density (a per-slice null, as in Mucha et al. 2010); an explicit γ is one "
                "absolute density in the raw tie-weight units of --edge-weight-strategy, the same in every "
                "year. Lower = fewer, larger communities; higher = more, smaller ones.",
            ),
            StrategyParam(
                "interslice",
                "float",
                TEMPORAL_DEFAULT_INTERSLICE,
                minimum=0.0,
                label="Coupling ω",
                help="Weight of the identity link tying each channel to itself in adjacent years "
                "(Mucha et al. 2010), as a multiple of the year slices' mean tie weight: 1 = as strong as an "
                "average tie, whatever --edge-weight-strategy. 0 = years partitioned independently; higher = "
                "smoother, more persistent communities across the timeline.",
            ),
        ),
        primary_keys=("leiden_temporal",),
    ),
    "SBM_ASSORTATIVE": StrategySpec(
        "SBM_ASSORTATIVE",
        "Assortative SBM",
        params=(
            StrategyParam(
                "refine",
                "enum",
                SBM_DEFAULT_REFINE,
                choices=("MCMC",),
                label="Refine",
                help="Empty = single greedy fit. MCMC equilibrates the fit and samples the posterior, "
                "reporting each channel's most probable community plus a per-channel "
                "assignment-confidence column (share of posterior samples agreeing).",
            ),
        ),
        primary_keys=("sbm_assortative",),
    ),
    "CONSENSUS": StrategySpec(
        "CONSENSUS",
        "Consensus",
        params=(
            StrategyParam(
                "threshold",
                "float",
                CONSENSUS_DEFAULT_THRESHOLD,
                minimum=0.0,
                maximum=1.0,
                label="Threshold τ",
                help="Minimum share of the input partitions that must co-assign two channels for the "
                "pair to survive into the consensus graph (Lancichinetti & Fortunato 2012). "
                "0.5 = a majority of the algorithms agree; higher = stricter, smaller cores.",
            ),
        ),
        primary_keys=("consensus",),
    ),
}

# Base partition keys owned by a parameterised strategy, longest first — feeds canonical_strategy_key.
_STRATEGY_BASE_KEYS: tuple[str, ...] = base_keys_for(PARAMETERISED_STRATEGIES)


class StrategyInstance(TokenInstance):
    """One requested community strategy with its resolved parameters.

    Thin :class:`~network.tokens.TokenInstance` subclass exposing ``strategy`` (the name), its
    ``spec`` from ``PARAMETERISED_STRATEGIES``, and ``key`` — the parameter-suffixed node-attribute
    key under which this instance's partition lives in ``node['communities']`` (e.g.
    ``leiden_cpm_resolution_0_05``; just ``leiden_directed`` for parameter-free strategies).
    """

    @property
    def strategy(self) -> str:
        return self.name

    @property
    def spec(self) -> "StrategySpec | None":
        return PARAMETERISED_STRATEGIES.get(self.name)

    @property
    def key(self) -> str:
        return self.name.lower() + self.suffix()

    @property
    def label(self) -> str:
        gid = labelgroup_id(self.name)
        if gid is not None:
            group = LabelGroup.objects.filter(pk=gid).first()
            base = custom_label_display(group.name) if group else self.name
        else:
            base = COMMUNITY_STRATEGY_LABELS.get(self.name, self.name.title())
        return base + self.label_annotation()


def parse_strategies(
    tokens: list[str],
    *,
    defaults: dict[str, dict[str, object]] | None = None,
) -> list["StrategyInstance"]:
    """Parse ``--community-strategies`` tokens into ordered, de-duplicated StrategyInstance objects.

    ``ALL`` expands to every strategy with default parameters — including one ``LABELGROUP<id>`` per
    partition LabelGroup (queried fresh each call, so newly-added groups appear). ``defaults`` supplies
    per-strategy parameter overrides for omitted values (the command passes an explicitly given
    ``--leiden-cpm-resolution`` so a bare ``LEIDEN_CPM`` inherits it; without it a bare ``LEIDEN_CPM`` is
    auto — the network density, key ``leiden_cpm``). Raises ``ValueError`` on unknown
    strategies, bad/duplicate parameters — mirroring ``measures.parse_measures``.
    """
    labelgroup_tokens = labelgroup_strategy_tokens()
    return parse_tokens(
        tokens,
        registry=PARAMETERISED_STRATEGIES,
        known_tokens=VALID_STRATEGIES | set(labelgroup_tokens),
        # ALL expands to the metadata partitions first, then the
        # algorithms — minus the strategies that only work in specific run shapes (EXCLUDED_FROM_ALL:
        # LEIDEN_TEMPORAL needs a year timeline, so it must be requested explicitly).
        all_tokens=labelgroup_tokens + [s for s in ALL_STRATEGIES if s not in EXCLUDED_FROM_ALL],
        instance_cls=StrategyInstance,
        defaults=defaults,
        noun="strategy",
    )


def canonical_strategy_key(key: str) -> str:
    """Strip a parameter suffix back to the base strategy key (``leiden_cpm_resolution_0_05`` →
    ``leiden_cpm``). Parameter-free keys are returned unchanged."""
    return canonical_key(key, _STRATEGY_BASE_KEYS)


def strategy_display_label(key: str) -> str:
    """Human label for a partition key, e.g. ``leiden_cpm_resolution_0_05`` → ``Leiden CPM (resolution=0.05)``.

    Mirrors ``StrategyInstance.label`` but works from the bare node-attribute key (used by the static
    table/CSV writers, which only have the key). The base maps through ``COMMUNITY_STRATEGY_LABELS``; the
    parameter suffix is reconstructed from the spec's param names (the float value slug ``0_05`` reads
    back as ``0.05``). The JS mirror is ``strategy_label`` in ``webapp_engine/map/js/labels.js``.
    """
    gid = labelgroup_id(key)
    if gid is not None:
        group = LabelGroup.objects.filter(pk=gid).first()
        return custom_label_display(group.name) if group else key
    base = canonical_strategy_key(key)
    label = COMMUNITY_STRATEGY_LABELS.get(base.upper(), base.replace("_", " ").title())
    if key == base:
        return label
    spec = PARAMETERISED_STRATEGIES.get(base.upper())
    rest = key[len(base) + 1 :]  # drop "base_" → e.g. "mode_nested_weights_poisson"
    parts: list[str] = []
    params = list(spec.params) if spec else []
    for i, param in enumerate(params):
        prefix = f"{param.name}_"
        if not rest.startswith(prefix):
            continue  # omitted (empty-default) parameter — absent from the suffix
        value_part = rest[len(prefix) :]
        # The value runs until the next declared parameter's "_<name>_" boundary (suffix order is
        # spec order, so only later params can follow). Enum values carry no "_" and float slugs
        # are digits and "_", so a parameter-name boundary is unambiguous.
        cut = len(value_part)
        for later in params[i + 1 :]:
            pos = value_part.find(f"_{later.name}_")
            if pos != -1 and pos < cut:
                cut = pos
        raw = value_part[:cut]
        rest = value_part[cut + 1 :] if cut < len(value_part) else ""
        value = raw.replace("_", ".") if param.kind == "float" else raw
        parts.append(f"{param.name}={value}")
    return f"{label} ({', '.join(parts)})" if parts else label


def sbm_confidence_key(strategy_key: str) -> str:
    """Node-attribute key of the SBM assignment-confidence column for an SBM-family instance key.

    ``sbm_mode_nested_refine_mcmc`` → ``sbm_confidence_mode_nested_refine_mcmc``;
    ``sbm_assortative_refine_mcmc`` → ``sbm_confidence_assortative_refine_mcmc``. Only populated
    when the instance ran with ``refine=MCMC``; exporters probe the nodes for its presence.
    """
    return SBM_CONFIDENCE_BASE_KEY + strategy_key[len("sbm") :]


def sbm_confidence_display_label(strategy_key: str) -> str:
    """Human label for an SBM-family confidence column, e.g. ``SBM confidence (mode=nested, refine=mcmc)``
    or ``Assortative SBM confidence (refine=mcmc)``."""
    prefix = (
        "Assortative SBM confidence" if canonical_strategy_key(strategy_key) == "sbm_assortative" else "SBM confidence"
    )
    label = strategy_display_label(strategy_key)
    idx = label.find(" (")
    return prefix + (label[idx:] if idx != -1 else "")


type CommunityMap = dict[str, int]
type CommunityPalette = dict[int, ColorTuple]


def build_community_label(community_id: int | str, strategy: str) -> str:
    return slugify(f"{community_id}-{strategy}")


def normalize_community_map(community_map: CommunityMap) -> CommunityMap:
    community_counts = Counter(community_map.values())
    ordered = sorted(community_counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {community_id: index for index, (community_id, _) in enumerate(ordered, start=1)}
    return {node_id: remap[community_id] for node_id, community_id in community_map.items()}


def build_community_palette(
    community_map: CommunityMap,
    palette_name: str,
    *,
    reverse: bool = False,
) -> CommunityPalette:
    if not community_map:
        return {}
    total = max(community_map.values())
    source_colors = palette_colors(palette_name, reverse=reverse)
    colors = expand_colors(source_colors, total)
    return {
        index: parse_color(colors[index - 1]) if index <= len(colors) else DEFAULT_FALLBACK_COLOR
        for index in range(1, total + 1)
    }


def _merge_isolated_nodes(graph: nx.DiGraph, community_map: CommunityMap) -> CommunityMap:
    """Assign all isolated nodes (no edges) to the same community as the first isolated node."""
    isolated = sorted((node_id for node_id in graph.nodes() if graph.degree(node_id) == 0), key=str)
    if len(isolated) <= 1:
        return community_map
    target_community = community_map[isolated[0]]
    for node_id in isolated[1:]:
        community_map[node_id] = target_community
    return community_map


# ── Fixed parameters of the detectors ─────────────────────────────────────────
#
# Every value below is fixed in the code (not a run option) and is passed explicitly where it is used —
# library defaults included — so FIXED_PARAMETERS (written to the export's PARAMETERS.md) is read from
# the very values the detectors run with.

#: Seed of the first leidenalg optimisation (LEIDEN, LEIDEN_DIRECTED, LEIDEN_CPM, LEIDEN_TEMPORAL, CONSENSUS); run k
#: of a best-of-:data:`LEIDEN_RUNS` fit uses ``LEIDEN_SEED + k``.
LEIDEN_SEED = 0
#: Independent seeded Leiden optimisations per partition; the one with the highest quality is reported. Modularity
#: and CPM landscapes are degenerate — one run lands on one of many near-optimal, mutually dissimilar partitions
#: (Good, de Montjoye & Clauset 2010) — so a single seed reports an arbitrary one.
LEIDEN_RUNS = 50
#: Leiden iterations per optimisation: negative = iterate until an iteration no longer improves the partition.
LEIDEN_N_ITERATIONS = -1
#: Largest community leidenalg may form, in nodes — leidenalg's own default (0 = no limit).
LEIDEN_MAX_COMM_SIZE = 0
#: Modularity resolution γ of LEIDEN, LEIDEN_DIRECTED, LOUVAIN and the CONSENSUS clustering, and of the
#: modularity community_stats reports. leidenalg's ModularityVertexPartition has no resolution parameter (it
#: is standard modularity, γ = 1); networkx's Louvain and modularity receive it explicitly.
MODULARITY_RESOLUTION = 1
#: Seed of the first networkx Louvain run, which randomises the node-visit order; run k uses ``LOUVAIN_SEED + k``.
LOUVAIN_SEED = 0
#: Independent seeded Louvain runs per partition; the one with the highest modularity is reported.
LOUVAIN_RUNS = 50
#: Minimum modularity gain for Louvain to go on to a further aggregation level — networkx's own default.
LOUVAIN_THRESHOLD = 1e-07
#: Maximum number of Louvain aggregation levels — networkx's own default (None = no limit).
LOUVAIN_MAX_LEVEL = None
#: Whether the single-graph detectors put every isolated node into one shared community (the first
#: isolated node's, by id) instead of leaving each as its own singleton community.
MERGE_ISOLATED_NODES = True
#: KCORE coreness floor: isolated nodes (coreness 0) are folded into the 1-shell, the outermost community.
KCORE_MIN_SHELL = 1
#: Default CPM resolution γ of a LEIDEN_CPM / LEIDEN_TEMPORAL token that omits ``resolution`` (or gives
#: ``auto``) — the rule :func:`cpm_density_resolution` applies, to the graph (or each year slice) CPM runs on.
CPM_DEFAULT_RESOLUTION_RULE = (
    "γ = Σ w_ij / (n(n−1)/2): the weighted edge density of the undirected W+Wᵀ projection, on the raw tie "
    "weights, self-loops excluded (0 when n < 2)"
)
#: CPM resolution of LEIDEN_TEMPORAL's interslice coupling layer, as in leidenalg.find_partition_temporal.
TEMPORAL_INTERSLICE_RESOLUTION = 0
#: Weight of every layer (each year slice and the interslice layer) in LEIDEN_TEMPORAL's joint quality —
#: leidenalg's own default (``layer_weights=None`` → 1 per layer).
TEMPORAL_LAYER_WEIGHT = 1
#: How LEIDEN_TEMPORAL's full-range column summarises the per-year partitions (detect_leiden_temporal).
TEMPORAL_PLURALITY_RULE = (
    "each channel's most frequent community across the year slices it appears in; ties go to its latest "
    "year's community when that is among the tied, else to the smallest community id"
)
#: How LEIDEN_TEMPORAL turns its relative coupling ω into the identity-link weight (temporal_interslice_weight).
TEMPORAL_INTERSLICE_SCALE_RULE = (
    "identity-link weight = ω × the mean tie weight of the year slices (the undirected W+Wᵀ projection on the raw "
    "tie weights, self-loops excluded, averaged over every slice's ties)"
)
#: How CONSENSUS turns the input partitions into one (detect_consensus).
CONSENSUS_CLUSTERING_RULE = (
    "one pass: Leiden modularity clustering (best of LEIDEN_RUNS seeds) of the consensus graph, which links two "
    "channels when the share of input partitions co-assigning them is ≥ τ, weighted by that share; channels "
    "without a tie in the graph are left out of the co-assignment counts"
)
#: Seed of every SBM / SBM_ASSORTATIVE fit: graph-tool's own generator (``seed_rng``) and numpy's global
#: one, which graph-tool's Python layer draws from (nested-level shuffles, MCMC sweeps, partition modes).
#: Non-zero: graph-tool reads ``seed_rng(0)`` as "use the system's entropy source".
SBM_SEED = 42
#: SBM fits the degree-corrected block model — graph-tool's BlockState default.
SBM_DEGREE_CORRECTED = True
#: SBM minimum-description-length fit: merge-split sweeps per multilevel step and their inverse temperature
#: (∞ = greedy descent) — graph-tool's minimize_blockmodel_dl / minimize_nested_blockmodel_dl defaults.
SBM_FIT_NITER = 1
SBM_FIT_BETA = math.inf
#: Independent fits per SBM / SBM_ASSORTATIVE partition; the one with the lowest description length (the most
#: probable partition) is reported — graph-tool's own advice, as a single agglomerative fit can stop in a poor local
#: minimum. Run k draws on the continuing seeded stream, so the set of fits is reproducible.
SBM_FIT_RESTARTS = 10
#: Zero-temperature merge-split refinement after each SBM fit: this many sweeps of ``SBM_REFINE_NITER`` moves each
#: — graph-tool's documented pattern for improving a minimize_*_blockmodel_dl result.
SBM_REFINE_SWEEPS = 100
SBM_REFINE_NITER = 10
# SBM(refine=MCMC) run lengths: `wait` bounds the multiflip equilibration phase, `samples` is the
# number of posterior partitions collected for the marginals. Modest by graph-tool-docs standards
# (which use wait=1000), sized for Pulpit's few-hundred-to-few-thousand-node citation graphs.
SBM_MCMC_WAIT = 100
SBM_MCMC_SAMPLES = 100
#: refine=MCMC equilibration ends once the ``wait`` criterion has been met this many times, a sweep counting
#: as a change when its relative entropy change is at least ``epsilon`` — graph-tool's mcmc_equilibrate
#: defaults.
SBM_MCMC_NBREAKS = 2
SBM_MCMC_EPSILON = 0
#: refine=MCMC: merge-split sweeps per MCMC step (equilibration and sampling alike — one posterior sample is
#: taken per step).
SBM_MCMC_SWEEP_NITER = 10
#: refine=MCMC inverse temperature — graph-tool's default (1 = sampling the posterior itself).
SBM_MCMC_BETA = 1.0
#: refine=MCMC moves are graph-tool's merge-split (multiflip) moves — mcmc_equilibrate's default.
SBM_MCMC_MULTIFLIP = True
#: Empty hierarchy levels appended to a nested SBM fit before refine=MCMC, so the hierarchy can grow during
#: sampling — graph-tool's documented equilibration pattern.
SBM_NESTED_PAD_LEVELS = 4
#: refine=MCMC partition mode (Peixoto 2021, ``PartitionModeState``): align the sample labels first
#: (graph-tool's default) and iterate the alignment until it converges.
SBM_MODE_RELABEL = True
SBM_MODE_CONVERGE = True
# Zero-temperature merge-split sweeps refining each planted-partition fit (started from graph-tool's multilevel
# minimize_blockmodel_dl) — the value used in graph-tool's own PPBlockState documentation example.
PP_GREEDY_NITER = 1000
#: Inverse temperature of the planted-partition greedy fit (∞ = zero temperature).
PP_GREEDY_BETA = math.inf

_SOURCE = "network/community.py"
_LEIDENALG_STRATEGIES = ("LEIDEN", "LEIDEN_DIRECTED", "LEIDEN_CPM", "LEIDEN_TEMPORAL", "CONSENSUS")
_MERGING_STRATEGIES = ("LEIDEN", "LEIDEN_DIRECTED", "LEIDEN_CPM", "LOUVAIN", "SBM", "SBM_ASSORTATIVE", "CONSENSUS")
_SBM_STRATEGIES = ("SBM", "SBM_ASSORTATIVE")


def _per_strategy(
    strategies: tuple[str, ...], *, name: str, value: object, affects: str, constant: str, note: str = ""
) -> tuple[FixedParameter, ...]:
    """One :class:`FixedParameter` per strategy family sharing a constant, scoped ``strategy:<TOKEN>``."""
    return tuple(
        FixedParameter(
            name=name,
            value=value,
            scope=f"strategy:{strategy}",
            affects=affects,
            source=f"{_SOURCE}: {constant}",
            note=note,
        )
        for strategy in strategies
    )


#: The values fixed in this module that shape community detection (``PARAMETERS.md``). Strategy parameters
#: given in a token, ``--community-backbone-alpha`` and the palette are run options, not listed here; the
#: value a strategy uses for an *omitted* token parameter is.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    *_per_strategy(
        _LEIDENALG_STRATEGIES,
        name="Leiden random seed",
        value=LEIDEN_SEED,
        affects="Seeds the first of the Leiden runs (run k uses this + k), so the set of runs — and hence the "
        "reported partition — is reproducible.",
        constant="LEIDEN_SEED",
    ),
    *_per_strategy(
        _LEIDENALG_STRATEGIES,
        name="Leiden runs",
        value=LEIDEN_RUNS,
        affects="Independent seeded optimisations per partition; the highest-quality one is reported and the "
        "runs' agreement with it is recorded as the partition's stability (summary.json community_fits).",
        constant="LEIDEN_RUNS",
        note="Modularity and CPM landscapes are degenerate: single runs land on different near-optimal "
        "partitions (Good, de Montjoye & Clauset 2010).",
    ),
    *_per_strategy(
        _LEIDENALG_STRATEGIES,
        name="Leiden iterations",
        value=LEIDEN_N_ITERATIONS,
        affects="Number of full Leiden iterations (local moves, refinement, aggregation) per optimisation; "
        "negative = iterate until an iteration no longer improves the quality function.",
        constant="LEIDEN_N_ITERATIONS",
    ),
    *_per_strategy(
        _LEIDENALG_STRATEGIES,
        name="Leiden maximum community size",
        value=LEIDEN_MAX_COMM_SIZE,
        affects="Largest community, in channels, the Leiden optimiser may form; 0 = no limit.",
        constant="LEIDEN_MAX_COMM_SIZE",
        note="leidenalg's own default, passed explicitly.",
    ),
    *_per_strategy(
        ("LEIDEN", "LEIDEN_DIRECTED", "LOUVAIN", "CONSENSUS"),
        name="Modularity resolution γ",
        value=MODULARITY_RESOLUTION,
        affects="Resolution of the modularity objective the partition maximises: 1 = standard modularity; a "
        "higher value would favour more, smaller communities.",
        constant="MODULARITY_RESOLUTION",
        note="Inherent to leidenalg's ModularityVertexPartition (LEIDEN, LEIDEN_DIRECTED, the CONSENSUS "
        "clustering), which takes no resolution parameter; passed explicitly to networkx's Louvain, whose own "
        "default it is.",
    ),
    *_per_strategy(
        _MERGING_STRATEGIES,
        name="Merge isolated channels",
        value=MERGE_ISOLATED_NODES,
        affects="Channels with no tie in the graph the detection ran on all share one community (the first "
        "isolated channel's, by id) instead of each forming its own singleton community. The shared community "
        "is a display convenience: these channels are left out of the CONSENSUS co-assignment counts and of the "
        "partition-comparison matrices.",
        constant="MERGE_ISOLATED_NODES",
    ),
    FixedParameter(
        name="CPM resolution γ when omitted",
        value=CPM_DEFAULT_RESOLUTION_RULE,
        scope="strategy:LEIDEN_CPM",
        affects="A LEIDEN_CPM token without a resolution (or with resolution=auto) runs at this γ, so a "
        "community is a group denser than the network as a whole, whatever the scale of the weights.",
        source=f"{_SOURCE}: CPM_DEFAULT_RESOLUTION_RULE",
        note="CPM at γ = density is the Reichardt & Bornholdt (2006) quality with an Erdős–Rényi null at "
        "γ_RB = 1 (cpm_density_resolution).",
    ),
    FixedParameter(
        name="Slice resolution γ when omitted",
        value=CPM_DEFAULT_RESOLUTION_RULE,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="A LEIDEN_TEMPORAL token without a resolution (or with resolution=auto) gives each year slice "
        "its own γ by this rule, computed on that slice.",
        source=f"{_SOURCE}: CPM_DEFAULT_RESOLUTION_RULE",
        note="A per-slice null model, as in Mucha et al. (2010) (temporal_slice_resolutions).",
    ),
    FixedParameter(
        name="Coupling ω when omitted",
        value=TEMPORAL_DEFAULT_INTERSLICE,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="Coupling of the identity link tying each channel to itself in adjacent years when a "
        "LEIDEN_TEMPORAL token omits interslice, as a multiple of the slices' mean tie weight (1 = as strong as an "
        "average tie); higher = smoother, more persistent communities across years.",
        source=f"{_SOURCE}: TEMPORAL_DEFAULT_INTERSLICE",
    ),
    FixedParameter(
        name="Coupling ω scale",
        value=TEMPORAL_INTERSLICE_SCALE_RULE,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="Turns the relative ω of every LEIDEN_TEMPORAL token into the absolute identity-link weight, so "
        "the same ω couples the years equally strongly under every --edge-weight-strategy (the absolute weight "
        "used is recorded in summary.json community_resolutions).",
        source=f"{_SOURCE}: TEMPORAL_INTERSLICE_SCALE_RULE",
    ),
    FixedParameter(
        name="Interslice-layer resolution",
        value=TEMPORAL_INTERSLICE_RESOLUTION,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="CPM resolution of the layer holding the identity links: 0, so the coupling only rewards "
        "keeping a channel in the same community across years and adds no size penalty of its own.",
        source=f"{_SOURCE}: TEMPORAL_INTERSLICE_RESOLUTION",
        note="As in leidenalg.find_partition_temporal.",
    ),
    FixedParameter(
        name="Layer weight",
        value=TEMPORAL_LAYER_WEIGHT,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="Weight of each year slice, and of the interslice layer, in the joint multislice quality; equal "
        "weights make every year count the same.",
        source=f"{_SOURCE}: TEMPORAL_LAYER_WEIGHT",
        note="leidenalg's own default (layer_weights=None), passed explicitly.",
    ),
    FixedParameter(
        name="Full-range plurality rule",
        value=TEMPORAL_PLURALITY_RULE,
        scope="strategy:LEIDEN_TEMPORAL",
        affects="Sets the full-range LEIDEN_TEMPORAL column (map, tables, exports) — a summary of the per-year "
        "partitions, not a detection of the full-range graph.",
        source=f"{_SOURCE}: TEMPORAL_PLURALITY_RULE",
    ),
    FixedParameter(
        name="Louvain random seed",
        value=LOUVAIN_SEED,
        scope="strategy:LOUVAIN",
        affects="Seeds the first Louvain run (run k uses this + k); networkx's Louvain randomises the node-visit "
        "order, so the seeds make the set of runs — and the reported partition — reproducible.",
        source=f"{_SOURCE}: LOUVAIN_SEED",
    ),
    FixedParameter(
        name="Louvain runs",
        value=LOUVAIN_RUNS,
        scope="strategy:LOUVAIN",
        affects="Independent seeded Louvain runs; the highest-modularity one is reported and the runs' agreement "
        "with it is recorded as the partition's stability (summary.json community_fits).",
        source=f"{_SOURCE}: LOUVAIN_RUNS",
    ),
    FixedParameter(
        name="Louvain level threshold",
        value=LOUVAIN_THRESHOLD,
        scope="strategy:LOUVAIN",
        affects="Louvain stops aggregating once a level raises modularity by less than this.",
        source=f"{_SOURCE}: LOUVAIN_THRESHOLD",
        note="networkx's own default, passed explicitly.",
    ),
    FixedParameter(
        name="Louvain maximum levels",
        value=LOUVAIN_MAX_LEVEL,
        scope="strategy:LOUVAIN",
        affects="Maximum number of Louvain aggregation levels; None = no limit (the level threshold stops it).",
        source=f"{_SOURCE}: LOUVAIN_MAX_LEVEL",
        note="networkx's own default, passed explicitly.",
    ),
    FixedParameter(
        name="K-core shell floor",
        value=KCORE_MIN_SHELL,
        scope="strategy:KCORE",
        affects="Isolated channels (coreness 0) are folded into the 1-shell, the outermost community, rather "
        "than forming a 0-shell of their own.",
        source=f"{_SOURCE}: KCORE_MIN_SHELL",
    ),
    FixedParameter(
        name="SBM mode when omitted",
        value=SBM_DEFAULT_MODE,
        scope="strategy:SBM",
        affects="An SBM token without a mode fits the nested SBM and reads its partition at the finest level.",
        source=f"{_SOURCE}: SBM_DEFAULT_MODE",
        note="Nested SBM: Peixoto (2017).",
    ),
    FixedParameter(
        name="SBM weights when omitted",
        value=SBM_DEFAULT_WEIGHTS,
        scope="strategy:SBM",
        affects="An SBM token without weights (empty) fits the binary citation structure, so the partition is "
        "invariant to --edge-weight-strategy.",
        source=f"{_SOURCE}: SBM_DEFAULT_WEIGHTS",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="SBM refinement when omitted",
        value=SBM_DEFAULT_REFINE,
        affects="A token without refine (empty) reports the single point estimate — no posterior sampling and "
        "no confidence column.",
        constant="SBM_DEFAULT_REFINE",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="graph-tool seed",
        value=SBM_SEED,
        affects="Seeds graph-tool's generator (seed_rng) and numpy's global one for the duration of every fit, "
        "so the same graph gives the same blocks (and refine=MCMC confidences) on every run.",
        constant="SBM_SEED",
        note="Non-zero on purpose: graph-tool reads seed_rng(0) as 'use the system's entropy source'. numpy's "
        "previous global state is restored after the fit.",
    ),
    FixedParameter(
        name="Degree correction",
        value=SBM_DEGREE_CORRECTED,
        scope="strategy:SBM",
        affects="Fits the degree-corrected SBM, so blocks reflect structure beyond each channel's in/out-degree.",
        source=f"{_SOURCE}: SBM_DEGREE_CORRECTED",
        note="Karrer & Newman (2011); graph-tool's BlockState default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="Fit sweeps per step",
        value=SBM_FIT_NITER,
        affects="Merge-split sweeps per step of the multilevel minimum-description-length fit (the nested fit "
        "repeats the step level by level until the description length stops changing).",
        constant="SBM_FIT_NITER",
        note="graph-tool's minimize_blockmodel_dl / minimize_nested_blockmodel_dl default, passed explicitly; "
        "the other multilevel-sweep settings are graph-tool's defaults.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="Fit inverse temperature β",
        value=SBM_FIT_BETA,
        affects="Inverse temperature of the minimum-description-length fit: ∞ = greedy descent.",
        constant="SBM_FIT_BETA",
        note="graph-tool's minimize_blockmodel_dl / minimize_nested_blockmodel_dl default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="Fit restarts",
        value=SBM_FIT_RESTARTS,
        affects="Independent fits per partition; the one with the lowest description length (the most probable "
        "partition) is reported and the fits' agreement with it is recorded as the partition's stability "
        "(summary.json community_fits).",
        constant="SBM_FIT_RESTARTS",
        note="A single agglomerative fit can stop in a poor local minimum; graph-tool's documentation advises "
        "repeating it and keeping the smallest description length.",
    ),
    FixedParameter(
        name="Refinement sweeps",
        value=SBM_REFINE_SWEEPS,
        scope="strategy:SBM",
        affects="Zero-temperature merge-split sweeps run after every fit to lower its description length further "
        "before the fits are compared.",
        source=f"{_SOURCE}: SBM_REFINE_SWEEPS",
        note="graph-tool's documented refinement pattern.",
    ),
    FixedParameter(
        name="Refinement moves per sweep",
        value=SBM_REFINE_NITER,
        scope="strategy:SBM",
        affects="Merge-split moves (niter) in each refinement sweep.",
        source=f"{_SOURCE}: SBM_REFINE_NITER",
    ),
    FixedParameter(
        name="Planted-partition greedy sweeps",
        value=PP_GREEDY_NITER,
        scope="strategy:SBM_ASSORTATIVE",
        affects="Zero-temperature merge-split sweeps refining each multilevel planted-partition fit before the "
        "fits are compared.",
        source=f"{_SOURCE}: PP_GREEDY_NITER",
        note="The value in graph-tool's PPBlockState documentation example.",
    ),
    FixedParameter(
        name="Planted-partition inverse temperature β",
        value=PP_GREEDY_BETA,
        scope="strategy:SBM_ASSORTATIVE",
        affects="Inverse temperature of the planted-partition fit: ∞ = greedy descent of the description length.",
        source=f"{_SOURCE}: PP_GREEDY_BETA",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC equilibration wait",
        value=SBM_MCMC_WAIT,
        affects="refine=MCMC: equilibration runs until this many steps pass without a new description-length "
        "record (repeated per the equilibration breaks).",
        constant="SBM_MCMC_WAIT",
        note="graph-tool's documentation uses 1000; sized for Pulpit's few-hundred-to-few-thousand-node graphs.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC equilibration breaks",
        value=SBM_MCMC_NBREAKS,
        affects="refine=MCMC: equilibration ends once the wait criterion has been met this many times.",
        constant="SBM_MCMC_NBREAKS",
        note="graph-tool's mcmc_equilibrate default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC equilibration change threshold",
        value=SBM_MCMC_EPSILON,
        affects="refine=MCMC: relative entropy change below which an equilibration step counts as no change; "
        "0 = only new description-length records reset the wait.",
        constant="SBM_MCMC_EPSILON",
        note="graph-tool's mcmc_equilibrate default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC posterior samples",
        value=SBM_MCMC_SAMPLES,
        affects="refine=MCMC: posterior partitions collected after equilibration; each channel's community is "
        "its max-marginal block across them and its confidence the share of samples agreeing.",
        constant="SBM_MCMC_SAMPLES",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC sweeps per step",
        value=SBM_MCMC_SWEEP_NITER,
        affects="refine=MCMC: merge-split sweeps per MCMC step, in equilibration and sampling (one sample per step).",
        constant="SBM_MCMC_SWEEP_NITER",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC inverse temperature β",
        value=SBM_MCMC_BETA,
        affects="refine=MCMC: inverse temperature of the chain; 1 = sampling the posterior itself.",
        constant="SBM_MCMC_BETA",
        note="graph-tool's default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="MCMC merge-split moves",
        value=SBM_MCMC_MULTIFLIP,
        affects="refine=MCMC: the chain uses merge-split (multiflip) moves rather than single-node moves.",
        constant="SBM_MCMC_MULTIFLIP",
        note="graph-tool's mcmc_equilibrate default, passed explicitly.",
    ),
    FixedParameter(
        name="Nested hierarchy padding",
        value=SBM_NESTED_PAD_LEVELS,
        scope="strategy:SBM",
        affects="refine=MCMC with mode=NESTED: empty hierarchy levels appended before sampling so the hierarchy "
        "can grow.",
        source=f"{_SOURCE}: SBM_NESTED_PAD_LEVELS",
        note="graph-tool's documented equilibration pattern.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="Partition-mode label alignment",
        value=SBM_MODE_RELABEL,
        affects="refine=MCMC: posterior samples are aligned to a common labelling before each channel's "
        "max-marginal block and confidence are read.",
        constant="SBM_MODE_RELABEL",
        note="Peixoto (2021), PartitionModeState; graph-tool's default, passed explicitly.",
    ),
    *_per_strategy(
        _SBM_STRATEGIES,
        name="Partition-mode convergence",
        value=SBM_MODE_CONVERGE,
        affects="refine=MCMC: the label alignment is iterated until it converges, not run once.",
        constant="SBM_MODE_CONVERGE",
        note="Peixoto (2021), PartitionModeState.",
    ),
    FixedParameter(
        name="Consensus threshold τ when omitted",
        value=CONSENSUS_DEFAULT_THRESHOLD,
        scope="strategy:CONSENSUS",
        affects="A CONSENSUS token without a threshold links two channels in the consensus graph only when at "
        "least this share of the input partitions co-assign them (0.5 = a majority).",
        source=f"{_SOURCE}: CONSENSUS_DEFAULT_THRESHOLD",
        note="Lancichinetti & Fortunato (2012).",
    ),
    FixedParameter(
        name="Consensus clustering",
        value=CONSENSUS_CLUSTERING_RULE,
        scope="strategy:CONSENSUS",
        affects="How the consensus partition is drawn from the inputs; Lancichinetti & Fortunato's re-clustering "
        "loop is not run, as deterministic inputs make it a fixed point after one pass.",
        source=f"{_SOURCE}: CONSENSUS_CLUSTERING_RULE",
    ),
)


# ── Shared scaffolding for the per-algorithm detect_* functions ────────────────


def _node_id_index(graph: nx.DiGraph) -> tuple[list[str], dict[str, int]]:
    """Stable sorted ``node_ids`` plus ``{node_id: index}`` map. Used by every
    igraph- or matrix-based detector to translate between str ids and 0..n-1 indices."""
    node_ids = sorted(graph.nodes())
    return node_ids, {node_id: index for index, node_id in enumerate(node_ids)}


# ``build_graph`` stores two weights per edge: ``weight`` — rescaled to 10·w/max(w) *per graph*, the
# display / layout scale — and ``weight_raw`` — the un-rescaled tie weight in the units of
# ``--edge-weight-strategy``. Modularity (LEIDEN, LEIDEN_DIRECTED, LOUVAIN) is invariant to a uniform
# rescale, so those detectors keep ``weight``; CPM's resolution γ (LEIDEN_CPM, LEIDEN_TEMPORAL) and the
# weighted SBM's edge covariates read weights in absolute units, so they use the raw value — otherwise
# the same γ would mean a different density on every graph / year / weight strategy, and a
# ``TOTAL`` count graph would reach SBM(weights=POISSON) as non-integers (``network.utils.tie_weight_key``
# picks the attribute).


def _build_directed_igraph(
    graph: nx.DiGraph, node_ids: list[str], node_id_map: dict[str, int]
) -> tuple[ig.Graph, list[float]]:
    """Build a directed igraph from a NetworkX DiGraph preserving edge weights."""
    ig_graph = ig.Graph(n=len(node_ids), directed=True)
    edges = [(node_id_map[s], node_id_map[t]) for s, t in graph.edges()]
    weights = [graph.edges[s, t].get("weight", 1.0) for s, t in graph.edges()]
    ig_graph.add_edges(edges)
    return ig_graph, weights


def _assign_from_membership(membership: Iterable[int], node_ids: list[str]) -> CommunityMap:
    """Build {node_id: community_index} from a membership vector aligned with ``node_ids``."""
    return {node_ids[index]: int(community) + 1 for index, community in enumerate(membership)}


# ── Best-of-N fitting ─────────────────────────────────────────────────────────
#
# Every algorithmic detector is a stochastic optimiser over a degenerate landscape: different seeds return
# different, comparably good partitions (Good, de Montjoye & Clauset 2010). Each detector therefore runs several
# seeded fits and reports the best one by its own objective; ``diagnostics_out`` receives how the fits compare,
# so an export records how reproducible each partition is (summary.json ``community_fits``, PARAMETERS.md).


def _select_best_run(
    runs: "list[tuple[float, Any]]",
    *,
    objective: str,
    minimise: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> int:
    """Index of the best of several seeded fits, recording how much the fits agree with it.

    ``runs`` holds one ``(quality, labels)`` pair per fit, ``labels`` a community id per node over one fixed node
    order. The best fit has the highest quality — the lowest with ``minimise`` (a description length) — and a tie
    goes to the earliest fit, so the choice is deterministic. ``diagnostics_out`` receives ``objective``, ``runs``,
    ``best`` / ``worst`` quality, ``stability`` — the mean Adjusted Rand Index of the other fits to the reported
    one (``None`` for a single fit) — and ``identical_share``, the share of fits that found exactly the reported
    partition.
    """
    qualities = [float(quality) for quality, _ in runs]
    best_quality = min(qualities) if minimise else max(qualities)
    best = qualities.index(best_quality)
    if diagnostics_out is not None:
        from sklearn.metrics import adjusted_rand_score

        reference = list(runs[best][1])
        agreement = [
            float(adjusted_rand_score(reference, list(labels)))
            for index, (_, labels) in enumerate(runs)
            if index != best
        ]
        diagnostics_out.update(
            {
                "objective": objective,
                "runs": len(runs),
                "best": round(best_quality, 6),
                "worst": round(max(qualities) if minimise else min(qualities), 6),
                "stability": round(sum(agreement) / len(agreement), 4) if agreement else None,
                "identical_share": round((1 + sum(1 for a in agreement if a >= 1.0 - 1e-12)) / len(runs), 4),
            }
        )
    return best


def _best_leiden_membership(
    ig_graph: ig.Graph,
    partition_type: Any,
    *,
    objective: str,
    diagnostics_out: "dict[str, Any] | None" = None,
    **partition_kwargs: Any,
) -> list[int]:
    """Membership vector of the best of :data:`LEIDEN_RUNS` seeded ``leidenalg.find_partition`` runs.

    Run k uses seed ``LEIDEN_SEED + k``; the highest ``quality()`` wins (:func:`_select_best_run`).
    ``partition_kwargs`` (weights, resolution) are passed to every run.
    """
    runs: list[tuple[float, list[int]]] = []
    for run in range(LEIDEN_RUNS):
        partition = leidenalg.find_partition(
            ig_graph,
            partition_type,
            n_iterations=LEIDEN_N_ITERATIONS,
            max_comm_size=LEIDEN_MAX_COMM_SIZE,
            seed=LEIDEN_SEED + run,
            **partition_kwargs,
        )
        runs.append((partition.quality(), list(partition.membership)))
    return runs[_select_best_run(runs, objective=objective, diagnostics_out=diagnostics_out)][1]


def _finalize_partition(
    graph: nx.DiGraph,
    community_map: CommunityMap,
    palette_name: str,
    *,
    reverse: bool = False,
    merge_isolated: bool = MERGE_ISOLATED_NODES,
) -> tuple[CommunityMap, CommunityPalette]:
    """Common closing for every detect_* function: optional isolated-node merge,
    canonical id renumbering, palette construction."""
    if merge_isolated:
        community_map = _merge_isolated_nodes(graph, community_map)
    community_map = normalize_community_map(community_map)
    return community_map, build_community_palette(community_map, palette_name, reverse=reverse)


# ── Detection algorithms ──────────────────────────────────────────────────────


def detect_labelgroup(group_id: int, channel_dict: dict[str, Any]) -> tuple[CommunityMap, CommunityPalette]:
    """Partition nodes by their resolved label in LabelGroup ``group_id`` for the window.

    Reads the per-group window resolution ``graph_builder`` stored in ``node['group_partitions']``;
    nodes with no label in the group (dead leaves, or simply unlabelled in this group) are left
    ungrouped. The primary group resolves in-target labels only; a descriptive group (e.g. "Nation")
    partitions by every label it carries, in-target or not. Community ids are ``Label`` pks and the
    palette is built from each label's own colour, so the ``palette_name`` / ``reverse`` flags don't
    apply.
    """
    community_map: CommunityMap = {}
    community_palette: CommunityPalette = {}
    for channel_id, item in channel_dict.items():
        entry = (item["data"].get("group_partitions") or {}).get(group_id)
        if entry is None:
            continue
        label_id, label_color = entry
        community_map[channel_id] = label_id
        if label_id not in community_palette:
            community_palette[label_id] = parse_color(label_color)
    return community_map, community_palette


def detect_kcore(
    graph: nx.DiGraph, palette_name: str, *, reverse: bool = False
) -> tuple[CommunityMap, CommunityPalette]:
    """K-core decomposition (Seidman 1983; Kitsak et al. 2010).

    A node's coreness is the largest k such that it belongs to the maximal subgraph
    where every member has at least k internal connections. Communities are the
    resulting k-shells, numbered from the innermost (community 1) outwards — the
    shell order IS the information, so we bypass ``_finalize_partition`` rather
    than renumbering by community size like every other detector.

    Computed on the W+Wᵀ undirected projection (``to_undirected_sum``) with self-loops
    removed (``nx.core_number`` rejects them, and they're present whenever
    ``--self-references`` is on). ``nx.core_number`` is unweighted, so the partition
    is invariant to ``--edge-weight-strategy``. Isolated nodes (coreness 0) are
    folded into shell 1 and end up in the outermost community.
    """
    undirected = to_undirected_sum(graph)
    undirected.remove_edges_from(nx.selfloop_edges(undirected))
    coreness = nx.core_number(undirected)
    raw: CommunityMap = {node_id: max(k, KCORE_MIN_SHELL) for node_id, k in coreness.items()}
    shells = sorted(set(raw.values()), reverse=True)
    remap = {shell: index for index, shell in enumerate(shells, start=1)}
    community_map: CommunityMap = {node_id: remap[shell] for node_id, shell in raw.items()}
    return community_map, build_community_palette(community_map, palette_name, reverse=reverse)


def detect_leiden(
    graph: nx.DiGraph,
    palette_name: str,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Modularity (Newman 2006) via leidenalg on the undirected W+Wᵀ projection.

    Best of :data:`LEIDEN_RUNS` seeded runs by modularity (:func:`_best_leiden_membership`);
    ``diagnostics_out`` receives how the runs agree.
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map)
    if weights:
        ig_graph.es["weight"] = weights
    membership = _best_leiden_membership(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        objective="modularity",
        diagnostics_out=diagnostics_out,
        weights="weight" if weights else None,
    )
    return _finalize_partition(graph, _assign_from_membership(membership, node_ids), palette_name, reverse=reverse)


def detect_leiden_directed(
    graph: nx.DiGraph,
    palette_name: str,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Directed modularity (Leicht & Newman 2008) via leidenalg.

    Uses ModularityVertexPartition on a directed igraph so the null model is
    k_out_i * k_in_j / m rather than the undirected k_i * k_j / (2m).
    Communities are built from asymmetric citation patterns: a source that
    cites many channels without being cited back is treated differently from
    a target that is widely cited.  Edge direction is preserved throughout
    the optimisation. Best of :data:`LEIDEN_RUNS` seeded runs by directed modularity.
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_directed_igraph(graph, node_ids, node_id_map)
    if weights:
        ig_graph.es["weight"] = weights
    membership = _best_leiden_membership(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        objective="directed modularity",
        diagnostics_out=diagnostics_out,
        weights="weight" if weights else None,
    )
    return _finalize_partition(graph, _assign_from_membership(membership, node_ids), palette_name, reverse=reverse)


def _build_undirected_igraph(
    graph: nx.DiGraph, node_ids: list[str], node_id_map: dict[str, int], weight: str = "weight"
) -> tuple[ig.Graph, list[float]]:
    """Build an undirected igraph from a NetworkX DiGraph, summing reciprocal edge weights.

    ``weight`` names the edge attribute summed into the W+Wᵀ projection — ``weight`` (rescaled) by
    default, :data:`RAW_WEIGHT_KEY` for the scale-sensitive CPM objective (see :func:`tie_weight_key`).
    """
    undirected = to_undirected_sum(graph, weight=weight)
    ig_graph = ig.Graph(n=len(node_ids), directed=False)
    edges, weights = [], []
    for s, t in undirected.edges():
        edges.append((node_id_map[s], node_id_map[t]))
        weights.append(undirected.edges[s, t].get(weight, 1.0))
    ig_graph.add_edges(edges)
    return ig_graph, weights


def best_modularity(graph: nx.DiGraph, *, directed: bool, runs: int, seed: int = LEIDEN_SEED) -> float:
    """The highest modularity ``runs`` seeded Leiden optimisations reach on ``graph``.

    ``directed`` selects Leicht & Newman's directed modularity on the citation graph, else Newman's modularity of
    the undirected W+Wᵀ projection — the two objectives the reported modularity is computed against. Weighted by
    ``weight`` (modularity is invariant to its uniform rescale). The random-graph side of the modularity
    significance test (``community_stats``): how modular a graph with no community structure but the same
    degrees and strengths can be made to look. ``0.0`` for a graph without edges.
    """
    if graph.number_of_edges() == 0:
        return 0.0
    node_ids, node_id_map = _node_id_index(graph)
    build = _build_directed_igraph if directed else _build_undirected_igraph
    ig_graph, weights = build(graph, node_ids, node_id_map)
    return max(
        leidenalg.find_partition(
            ig_graph,
            leidenalg.ModularityVertexPartition,
            weights=weights if weights else None,
            n_iterations=LEIDEN_N_ITERATIONS,
            max_comm_size=LEIDEN_MAX_COMM_SIZE,
            seed=seed + run,
        ).quality()
        for run in range(runs)
    )


def cpm_density_resolution(graph: nx.Graph, weight: str | None = None) -> float:
    """Default CPM resolution γ: the weighted edge density of the graph CPM runs on.

    ``p = Σ w_ij / (n(n−1)/2)`` — the total tie weight of the undirected W+Wᵀ projection CPM is
    optimised on (self-loops excluded: CPM's ``n_c(n_c−1)/2`` penalty counts distinct pairs only)
    over its number of node pairs; ``0.0`` when ``n < 2``. Summing the directed edges of a DiGraph
    gives the same total as summing its W+Wᵀ projection, so either can be passed. ``weight`` names the
    edge attribute (default :func:`tie_weight_key` — the raw tie weight CPM reads).

    CPM at γ = p is exactly the Reichardt–Bornholdt quality function with an Erdős–Rényi null model at
    γ_RB = 1 (Reichardt & Bornholdt 2006; Traag, Van Dooren & Nesterov 2011 — leidenalg's
    ``RBERVertexPartition``): a community is a group denser than the network as a whole. Because p
    scales with the weights, the partition is invariant to a uniform rescale of the tie weights,
    unlike a fixed γ — and it adapts to each graph, year slice or backbone it is computed on.
    """
    n = graph.number_of_nodes()
    if n < 2:
        return 0.0
    key = weight or tie_weight_key(graph)
    total = sum(float(data.get(key, 1.0)) for u, v, data in graph.edges(data=True) if u != v)
    return total / (n * (n - 1) / 2)


def instance_resolution(instance: "StrategyInstance") -> float | None:
    """The explicit CPM resolution γ of a LEIDEN_CPM / LEIDEN_TEMPORAL instance, or ``None`` when it is
    auto (the token omitted ``resolution``, or gave ``auto``) — the graph's density, resolved per graph by
    :func:`cpm_density_resolution`."""
    value = instance.params_dict.get("resolution", "")
    return None if value in ("", None) else float(value)


def cpm_resolution(instance: "StrategyInstance", graph: nx.DiGraph) -> float:
    """The γ a LEIDEN_CPM instance runs with on ``graph`` (the graph passed to :func:`detect`, i.e. the
    community backbone when one is set): its explicit ``resolution``, else ``graph``'s weighted edge
    density. The same computation :func:`detect_leiden_cpm` performs, so callers can record the γ used."""
    explicit = instance_resolution(instance)
    return explicit if explicit is not None else cpm_density_resolution(graph)


def temporal_slice_resolutions(year_graphs: dict[int, nx.DiGraph], resolution: float | None) -> dict[int, float]:
    """The γ each LEIDEN_TEMPORAL year slice runs with: the explicit ``resolution`` for every slice, or —
    when ``None`` (auto) — each slice's own weighted edge density (:func:`cpm_density_resolution`, on the
    raw-weight attribute chosen once across all slices, as :func:`detect_leiden_temporal` does). The
    multislice analogue of the single-graph default: Mucha et al. (2010) give every slice its own null
    model."""
    if resolution is not None:
        return {year: float(resolution) for year in sorted(year_graphs)}
    weight_key = tie_weight_key(*year_graphs.values())
    return {year: cpm_density_resolution(year_graphs[year], weight_key) for year in sorted(year_graphs)}


def temporal_interslice_weight(year_graphs: dict[int, nx.DiGraph], interslice: float) -> float:
    """The absolute identity-link weight of a LEIDEN_TEMPORAL coupling ω: ``ω ×`` the mean tie weight of the slices.

    The mean runs over every tie of every year slice's undirected W+Wᵀ projection — the graphs the multislice CPM
    is optimised on — on the raw tie weights (:func:`tie_weight_key`, chosen once across the slices), self-loops
    excluded. ω is thereby relative: 1 makes an identity link as strong as an average tie under every
    ``--edge-weight-strategy`` (a citation share under PARTIAL_*, a count under TOTAL, 1 under NONE), where an
    absolute ω would couple the years tightly under one strategy and negligibly under another. Falls back to the
    plain ω when the slices hold no tie.
    """
    weight_key = tie_weight_key(*year_graphs.values())
    weights = [
        float(w)
        for graph in year_graphs.values()
        for u, v, w in to_undirected_sum(graph, weight=weight_key).edges(data=weight_key, default=1.0)
        if u != v
    ]
    mean = sum(weights) / len(weights) if weights else 1.0
    return float(interslice) * mean


def detect_leiden_cpm(
    graph: nx.DiGraph,
    palette_name: str,
    resolution: float | None = None,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Leiden algorithm with the Constant Potts Model objective (Traag, Van Dooren & Nesterov 2011).

    Unlike modularity, CPM has no resolution limit: a community is stable when
    its internal edge density exceeds ``resolution`` (γ), independently of
    community size.  Low γ → few large communities; high γ → many small ones.

    Same Leiden machinery as ``detect_leiden``: undirected W+Wᵀ projection via
    ``to_undirected_sum``, weights honoured, seed=0, connectivity refinement.
    Only the quality function differs — and, because CPM (unlike modularity) is
    *not* invariant to a uniform rescale of the weights, the projection sums the
    raw tie weights (``weight_raw``, see :func:`tie_weight_key`) rather than the
    per-graph ×10/max ``weight``. An explicit γ is therefore a density in the units of
    ``--edge-weight-strategy`` (binary under NONE, citation shares under
    PARTIAL_*, counts under TOTAL), comparable across graphs, years and datasets.

    ``resolution=None`` (a bare ``LEIDEN_CPM``) uses the graph's own weighted edge density
    (:func:`cpm_density_resolution`) — the Reichardt–Bornholdt Erdős–Rényi null at γ_RB = 1, invariant
    to a uniform rescale of the weights. :func:`cpm_resolution` reports the γ used. Best of :data:`LEIDEN_RUNS`
    seeded runs by CPM quality.
    """
    node_ids, node_id_map = _node_id_index(graph)
    ig_graph, weights = _build_undirected_igraph(graph, node_ids, node_id_map, weight=tie_weight_key(graph))
    gamma = resolution if resolution is not None else cpm_density_resolution(graph)
    membership = _best_leiden_membership(
        ig_graph,
        leidenalg.CPMVertexPartition,
        objective="CPM quality",
        diagnostics_out=diagnostics_out,
        weights=weights if weights else None,
        resolution_parameter=gamma,
    )
    return _finalize_partition(graph, _assign_from_membership(membership, node_ids), palette_name, reverse=reverse)


def detect_leiden_temporal(
    year_graphs: dict[int, nx.DiGraph],
    palette_name: str,
    resolution: float | None,
    interslice_weight: float,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[dict[int, CommunityMap], CommunityMap, CommunityPalette]:
    """Interslice-coupled temporal communities over the timeline years (Mucha et al. 2010).

    ``year_graphs`` maps each non-empty timeline year to its citation graph (built with the same
    scope/weight settings as that year's export). Each year becomes one **slice** — the undirected
    W+Wᵀ projection with edge weights, exactly as ``LEIDEN_CPM`` sees a single graph (raw tie weights,
    so γ and ω are on one scale across every year rather than each year's own ×10/max rescale) — and
    every channel present in two consecutive slices is tied to *itself* across them by an identity link of
    relative weight ``interslice_weight`` (ω, a multiple of the slices' mean tie weight — see
    :func:`temporal_interslice_weight`). The CPM objective is then optimised over all slices at once,
    so a community's identity is **shared across years**: persistence, splits, and merges become
    properties of the partition itself rather than post-hoc ribbon-reading in the alluvial diagram.
    The identity link ties a channel only to itself in adjacent years — no multi-hop flow claim — so
    the strategy stays inside the one-degree attribution model.

    ``resolution`` is the CPM γ of every slice; ``None`` (auto) gives each slice its **own** weighted
    edge density (:func:`temporal_slice_resolutions`) — the per-slice null of Mucha et al. 2010, which
    ``leidenalg.find_partition_temporal`` (one γ for every slice) cannot express. So the optimisation
    replicates ``find_partition_temporal`` step for step with leidenalg's lower-level API
    (``time_slices_to_layers``, one ``CPMVertexPartition`` per layer, the zero-resolution interslice
    partition, a seeded ``Optimiser.optimise_partition_multiplex``), repeated for :data:`LEIDEN_RUNS` seeds and
    keeping the run with the highest joint quality. ``diagnostics_out`` receives how the runs agree plus the
    absolute identity-link weight used (``interslice_weight``).

    Returns ``(per_year, plurality, palette)``:

    * ``per_year`` — one :type:`CommunityMap` per year, all sharing a single global community-id
      space (ids renumbered once, by total membership across every slice, so "community 3" means
      the same cohort in 2021 and 2022 — and keeps the same colour).
    * ``plurality`` — the full-range summary column: each channel's most frequent community
      across the slices it appears in, ties broken by its latest year's assignment. This is a
      *derived summary* for the full-range map/table, not an independent detection of the
      full-range graph (which is why the strategy is not consensus-eligible).
    * ``palette`` — one palette over the global id space, shared by every year.

    Isolated-in-a-year channels are deliberately *not* merged into a residual community (unlike
    the single-graph detectors): the interslice coupling lets a channel isolated in one year
    inherit its neighbouring years' community, which is exactly the point of the method.
    """
    if len(year_graphs) < 2:
        raise ValueError(
            "LEIDEN_TEMPORAL needs at least two non-empty timeline years to couple; "
            f"got {len(year_graphs)}. Check --timeline-step year and the date window."
        )
    years = sorted(year_graphs)
    # Raw tie weights, not each year's own ×10/max rescale: one γ (and one ω) must couple slices
    # that sit on the same scale, or a year whose heaviest tie is light would be inflated.
    weight_key = tie_weight_key(*year_graphs.values())
    gammas = temporal_slice_resolutions(year_graphs, resolution)
    coupling = temporal_interslice_weight(year_graphs, interslice_weight)
    slices: list[ig.Graph] = []
    for year in years:
        undirected = to_undirected_sum(year_graphs[year], weight=weight_key)
        node_ids = sorted(undirected.nodes())
        node_id_map = {node_id: index for index, node_id in enumerate(node_ids)}
        slice_graph = ig.Graph(n=len(node_ids), directed=False)
        slice_graph.vs["id"] = node_ids  # identity attribute the interslice coupling joins on
        edges, weights = [], []
        for s, t in undirected.edges():
            edges.append((node_id_map[s], node_id_map[t]))
            weights.append(undirected.edges[s, t].get(weight_key, 1.0))
        slice_graph.add_edges(edges)
        slice_graph.es["weight"] = weights
        slices.append(slice_graph)

    # leidenalg.find_partition_temporal(slices, CPMVertexPartition, interslice_weight=ω,
    # vertex_id_attr="id", weight_attr="weight", seed=0, resolution_parameter=γ), unrolled so each
    # layer can carry its own γ. Each layer holds every slice's nodes but only its own slice's edges;
    # node_size is 1 for that slice's nodes and 0 for the rest, so a layer's CPM penalty counts its
    # own slice only. The interslice layer carries the identity links at resolution 0.
    layers, interslice_layer, union = leidenalg.time_slices_to_layers(
        slices, interslice_weight=coupling, vertex_id_attr="id", weight_attr="weight"
    )
    runs: list[tuple[float, list[int]]] = []
    for run in range(LEIDEN_RUNS):
        partitions = [
            leidenalg.CPMVertexPartition(
                layer, node_sizes="node_size", weights="weight", resolution_parameter=gammas[year]
            )
            for year, layer in zip(years, layers, strict=True)
        ]
        interslice_partition = leidenalg.CPMVertexPartition(
            interslice_layer,
            resolution_parameter=TEMPORAL_INTERSLICE_RESOLUTION,
            node_sizes="node_size",
            weights="weight",
        )
        optimiser = leidenalg.Optimiser()
        optimiser.max_comm_size = LEIDEN_MAX_COMM_SIZE
        optimiser.set_rng_seed(LEIDEN_SEED + run)
        layers_to_optimise = partitions + [interslice_partition]
        optimiser.optimise_partition_multiplex(
            layers_to_optimise,
            layer_weights=[TEMPORAL_LAYER_WEIGHT] * len(layers_to_optimise),
            n_iterations=LEIDEN_N_ITERATIONS,
        )
        quality = sum(TEMPORAL_LAYER_WEIGHT * layer_partition.quality() for layer_partition in layers_to_optimise)
        runs.append((quality, list(partitions[0].membership)))
    best_membership = runs[_select_best_run(runs, objective="multislice CPM quality", diagnostics_out=diagnostics_out)][
        1
    ]
    if diagnostics_out is not None:
        diagnostics_out["interslice_weight"] = round(coupling, 6)
    union_membership = {(v["slice"], v["id"]): m for v, m in zip(union.vs, best_membership, strict=True)}
    memberships = [
        [union_membership[(slice_index, v["id"])] for v in slice_graph.vs]
        for slice_index, slice_graph in enumerate(slices)
    ]

    per_year: dict[int, CommunityMap] = {}
    for year, slice_graph, membership in zip(years, slices, memberships, strict=True):
        per_year[year] = {slice_graph.vs[index]["id"]: int(cid) for index, cid in enumerate(membership)}

    # One global renumbering by total membership across all slices (size desc, id asc — the
    # normalize_community_map convention, applied once so ids and colours are stable across years).
    counts = Counter(cid for community_map in per_year.values() for cid in community_map.values())
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    remap = {cid: index for index, (cid, _) in enumerate(ordered, start=1)}
    per_year = {
        year: {node_id: remap[cid] for node_id, cid in community_map.items()}
        for year, community_map in per_year.items()
    }

    # Full-range plurality: most frequent community per channel, ties → the latest year's assignment.
    votes: dict[str, Counter] = {}
    latest: dict[str, int] = {}
    for year in years:
        for node_id, cid in per_year[year].items():
            votes.setdefault(node_id, Counter())[cid] += 1
            latest[node_id] = cid
    plurality: CommunityMap = {}
    for node_id, counter in votes.items():
        top = max(counter.values())
        tied = {cid for cid, count in counter.items() if count == top}
        plurality[node_id] = latest[node_id] if latest[node_id] in tied else min(tied)

    palette = build_community_palette({str(cid): cid for cid in remap.values()}, palette_name, reverse=reverse)
    return per_year, plurality, palette


def detect_louvain(
    graph: nx.DiGraph,
    palette_name: str,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Louvain modularity maximisation (Blondel et al. 2008) — the classic baseline, superseded by Leiden.

    Greedy modularity optimisation on the undirected W+Wᵀ projection
    (``to_undirected_sum``) — the same symmetrised graph and edge-weight handling
    as ``detect_leiden``; only the optimiser differs (no Leiden refinement pass).
    Louvain is the field-standard community detector that predates Leiden; it is
    kept in Pulpit so a run can be compared against the large body of older
    studies that report Louvain partitions. **For Pulpit's own analyses prefer**
    ``LEIDEN`` — or ``LEIDEN_DIRECTED`` when citation direction matters — since
    Leiden adds a refinement step that guarantees every community is internally
    well-connected, fixing the two Louvain weaknesses: occasionally disconnected
    communities, and a sharper exposure to the modularity resolution limit
    (Fortunato & Barthélemy 2007).

    Edge weights from ``--edge-weight-strategy`` shape the partition; citation
    direction is dropped by the symmetrisation (so it shares
    ``UNDIRECTED_BASIS_STRATEGIES`` modularity reporting with ``LEIDEN``).
    NetworkX's Louvain randomises the node-visit order, so it runs
    :data:`LOUVAIN_RUNS` times with seeds ``LOUVAIN_SEED + k`` and the
    highest-modularity run is reported (``diagnostics_out`` receives how the runs agree).
    """
    undirected = to_undirected_sum(graph)
    node_ids, node_id_map = _node_id_index(graph)
    runs: list[tuple[float, list[int]]] = []
    for run in range(LOUVAIN_RUNS):
        communities = nx.community.louvain_communities(
            undirected,
            weight="weight",
            resolution=MODULARITY_RESOLUTION,
            threshold=LOUVAIN_THRESHOLD,
            max_level=LOUVAIN_MAX_LEVEL,
            seed=LOUVAIN_SEED + run,
        )
        quality = (
            nx.community.modularity(undirected, communities, weight="weight", resolution=MODULARITY_RESOLUTION)
            if undirected.number_of_edges()
            else 0.0
        )
        labels = [0] * len(node_ids)
        for index, members in enumerate(communities):
            for node_id in members:
                labels[node_id_map[node_id]] = index
        runs.append((quality, labels))
    membership = runs[_select_best_run(runs, objective="modularity", diagnostics_out=diagnostics_out)][1]
    return _finalize_partition(graph, _assign_from_membership(membership, node_ids), palette_name, reverse=reverse)


def detect_consensus(
    graph: nx.DiGraph,
    palette_name: str,
    input_maps: dict[str, CommunityMap],
    threshold: float,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Consensus partition over the other selected algorithmic strategies (Lancichinetti & Fortunato 2012).

    ``input_maps`` holds one :type:`CommunityMap` per consensus-eligible strategy instance
    (see :func:`consensus_eligible`) — the partitions this run already computed. The
    co-assignment matrix ``D_ij`` = the fraction of input partitions placing ``i`` and ``j``
    in the same community; pairs with ``D_ij ≥ threshold`` become the weighted, undirected
    *consensus graph*, which is clustered with Leiden modularity (best of :data:`LEIDEN_RUNS`
    seeds, the same machinery as ``LEIDEN``). Channels grouped together only when at least a
    ``threshold`` share of the algorithms agree; channels no algorithm coalition can place end
    up as singletons — an honest "no consensus" answer rather than a forced assignment.

    Channels with no tie in ``graph`` are left out of the co-assignment counts: every merging
    detector puts them in one shared residual community (:data:`MERGE_ISOLATED_NODES`), so
    counting them would turn that display convenience into unanimous "agreement" — a clique of
    unrelated channels in the consensus graph. They end up in the residual community here too.

    **Adaptation note.** Lancichinetti & Fortunato iterate — recluster ``D`` with the base
    algorithm ``n_P`` times, rebuild ``D``, repeat until block-diagonal — because their
    inputs are stochastic re-runs of one algorithm. Pulpit's input partitions are
    deterministic (every detector is seeded and reports its best fit), so the procedure degenerates: after the first
    clustering pass the rebuilt ``D`` is exactly the 0/1 block matrix of that partition and
    every further pass is a fixed point. One pass is therefore the faithful specialisation,
    and what runs here. This is *method* consensus (different algorithms, one run each) in
    the lineage of ensemble approaches such as Evkoski et al. 2021's Ensemble Louvain,
    rather than *run* consensus.

    The result is a genuine partition: it joins the ARI/AMI/NMI/VI comparison matrices
    (measuring, e.g., how much of the analyst's label structure survives across-method
    agreement) but is excluded from the consensus balloon plot's inputs, which it would
    double-count. Weights/direction enter only through the input partitions.
    """
    if len(input_maps) < 2:
        raise ValueError(
            "CONSENSUS needs at least two consensus-eligible input partitions "
            "(algorithmic strategies other than KCORE) in --community-strategies."
        )
    node_ids, node_id_map = _node_id_index(graph)
    n_partitions = len(input_maps)
    pair_counts: Counter[tuple[int, int]] = Counter()
    for community_map in input_maps.values():
        by_community: dict[Any, list[int]] = {}
        for node_id, community_id in community_map.items():
            index = node_id_map.get(node_id)
            if index is not None and graph.degree(node_id) > 0:
                by_community.setdefault(community_id, []).append(index)
        for members in by_community.values():
            members.sort()
            pair_counts.update(combinations(members, 2))

    consensus_graph = ig.Graph(n=len(node_ids), directed=False)
    edges: list[tuple[int, int]] = []
    weights: list[float] = []
    for pair, count in pair_counts.items():
        agreement = count / n_partitions
        if agreement >= threshold:
            edges.append(pair)
            weights.append(agreement)
    consensus_graph.add_edges(edges)
    membership = _best_leiden_membership(
        consensus_graph,
        leidenalg.ModularityVertexPartition,
        objective="modularity of the consensus graph",
        diagnostics_out=diagnostics_out,
        weights=weights if weights else None,
    )
    return _finalize_partition(graph, _assign_from_membership(membership, node_ids), palette_name, reverse=reverse)


@contextmanager
def _seeded_graph_tool(gt: Any) -> Iterator[None]:
    """Seed one SBM-family fit: graph-tool's generator and numpy's global one (``SBM_SEED``).

    graph-tool's Python layer draws from numpy's global generator (nested-level shuffles, MCMC
    sweeps, partition-mode initialisation), which ``seed_rng`` does not touch, so both are seeded;
    numpy's previous global state is restored afterwards so the fit leaves no trace on other code.
    """
    import numpy as np

    saved = np.random.get_state()  # noqa: NPY002 — graph-tool draws from numpy's legacy global RNG
    gt.seed_rng(SBM_SEED)
    np.random.seed(SBM_SEED)  # noqa: NPY002
    try:
        yield
    finally:
        np.random.set_state(saved)  # noqa: NPY002


def _mcmc_partition_mode(
    gt: Any, state: Any, gt_graph: Any, node_ids: list[str], sample_blocks: Callable[[Any], Any]
) -> tuple[CommunityMap, dict[str, float]]:
    """``refine=MCMC`` for the SBM family: equilibrate ``state``, collect ``SBM_MCMC_SAMPLES`` posterior
    partitions (``sample_blocks(state)`` reads one), and return each node's max-marginal block after label
    alignment (Peixoto 2021, ``PartitionModeState``) with its assignment confidence — the share of samples
    agreeing with that block."""
    import numpy as np

    mcmc_args = {"niter": SBM_MCMC_SWEEP_NITER, "beta": SBM_MCMC_BETA}
    gt.mcmc_equilibrate(
        state,
        wait=SBM_MCMC_WAIT,
        nbreaks=SBM_MCMC_NBREAKS,
        epsilon=SBM_MCMC_EPSILON,
        multiflip=SBM_MCMC_MULTIFLIP,
        mcmc_args=mcmc_args,
    )

    partitions: list[Any] = []

    def _collect(s: Any) -> None:
        partitions.append(np.asarray(sample_blocks(s).a).copy())

    gt.mcmc_equilibrate(
        state, force_niter=SBM_MCMC_SAMPLES, multiflip=SBM_MCMC_MULTIFLIP, mcmc_args=mcmc_args, callback=_collect
    )
    pmode = gt.PartitionModeState(partitions, relabel=SBM_MODE_RELABEL, converge=SBM_MODE_CONVERGE)
    marginals = pmode.get_marginal(gt_graph)
    b_max = pmode.get_max(gt_graph)
    n_samples = len(partitions)
    community_map: CommunityMap = {}
    confidence: dict[str, float] = {}
    for index, node_id in enumerate(node_ids):
        block = int(b_max[index])
        community_map[node_id] = block
        marginal_counts = marginals[index]
        agree = marginal_counts[block] if block < len(marginal_counts) else 0
        confidence[node_id] = round(float(agree) / n_samples, 4) if n_samples else 0.0
    return community_map, confidence


def _best_sbm_fit(
    fit: Callable[[], Any],
    blocks_of: Callable[[Any], Any],
    *,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> Any:
    """The lowest-description-length state of :data:`SBM_FIT_RESTARTS` graph-tool fits.

    ``fit()`` runs one complete fit (multilevel minimisation plus zero-temperature refinement) and returns its
    state; ``blocks_of(state)`` reads the node-level partition for the agreement diagnostics. The fits draw on
    the RNG stream :func:`_seeded_graph_tool` seeded, so the set of fits — and the choice — is reproducible.
    """
    import numpy as np

    runs: list[tuple[float, Any]] = []
    best_state: Any = None
    for _ in range(SBM_FIT_RESTARTS):
        state = fit()
        entropy = float(state.entropy())
        if best_state is None or entropy < min(quality for quality, _ in runs):
            best_state = state
        runs.append((entropy, np.asarray(blocks_of(state).a).copy()))
    _select_best_run(runs, objective="description length (nats)", minimise=True, diagnostics_out=diagnostics_out)
    return best_state


def detect_sbm(
    graph: nx.DiGraph,
    palette_name: str,
    mode: str,
    weights: str = SBM_DEFAULT_WEIGHTS,
    refine: str = SBM_DEFAULT_REFINE,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette, "dict[str, float] | None"]:
    """Bayesian degree-corrected stochastic block model (Karrer & Newman 2011; Peixoto 2014, 2017) via graph-tool.

    Fits a **directed, degree-corrected** SBM by minimum description length. Unlike the
    modularity / CPM detectors — which only find *assortative* communities (dense-within,
    sparse-between) — the SBM recovers arbitrary block structure: assortative,
    disassortative, core-periphery and bipartite *source / amplifier* patterns alike.
    A block is a set of channels that are *stochastically equivalent* — they cite, and are
    cited by, the rest of the network the same way — i.e. a **citation-role / structural-
    equivalence class** (Lorrain & White 1971), NOT necessarily a cohesive, mutually-citing
    community. The block-affinity matrix entry is a one-step, group-to-group *direct citation
    rate*, never a transmission / flow quantity, so the strategy is consistent with the
    one-degree attribution model (see docs/community-detection.md).

    Built on the **directed** citation graph (direction preserved → asymmetric block
    affinities) and **degree-corrected**, so the partition reflects block structure *beyond*
    the in-degree heterogeneity of the star topology rather than merely re-encoding it.

    ``weights`` selects the edge model. Empty (default): **unweighted** binary citation
    structure — edge weights are not passed, so the partition is invariant to
    ``--edge-weight-strategy``, like ``KCORE``. ``POISSON`` /
    ``EXPONENTIAL`` fit a **weighted SBM** with the edge weights as covariates (Peixoto 2018,
    "Nonparametric weighted stochastic block models"): POISSON models discrete counts (pair
    with ``--edge-weight-strategy TOTAL``), EXPONENTIAL positive reals (pair with the
    ratio-valued ``PARTIAL_*`` strategies). The covariate is the raw tie weight
    (``weight_raw``, see :func:`tie_weight_key`), not the per-graph ×10/max ``weight``, so
    TOTAL's counts stay integers. The weight model is validated against the actual edge
    weights before graph-tool is imported.

    ``mode``: ``NESTED`` (default) fits the nested SBM (Peixoto 2017) and takes the partition
    at the bottom (finest) hierarchy level — better model selection on large graphs, avoiding
    the underfitting of the flat model; ``FLAT`` fits a single-level SBM.

    The point estimate is the lowest description length of :data:`SBM_FIT_RESTARTS` fits, each
    refined by :data:`SBM_REFINE_SWEEPS` zero-temperature merge-split sweeps (graph-tool's advice:
    a single agglomerative fit can stop in a poor local minimum); ``diagnostics_out`` receives how
    the fits agree.

    ``refine``: empty (default) reports that point estimate. ``MCMC`` follows the
    best fit with multiflip MCMC equilibration and collects ``SBM_MCMC_SAMPLES`` posterior
    partitions; the reported partition is then each node's **maximum-marginal** block after
    label alignment (Peixoto 2021, "Revealing consensus and dissensus between network
    partitions", via ``PartitionModeState``), and the third return value maps each node to
    its **assignment confidence** — the share of posterior samples agreeing with the reported
    block (1.0 = the data pin the channel down; low values = structurally ambiguous). Without
    ``MCMC`` the third return value is ``None``.

    graph-tool's inference is stochastic (agglomerative + multiflip MCMC); the RNG is seeded
    for a reproducible partition. Requires the ``graph-tool`` package (conda-forge / system
    packages — it is *not* installable from pip; see docs/community-detection.md).
    """
    weights = (weights or "").upper()
    refine = (refine or "").upper()

    edge_weights: list[float] = []
    if weights:
        # Raw tie weights: the per-graph ×10/max ``weight`` would turn TOTAL's integer counts into
        # non-integers (rejected by POISSON) and put every graph's covariates on its own scale.
        weight_key = tie_weight_key(graph)
        edge_weights = [float(graph.edges[s, t].get(weight_key, 1.0)) for s, t in graph.edges()]
        if weights == "POISSON":
            bad = next((w for w in edge_weights if w < 0 or not w.is_integer()), None)
            if bad is not None:
                raise ValueError(
                    "SBM(weights=POISSON) models edge weights as discrete counts, but the graph carries "
                    f"non-integer weights (e.g. {bad!r}). Use --edge-weight-strategy TOTAL (raw counts), "
                    "or switch to weights=EXPONENTIAL for the ratio-valued PARTIAL_* strategies."
                )
        elif weights == "EXPONENTIAL":
            bad = next((w for w in edge_weights if w <= 0), None)
            if bad is not None:
                raise ValueError(
                    "SBM(weights=EXPONENTIAL) models edge weights as positive reals, but the graph carries "
                    f"a non-positive weight ({bad!r}). Check --edge-weight-strategy."
                )
        else:  # defensive — parse_strategies already validated the enum
            raise ValueError(f"Unknown SBM weights model: {weights!r}. Choose POISSON or EXPONENTIAL.")

    try:
        import graph_tool.all as gt
    except ImportError as exc:  # pragma: no cover - optional heavy dependency
        raise ValueError(
            "The SBM community strategy requires the 'graph-tool' package, which is not installed. "
            "Install it via conda-forge ('conda install -c conda-forge graph-tool') or your system "
            "package manager — it is not available from pip. See docs/community-detection.md."
        ) from exc

    with _seeded_graph_tool(gt):
        node_ids, node_id_map = _node_id_index(graph)
        gt_graph = gt.Graph(directed=True)
        gt_graph.add_vertex(len(node_ids))
        state_args: dict[str, Any] = {"deg_corr": SBM_DEGREE_CORRECTED}
        if weights:
            rec = gt_graph.new_edge_property("int" if weights == "POISSON" else "double")
            gt_graph.add_edge_list(
                [(node_id_map[s], node_id_map[t], w) for (s, t), w in zip(graph.edges(), edge_weights, strict=True)],
                eprops=[rec],
            )
            state_args["recs"] = [rec]
            state_args["rec_types"] = ["discrete-poisson" if weights == "POISSON" else "real-exponential"]
        else:
            gt_graph.add_edge_list([(node_id_map[s], node_id_map[t]) for s, t in graph.edges()])

        nested = mode.upper() != "FLAT"
        fit_args = {"niter": SBM_FIT_NITER, "beta": SBM_FIT_BETA}

        def _fit() -> Any:
            if nested:
                fitted = gt.minimize_nested_blockmodel_dl(
                    gt_graph, state_args=state_args, multilevel_mcmc_args=fit_args
                )
            else:
                fitted = gt.minimize_blockmodel_dl(gt_graph, state_args=state_args, multilevel_mcmc_args=fit_args)
            for _ in range(SBM_REFINE_SWEEPS):
                fitted.multiflip_mcmc_sweep(beta=SBM_FIT_BETA, niter=SBM_REFINE_NITER)
            return fitted

        state = _best_sbm_fit(
            _fit,
            lambda fitted: (fitted.get_levels()[0] if nested else fitted).get_blocks(),
            diagnostics_out=diagnostics_out,
        )

        confidence: dict[str, float] | None = None
        community_map: CommunityMap
        if refine == "MCMC":
            import numpy as np

            if nested:
                # Pad the hierarchy with empty levels so it can grow during sampling — graph-tool's documented
                # equilibration pattern. (Older releases also took ``sampling=True`` here; graph-tool ≥ 2.4x
                # dropped it — nested states are always sampling-ready — and warns on the unknown keyword.)
                state = state.copy(bs=state.get_bs() + [np.zeros(1)] * SBM_NESTED_PAD_LEVELS)
            community_map, confidence = _mcmc_partition_mode(
                gt, state, gt_graph, node_ids, lambda s: s.levels[0].b if nested else s.b
            )
        else:
            blocks = (state.get_levels()[0] if nested else state).get_blocks()
            community_map = {node_ids[index]: int(blocks[index]) for index in range(len(node_ids))}

    final_map, palette = _finalize_partition(graph, community_map, palette_name, reverse=reverse)
    return final_map, palette, confidence


def detect_sbm_assortative(
    graph: nx.DiGraph,
    palette_name: str,
    refine: str = SBM_DEFAULT_REFINE,
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette, "dict[str, float] | None"]:
    """Bayesian planted-partition communities (Zhang & Peixoto 2020) via graph-tool's ``PPBlockState``.

    The **inferential counterpart of Leiden**: like the modularity family it looks only for
    *assortative* structure — groups denser inside than out — but as a generative model selected
    by description length it places a community boundary only where the data statistically
    support one. Zhang & Peixoto show this "succeeds in finding statistically significant
    assortative modules … unlike alternatives such as modularity maximization, which
    systematically overfits", with no resolution limit. Where ``SBM`` answers "which channels
    play the same role?", this answers Leiden's question — "where are the cohesive blocs?" —
    with statistical backing: a partition boundary that survives here is evidence, not an
    optimiser's preference. Read the two side by side in the partition-comparison matrices.

    Fitted on the **undirected W+Wᵀ projection** (assortativity is a symmetric notion — the
    same projection the Leiden family uses) and **unweighted** (binary citation structure, so
    the partition is invariant to ``--edge-weight-strategy``, like ``KCORE`` and the binary
    ``SBM``). Parameter-free and seeded. Each fit starts from graph-tool's multilevel
    ``minimize_blockmodel_dl(state=PPBlockState)`` and is refined by ``PP_GREEDY_NITER``
    zero-temperature merge-split sweeps; the lowest description length of
    :data:`SBM_FIT_RESTARTS` fits is reported (``diagnostics_out`` receives how they agree). A
    single greedy sweep from a random start — the earlier procedure — routinely stopped in a poor
    local minimum, reporting fewer, coarser communities than the data support.

    ``refine``: empty (default) reports that point estimate. ``MCMC`` equilibrates and
    samples the posterior exactly like ``SBM(refine=MCMC)`` — the reported partition becomes
    each channel's max-marginal community and the third return value carries the per-channel
    assignment confidence (share of posterior samples agreeing); ``None`` without MCMC.

    Requires the ``graph-tool`` package (conda-forge / system packages — not pip-installable);
    a clear ``ValueError`` is raised when it is absent.
    """
    refine = (refine or "").upper()
    try:
        import graph_tool.all as gt
    except ImportError as exc:  # pragma: no cover - optional heavy dependency
        raise ValueError(
            "The SBM_ASSORTATIVE community strategy requires the 'graph-tool' package, which is not "
            "installed. Install it via conda-forge ('conda install -c conda-forge graph-tool') or your "
            "system package manager — it is not available from pip. See docs/community-detection.md."
        ) from exc

    with _seeded_graph_tool(gt):
        node_ids, node_id_map = _node_id_index(graph)
        undirected = to_undirected_sum(graph)
        gt_graph = gt.Graph(directed=False)
        gt_graph.add_vertex(len(node_ids))
        gt_graph.add_edge_list([(node_id_map[s], node_id_map[t]) for s, t in undirected.edges()])

        fit_args = {"niter": SBM_FIT_NITER, "beta": SBM_FIT_BETA}

        def _fit() -> Any:
            fitted = gt.minimize_blockmodel_dl(gt_graph, state=gt.PPBlockState, multilevel_mcmc_args=fit_args)
            fitted.multiflip_mcmc_sweep(beta=PP_GREEDY_BETA, niter=PP_GREEDY_NITER)
            return fitted

        state = _best_sbm_fit(_fit, lambda fitted: fitted.get_blocks(), diagnostics_out=diagnostics_out)

        confidence: dict[str, float] | None = None
        community_map: CommunityMap
        if refine == "MCMC":
            community_map, confidence = _mcmc_partition_mode(gt, state, gt_graph, node_ids, lambda s: s.get_blocks())
        else:
            blocks = state.get_blocks()
            community_map = {node_ids[index]: int(blocks[index]) for index in range(len(node_ids))}

    final_map, palette = _finalize_partition(graph, community_map, palette_name, reverse=reverse)
    return final_map, palette, confidence


def _write_confidence(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    instance: "StrategyInstance",
    confidence: "dict[str, float] | None",
) -> None:
    """Attach an SBM-family ``refine=MCMC`` confidence map to the node data and channel_dict.

    The confidence companion rides on the node data like a measure column, under the instance's
    parameter-suffixed key (:func:`sbm_confidence_key`); exporters probe the nodes for its presence.
    No-op when ``confidence`` is ``None``/empty (no MCMC refinement ran).
    """
    if not confidence:
        return
    conf_key = sbm_confidence_key(instance.key)
    for node_id, value in confidence.items():
        if node_id in graph.nodes:
            graph.nodes[node_id].setdefault("data", {})[conf_key] = value
        entry = channel_dict.get(node_id)
        if entry is not None:
            entry["data"][conf_key] = value


def detect(
    instance: "StrategyInstance | str",
    palette_name: str,
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    *,
    reverse: bool = False,
    diagnostics_out: "dict[str, Any] | None" = None,
) -> tuple[CommunityMap, CommunityPalette]:
    """Run community detection for one strategy instance. Returns (community_map, community_palette).

    ``instance`` is a :class:`StrategyInstance`; a bare strategy-name string is also accepted (wrapped
    as a parameter-free instance) for convenience. Parameterised strategies read their tunable values
    from the instance — LEIDEN_CPM its ``resolution`` γ, which when omitted (auto) is the weighted edge
    density of ``graph`` (:func:`cpm_resolution` reports the γ used).

    ``diagnostics_out``, when given, receives the fit summary of the stochastic detectors — how many
    seeded fits ran, the best and worst objective value, and how far the fits agree with the reported
    partition (:func:`_select_best_run`). KCORE and the label-group partitions are deterministic and
    leave it empty.
    """
    if isinstance(instance, str):
        instance = StrategyInstance(instance.upper())
    strategy = instance.name
    params = instance.params_dict
    if strategy == "CONSENSUS":
        # Derived from the other strategies' partitions — the export pipeline dispatches it to
        # detect_consensus() after every other strategy has run; it cannot be detected standalone.
        raise ValueError(
            "CONSENSUS is computed from the other selected strategies' partitions and is "
            "dispatched separately by the export pipeline (detect_consensus), not by detect()."
        )
    if strategy == "LEIDEN_TEMPORAL":
        # Needs every timeline year's slice at once — the export pipeline precomputes it via
        # detect_leiden_temporal() and applies the per-year / plurality maps directly.
        raise ValueError(
            "LEIDEN_TEMPORAL is computed over the per-year timeline slices and is dispatched "
            "separately by the export pipeline (detect_leiden_temporal), not by detect()."
        )
    if strategy == "KCORE":
        return detect_kcore(graph, palette_name, reverse=reverse)
    if strategy == "LEIDEN":
        return detect_leiden(graph, palette_name, reverse=reverse, diagnostics_out=diagnostics_out)
    if strategy == "LEIDEN_DIRECTED":
        return detect_leiden_directed(graph, palette_name, reverse=reverse, diagnostics_out=diagnostics_out)
    if strategy == "LEIDEN_CPM":
        # An omitted / auto resolution reaches the detector as None → the graph's own density.
        return detect_leiden_cpm(
            graph, palette_name, instance_resolution(instance), reverse=reverse, diagnostics_out=diagnostics_out
        )
    if strategy == "LOUVAIN":
        return detect_louvain(graph, palette_name, reverse=reverse, diagnostics_out=diagnostics_out)
    if strategy == "SBM":
        community_map, community_palette, confidence = detect_sbm(
            graph,
            palette_name,
            str(params.get("mode", SBM_DEFAULT_MODE)),
            str(params.get("weights", SBM_DEFAULT_WEIGHTS) or ""),
            str(params.get("refine", SBM_DEFAULT_REFINE) or ""),
            reverse=reverse,
            diagnostics_out=diagnostics_out,
        )
        _write_confidence(graph, channel_dict, instance, confidence)
        return community_map, community_palette
    if strategy == "SBM_ASSORTATIVE":
        community_map, community_palette, confidence = detect_sbm_assortative(
            graph,
            palette_name,
            str(params.get("refine", SBM_DEFAULT_REFINE) or ""),
            reverse=reverse,
            diagnostics_out=diagnostics_out,
        )
        _write_confidence(graph, channel_dict, instance, confidence)
        return community_map, community_palette
    gid = labelgroup_id(strategy)
    if gid is not None:
        # LABELGROUP<id> builds its palette from each Label's own colour directly, so the
        # palette_name / reverse flags don't apply.
        return detect_labelgroup(gid, channel_dict)
    raise ValueError(f"Unknown community strategy: {strategy!r}. Choose from {sorted(VALID_STRATEGIES)}.")


def apply_to_graph(
    graph: nx.DiGraph,
    channel_dict: dict[str, Any],
    community_map: CommunityMap,
    community_palette: CommunityPalette,
    strategy: "StrategyInstance | str",
) -> None:
    """Write this strategy instance's community label into each node's communities dict, plus colours.

    ``strategy`` is a :class:`StrategyInstance` (a bare name string is also accepted); the partition is
    stored under ``instance.key`` — the parameter-suffixed key for parameterised strategies, the plain
    lowercase name otherwise.
    """
    instance = strategy if isinstance(strategy, StrategyInstance) else StrategyInstance(str(strategy).upper())
    strategy_name = instance.name
    strategy_key = instance.key
    metadata = is_metadata_strategy(strategy_name)
    if metadata:
        label_ids = set(community_map.values())
        label_names = {lbl.pk: lbl.name for lbl in Label.objects.filter(pk__in=label_ids)}

    for node_id, node_data in graph.nodes(data="data"):
        community_id = community_map.get(node_id)
        if community_id is not None:
            detected_community = (
                label_names.get(community_id, str(community_id))
                if metadata
                else build_community_label(community_id, strategy_name)
            )
            node_data.setdefault("communities", {})[strategy_key] = detected_community
            channel_dict[node_id]["data"].setdefault("communities", {})[strategy_key] = detected_community
        community_color = community_palette.get(community_id) if community_id is not None else DEFAULT_FALLBACK_COLOR
        if community_color is None:
            community_color = DEFAULT_FALLBACK_COLOR
        rgb_color = ",".join(str(value) for value in community_color)
        node_data["color"] = rgb_color
        channel_dict[node_id]["data"]["color"] = rgb_color


def apply_edge_colors(graph: nx.DiGraph, edge_list: list[list[str | float]], channel_dict: dict[str, Any]) -> None:
    """Assign averaged colors to graph edges."""
    for edge in edge_list:
        source_color = channel_dict[edge[0]]["data"]["color"]
        target_color = channel_dict[edge[1]]["data"]["color"]
        color = rgb_avg(parse_color(source_color), parse_color(target_color))
        color_strs = [str(int(c * 0.75)) for c in color]
        graph.edges[edge[0], edge[1]]["color"] = ",".join(color_strs)


def build_communities_payload(
    strategies: list["StrategyInstance"],
    results: dict[str, tuple[CommunityMap, CommunityPalette]],
) -> dict[str, Any]:
    """Build the communities metadata dict for the accessory JSON file, covering all strategy instances.

    ``results`` is keyed by ``StrategyInstance.key`` (the parameter-suffixed partition key); the
    returned dict is keyed the same way.
    """
    communities_data: dict[str, Any] = {}
    for instance in strategies:
        strategy = instance.name
        strategy_key = instance.key
        community_map, community_palette = results[strategy_key]
        if strategy in COMMUNITY_ALGORITHMS:
            community_counts = Counter(community_map.values())
            groups = []
            for community_id, count in community_counts.items():
                rgb = community_palette.get(community_id, DEFAULT_FALLBACK_COLOR)
                detected_community = build_community_label(community_id, strategy)
                groups.append((str(community_id), count, detected_community, rgb_to_hex(rgb)))
            main_groups = {
                str(community_id): build_community_label(community_id, strategy) for community_id in community_counts
            }
        else:
            # LABELGROUP<id>: counts come from the resolved per-window community map (consistent with
            # node colouring), not a raw membership count — only labels that actually own a node appear.
            community_counts = Counter(community_map.values())
            label_objs = {lbl.pk: lbl for lbl in Label.objects.filter(pk__in=list(community_counts))}
            groups = [
                (label_id, count, label_objs[label_id].name, label_objs[label_id].color)
                for label_id, count in community_counts.items()
                if label_id in label_objs
            ]
            main_groups = {
                label_objs[label_id].key: label_objs[label_id].name
                for label_id in community_counts
                if label_id in label_objs
            }
        if strategy == "KCORE":
            groups = sorted(groups, key=lambda x: int(x[0]))
        else:
            groups = sorted(groups, key=lambda x: -x[1])
        communities_data[strategy_key] = {"groups": groups, "main_groups": main_groups}
    return communities_data

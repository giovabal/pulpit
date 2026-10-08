"""The parameters behind an export, written to ``PARAMETERS.md`` by ``structural_analysis``.

Two kinds of parameter shape every number an export reports:

* **Run options** — what the analyst chose (CLI flags / Operations panel / configuration
  fallbacks), as resolved for the run: ``ResolvedOptions`` in the command.
* **Fixed parameters** — values the code itself decides: named constants, seeds, iteration
  counts, thresholds, and the library defaults the code relies on. Each analysis module
  declares its own in a module-level ``FIXED_PARAMETERS`` tuple of :class:`FixedParameter`,
  next to the constants it uses, so the document is read from the very values the
  computation uses and cannot drift from them. A library default the code relies on is
  named as a module constant and passed explicitly, so it is declared like any other.

``scope`` says which part of the run a fixed parameter affects; the document lists a fixed
parameter only when its scope was active in the run. Scope keys:

* ``graph`` — graph construction and edge weights (always active)
* ``near_copies`` — near-copy edges (``--near-copy-edges``)
* ``environment`` — environment channels admitted (``--environment-depth`` > 0)
* ``measure:<TOKEN>`` — a selected measure, e.g. ``measure:PAGERANK``, ``measure:MODULEROLE``
* ``communities`` — any community detection (settings shared by every strategy)
* ``strategy:<TOKEN>`` — a selected strategy family, e.g. ``strategy:LEIDEN_CPM``,
  ``strategy:SBM``; ``strategy:LABELGROUP`` for the analyst's label-group partitions
* ``community_backbone`` — detection on the disparity backbone (``--community-backbone-alpha``)
* ``community_stats`` — whole-network and per-community statistics
* ``layout_2d`` / ``layout_3d`` — the main (ForceAtlas2) map layouts
* ``layout:<TOKEN>`` — an extra map layout (``--layouts-2d`` / ``--layouts-3d``), e.g. ``layout:TSNE``
* ``robustness`` / ``robustness_replay`` — the robustness analysis and its ban replay
* ``coordination`` — the co-forwarding coordination layer
* ``dominance`` — the dominance analysis
* ``vacancy`` — the vacancy (replacement-candidate) analysis
* ``interest`` — the structural interest of messages
* ``timeline`` — the per-year exports
"""

import datetime
import importlib
import importlib.metadata
import importlib.util
import logging
import math
import numbers
import os
import platform
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

SCOPES: frozenset[str] = frozenset(
    {
        "graph",
        "near_copies",
        "environment",
        "communities",
        "community_backbone",
        "community_stats",
        "layout_2d",
        "layout_3d",
        "robustness",
        "robustness_replay",
        "coordination",
        "dominance",
        "vacancy",
        "interest",
        "timeline",
    }
)
SCOPE_PREFIXES: tuple[str, ...] = ("measure:", "strategy:", "layout:")


def is_valid_scope(scope: str) -> bool:
    """Whether ``scope`` is one of :data:`SCOPES` or a ``measure:`` / ``strategy:`` token scope."""
    if scope in SCOPES:
        return True
    return any(scope.startswith(prefix) and len(scope) > len(prefix) for prefix in SCOPE_PREFIXES)


@dataclass(frozen=True)
class FixedParameter:
    """One value fixed in the code that influences a measure or computation.

    ``name`` is a short human label ("PageRank damping factor α"), ``value`` the live value
    (the constant itself, never a copy), ``scope`` a key from the module docstring, ``affects``
    one sentence on what it changes, ``source`` where it is set (``module.py: CONSTANT``), and
    ``note`` an optional reference or rationale.
    """

    name: str
    value: object
    scope: str
    affects: str
    source: str
    note: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# PARAMETERS.md — the reproducibility record of an export
# ══════════════════════════════════════════════════════════════════════════════
#
# Nothing below imports an analysis module at load time: those modules import this one for
# FixedParameter, so the collectors import them lazily, by name.

PARAMETERS_FILENAME = "PARAMETERS.md"

# Modules whose ``FIXED_PARAMETERS`` the document collects. A package (``network.measures``,
# ``network.robustness``) aggregates its submodules' declarations in its ``__init__``.
PARAMETER_MODULES: tuple[str, ...] = (
    "network.graph_builder",
    "network.utils",
    "network.near_copies",
    "network.measures",
    "network.community",
    "network.community_stats",
    "network.layout",
    "network.robustness",
    "network.dominance",
    "network.coordination",
    "network.vacancy_analysis",
    "network.interest_structural",
)

# Sections of the "Fixed parameters" part, in document order, and the scope(s) each one lists.
SECTION_ORDER: tuple[str, ...] = (
    "Graph & edges",
    "Measures",
    "Communities",
    "Network & community statistics",
    "Layout",
    "Robustness",
    "Coordination",
    "Dominance",
    "Vacancy analysis",
    "Structural interest",
    "Timeline",
)
_SECTION_BY_SCOPE: dict[str, str] = {
    "graph": "Graph & edges",
    "near_copies": "Graph & edges",
    "environment": "Graph & edges",
    "communities": "Communities",
    "community_backbone": "Communities",
    "community_stats": "Network & community statistics",
    "layout_2d": "Layout",
    "layout_3d": "Layout",
    "robustness": "Robustness",
    "robustness_replay": "Robustness",
    "coordination": "Coordination",
    "dominance": "Dominance",
    "vacancy": "Vacancy analysis",
    "interest": "Structural interest",
    "timeline": "Timeline",
}
_SECTION_BY_PREFIX: dict[str, str] = {"measure:": "Measures", "strategy:": "Communities", "layout:": "Layout"}

# Row order inside a section: the plain scopes in this order, then the token scopes alphabetically.
_SCOPE_RANK: dict[str, int] = {scope: rank for rank, scope in enumerate(_SECTION_BY_SCOPE)}

# "Applies to" label of a scope, shown when a section mixes several scopes.
_SCOPE_LABELS: dict[str, str] = {
    "graph": "graph construction",
    "near_copies": "near-copy edges",
    "environment": "environment channels",
    "communities": "every strategy",
    "community_backbone": "detection backbone",
    "community_stats": "statistics",
    "layout_2d": "2D layout",
    "layout_3d": "3D layout",
    "robustness": "robustness",
    "robustness_replay": "ban replay",
    "coordination": "coordination",
    "dominance": "dominance",
    "vacancy": "vacancy analysis",
    "interest": "structural interest",
    "timeline": "timeline",
    "strategy:LABELGROUP": "label-group partitions",
}


def section_of(scope: str) -> str:
    """The "Fixed parameters" section a scope is listed under."""
    if scope in _SECTION_BY_SCOPE:
        return _SECTION_BY_SCOPE[scope]
    for prefix, section in _SECTION_BY_PREFIX.items():
        if scope.startswith(prefix):
            return section
    return "Other"


def scope_label(scope: str) -> str:
    """Short human label of a scope (``measure:PAGERANK`` → ``PAGERANK``)."""
    if scope in _SCOPE_LABELS:
        return _SCOPE_LABELS[scope]
    for prefix in SCOPE_PREFIXES:
        if scope.startswith(prefix):
            return scope[len(prefix) :]
    return scope


def _scope_sort_key(scope: str) -> tuple[int, str]:
    return (_SCOPE_RANK.get(scope, len(_SCOPE_RANK)), scope)


def declared_parameters(modules: Iterable[str] = PARAMETER_MODULES) -> list[FixedParameter]:
    """Every :class:`FixedParameter` the given modules declare, in module and declaration order.

    Read defensively — ``getattr(module, "FIXED_PARAMETERS", ())`` — so a module that declares
    nothing contributes nothing. Entries that are not a ``FixedParameter`` or carry an unknown
    scope are skipped with a warning (``network.tests`` fails on them); an exact duplicate
    (same name, scope and source, e.g. re-exported by a package) is listed once.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[FixedParameter] = []
    for name in modules:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            logger.warning("PARAMETERS.md: cannot import %s (%s); its fixed parameters are not listed.", name, exc)
            continue
        for entry in getattr(module, "FIXED_PARAMETERS", ()) or ():
            if not isinstance(entry, FixedParameter):
                logger.warning(
                    "PARAMETERS.md: %s.FIXED_PARAMETERS holds a non-FixedParameter %r; skipped.", name, entry
                )
                continue
            if not is_valid_scope(entry.scope):
                logger.warning(
                    "PARAMETERS.md: %s declares %r with unknown scope %r; skipped.", name, entry.name, entry.scope
                )
                continue
            identity = (entry.name, entry.scope, entry.source)
            if identity in seen:
                continue
            seen.add(identity)
            out.append(entry)
    return out


def active_scopes(opts: Any, *, coordination_laid_out: bool = True) -> set[str]:
    """The scopes of the parts of the analysis a run with the resolved options ``opts`` computes.

    ``opts`` is the command's ``ResolvedOptions``. The derivation mirrors ``structural_analysis``:

    * ``graph`` always; ``near_copies`` with ``--near-copy-edges``; ``environment`` when the
      resolved ``--environment-depth`` is set (it resolves to ``None`` when 0 or nothing is registered).
    * ``measure:<NAME>`` per selected measure (a setting shared by two measures — HITS hub and
      authority come out of one computation — is declared under both scopes and listed once).
    * ``communities`` + ``strategy:<FAMILY>`` per selected strategy (``strategy:LABELGROUP`` for the
      ``LABELGROUP<id>`` partitions); ``community_backbone`` when ``--community-backbone-alpha`` > 0
      and at least one algorithmic strategy runs on it.
    * ``community_stats`` whenever ``community_stats`` computes something: the network/community
      tables (``--html``, ``--xlsx``, ``--consensus-matrix``), the structural / behavioural
      equivalence matrices, and every timeline year (the per-year export always computes them).
    * ``layout_2d`` for either structural map (the 3D map is seeded from the same pass, which also
      computes the 2D positions) and for the coordination maps, whose own 2D layout is always
      computed when ties exist (``coordination_laid_out``); ``layout_3d`` for ``--graph-3d`` and
      ``--coordination-3d``; ``layout:<TOKEN>`` per extra layout selected for a map that is drawn.
    * ``robustness`` (+ ``robustness_replay``, which only runs inside it), ``coordination``,
      ``dominance``, ``vacancy``, ``interest`` and ``timeline`` with their own options.
    """
    from network.community import is_metadata_strategy

    scopes = {"graph"}
    if opts.include_near_copies:
        scopes.add("near_copies")
    if opts.environment_depth:
        scopes.add("environment")

    scopes.update(f"measure:{inst.measure}" for inst in opts.measure_instances)

    if opts.communities_strategy:
        scopes.add("communities")
        algorithmic = False
        for inst in opts.communities_strategy:
            if is_metadata_strategy(inst.name):
                scopes.add("strategy:LABELGROUP")
            else:
                scopes.add(f"strategy:{inst.name}")
                algorithmic = True
        if opts.community_backbone_alpha and algorithmic:
            scopes.add("community_backbone")

    timeline = opts.timeline_step == "year"
    if (
        opts.do_html
        or opts.do_xlsx
        or opts.do_consensus_matrix
        or opts.do_structural_similarity
        or opts.do_behavioural_equivalence
        or timeline
    ):
        scopes.add("community_stats")

    if opts.do_graph or opts.do_3dgraph:
        scopes.add("layout_2d")
    if opts.do_3dgraph:
        scopes.add("layout_3d")
    # Extra layouts run only for the map they belong to (2D tokens with the 2D map, 3D with the 3D).
    if opts.do_graph:
        scopes.update(f"layout:{name}" for name in opts.extra_layout_names)
    if opts.do_3dgraph:
        scopes.update(f"layout:{name}" for name in opts.extra_layout_names_3d)
    if opts.do_coordination:
        scopes.add("coordination")
        if coordination_laid_out:
            scopes.add("layout_2d")
            if opts.do_coordination_3d:
                scopes.add("layout_3d")

    if opts.do_robustness:
        scopes.add("robustness")
        if opts.do_robustness_replay:
            scopes.add("robustness_replay")
    if opts.do_dominance:
        scopes.add("dominance")
    if opts.do_vacancy:
        scopes.add("vacancy")
    if opts.do_interest_structural:
        scopes.add("interest")
    if timeline:
        scopes.add("timeline")
    return scopes


@dataclass(frozen=True)
class ListedParameter(FixedParameter):
    """A :class:`FixedParameter` as the document lists it: ``scopes`` are all the active scopes it
    was declared under (one setting may be declared once per scope it serves — e.g. HITS for both
    ``measure:HITSHUB`` and ``measure:HITSAUTH``); ``scope`` stays the first of them."""

    scopes: tuple[str, ...] = ()


def collect_fixed_parameters(
    scopes: Iterable[str], declared: Iterable[FixedParameter] | None = None
) -> dict[str, list[ListedParameter]]:
    """The declared fixed parameters whose scope is in ``scopes``, grouped by section.

    ``declared`` defaults to :func:`declared_parameters` (every analysis module). A setting declared
    under several active scopes — same ``(name, source)`` — is listed once, in the section of its
    first declaration, with every active scope in ``scopes``. Sections come in
    :data:`SECTION_ORDER` (empty ones omitted); inside a section, rows are grouped by scope and keep
    their declaration order.
    """
    active = set(scopes)
    params = declared_parameters() if declared is None else list(declared)
    listed: list[ListedParameter] = []
    position: dict[tuple[str, str], int] = {}
    for param in params:
        if param.scope not in active:
            continue
        identity = (param.name, param.source)
        if identity in position:
            first = listed[position[identity]]
            if param.scope not in first.scopes:
                listed[position[identity]] = replace(first, scopes=(*first.scopes, param.scope))
            continue
        position[identity] = len(listed)
        values = {f.name: getattr(param, f.name) for f in fields(FixedParameter)}  # no deep copy of the value
        listed.append(ListedParameter(**values, scopes=(param.scope,)))
    grouped: dict[str, list[tuple[tuple[int, str], int, ListedParameter]]] = {}
    for index, param in enumerate(listed):
        grouped.setdefault(section_of(param.scope), []).append((_scope_sort_key(param.scope), index, param))
    order = [*SECTION_ORDER, *sorted(set(grouped) - set(SECTION_ORDER))]
    return {section: [p for *_, p in sorted(grouped[section])] for section in order if section in grouped}


# ── Software versions ─────────────────────────────────────────────────────────

# (display name, distribution names tried in turn, import name for a ``__version__`` fallback —
# graph-tool is installed by conda/apt and has no pip metadata — and what it computes).
LIBRARIES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("networkx", ("networkx",), "networkx", "graph model, centrality measures, paths, clustering, Louvain, k-core"),
    ("python-igraph", ("igraph", "python-igraph"), "igraph", "graph backend of the Leiden detections"),
    ("leidenalg", ("leidenalg",), "leidenalg", "Leiden, CPM, temporal and consensus partitions"),
    ("graph-tool", ("graph-tool", "graph_tool"), "graph_tool", "stochastic block models (SBM, SBM_ASSORTATIVE)"),
    ("numpy", ("numpy",), "numpy", "numerical arrays and random number generation"),
    ("scipy", ("scipy",), "scipy", "sparse linear algebra, hypergeometric tests, SpringRank"),
    ("scikit-learn", ("scikit-learn",), "sklearn", "partition comparison (ARI, AMI, NMI), t-SNE layouts"),
    ("umap-learn", ("umap-learn",), "umap", "UMAP layouts"),
    ("fa2", ("fa2",), "fa2", "ForceAtlas2 map layouts"),
    ("Django", ("Django",), "django", "the database queries every count is read from"),
)


def _library_version(distributions: tuple[str, ...], module_name: str) -> str:
    for dist in distributions:
        try:
            return importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            continue
    module = sys.modules.get(module_name)
    if module is None:
        try:
            if importlib.util.find_spec(module_name) is None:
                return "not installed"
        except (ImportError, ValueError):
            return "not installed"
        try:
            module = importlib.import_module(module_name)
        except Exception:  # any import failure means "present but unusable"
            return "installed, not importable"
    version = str(getattr(module, "__version__", "") or "").strip()
    return version.split()[0] if version else "installed (version unknown)"


def library_versions() -> list[tuple[str, str, str]]:
    """``(library, version, what it computes)`` for every library behind the export's numbers."""
    return [(name, _library_version(dists, module), purpose) for name, dists, module, purpose in LIBRARIES]


# ── Value formatting ──────────────────────────────────────────────────────────


def _format_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "∞" if value > 0 else "−∞"
    return format(value, ".6g")


def _code(text: object) -> str:
    """``text`` as an inline code span (plain when it is empty or holds a backtick)."""
    text = str(text)
    return f"`{text}`" if text and "`" not in text else text


def format_value(value: object) -> str:
    """Readable Markdown for a parameter value: floats without float noise (6 significant
    digits), booleans as yes/no, strings as code, collections joined, mappings as ``k = v``."""
    if value is None:
        return "none"
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        return "yes" if value else "no"
    if isinstance(value, numbers.Integral):
        return str(int(value))
    if isinstance(value, numbers.Real):
        return _format_float(float(value))
    if isinstance(value, str):
        return _code(value) if value else "empty"
    if isinstance(value, Mapping):
        return ", ".join(f"{key} = {format_value(item)}" for key, item in value.items()) or "empty"
    if isinstance(value, (set, frozenset)):
        return ", ".join(format_value(item) for item in sorted(value, key=str)) or "empty"
    if isinstance(value, (list, tuple, range)):
        return ", ".join(format_value(item) for item in value) or "empty"
    enum_value = getattr(value, "value", None)
    if enum_value is not None and type(value).__module__ != "builtins" and hasattr(type(value), "__members__"):
        return format_value(enum_value)
    if callable(value):
        return _code(getattr(value, "__qualname__", None) or getattr(value, "__name__", None) or repr(value))
    return str(value)


def _cell(text: object) -> str:
    """A table cell: pipes escaped, line breaks folded."""
    return " ".join(str(text).split("\n")).replace("|", "\\|")


def _table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return lines


def _yes(flag: object) -> str:
    return "yes" if flag else "no"


def _flags(*names: str) -> str:
    return " / ".join(_code(name) for name in names)


# ── Run options ───────────────────────────────────────────────────────────────


@dataclass
class RunFacts:
    """Values the command resolves while it runs, recorded next to the options that led to them.

    ``community_resolutions`` is the full-range ``{partition key: γ}`` (a ``{"<year>": γ}`` dict for a
    LEIDEN_TEMPORAL instance) and ``year_resolutions`` the same per timeline year; ``measure_notes``
    maps a measure token to what became of it (``MODULEROLE``'s resolved basis, a skipped instance).
    The ``fa2_iterations`` values are the resolved run lengths, ``coordination_ties`` the number of
    full-range coordination ties (``None`` = not computed), ``interest_*`` the automatically chosen
    structural-interest basis and authority attribute.
    """

    nodes: int | None = None
    edges: int | None = None
    community_resolutions: dict[str, Any] = field(default_factory=dict)
    year_resolutions: dict[int, dict[str, Any]] = field(default_factory=dict)
    measure_notes: dict[str, str] = field(default_factory=dict)
    fa2_iterations: int | None = None
    coordination_fa2_iterations: int | None = None
    coordination_ties: int | None = None
    near_copies: int | None = None
    interest_community: str = ""
    interest_authority: str = ""
    timeline_years: list[int] = field(default_factory=list)


_EDGE_WEIGHT_DESCRIPTIONS: dict[str, str] = {
    "NONE": "every citing pair weighs 1",
    "TOTAL": "the raw count of forwards and links",
    "PARTIAL_MESSAGES": "the count divided by the citing channel's total messages",
    "PARTIAL_REFERENCES": "the count divided by the citing channel's citing messages (those carrying a forward or "
    "a t.me/ link)",
}

_MEASURE_DESCRIPTIONS: dict[str, str] = {
    "PAGERANK": "PageRank: importance from being cited by important channels.",
    "HITSHUB": "HITS hub score: citing many good authorities.",
    "HITSAUTH": "HITS authority score: being cited by many good hubs.",
    "INDEGCENTRALITY": "Share of the other channels that cite this one (unweighted).",
    "OUTDEGCENTRALITY": "Share of the other channels this one cites (unweighted).",
    "BURTCONSTRAINT": "Burt's constraint: how redundant a channel's ties are (low = structural-hole broker).",
    "LOCALCLUSTERING": "Directed local clustering coefficient (Fagiolo 2007).",
    "RECIPROCITY": "Share of a channel's citation partners that cite it back.",
    "MODULEROLE": "Guimerà–Amaral within-module degree z, participation coefficient and role, read against the "
    "basis partition.",
    "AMPLIFICATION": "Forwards received from channels in scope per own message.",
    "CONTENTORIGINALITY": "1 − the share of the channel's messages that are forwards.",
    "DIFFUSIONLAG": "Median hours between an original post and its forwards, within the window.",
}

_STRATEGY_DESCRIPTIONS: dict[str, str] = {
    "LEIDEN": "Leiden modularity partition of the undirected (W+Wᵀ) projection.",
    "LEIDEN_DIRECTED": "Leiden partition maximising directed modularity.",
    "LEIDEN_CPM": "Leiden partition under the Constant Potts Model at resolution γ.",
    "LEIDEN_TEMPORAL": "Multislice Leiden/CPM over the yearly slices, coupled across years by ω (Mucha et al. 2010).",
    "LOUVAIN": "Classic Louvain modularity partition, kept as a comparison baseline.",
    "KCORE": "k-core shell decomposition of the undirected projection.",
    "SBM": "Directed degree-corrected stochastic block model (citation-role classes).",
    "SBM_ASSORTATIVE": "Bayesian planted-partition SBM: statistically supported cohesive communities.",
    "CONSENSUS": "Lancichinetti–Fortunato consensus of the other selected partitions at threshold τ.",
}

# How an omitted (empty-default, auto-resolved) token parameter reads in the document.
_AUTO_PARAMETER_VALUES: dict[str, str] = {
    "resolution": "auto (network density)",
    "weights": "none (binary fit)",
    "refine": "none (single fit)",
    "basis": "auto",
}

Row = tuple[str, str, str, str]


def _token_parameters(instance: Any, *, skip: tuple[str, ...] = ()) -> list[str]:
    """``label = value`` for each declared parameter of a measure / strategy instance."""
    spec = instance.spec
    if spec is None:
        return []
    values = instance.params_dict
    parts: list[str] = []
    for param in spec.params:
        if param.name in skip:
            continue
        value = values.get(param.name, param.default)
        shown = _AUTO_PARAMETER_VALUES.get(param.name, "auto") if value in ("", None) else format_value(value)
        parts.append(f"{param.label or param.name} = {shown}")
    return parts


def _measure_rows(opts: Any, facts: RunFacts) -> list[Row]:
    rows: list[Row] = []
    for inst in opts.measure_instances:
        token = inst.token()
        note = facts.measure_notes.get(token, "")
        if inst.measure == "MODULEROLE" and note:
            parts = [note]  # the resolved basis (or why the instance was skipped) replaces "basis = auto"
        else:
            parts = _token_parameters(inst)
            if inst.measure == "DIFFUSIONLAG" and inst.params_dict.get("window") == 0:
                parts = ["Window (days) = 0 (no window)"]
            if note:
                parts.append(note)
        description = _MEASURE_DESCRIPTIONS.get(inst.measure, "")
        rows.append((_code(token), "; ".join(parts) or "—", _code("--measures"), description))
    return rows


def _strategy_value(inst: Any, opts: Any, facts: RunFacts) -> str:
    from network.community import consensus_eligible

    gamma_used = facts.community_resolutions.get(inst.key)
    explicit = inst.params_dict.get("resolution") not in ("", None)
    parts: list[str] = []
    if inst.name == "LEIDEN_CPM":
        if explicit:
            parts.append(f"Resolution γ = {format_value(inst.params_dict['resolution'])}")
        elif isinstance(gamma_used, numbers.Real):
            where = "the detection backbone's" if opts.community_backbone_alpha else "the network's"
            parts.append(f"Resolution γ = {format_value(gamma_used)} ({where} weighted edge density)")
        else:
            parts.append("Resolution γ = auto (the network's weighted edge density)")
    elif inst.name == "LEIDEN_TEMPORAL":
        if explicit:
            parts.append(f"Resolution γ = {format_value(inst.params_dict['resolution'])} in every year")
        else:
            parts.append("Resolution γ = each year's own weighted edge density (see the table below)")
    parts.extend(_token_parameters(inst, skip=("resolution",)))
    if inst.name == "CONSENSUS":
        inputs = [i.label for i in opts.communities_strategy if consensus_eligible(i.name)]
        parts.append("inputs: " + (", ".join(inputs) or "none"))
    return "; ".join(parts) or "—"


def _community_rows(opts: Any, facts: RunFacts) -> list[Row]:
    from network.community import is_metadata_strategy

    rows: list[Row] = []
    for inst in opts.communities_strategy:
        flags = ["--community-strategies"]
        if inst.name == "LEIDEN_CPM" and opts.leiden_cpm_resolution is not None:
            flags.append("--leiden-cpm-resolution")
        if is_metadata_strategy(inst.name):
            option = f"{_code(inst.token())} ({inst.label})"
            value = "—"
            description = "The analyst's own label-group partition: each label is a community."
        else:
            option = _code(inst.token())
            value = _strategy_value(inst, opts, facts)
            description = _STRATEGY_DESCRIPTIONS.get(inst.name, "")
        rows.append((option, value, _flags(*flags), description))
    alpha = opts.community_backbone_alpha
    rows.append(
        (
            "Detection backbone α",
            format_value(alpha) if alpha else "off (full graph)",
            _code("--community-backbone-alpha"),
            "The algorithmic detections run on the disparity-filter backbone (Serrano et al. 2009) keeping the "
            "edges significant at α; label-group partitions, measures and layout stay on the full graph.",
        )
    )
    return rows


def _year_gamma_table(opts: Any, facts: RunFacts) -> list[str]:
    """Per-year γ of the auto-resolution CPM-family partitions (timeline years, LEIDEN_TEMPORAL slices).

    An instance with an explicit ``resolution`` runs at that γ in every year — already in its row —
    so only the instances whose γ is each graph's own density get a column.
    """
    cpm = [
        inst
        for inst in opts.communities_strategy
        if inst.name in ("LEIDEN_CPM", "LEIDEN_TEMPORAL") and inst.params_dict.get("resolution") in ("", None)
    ]
    if not cpm:
        return []
    per_year: dict[str, dict[str, float]] = {}
    for year, resolutions in facts.year_resolutions.items():
        for key, gamma in (resolutions or {}).items():
            if isinstance(gamma, numbers.Real):
                per_year.setdefault(str(year), {})[key] = gamma
    for inst in cpm:
        slices = facts.community_resolutions.get(inst.key)
        if isinstance(slices, Mapping):
            for year, gamma in slices.items():
                if isinstance(gamma, numbers.Real):
                    per_year.setdefault(str(year), {}).setdefault(inst.key, gamma)
    if not per_year:
        return []
    rows = [
        [year, *(format_value(per_year[year][inst.key]) if inst.key in per_year[year] else "—" for inst in cpm)]
        for year in sorted(per_year)
    ]
    return ["", "CPM resolution γ used for each year's graph:", "", *_table(["Year", *(i.label for i in cpm)], rows)]


def _filter_label_names(ids: Iterable[int]) -> str:
    ids = list(ids)
    if not ids:
        return "— (all in-target channels)"
    try:
        from webapp.models import Label

        names = dict(Label.objects.filter(pk__in=ids).values_list("pk", "name"))
    except Exception:  # a lookup failure must not cost the export its record
        names = {}
    return ", ".join(f"{names[i]} (#{i})" if i in names else f"#{i}" for i in ids)


def _run_option_topics(opts: Any, facts: RunFacts, scopes: set[str]) -> tuple[list[tuple[str, list[Row]]], list[str]]:
    """The run-option tables, by topic, and the features this run did not compute."""
    topics: list[tuple[str, list[Row]]] = []
    off: list[str] = []

    def _off(label: str, *flag_names: str) -> None:
        off.append(f"{label} ({_flags(*flag_names)})")

    topics.append(
        (
            "Scope & data window",
            [
                (
                    "Start date",
                    opts.start_date.isoformat() if opts.start_date else "— (from the first message)",
                    _code("--startdate"),
                    "Messages dated before it are ignored.",
                ),
                (
                    "End date",
                    opts.end_date.isoformat() if opts.end_date else "— (up to the last message)",
                    _code("--enddate"),
                    "Messages dated after it are ignored.",
                ),
                (
                    "Channel types",
                    format_value(list(opts.channel_types)),
                    _code("--channel-types"),
                    "Telegram entity types admitted as channels.",
                ),
                (
                    "Channel sources",
                    format_value(list(opts.channel_sources)) if opts.channel_sources else "— (all sources)",
                    _code("--channel-sources"),
                    "Only channels belonging to at least one of these sources enter the graph.",
                ),
                (
                    "Scope filter",
                    _filter_label_names(opts.filter_labels),
                    _code("--filter-labels"),
                    "Only channels holding a label under one of these container labels take part.",
                ),
                (
                    "Lost channels",
                    _yes(opts.include_lost),
                    _code("--include-lost"),
                    "Whether channels marked lost are kept.",
                ),
                (
                    "Private channels",
                    _yes(opts.include_private),
                    _code("--include-private"),
                    "Whether channels marked private are kept.",
                ),
                (
                    "Dead leaves",
                    _yes(opts.draw_dead_leaves),
                    _code("--draw-dead-leaves"),
                    "Whether out-of-target channels cited by in-target ones join the graph as leaf nodes.",
                ),
                (
                    "Environment depth",
                    f"{opts.environment_depth} hop(s)" if opts.environment_depth else "off (in-target channels only)",
                    _code("--environment-depth"),
                    "Out-of-target channels the crawler reached within this many citation hops take part in full.",
                ),
            ],
        )
    )

    weight = opts.edge_weight_strategy
    topics.append(
        (
            "Edges & weights",
            [
                (
                    "Edge-weight strategy",
                    _code(weight),
                    _code("--edge-weight-strategy"),
                    f"How citation counts become edge weights: {_EDGE_WEIGHT_DESCRIPTIONS.get(weight, weight)}.",
                ),
                (
                    "Mentions as citations",
                    _yes(opts.include_mentions),
                    _code("--mentions"),
                    "Whether t.me/ links count as citations alongside forwards.",
                ),
                (
                    "Self-references",
                    _yes(opts.include_self_references),
                    _code("--self-references"),
                    "Whether a channel citing itself is kept as a self-loop.",
                ),
            ],
        )
    )

    if opts.include_near_copies:
        rows = [
            (
                "Near-copy edges",
                "on",
                _code("--near-copy-edges"),
                "An original post near-identical to an earlier original post counts as a forward of the earliest one.",
            ),
            (
                "Similarity threshold",
                format_value(opts.near_copy_threshold),
                _code("--near-copy-threshold"),
                "Minimum Jaccard resemblance of the two posts' word-shingle sets.",
            ),
            (
                "Minimum tokens",
                format_value(opts.near_copy_min_tokens),
                _code("--near-copy-min-tokens"),
                "Posts with fewer normalised word tokens are ignored.",
            ),
            (
                "Shingle size",
                format_value(opts.near_copy_shingle_size),
                _code("--near-copy-shingle-size"),
                "Length, in words, of the shingles the resemblance is computed over.",
            ),
        ]
        if facts.near_copies is not None:
            rows.append(
                (
                    "Near-copy links found",
                    str(facts.near_copies),
                    "—",
                    "Copy → origin links the graph was built with (listed in data/near_copies.csv).",
                )
            )
        topics.append(("Near-copies", rows))
    else:
        _off("near-copy edges", "--near-copy-edges")

    if opts.measure_instances:
        topics.append(("Measures", _measure_rows(opts, facts)))
    else:
        _off("measures", "--measures")

    if opts.communities_strategy:
        topics.append(("Communities", _community_rows(opts, facts)))
    else:
        _off("community detection", "--community-strategies")

    if "community_stats" in scopes:
        groups = sorted(opts.selected_network_groups)
        rows = [
            (
                "Whole-network statistic groups",
                format_value(groups) if groups else "none",
                _code("--network-stat-groups"),
                "Groups of whole-network statistics computed for the network table.",
            )
        ]
        for flag_on, label, flag, description in (
            (
                opts.do_consensus_matrix,
                "Consensus matrix",
                "--consensus-matrix",
                "How consistently each channel pair is co-clustered across the algorithmic partitions.",
            ),
            (
                opts.do_structural_similarity,
                "Structural equivalence matrix",
                "--structural-similarity",
                "Cosine similarity of the channels' weighted in+out tie profiles (Lorrain & White 1971).",
            ),
            (
                opts.do_behavioural_equivalence,
                "Behavioural equivalence matrix",
                "--behavioural-equivalence",
                "Cosine similarity of the channels' behavioural-measure profiles.",
            ),
        ):
            if flag_on:
                rows.append((label, "yes", _code(flag), description))
        topics.append(("Network & community statistics", rows))
    else:
        _off("network & community statistics", "--html", "--xlsx")

    if "layout_2d" in scopes or "layout_3d" in scopes:
        from network.layout import FA2_ITERATIONS_DEFAULT

        raw_iterations = str(opts.fa2_iterations or FA2_ITERATIONS_DEFAULT)
        maps = [name for flag_on, name in ((opts.do_graph, "2D"), (opts.do_3dgraph, "3D")) if flag_on]
        rows = [
            (
                "Structural maps",
                ", ".join(maps) or "none (coordination maps only)",
                _flags("--graph-2d", "--graph-3d"),
                "Maps whose ForceAtlas2 layouts were computed (Kamada–Kawai seed, then ForceAtlas2).",
            ),
            (
                "ForceAtlas2 iterations",
                f"{_code(raw_iterations)} → {facts.fa2_iterations} iterations"
                if facts.fa2_iterations
                else _code(raw_iterations),
                _code("--fa2-iterations"),
                "Length of every ForceAtlas2 run: a count, or Nx = N × the number of channels (at least 100).",
            ),
            (
                "Orientation",
                "vertical" if opts.vertical_layout else "horizontal",
                _code("--vertical-layout"),
                "The finished 2D layout is turned 90° when its aspect ratio does not match the orientation.",
            ),
        ]
        if opts.do_graph and opts.extra_layout_names:
            rows.append(
                (
                    "Extra 2D layouts",
                    format_value(list(opts.extra_layout_names)),
                    _code("--layouts-2d"),
                    "Alternative 2D layouts computed for the map's layout switcher.",
                )
            )
        if opts.do_3dgraph and opts.extra_layout_names_3d:
            rows.append(
                (
                    "Extra 3D layouts",
                    format_value(list(opts.extra_layout_names_3d)),
                    _code("--layouts-3d"),
                    "Alternative 3D layouts computed for the 3D map's layout switcher.",
                )
            )
        if facts.coordination_fa2_iterations:
            rows.append(
                (
                    "Coordination-map iterations",
                    f"{facts.coordination_fa2_iterations} iterations",
                    _code("--fa2-iterations"),
                    "ForceAtlas2 run length of the coordination maps (the same setting, resolved against their "
                    "channel count).",
                )
            )
        topics.append(("Layout", rows))
    else:
        _off("map layouts", "--graph-2d", "--graph-3d")

    if opts.do_robustness:
        alpha = opts.robustness_alpha
        topics.append(
            (
                "Robustness",
                [
                    (
                        "Backbone α",
                        format_value(alpha) if alpha else "off (full graph)",
                        _code("--robustness-alpha"),
                        "Disparity-filter threshold applied before the attacks (0 = the full graph).",
                    ),
                    (
                        "Attack strategies",
                        format_value(list(opts.robustness_strategies)),
                        _code("--robustness-strategies"),
                        "Node-removal orders whose damage curves are measured.",
                    ),
                    (
                        "Random-failure runs",
                        format_value(opts.robustness_runs),
                        _code("--robustness-runs"),
                        "Independent random removal orders averaged for the random strategy.",
                    ),
                    (
                        "Null-model simulations K",
                        format_value(opts.robustness_null),
                        _code("--robustness-null"),
                        "Rewired networks behind each z-score and empirical p (0 = no null model).",
                    ),
                    (
                        "Null model",
                        _code(opts.robustness_null_model),
                        _code("--robustness-null-model"),
                        "What the rewired networks preserve: degrees and strengths, or also the reciprocated dyads.",
                    ),
                    (
                        "Seed",
                        format_value(opts.robustness_seed),
                        _code("--robustness-seed"),
                        "Seed of every random draw in the robustness analysis.",
                    ),
                    (
                        "Reach sample",
                        format_value(opts.robustness_sample),
                        _code("--robustness-sample"),
                        "Source-sample size for the reach metric on graphs larger than this.",
                    ),
                    (
                        "Backbone α grid",
                        format_value(list(opts.robustness_alpha_grid))
                        if opts.robustness_alpha_grid
                        else "— (no sweep)",
                        _code("--robustness-alpha-grid"),
                        "α values of the backbone-sensitivity sweep.",
                    ),
                    (
                        "Ban replay",
                        _yes(opts.do_robustness_replay),
                        _code("--robustness-replay"),
                        "Historical validation: each year's recorded closures removed from the previous year's graph.",
                    ),
                ],
            )
        )
    else:
        _off("robustness", "--robustness")

    if opts.do_coordination:
        maps = [name for flag_on, name in ((opts.do_coordination_2d, "2D"), (opts.do_coordination_3d, "3D")) if flag_on]
        rows = [
            (
                "Coordination maps",
                ", ".join(maps),
                _flags("--coordination-2d", "--coordination-3d"),
                "Maps of the temporal co-forwarding coordination layer.",
            ),
            (
                "Co-forwarding window",
                f"{opts.coordination_window} s",
                _code("--coordination-window"),
                "Two forwards of the same origin message within this many seconds count as one coordinated event.",
            ),
            (
                "Minimum shared origins",
                format_value(opts.coordination_min_events),
                _code("--coordination-min-events"),
                "Distinct co-forwarded origin messages a channel pair needs for its tie to be kept.",
            ),
        ]
        if facts.coordination_ties is not None:
            rows.append(
                (
                    "Coordination ties found",
                    str(facts.coordination_ties) if facts.coordination_ties else "none (maps skipped)",
                    "—",
                    "Channel pairs that passed both thresholds over the full range.",
                )
            )
        topics.append(("Coordination", rows))
    else:
        _off("coordination", "--coordination-2d", "--coordination-3d")

    if opts.do_dominance:
        topics.append(
            (
                "Dominance",
                [
                    (
                        "Minimum citation events",
                        format_value(opts.dominance_min_events),
                        _code("--dominance-min-events"),
                        "A link needs this many citations to be tested and to count as a satellite tie; a channel "
                        "needs this many citing messages for its own dependence to be assessed.",
                    ),
                    (
                        "Hierarchy-test permutations",
                        format_value(opts.dominance_permutations),
                        _code("--dominance-permutations"),
                        "Orientation-shuffled null networks behind the hierarchy p-values (0 skips the tests).",
                    ),
                ],
            )
        )
    else:
        _off("dominance", "--dominance")

    if opts.do_vacancy:
        topics.append(
            (
                "Vacancy analysis",
                [
                    (
                        "Vacancy measures",
                        format_value(sorted(opts.selected_vacancy_measures)),
                        _code("--vacancy-measures"),
                        "Replacement-candidate scores computed for every recorded vacancy.",
                    ),
                    (
                        "Months before",
                        format_value(opts.vacancy_months_before),
                        _code("--vacancy-months-before"),
                        "Look-back window before each closure that defines the orphaned amplifiers.",
                    ),
                    (
                        "Months after",
                        format_value(opts.vacancy_months_after),
                        _code("--vacancy-months-after"),
                        "Window after each closure in which replacement candidates are scored.",
                    ),
                    (
                        "Candidate cap",
                        format_value(opts.vacancy_max_candidates),
                        _code("--vacancy-max-candidates"),
                        "Maximum candidates scored per vacancy — also the BH family size of every q-value.",
                    ),
                ],
            )
        )
    else:
        _off("vacancy analysis", "--vacancy-measures")

    if opts.do_interest_structural:
        window = opts.interest_window_days
        topics.append(
            (
                "Structural interest",
                [
                    (
                        "Reaction window",
                        f"{window} days" if window else "0 (no window)",
                        _code("--interest-window-days"),
                        "Only forwards within this many days of the origin post count toward C and D.",
                    ),
                    (
                        "Include mentions",
                        f"{_yes(opts.interest_include_mentions)} (no effect yet)",
                        _code("--interest-include-mentions"),
                        "Accepted for forward compatibility; it does not change the scores.",
                    ),
                    (
                        "Community basis",
                        _code(facts.interest_community) if facts.interest_community else "—",
                        "— (automatic)",
                        "Partition whose communities the cross-community reach C counts (LEIDEN_DIRECTED preferred).",
                    ),
                    (
                        "Authority weight",
                        _code(facts.interest_authority) if facts.interest_authority else "—",
                        "— (automatic)",
                        "Node attribute weighting the authority-weighted reach D (PageRank, else HITS authority, else "
                        "in-strength).",
                    ),
                ],
            )
        )
    else:
        _off("structural interest", "--interest-structural")

    if opts.timeline_step == "year":
        years = sorted(facts.timeline_years)
        if years and years == list(range(years[0], years[-1] + 1)) and len(years) > 1:
            span = f"{years[0]}–{years[-1]} ({len(years)} years)"
        else:
            span = ", ".join(map(str, years)) or "none"
        topics.append(
            (
                "Timeline",
                [
                    (
                        "Timeline step",
                        _code("year"),
                        _code("--timeline-step"),
                        "The analysis is repeated for every calendar year with the same options; each year has its "
                        "own graph, measures, communities and layout.",
                    ),
                    ("Years exported", span, "—", "Years that produced a non-empty graph."),
                ],
            )
        )
    else:
        _off("timeline", "--timeline-step")
    return topics, off


# ── Document ──────────────────────────────────────────────────────────────────

_HOW_TO_READ = (
    "Every number in this export depends on two kinds of parameter. **Run options** were chosen for this run — "
    "on the command line, in the Operations panel, or taken from the configuration files when neither set "
    "them — and are shown as resolved: defaults filled in, and automatic values (such as a CPM resolution γ "
    "left to the network density) replaced by the value actually used. **Fixed parameters** are set in "
    "Pulpit's code — seeds, iteration counts, thresholds, and the library defaults the code relies on — and "
    "are listed only for the parts of the analysis that ran. Together with the software versions at the end, "
    "they are the record needed to reproduce this export; `summary.json` carries the run options in "
    "machine-readable form."
)


def render_parameters_markdown(
    opts: Any,
    facts: RunFacts | None = None,
    *,
    export_name: str | None = None,
    generated_at: datetime.datetime | None = None,
    fixed: Mapping[str, list[FixedParameter]] | None = None,
    versions: list[tuple[str, str, str]] | None = None,
) -> str:
    """Render ``PARAMETERS.md`` for a run with the resolved options ``opts`` (``ResolvedOptions``).

    ``facts`` carries the values resolved while running (see :class:`RunFacts`). ``fixed`` defaults
    to the declared fixed parameters of the run's :func:`active_scopes`, ``versions`` to
    :func:`library_versions`; both are injectable for tests.
    """
    facts = facts or RunFacts()
    name = export_name if export_name is not None else getattr(opts, "export_name", "")
    generated_at = generated_at or datetime.datetime.now().astimezone()
    coordination_laid_out = facts.coordination_ties is None or facts.coordination_ties > 0
    scopes = active_scopes(opts, coordination_laid_out=coordination_laid_out)
    if fixed is None:
        fixed = collect_fixed_parameters(scopes)
    if versions is None:
        versions = library_versions()
    app_version = str(getattr(settings, "APP_VERSION", "") or "unknown")

    lines = [f"# Parameters — {name}" if name else "# Parameters", ""]
    lines.append(f"Generated {generated_at.strftime('%Y-%m-%d %H:%M:%S %Z').strip()} by Pulpit {app_version}.")
    if facts.nodes is not None and facts.edges is not None:
        lines.extend(["", f"Full-range graph: {facts.nodes} channels, {facts.edges} citation edges."])
    lines.extend(["", "## How to read this", "", _HOW_TO_READ, "", "## Run options"])

    topics, off = _run_option_topics(opts, facts, scopes)
    for topic, rows in topics:
        lines.extend(["", f"### {topic}", ""])
        lines.extend(_table(["Option", "Value", "CLI flag", "What it controls"], rows))
        if topic == "Communities":
            lines.extend(_year_gamma_table(opts, facts))
    if off:
        lines.extend(["", "**Not computed in this run:** " + ", ".join(off) + "."])

    lines.extend(
        [
            "",
            "## Fixed parameters",
            "",
            "Values set in the code for the parts of the analysis that ran, read from the very constants the "
            "computation uses. *Set in* names the module and constant to look up.",
        ]
    )
    if not fixed:
        lines.extend(["", "_No fixed parameters are declared for the parts of the analysis that ran._"])
    for section, params in fixed.items():
        param_scopes = [getattr(p, "scopes", ()) or (p.scope,) for p in params]
        mixed = len(set(param_scopes)) > 1 or any(len(s) > 1 for s in param_scopes)
        headers = (["Applies to"] if mixed else []) + ["Parameter", "Value", "Affects", "Set in", "Note"]
        rows = [
            ([", ".join(scope_label(s) for s in scopes)] if mixed else [])
            + [p.name, format_value(p.value), p.affects, _code(p.source), p.note or "—"]
            for p, scopes in zip(params, param_scopes, strict=True)
        ]
        lines.extend(["", f"### {section}", "", *_table(headers, rows)])

    lines.extend(["", "## Software", ""])
    software = [("Pulpit", app_version, "this export"), ("Python", platform.python_version(), "—"), *versions]
    lines.extend(_table(["Component", "Version", "Computes"], software))
    lines.append("")
    return "\n".join(lines)


def write_parameters_md(export_dir: str, text: str) -> str:
    """Write ``PARAMETERS.md`` at the export root; returns its path."""
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, PARAMETERS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path

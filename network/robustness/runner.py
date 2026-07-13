"""Top-level orchestrator for the robustness battery.

:func:`run_robustness` ties the rest of the package together:

    1. Optionally apply the disparity-filter backbone (``alpha`` in ``(0, 1)``).
    2. Compute the baseline weighted global efficiency.
    3. For each enabled attack strategy: build the removal order, generate
       residual-size curves for WCC / SCC / REACH / STRENGTH, compute R and
       f_c.  ``random`` is averaged over ``n_random_runs`` independent orders.
    4. For each strategy: sample the weighted global efficiency along the
       removal order on a coarse grid (observed backbone only — an all-pairs
       Dijkstra per null draw would be prohibitive).
    5. For each strategy: optionally run ``n_null`` rewired-weight null
       simulations and report z-score + mean/std of R *and* of the S(f)
       curves so the HTML page can shade a null-model band.
    6. For each available partition: compute intra/inter community
       edge-survival curves alongside each attack strategy, plus the
       ban-wave scenarios (whole-block removal vs the equal-q random
       baseline).

The strategy set is fully user-driven via ``RobustnessConfig.strategies``:
any subset of :data:`~network.robustness.attacks.STRATEGY_SPECS` keys is
accepted.  Default is the list in
:data:`~network.robustness.attacks.DEFAULT_STRATEGIES`.

The output is a single JSON-serialisable dict whose shape is documented on
:func:`run_robustness`; the runner is the only module that knows it.

All stochastic operations share a single ``np.random.Generator`` derived from
``config.seed`` so the entire payload is reproducible from one integer.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from network.robustness.attacks import (
    ALL_STRATEGIES,
    DEFAULT_STRATEGIES,
    DYNAMIC_STRATEGIES,
    STATIC_STRATEGIES,
    STRATEGY_SPECS,
    parse_strategy,
    removal_order,
    strategy_label,
)
from network.robustness.disparity_filter import disparity_filter
from network.robustness.metrics import (
    attack_curve,
    critical_threshold,
    efficiency_curve,
    r_index,
    weighted_global_efficiency,
)
from network.robustness.modular import modular_robustness_curves
from network.robustness.null_model import null_distribution, z_score
from network.robustness.scenarios import ban_wave_rows

import networkx as nx
import numpy as np

_METRICS: tuple[str, ...] = ("wcc", "scc", "reach", "strength")
_METRIC_KEYS: dict[str, str] = {"wcc": "WCC", "scc": "SCC", "reach": "REACH", "strength": "STRENGTH"}
# Random-strategy efficiency curves are averaged over at most this many of its
# orders — each grid point costs an all-pairs Dijkstra, so the full
# n_random_runs averaging used for the (cheap) residual sizes is off the table.
_EFFICIENCY_ORDERS_CAP = 10


@dataclass(frozen=True)
class RobustnessConfig:
    """Configuration for :func:`run_robustness`.

    ``alpha``           disparity-filter threshold; ``None`` or values outside
                        ``(0, 1)`` disable the filter and use the full graph
    ``strategies``      list of attack-strategy tokens (any of
                        :data:`~network.robustness.attacks.STRATEGY_SPECS` keys).
                        ``None`` uses
                        :data:`~network.robustness.attacks.DEFAULT_STRATEGIES`.
    ``n_random_runs``   independent random orders averaged into the
                        ``"random"`` strategy curve (≥ 1)
    ``n_null``          number of weight-rewiring null simulations per
                        strategy; ``0`` disables the null model
    ``seed``            single seed driving every stochastic component
    ``reach_sample``    source-sample size for ``"REACH"`` curves on graphs
                        larger than this many nodes
    ``n_rewire_swaps``  per-null-simulation swap budget; ``None`` lets the
                        null model use its own default of ``10·|E|``
    """

    alpha: float | None = 0.05
    strategies: list[str] | None = None
    n_random_runs: int = 100
    n_null: int = 20
    seed: int = 42
    reach_sample: int = 500
    n_rewire_swaps: int | None = field(default=None)

    def __post_init__(self) -> None:
        if self.n_random_runs < 1:
            raise ValueError(f"n_random_runs must be >= 1; got {self.n_random_runs}")
        if self.n_null < 0:
            raise ValueError(f"n_null must be >= 0; got {self.n_null}")
        if self.alpha is not None and not (0 <= self.alpha <= 1):
            raise ValueError(f"alpha must be in [0, 1] or None; got {self.alpha}")
        if self.reach_sample <= 0:
            raise ValueError(f"reach_sample must be positive; got {self.reach_sample}")
        if self.strategies is not None:
            if not self.strategies:
                raise ValueError("strategies must contain at least one entry; got an empty list")
            for token in self.strategies:
                parse_strategy(token)  # raises ValueError on unknown names


def run_robustness(
    G: nx.DiGraph,
    partitions: dict[str, dict[Any, Any]] | None = None,
    config: RobustnessConfig | None = None,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the full robustness battery on *G* and return a JSON-serialisable payload.

    *partitions* maps a partition label (e.g. ``"leiden"``) to a
    ``{node_id: community_id}`` dict — usually a strategy result from
    :mod:`network.community`.  Pass ``None`` to skip modular curves.

    *progress* receives a short status label before each major step
    (``"disparity"``, ``"baseline-efficiency"``, ``"pagerank"``,
    ``"null/pagerank/3"``, ``"modular/leiden"``, …) so the CLI command can
    stream live log output.

    Payload shape::

        {
          "config":     {alpha, strategies, n_random_runs, n_null, seed,
                         reach_sample, n_rewire_swaps},
          "graph":      {n, m, alpha, backbone_n, backbone_m,
                         filtered: bool},
          "efficiency": {
            "baseline":  float,
            "fractions": [...],                      # coarse grid, shared by all curves
            "curves":    {<strategy_key>: [...], …}, # observed backbone only, no null
          },
          "strategies": {
            <strategy_key>: {
              "label":       human-readable name,
              "curve_wcc":   [...], "curve_scc": [...],
              "curve_reach": [...], "curve_strength": [...],
              "r_<metric>":  float,        # for each of wcc / scc / reach / strength
              "fc_<metric>": float|None,
              "null": {
                "r_<metric>":          {"mean": float, "std": float, "z": float},
                "curve_<metric>_mean": [...],
                "curve_<metric>_std":  [...],
              } | None,
            }, ...
          },
          "modular": {
            <partition_label>: {
              <strategy_key>: {"intra": [...], "inter": [...], "ratio": [...]},
              ...
            }, ...
          } | None,
          "ban_waves": {
            <partition_label>: [
              {"community": str, "n": int, "fraction": float,
               "s_<metric>": float, "random_<metric>": float|None},
              ...                                    # sorted by block size desc
            ], ...
          } | None,
        }

    ``<strategy_key>`` is the canonical strategy token (a bare lowercase name).
    """
    config = config or RobustnessConfig()
    progress = progress or (lambda _: None)
    rng = np.random.default_rng(config.seed)

    # 1. Optional disparity-filter backbone
    progress("disparity")
    if config.alpha is not None and 0 < config.alpha < 1:
        backbone = disparity_filter(G, alpha=config.alpha)
        filtered = True
    else:
        backbone = G.copy()
        filtered = False

    # 2. Baseline weighted global efficiency
    progress("baseline-efficiency")
    baseline_eff = weighted_global_efficiency(backbone)

    # 3. Resolve strategy list — apply defaults and parse each token to its
    # canonical lowercase name, which is the dict key used in the payload.
    raw_strategies = list(config.strategies) if config.strategies else list(DEFAULT_STRATEGIES)
    resolved: list[str] = []
    for token in raw_strategies:
        resolved.append(parse_strategy(token))
    # de-duplicate while preserving order
    seen: set[str] = set()
    resolved = [c for c in resolved if not (c in seen or seen.add(c))]

    # 4. Per-strategy curves on the (possibly filtered) backbone
    strategy_results: dict[str, dict[str, Any]] = {}
    strategy_orders: dict[str, list[list[Any]]] = {}
    for canonical in resolved:
        progress(canonical)
        orders, mean_curves = _compute_strategy_curves(
            backbone, canonical, config.n_random_runs, config.reach_sample, rng
        )
        strategy_orders[canonical] = orders
        strategy_results[canonical] = {
            "label": strategy_label(canonical),
            **{f"curve_{m}": mean_curves[m] for m in _METRICS},
            **{f"r_{m}": r_index(mean_curves[m]) for m in _METRICS},
            **{f"fc_{m}": critical_threshold(mean_curves[m]) for m in _METRICS},
            "null": None,
        }

    # 5. Coarse weighted-efficiency curves — observed backbone only.  The null
    # re-runs every attack K times and each grid point costs an all-pairs
    # Dijkstra, so the null band covers the residual-size metrics instead.
    eff_fractions: list[float] = [0.0]
    eff_curves: dict[str, list[float]] = {}
    for canonical in resolved:
        progress(f"efficiency/{canonical}")
        per_order = [efficiency_curve(backbone, order) for order in strategy_orders[canonical][:_EFFICIENCY_ORDERS_CAP]]
        eff_fractions = per_order[0][0]
        eff_curves[canonical] = _mean_curve([values for _, values in per_order])

    # 6. Null-model simulations
    if config.n_null > 0:
        null_rs: dict[str, dict[str, list[float]]] = {canonical: {m: [] for m in _METRICS} for canonical in resolved}
        null_curves: dict[str, dict[str, list[list[float]]]] = {
            canonical: {m: [] for m in _METRICS} for canonical in resolved
        }
        for k, null_g in enumerate(
            null_distribution(backbone, n_simulations=config.n_null, rng=rng, n_swaps=config.n_rewire_swaps),
            start=1,
        ):
            for canonical in resolved:
                progress(f"null/{canonical}/{k}")
                _, mean_curves_null = _compute_strategy_curves(
                    null_g, canonical, config.n_random_runs, config.reach_sample, rng
                )
                for m in _METRICS:
                    curve = mean_curves_null[m]
                    null_curves[canonical][m].append(curve)
                    null_rs[canonical][m].append(r_index(curve))
        for canonical in resolved:
            null_data: dict[str, Any] = {}
            for m in _METRICS:
                observed = strategy_results[canonical][f"r_{m}"]
                z, mean, std = z_score(observed, null_rs[canonical][m])
                null_data[f"r_{m}"] = {"mean": mean, "std": std, "z": z}
                mean_curve, std_curve = _mean_and_std_curve(null_curves[canonical][m])
                null_data[f"curve_{m}_mean"] = mean_curve
                null_data[f"curve_{m}_std"] = std_curve
            strategy_results[canonical]["null"] = null_data

    # 7. Modular curves per partition × strategy
    modular_results: dict[str, dict[str, Any]] | None = None
    if partitions:
        modular_results = {}
        for partition_name, partition in partitions.items():
            progress(f"modular/{partition_name}")
            modular_results[partition_name] = {
                canonical: modular_robustness_curves(backbone, strategy_orders[canonical][0], partition)
                for canonical in resolved
            }

    # 8. Ban-wave scenarios per partition — whole-block removal vs the
    # equal-q random baseline.  Reuses the random strategy's mean curves when
    # it was selected; otherwise computes a dedicated set so the baseline
    # columns are always present.
    ban_waves: dict[str, list[dict[str, Any]]] | None = None
    if partitions:
        if "random" in strategy_results:
            random_curves = {m: strategy_results["random"][f"curve_{m}"] for m in _METRICS}
        else:
            progress("banwave/random-baseline")
            _, random_curves = _compute_strategy_curves(
                backbone, "random", config.n_random_runs, config.reach_sample, rng
            )
        ban_waves = {}
        for partition_name, partition in partitions.items():
            progress(f"banwave/{partition_name}")
            rows = ban_wave_rows(backbone, partition, random_curves, reach_sample=config.reach_sample, rng=rng)
            if rows:
                ban_waves[partition_name] = rows
        ban_waves = ban_waves or None

    return {
        "config": {
            "alpha": config.alpha,
            "strategies": list(resolved),
            "n_random_runs": config.n_random_runs,
            "n_null": config.n_null,
            "seed": config.seed,
            "reach_sample": config.reach_sample,
            "n_rewire_swaps": config.n_rewire_swaps,
        },
        "graph": {
            "n": G.number_of_nodes(),
            "m": G.number_of_edges(),
            "alpha": config.alpha,
            "backbone_n": backbone.number_of_nodes(),
            "backbone_m": backbone.number_of_edges(),
            "filtered": filtered,
        },
        "efficiency": {"baseline": baseline_eff, "fractions": eff_fractions, "curves": eff_curves},
        "strategies": strategy_results,
        "modular": modular_results,
        "ban_waves": ban_waves,
    }


# ── private helpers ──────────────────────────────────────────────────────────


def _compute_strategy_curves(
    g: nx.DiGraph,
    strategy_token: str,
    n_random_runs: int,
    reach_sample: int,
    rng: np.random.Generator,
) -> tuple[list[list[Any]], dict[str, list[float]]]:
    """Return ``(orders, {metric: mean_curve})`` for *strategy_token* on *g*.

    For ``"random"`` the curves are means over ``n_random_runs`` independent
    orderings; for every other strategy the order is deterministic and the
    curve is a single trace.  The full *orders* list is returned so the
    modular pass can reuse the first order and the efficiency pass can
    average over (a capped number of) them without recomputing.
    """
    if strategy_token == "random":
        orders = [removal_order(g, "random", rng=rng) for _ in range(n_random_runs)]
    else:
        orders = [removal_order(g, strategy_token, rng=rng)]

    curves_per_metric: dict[str, list[list[float]]] = {m: [] for m in _METRICS}
    for order in orders:
        for m in _METRICS:
            kwargs: dict[str, Any] = {}
            if m == "reach":
                kwargs = {"reach_sample": reach_sample, "rng": rng}
            curves_per_metric[m].append(attack_curve(g, order, _METRIC_KEYS[m], **kwargs))

    return orders, {m: _mean_curve(curves_per_metric[m]) for m in _METRICS}


def _mean_curve(curves: list[list[float]]) -> list[float]:
    """Element-wise mean across a list of equally-long curves."""
    if not curves:
        return []
    arr = np.asarray(curves, dtype=float)
    return arr.mean(axis=0).tolist()


def _mean_and_std_curve(
    curves: list[list[float]],
) -> tuple[list[float], list[float]]:
    """Element-wise mean and sample std (``ddof=1`` when ≥ 2 samples)."""
    if not curves:
        return [], []
    arr = np.asarray(curves, dtype=float)
    ddof = 1 if arr.shape[0] > 1 else 0
    return arr.mean(axis=0).tolist(), arr.std(axis=0, ddof=ddof).tolist()


__all__ = [
    "ALL_STRATEGIES",
    "DEFAULT_STRATEGIES",
    "DYNAMIC_STRATEGIES",
    "RobustnessConfig",
    "STATIC_STRATEGIES",
    "STRATEGY_SPECS",
    "run_robustness",
]

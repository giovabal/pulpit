"""Top-level orchestrator for the robustness battery.

:func:`run_robustness` ties the rest of the package together:

    1. Optionally apply the disparity-filter backbone (``alpha`` in ``(0, 1)``).
    2. Compute the baseline weighted global efficiency.
    3. For each enabled attack strategy: build the removal order, generate
       residual-size curves for WCC / SCC / REACH, compute R and f_c.
       ``random`` is averaged over ``n_random_runs`` independent orders.
    4. For each strategy: optionally run ``n_null`` rewired-weight null
       simulations and report z-score + mean/std of R *and* of the S(f)
       curves so the HTML page can shade a null-model band.
    5. For each available partition: compute intra/inter community
       edge-survival curves alongside each attack strategy.

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
    DYNAMIC_STRATEGIES,
    STATIC_STRATEGIES,
    removal_order,
)
from network.robustness.disparity_filter import disparity_filter
from network.robustness.metrics import (
    attack_curve,
    critical_threshold,
    r_index,
    weighted_global_efficiency,
)
from network.robustness.modular import modular_robustness_curves
from network.robustness.null_model import null_distribution, z_score

import networkx as nx
import numpy as np

_METRICS: tuple[str, ...] = ("wcc", "scc", "reach")
_METRIC_KEYS: dict[str, str] = {"wcc": "WCC", "scc": "SCC", "reach": "REACH"}


@dataclass(frozen=True)
class RobustnessConfig:
    """Configuration for :func:`run_robustness`.

    ``alpha``           disparity-filter threshold; ``None`` or values outside
                        ``(0, 1)`` disable the filter and use the full graph
    ``n_random_runs``   independent random orders averaged into the
                        ``"random"`` strategy curve (≥ 1)
    ``n_null``          number of weight-rewiring null simulations per
                        strategy; ``0`` disables the null model
    ``dynamic``         when ``True``, also run the three ``_dyn`` strategies
                        (re-rank after each deletion — much costlier)
    ``seed``            single seed driving every stochastic component
    ``reach_sample``    source-sample size for ``"REACH"`` curves on graphs
                        larger than this many nodes
    ``n_rewire_swaps``  per-null-simulation swap budget; ``None`` lets the
                        null model use its own default of ``10·|E|``
    """

    alpha: float | None = 0.05
    n_random_runs: int = 100
    n_null: int = 20
    dynamic: bool = False
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
          "config":     {alpha, n_random_runs, n_null, dynamic, seed,
                         reach_sample, n_rewire_swaps},
          "graph":      {n, m, alpha, backbone_n, backbone_m,
                         filtered: bool},
          "efficiency": {"baseline": float},
          "strategies": {
            <strategy>: {
              "curve_wcc":   [...], "curve_scc":   [...], "curve_reach": [...],
              "r_wcc":   float, "r_scc":   float, "r_reach":   float,
              "fc_wcc":  float|None, "fc_scc":  float|None, "fc_reach":  float|None,
              "null": {
                "r_wcc":   {"mean": float, "std": float, "z": float},
                "r_scc":   {"mean": float, "std": float, "z": float},
                "r_reach": {"mean": float, "std": float, "z": float},
                "curve_wcc_mean":   [...], "curve_wcc_std":   [...],
                "curve_scc_mean":   [...], "curve_scc_std":   [...],
                "curve_reach_mean": [...], "curve_reach_std": [...],
              } | None,
            }, ...
          },
          "modular": {
            <partition_label>: {
              <strategy>: {"intra": [...], "inter": [...], "ratio": [...]},
              ...
            }, ...
          } | None,
        }
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

    # 3. Strategy list — static always, dynamic when opted in.
    strategies = [s for s in ALL_STRATEGIES if s in STATIC_STRATEGIES]
    if config.dynamic:
        strategies += [s for s in ALL_STRATEGIES if s in DYNAMIC_STRATEGIES]

    # 4. Per-strategy curves on the (possibly filtered) backbone
    strategy_results: dict[str, dict[str, Any]] = {}
    cached_orders: dict[str, list[Any]] = {}
    for strategy in strategies:
        progress(strategy)
        first_order, mean_curves = _compute_strategy_curves(
            backbone, strategy, config.n_random_runs, config.reach_sample, rng
        )
        cached_orders[strategy] = first_order
        strategy_results[strategy] = {
            **{f"curve_{m}": mean_curves[m] for m in _METRICS},
            **{f"r_{m}": r_index(mean_curves[m]) for m in _METRICS},
            **{f"fc_{m}": critical_threshold(mean_curves[m]) for m in _METRICS},
            "null": None,
        }

    # 5. Null-model simulations
    if config.n_null > 0:
        null_rs: dict[str, dict[str, list[float]]] = {s: {m: [] for m in _METRICS} for s in strategies}
        null_curves: dict[str, dict[str, list[list[float]]]] = {s: {m: [] for m in _METRICS} for s in strategies}
        for k, null_g in enumerate(
            null_distribution(backbone, n_simulations=config.n_null, rng=rng, n_swaps=config.n_rewire_swaps),
            start=1,
        ):
            for strategy in strategies:
                progress(f"null/{strategy}/{k}")
                _, mean_curves_null = _compute_strategy_curves(
                    null_g, strategy, config.n_random_runs, config.reach_sample, rng
                )
                for m in _METRICS:
                    curve = mean_curves_null[m]
                    null_curves[strategy][m].append(curve)
                    null_rs[strategy][m].append(r_index(curve))
        for strategy in strategies:
            null_data: dict[str, Any] = {}
            for m in _METRICS:
                observed = strategy_results[strategy][f"r_{m}"]
                z, mean, std = z_score(observed, null_rs[strategy][m])
                null_data[f"r_{m}"] = {"mean": mean, "std": std, "z": z}
                mean_curve, std_curve = _mean_and_std_curve(null_curves[strategy][m])
                null_data[f"curve_{m}_mean"] = mean_curve
                null_data[f"curve_{m}_std"] = std_curve
            strategy_results[strategy]["null"] = null_data

    # 6. Modular curves per partition × strategy
    modular_results: dict[str, dict[str, Any]] | None = None
    if partitions:
        modular_results = {}
        for partition_name, partition in partitions.items():
            progress(f"modular/{partition_name}")
            modular_results[partition_name] = {
                strategy: modular_robustness_curves(backbone, cached_orders[strategy], partition)
                for strategy in strategies
            }

    return {
        "config": {
            "alpha": config.alpha,
            "n_random_runs": config.n_random_runs,
            "n_null": config.n_null,
            "dynamic": config.dynamic,
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
        "efficiency": {"baseline": baseline_eff},
        "strategies": strategy_results,
        "modular": modular_results,
    }


# ── private helpers ──────────────────────────────────────────────────────────


def _compute_strategy_curves(
    g: nx.DiGraph,
    strategy: str,
    n_random_runs: int,
    reach_sample: int,
    rng: np.random.Generator,
) -> tuple[list[Any], dict[str, list[float]]]:
    """Return ``(first_order, {metric: mean_curve})`` for *strategy* on *g*.

    For ``"random"`` the curves are means over ``n_random_runs`` independent
    orderings; for every other strategy the order is deterministic and the
    curve is a single trace.  ``first_order`` is returned for the modular-
    curve pass so it does not need to recompute the order.
    """
    if strategy == "random":
        orders = [removal_order(g, "random", rng=rng) for _ in range(n_random_runs)]
    else:
        orders = [removal_order(g, strategy, rng=rng)]

    curves_per_metric: dict[str, list[list[float]]] = {m: [] for m in _METRICS}
    for order in orders:
        for m in _METRICS:
            kwargs: dict[str, Any] = {}
            if m == "reach":
                kwargs = {"reach_sample": reach_sample, "rng": rng}
            curves_per_metric[m].append(attack_curve(g, order, _METRIC_KEYS[m], **kwargs))

    return orders[0], {m: _mean_curve(curves_per_metric[m]) for m in _METRICS}


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

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
          "efficiency": {"baseline": float},
          "strategies": {
            <strategy_key>: {
              "label":       human-readable name,
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
              <strategy_key>: {"intra": [...], "inter": [...], "ratio": [...]},
              ...
            }, ...
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
    cached_orders: dict[str, list[Any]] = {}
    for canonical in resolved:
        progress(canonical)
        first_order, mean_curves = _compute_strategy_curves(
            backbone, canonical, config.n_random_runs, config.reach_sample, rng
        )
        cached_orders[canonical] = first_order
        strategy_results[canonical] = {
            "label": strategy_label(canonical),
            **{f"curve_{m}": mean_curves[m] for m in _METRICS},
            **{f"r_{m}": r_index(mean_curves[m]) for m in _METRICS},
            **{f"fc_{m}": critical_threshold(mean_curves[m]) for m in _METRICS},
            "null": None,
        }

    # 5. Null-model simulations
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

    # 6. Modular curves per partition × strategy
    modular_results: dict[str, dict[str, Any]] | None = None
    if partitions:
        modular_results = {}
        for partition_name, partition in partitions.items():
            progress(f"modular/{partition_name}")
            modular_results[partition_name] = {
                canonical: modular_robustness_curves(backbone, cached_orders[canonical], partition)
                for canonical in resolved
            }

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
        "efficiency": {"baseline": baseline_eff},
        "strategies": strategy_results,
        "modular": modular_results,
    }


# ── private helpers ──────────────────────────────────────────────────────────


def _compute_strategy_curves(
    g: nx.DiGraph,
    strategy_token: str,
    n_random_runs: int,
    reach_sample: int,
    rng: np.random.Generator,
) -> tuple[list[Any], dict[str, list[float]]]:
    """Return ``(first_order, {metric: mean_curve})`` for *strategy_token* on *g*.

    For ``"random"`` the curves are means over ``n_random_runs`` independent
    orderings; for every other strategy the order is deterministic and the
    curve is a single trace.  ``first_order`` is returned for the modular-
    curve pass so it does not need to recompute the order.
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


__all__ = [
    "ALL_STRATEGIES",
    "DEFAULT_STRATEGIES",
    "DYNAMIC_STRATEGIES",
    "RobustnessConfig",
    "STATIC_STRATEGIES",
    "STRATEGY_SPECS",
    "run_robustness",
]

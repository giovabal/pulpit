from network.parameters import FixedParameter
from network.robustness.attacks import (
    ALL_STRATEGIES,
    DEFAULT_STRATEGIES,
    DYNAMIC_STRATEGIES,
    FIXED_PARAMETERS as _ATTACKS_FIXED,
    STATIC_STRATEGIES,
    STRATEGY_SPECS,
    parse_strategy,
    removal_order,
    strategy_label,
)
from network.robustness.disparity_filter import (
    FIXED_PARAMETERS as _DISPARITY_FIXED,
    compute_alpha_values,
    disparity_filter,
    has_uniform_weights,
)
from network.robustness.metrics import (
    FIXED_PARAMETERS as _METRICS_FIXED,
    attack_curve,
    component_sizes,
    critical_threshold,
    efficiency_curve,
    r_index,
    residual_sizes,
    weighted_global_efficiency,
)
from network.robustness.modular import FIXED_PARAMETERS as _MODULAR_FIXED, modular_robustness_curves
from network.robustness.null_model import (
    FIXED_PARAMETERS as _NULL_MODEL_FIXED,
    bh_adjust,
    empirical_p,
    null_distribution,
    rewire_reciprocity_preserving,
    rewire_strength_preserving,
    z_score,
)
from network.robustness.replay import FIXED_PARAMETERS as _REPLAY_FIXED, ban_replay_rows
from network.robustness.runner import FIXED_PARAMETERS as _RUNNER_FIXED, RobustnessConfig, run_robustness
from network.robustness.scenarios import FIXED_PARAMETERS as _SCENARIOS_FIXED, ban_wave_rows

#: Every value fixed in the robustness package (``PARAMETERS.md``), gathered from its modules.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    _ATTACKS_FIXED
    + _DISPARITY_FIXED
    + _METRICS_FIXED
    + _NULL_MODEL_FIXED
    + _SCENARIOS_FIXED
    + _MODULAR_FIXED
    + _RUNNER_FIXED
    + _REPLAY_FIXED
)

__all__ = [
    "ALL_STRATEGIES",
    "DEFAULT_STRATEGIES",
    "DYNAMIC_STRATEGIES",
    "FIXED_PARAMETERS",
    "STATIC_STRATEGIES",
    "STRATEGY_SPECS",
    "RobustnessConfig",
    "attack_curve",
    "ban_replay_rows",
    "ban_wave_rows",
    "bh_adjust",
    "component_sizes",
    "compute_alpha_values",
    "critical_threshold",
    "disparity_filter",
    "efficiency_curve",
    "empirical_p",
    "has_uniform_weights",
    "modular_robustness_curves",
    "null_distribution",
    "parse_strategy",
    "r_index",
    "removal_order",
    "residual_sizes",
    "rewire_reciprocity_preserving",
    "rewire_strength_preserving",
    "run_robustness",
    "strategy_label",
    "weighted_global_efficiency",
    "z_score",
]

"""Dyadic regression of citation ties with MRQAP (``--mrqap``).

Why does one channel cite another? Every ordered pair of channels (i, j) is one observation: does i cite
j (``tie``, 0/1), and how often (``log1p`` of the citations). Both are regressed by ordinary least squares
on dyadic predictors at once:

* ``same_<group>`` — i and j hold the same label in a partition label group (Nation, Continent, …): the
  homophily effect *net of* the others. With nested groups (Nation inside Continent) the finer one reads
  as "same nation beyond same continent".
* ``reverse_tie`` — j cites i: the reciprocity control.
* sender / receiver activity — ``log1p`` of each side's messages in the analysis window.
* sender / receiver audience — ``log1p`` of each side's subscribers.

Dyads are not independent — every row and column of the matrix shares a channel — so ordinary standard
errors are wrong. Inference is by the multiple-regression quadratic assignment procedure with **double
semi-partialling** (Dekker, Krackhardt & Snijders 2007): for each predictor, its residual on the other
predictors is permuted (rows and columns together, by one random relabelling of the channels) and the
model refitted; the observed t-statistic is compared with the permuted ones (two-sided add-one p). It
is robust to the collinearity and the row/column autocorrelation of network data where the plain QAP
of Krackhardt (1988) is not. Each permutation is evaluated by the Frisch–Waugh–Lovell update, in O(n·p).

Actors are the observed channels (dead leaves' own citations are never read, so their row of the matrix
is unknown) holding a label in every partition group used. The ``tie`` model is a linear probability
model; ``reverse_tie`` is endogenous and read as a control, not as a causal effect.
"""

from dataclasses import dataclass, field
from typing import Any

from network.parameters import FixedParameter
from network.utils import GraphData, citation_count, dead_leaf_ids

import networkx as nx
import numpy as np

#: Default number of permutations per predictor (``--mrqap-permutations``).
MRQAP_PERMUTATIONS_DEFAULT = 1000
#: Seed of the channel relabellings (the same sequence serves every predictor and both models).
MRQAP_SEED = 42
#: Above this many actors the regression is skipped: the dyad count grows with the square.
MRQAP_MAX_ACTORS = 3000
#: A partition group enters as a predictor when it labels at least this share of the observed channels.
MRQAP_MIN_GROUP_COVERAGE = 0.5
#: Permutations evaluated per vectorised batch.
_PERMUTATION_BATCH = 50
#: Dependent variables, in report order.
DEPENDENTS: tuple[tuple[str, str], ...] = (("tie", "Tie (0/1)"), ("log_citations", "log(1 + citations)"))

ACTOR_RULE = (
    "observed channels (dead leaves excluded) holding a label in every partition group used; a partition group "
    "is used when it holds at least two labels and labels at least MRQAP_MIN_GROUP_COVERAGE of the observed "
    "channels"
)
PREDICTOR_RULE = (
    "same label per used partition group; reverse tie (j cites i); sender and receiver log(1 + messages in the "
    "window); sender and receiver log(1 + subscribers), a missing subscriber count read as 0; constant "
    "predictors dropped"
)

_SOURCE = "network/mrqap.py"

#: The values fixed in this module (``PARAMETERS.md``); the permutation count is a run option.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="MRQAP actors",
        value=ACTOR_RULE,
        scope="mrqap",
        affects="Which channels' ordered pairs are the observations of the dyadic regression.",
        source=f"{_SOURCE}: ACTOR_RULE",
    ),
    FixedParameter(
        name="MRQAP minimum label-group coverage",
        value=MRQAP_MIN_GROUP_COVERAGE,
        scope="mrqap",
        affects="A partition label group labelling a smaller share of the observed channels is left out of the "
        "predictors instead of dropping the unlabelled channels.",
        source=f"{_SOURCE}: MRQAP_MIN_GROUP_COVERAGE",
    ),
    FixedParameter(
        name="MRQAP predictors",
        value=PREDICTOR_RULE,
        scope="mrqap",
        affects="The dyadic covariates both models are fitted on.",
        source=f"{_SOURCE}: PREDICTOR_RULE",
    ),
    FixedParameter(
        name="MRQAP dependent variables",
        value=[label for _key, label in DEPENDENTS],
        scope="mrqap",
        affects="Two OLS models: a linear probability model of the tie and a model of its log citation count.",
        source=f"{_SOURCE}: DEPENDENTS",
    ),
    FixedParameter(
        name="MRQAP seed",
        value=MRQAP_SEED,
        scope="mrqap",
        affects="Seeds the channel relabellings, so every p-value is reproducible.",
        source=f"{_SOURCE}: MRQAP_SEED",
        note="Double semi-partialling: Dekker, Krackhardt & Snijders (2007).",
    ),
    FixedParameter(
        name="MRQAP maximum actors",
        value=MRQAP_MAX_ACTORS,
        scope="mrqap",
        affects="Above this many actors the regression is skipped (the dyad table grows with the square).",
        source=f"{_SOURCE}: MRQAP_MAX_ACTORS",
    ),
)


@dataclass
class Design:
    """The dyad table of one graph: actor ids, the (i, j) index of every ordered pair, the dependent
    variables and the predictor matrix (no intercept column)."""

    actors: list[str]
    rows: np.ndarray
    cols: np.ndarray
    dependents: dict[str, np.ndarray]
    predictors: np.ndarray
    keys: list[str]
    labels: list[str]
    dropped_actors: int = 0
    groups_used: list[str] = field(default_factory=list)
    groups_skipped: list[str] = field(default_factory=list)
    constant_predictors: list[str] = field(default_factory=list)


def _partition_group_names() -> dict[int, str]:
    from webapp.models import LabelGroup

    return dict(LabelGroup.objects.filter(is_partition=True).order_by("-is_primary", "name").values_list("pk", "name"))


def build_design(graph: nx.DiGraph, graph_data: GraphData) -> "Design | str":
    """The :class:`Design` of ``graph``, or the reason the regression cannot run."""
    dead = dead_leaf_ids(graph)
    observed = sorted(n for n in graph if n not in dead)
    if len(observed) < 3:
        return "fewer than three observed channels"
    labels_of = {n: (graph.nodes[n].get("data") or {}).get("group_partitions") or {} for n in observed}
    used: list[tuple[int, str]] = []
    skipped: list[str] = []
    for group_id, name in _partition_group_names().items():
        labelled = [n for n in observed if (labels_of[n].get(group_id) or (None,))[0] is not None]
        distinct = {labels_of[n][group_id][0] for n in labelled}
        if len(distinct) >= 2 and len(labelled) >= MRQAP_MIN_GROUP_COVERAGE * len(observed):
            used.append((group_id, name))
        elif labelled:
            skipped.append(name)
    actors = [n for n in observed if all((labels_of[n].get(gid) or (None,))[0] is not None for gid, _ in used)]
    n_actors = len(actors)
    if n_actors < 3:
        return "fewer than three channels hold a label in every partition group used"
    if n_actors > MRQAP_MAX_ACTORS:
        return f"{n_actors} actors exceed the limit of {MRQAP_MAX_ACTORS}"

    index = {n: i for i, n in enumerate(actors)}
    rows, cols = np.where(~np.eye(n_actors, dtype=bool))
    citations = np.zeros((n_actors, n_actors))
    for u, v, data in graph.edges(data=True):
        if u != v and u in index and v in index:
            citations[index[u], index[v]] = citation_count(data)
    tie = (citations > 0).astype(float)
    node_info = {node["id"]: node for node in graph_data["nodes"]}
    activity = np.log1p([float(node_info.get(n, {}).get("messages_count") or 0) for n in actors])
    audience = np.log1p([float(node_info.get(n, {}).get("fans") or 0) for n in actors])

    columns: list[np.ndarray] = []
    keys: list[str] = []
    names: list[str] = []
    for group_id, name in used:
        group_labels = np.array([labels_of[n][group_id][0] for n in actors])
        columns.append((group_labels[rows] == group_labels[cols]).astype(float))
        keys.append(f"same_labelgroup{group_id}")
        names.append(f"Same {name}")
    columns += [tie[cols, rows], activity[rows], activity[cols], audience[rows], audience[cols]]
    keys += ["reverse_tie", "sender_activity", "receiver_activity", "sender_audience", "receiver_audience"]
    names += [
        "Reverse tie (j cites i)",
        "Sender activity (log messages)",
        "Receiver activity (log messages)",
        "Sender audience (log subscribers)",
        "Receiver audience (log subscribers)",
    ]
    constant = [names[k] for k, column in enumerate(columns) if np.ptp(column) == 0]
    kept = [k for k, column in enumerate(columns) if np.ptp(column) > 0]
    return Design(
        actors=actors,
        rows=rows,
        cols=cols,
        dependents={"tie": tie[rows, cols], "log_citations": np.log1p(citations[rows, cols])},
        predictors=np.column_stack([columns[k] for k in kept]) if kept else np.empty((rows.size, 0)),
        keys=[keys[k] for k in kept],
        labels=[names[k] for k in kept],
        dropped_actors=len(observed) - n_actors,
        groups_used=[name for _gid, name in used],
        groups_skipped=skipped,
        constant_predictors=constant,
    )


def _ols(design_matrix: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Coefficients, t-statistics and R² of ``y`` on ``design_matrix`` (which includes the intercept)."""
    beta, *_ = np.linalg.lstsq(design_matrix, y, rcond=None)
    resid = y - design_matrix @ beta
    dof = design_matrix.shape[0] - design_matrix.shape[1]
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.inv(design_matrix.T @ design_matrix)
    with np.errstate(invalid="ignore", divide="ignore"):
        t = beta / np.sqrt(np.diag(cov))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else float("nan")
    return beta, t, r2


def compute_mrqap(
    graph: nx.DiGraph,
    graph_data: GraphData,
    *,
    permutations: int = MRQAP_PERMUTATIONS_DEFAULT,
    seed: int = MRQAP_SEED,
    design: "Design | str | None" = None,
) -> dict[str, Any]:
    """The MRQAP payload (module docstring); ``{"skipped": reason}`` when the regression cannot run.

    ``design`` lets the caller reuse a :func:`build_design` it already built (the dyadic export writes
    the same table).
    """
    design = build_design(graph, graph_data) if design is None else design
    if isinstance(design, str):
        return {"skipped": design, "models": []}
    n_dyads, n_pred = design.predictors.shape
    if n_pred == 0:
        return {"skipped": "every predictor is constant", "models": []}
    full = np.column_stack([np.ones(n_dyads), design.predictors])
    if np.linalg.matrix_rank(full) < full.shape[1]:
        return {"skipped": "the predictors are perfectly collinear", "models": []}
    permutations = max(int(permutations), 0)
    n_actors = len(design.actors)

    observed: dict[str, tuple[np.ndarray, np.ndarray, float]] = {
        key: _ols(full, y) for key, _label in DEPENDENTS for y in [design.dependents[key]]
    }
    exceed = {key: np.zeros(n_pred) for key, _label in DEPENDENTS}
    rng = np.random.default_rng(seed)
    if permutations:
        # Per predictor: Z = intercept + the other predictors, its residual-maker applied to the
        # predictor (the semi-partialled column to permute) and to each dependent variable.
        partials = []
        for k in range(n_pred):
            z = np.delete(full, k + 1, axis=1)
            z_pinv = np.linalg.pinv(z)
            residual = design.predictors[:, k] - z @ (z_pinv @ design.predictors[:, k])
            matrix = np.zeros((n_actors, n_actors))
            matrix[design.rows, design.cols] = residual
            y_res = {key: design.dependents[key] - z @ (z_pinv @ design.dependents[key]) for key, _l in DEPENDENTS}
            partials.append((z, z_pinv, matrix, y_res))
        dof = n_dyads - full.shape[1]
        done = 0
        while done < permutations:
            size = min(_PERMUTATION_BATCH, permutations - done)
            perms = np.array([rng.permutation(n_actors) for _ in range(size)])
            for k, (z, z_pinv, matrix, y_res) in enumerate(partials):
                c = matrix[perms[:, design.rows], perms[:, design.cols]].T  # (n_dyads, size)
                c_res = c - z @ (z_pinv @ c)
                cc = np.einsum("ij,ij->j", c_res, c_res)
                for key, _label in DEPENDENTS:
                    yr = y_res[key]
                    cy = c_res.T @ yr
                    rss = float(yr @ yr) - cy * cy / cc
                    with np.errstate(invalid="ignore", divide="ignore"):
                        t = (cy / cc) / np.sqrt((rss / dof) / cc)
                    t_obs = observed[key][1][k + 1]
                    exceed[key][k] += np.count_nonzero(np.abs(t) >= abs(t_obs) - 1e-12)
            done += size

    y_sd = {key: float(design.dependents[key].std()) for key, _label in DEPENDENTS}
    x_sd = design.predictors.std(axis=0)
    models = []
    for key, label in DEPENDENTS:
        beta, t, r2 = observed[key]
        coefficients = []
        for k in range(n_pred):
            std_beta = beta[k + 1] * x_sd[k] / y_sd[key] if y_sd[key] > 0 else float("nan")
            coefficients.append(
                {
                    "key": design.keys[k],
                    "label": design.labels[k],
                    "coef": _r(beta[k + 1], 6),
                    "beta": _r(std_beta, 4),
                    "t": _r(t[k + 1], 2),
                    "p": _r((exceed[key][k] + 1) / (permutations + 1), 4) if permutations else None,
                }
            )
        models.append(
            {
                "dependent": key,
                "label": label,
                "intercept": _r(beta[0], 6),
                "r2": _r(r2, 4),
                "mean": _r(float(design.dependents[key].mean()), 6),
                "coefficients": coefficients,
            }
        )
    return {
        "skipped": None,
        "actors": n_actors,
        "dropped_actors": design.dropped_actors,
        "dyads": n_dyads,
        "permutations": permutations,
        "groups_used": design.groups_used,
        "groups_skipped": design.groups_skipped,
        "constant_predictors": design.constant_predictors,
        "models": models,
    }


def _r(value: float, digits: int) -> float | None:
    return round(float(value), digits) if value is not None and np.isfinite(value) else None


# ── Flat row layouts shared by the XLSX sheet ──────────────────────────────────────────────────

MODEL_COLUMNS: tuple[str, ...] = ("Year", "Dependent", "R²", "Mean", "Intercept", "Actors", "Dyads", "Permutations")
COEFFICIENT_COLUMNS: tuple[str, ...] = ("Year", "Dependent", "Predictor", "Coefficient", "Standardised β", "t", "p")


def model_rows(payload: dict[str, Any], year: str) -> list[list[Any]]:
    return [
        [
            year,
            model["label"],
            model["r2"],
            model["mean"],
            model["intercept"],
            payload["actors"],
            payload["dyads"],
            payload["permutations"],
        ]
        for model in payload.get("models") or []
    ]


def coefficient_rows(payload: dict[str, Any], year: str) -> list[list[Any]]:
    return [
        [year, model["label"], c["label"], c["coef"], c["beta"], c["t"], c["p"]]
        for model in payload.get("models") or []
        for c in model["coefficients"]
    ]

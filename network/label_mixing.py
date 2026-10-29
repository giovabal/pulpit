"""Label mixing: homophily and citation flows between the labels of each partition label group.

For every *partition* label group (Nation, Continent, …) the analyst's labels are set against the
citation ties between the channels that carry them, and every statistic is tested against one null:
**label permutation** — the labels are shuffled over the labelled channels while the graph stays fixed
(the node-label permutation of the quadratic assignment procedure; Hubert & Schultz 1976; Krackhardt
1988; the test Krackhardt & Stern 1988 propose for the E-I index). Group sizes and the whole tie
structure are preserved, so every citation of a channel moves with it — the null controls for the
channels' activity and popularity and for the overdispersion of citation counts, and asks only whether
*which label a channel carries* predicts whom it cites.

Per group:

* **Nominal assortativity** *r* (Newman 2003, directed form) on ties and on citations — 1 = every tie
  stays inside its label, 0 = labels unrelated to ties, negative = ties prefer other labels.
* **E-I index** over labelled ties (Krackhardt & Stern 1988) next to its permutation expectation — the
  size-corrected reading: a large label is inward-looking under the null too.

Per label:

* **Inbreeding homophily** ``IH = (H − w) / (1 − w)`` (Coleman 1958; Currarini, Jackson & Pin 2009),
  where ``H`` is the share of the label's sent (``out``) or received (``in``) ties that stay inside it
  and ``w = (n − 1) / (N − 1)`` the share expected when partners are chosen regardless of label. A
  label holding half the channels has ``w ≈ 0.5``, so its raw internal share is discounted accordingly.
* **Net-exporter index** ``(cross-label received − given) / (received + given)``: positive = the
  label's channels are cited from other labels more than they cite them.
* **Out-of-scope share**: the share of the label's sent ties / citations that go to channels holding
  no label in the group, or to dead leaves (descriptive; not part of the null).

Per ordered label pair: the **flow matrix** of ties and citations, its permutation expectation, the
observed / expected ratio and, on ties, a two-sided permutation test with Benjamini–Hochberg control
across the tested cells.

Only observed channels enter (dead leaves' own citations are never read, so they could not be
permuted like the rest); self-loops are left out.
"""

import logging
from typing import Any

from network.parameters import FixedParameter
from network.robustness.null_model import bh_adjust, empirical_p, z_score
from network.utils import citation_count, dead_leaf_ids

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

#: Label permutations behind every p-value: the two-sided floor is 2/(K+1), low enough for the
#: Benjamini–Hochberg correction over a few hundred flow cells to reach q < 0.05.
LABEL_PERMUTATIONS = 10_000
#: Permutations evaluated per vectorised batch (capped further on very large graphs to bound memory).
LABEL_PERMUTATION_BATCH = 500
#: Upper bound on batch × ties, the size of the index array one batch builds.
_BATCH_CELLS = 4_000_000
#: Seed of the label permutations (each group draws from its own stream, seeded by this and its id).
LABEL_MIXING_SEED = 42
#: Labels with fewer channels get no inbreeding homophily: with one channel there is no partner inside.
HOMOPHILY_MIN_LABEL_SIZE = 2
#: A flow cell is tested when its observed or expected tie count reaches this floor.
FLOW_MIN_TIES = 3

NODE_RULE = (
    "observed channels (dead leaves excluded) holding a label in the group; ties between two of them, "
    "self-loops excluded"
)
UNIT_RULE = (
    "ties = distinct citing → cited channel pairs; citations = the raw forwards + mentions (+ near-copies) on "
    "them, whatever --edge-weight-strategy"
)
NULL_RULE = "labels shuffled over the labelled channels with the graph fixed (node-label permutation, QAP)"

_SOURCE = "network/label_mixing.py"

#: The values fixed in this module (``PARAMETERS.md``).
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Label-mixing channels and ties",
        value=NODE_RULE,
        scope="homophily",
        affects="Which channels and ties the homophily statistics and the label flow matrices describe.",
        source=f"{_SOURCE}: NODE_RULE",
    ),
    FixedParameter(
        name="Label-mixing units",
        value=UNIT_RULE,
        scope="homophily",
        affects="Assortativity, inbreeding homophily and flows are reported on ties; assortativity and flows "
        "also on citations.",
        source=f"{_SOURCE}: UNIT_RULE",
    ),
    FixedParameter(
        name="Label-mixing null model",
        value=NULL_RULE,
        scope="homophily",
        affects="Every homophily z, p and q, and the expected flows, compare the data with these permutations.",
        source=f"{_SOURCE}: NULL_RULE",
        note="Hubert & Schultz (1976); Krackhardt (1988); Krackhardt & Stern (1988).",
    ),
    FixedParameter(
        name="Label permutations",
        value=LABEL_PERMUTATIONS,
        scope="homophily",
        affects="Random relabellings per label group; the smallest two-sided p is 2/(K+1).",
        source=f"{_SOURCE}: LABEL_PERMUTATIONS",
        note="Add-one Monte-Carlo p-values (Phipson & Smyth 2010).",
    ),
    FixedParameter(
        name="Label permutation seed",
        value=LABEL_MIXING_SEED,
        scope="homophily",
        affects="Seeds the permutations (one stream per label group), so every p-value is reproducible.",
        source=f"{_SOURCE}: LABEL_MIXING_SEED",
    ),
    FixedParameter(
        name="Minimum label size for inbreeding homophily",
        value=HOMOPHILY_MIN_LABEL_SIZE,
        scope="homophily",
        affects="Labels with fewer channels report no inbreeding homophily (no partner can share the label).",
        source=f"{_SOURCE}: HOMOPHILY_MIN_LABEL_SIZE",
    ),
    FixedParameter(
        name="Minimum ties for a tested flow",
        value=FLOW_MIN_TIES,
        scope="homophily",
        affects="A label → label flow is tested (z, p, BH q) only when its observed or expected tie count "
        "reaches this floor; the others are listed untested.",
        source=f"{_SOURCE}: FLOW_MIN_TIES",
        note="Benjamini & Hochberg (1995) over the tested cells of each group.",
    ),
)


def _assortativity(mixing: np.ndarray) -> float | None:
    """Newman's (2003) nominal assortativity of a directed mixing matrix (counts or weights)."""
    total = float(mixing.sum())
    if total <= 0:
        return None
    e = mixing / total
    ab = float(e.sum(axis=1) @ e.sum(axis=0))
    if ab >= 1.0:
        return None
    return (float(np.trace(e)) - ab) / (1.0 - ab)


def _batched_assortativity(mixing: np.ndarray) -> np.ndarray:
    """:func:`_assortativity` over a stack of mixing matrices of shape (B, L, L); NaN where undefined."""
    totals = mixing.sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        e = mixing / totals[:, None, None]
        ab = np.einsum("bi,bi->b", e.sum(axis=2), e.sum(axis=1))
        trace = np.trace(e, axis1=1, axis2=2)
        r = (trace - ab) / (1.0 - ab)
    r[(totals <= 0) | (ab >= 1.0)] = np.nan
    return r


def _ei(trace: np.ndarray | float, total: float) -> np.ndarray | float:
    return (total - 2.0 * trace) / total


def _rounded(value: float | None, digits: int = 6) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def _test(observed: float | None, null: list[float]) -> dict[str, float | None]:
    """``{value, null_mean, z, p}`` of a scalar statistic against its permutation draws."""
    finite = [v for v in null if np.isfinite(v)]
    if observed is None or not finite:
        return {"value": _rounded(observed), "null_mean": None, "z": None, "p": None}
    z, mean, _sd = z_score(observed, finite)
    return {
        "value": _rounded(observed),
        "null_mean": _rounded(mean),
        "z": _rounded(z, 2),
        "p": _rounded(empirical_p(observed, finite), 4),
    }


class _Tally:
    """Streaming sum / sum of squares / tail counts of a statistic array across permutations."""

    def __init__(self, observed: np.ndarray) -> None:
        self.observed = observed
        self.n = np.zeros(observed.shape)
        self.total = np.zeros(observed.shape)
        self.squares = np.zeros(observed.shape)
        self.ge = np.zeros(observed.shape)
        self.le = np.zeros(observed.shape)

    def add(self, batch: np.ndarray) -> None:
        finite = np.isfinite(batch)
        values = np.where(finite, batch, 0.0)
        self.n += finite.sum(axis=0)
        self.total += values.sum(axis=0)
        self.squares += (values * values).sum(axis=0)
        self.ge += (finite & (batch >= self.observed)).sum(axis=0)
        self.le += (finite & (batch <= self.observed)).sum(axis=0)

    def mean(self) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            return self.total / self.n

    def z(self) -> np.ndarray:
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = self.total / self.n
            var = (self.squares - self.n * mean * mean) / (self.n - 1)
            sd = np.sqrt(np.clip(var, 0.0, None))
            z = (self.observed - mean) / sd
        z[~np.isfinite(z)] = np.nan
        return z

    def p(self) -> np.ndarray:
        """Two-sided add-one p (the :func:`empirical_p` convention), NaN without draws."""
        with np.errstate(invalid="ignore", divide="ignore"):
            low = (self.le + 1.0) / (self.n + 1.0)
            high = (self.ge + 1.0) / (self.n + 1.0)
            p = np.minimum(1.0, 2.0 * np.minimum(low, high))
        p[self.n == 0] = np.nan
        return p


def _internal_shares(mixing: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per label, the share of sent (rows) and received (columns) ties that stay inside it; NaN when none."""
    diagonal = np.diagonal(mixing, axis1=-2, axis2=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out_share = diagonal / mixing.sum(axis=-1)
        in_share = diagonal / mixing.sum(axis=-2)
    return out_share, in_share


def _matrix(values: np.ndarray, digits: int = 4, mask: np.ndarray | None = None) -> list[list[float | None]]:
    rows: list[list[float | None]] = []
    for i in range(values.shape[0]):
        row: list[float | None] = []
        for j in range(values.shape[1]):
            if mask is not None and not mask[i, j]:
                row.append(None)
            else:
                row.append(_rounded(values[i, j], digits))
        rows.append(row)
    return rows


def _group_mixing(
    graph: nx.DiGraph,
    group_id: int,
    group_name: str,
    node_labels: dict[str, int],
    label_names: dict[int, str],
    permutations: int,
    seed: int,
) -> dict[str, Any] | None:
    """The label-mixing payload of one partition group, or ``None`` when it has < 2 labels or no tie."""
    nodes = sorted(node_labels)
    label_ids = sorted({node_labels[n] for n in nodes}, key=lambda pk: (label_names.get(pk, ""), pk))
    if len(label_ids) < 2:
        return None
    label_index = {pk: i for i, pk in enumerate(label_ids)}
    node_index = {n: i for i, n in enumerate(nodes)}
    labels = np.array([label_index[node_labels[n]] for n in nodes], dtype=np.int64)
    n_labels = len(label_ids)
    n_nodes = len(nodes)

    src, dst, cites = [], [], []
    out_scope_ties = np.zeros(n_labels)
    out_scope_cites = np.zeros(n_labels)
    sent_ties_all = np.zeros(n_labels)
    sent_cites_all = np.zeros(n_labels)
    for u, v, data in graph.edges(data=True):
        if u == v or u not in node_index:
            continue
        count = citation_count(data)
        li = labels[node_index[u]]
        sent_ties_all[li] += 1
        sent_cites_all[li] += count
        if v in node_index:
            src.append(node_index[u])
            dst.append(node_index[v])
            cites.append(count)
        else:  # unlabelled in this group, a dead leaf, or an environment channel
            out_scope_ties[li] += 1
            out_scope_cites[li] += count
    if not src:
        return None
    src_arr = np.array(src, dtype=np.int64)
    dst_arr = np.array(dst, dtype=np.int64)
    cite_arr = np.array(cites, dtype=float)
    n_ties = len(src)
    cells = n_labels * n_labels

    def mixing_of(lab: np.ndarray, weights: np.ndarray | None) -> np.ndarray:
        codes = lab[src_arr] * n_labels + lab[dst_arr]
        return np.bincount(codes, weights=weights, minlength=cells).reshape(n_labels, n_labels).astype(float)

    ties_obs = mixing_of(labels, None)
    cites_obs = mixing_of(labels, cite_arr)
    out_share_obs, in_share_obs = _internal_shares(ties_obs)
    r_ties_obs = _assortativity(ties_obs)
    r_cites_obs = _assortativity(cites_obs)
    ei_obs = float(_ei(np.trace(ties_obs), n_ties))

    cell_tally = _Tally(ties_obs)
    out_tally = _Tally(out_share_obs)
    in_tally = _Tally(in_share_obs)
    cites_sum = np.zeros((n_labels, n_labels))
    r_ties_null: list[float] = []
    r_cites_null: list[float] = []
    ei_null: list[float] = []

    rng = np.random.default_rng([seed, group_id])
    batch = max(1, min(LABEL_PERMUTATION_BATCH, _BATCH_CELLS // n_ties))
    done = 0
    while done < permutations:
        size = min(batch, permutations - done)
        perm = rng.permuted(np.broadcast_to(labels, (size, n_nodes)), axis=1)
        offsets = (np.arange(size, dtype=np.int64) * cells)[:, None]
        codes = (perm[:, src_arr] * n_labels + perm[:, dst_arr] + offsets).ravel()
        ties_b = np.bincount(codes, minlength=size * cells).reshape(size, n_labels, n_labels).astype(float)
        cites_b = np.bincount(codes, weights=np.tile(cite_arr, size), minlength=size * cells).reshape(
            size, n_labels, n_labels
        )
        cell_tally.add(ties_b)
        cites_sum += cites_b.sum(axis=0)
        out_b, in_b = _internal_shares(ties_b)
        out_tally.add(out_b)
        in_tally.add(in_b)
        r_ties_null.extend(_batched_assortativity(ties_b).tolist())
        r_cites_null.extend(_batched_assortativity(cites_b).tolist())
        ei_null.extend(_ei(np.trace(ties_b, axis1=1, axis2=2), n_ties).tolist())
        done += size

    # ── per label ──
    sizes = np.bincount(labels, minlength=n_labels)
    out_p, in_p = out_tally.p(), in_tally.p()
    eligible = [i for i in range(n_labels) if sizes[i] >= HOMOPHILY_MIN_LABEL_SIZE]
    family: list[float] = []
    slots: list[tuple[str, int]] = []
    for i in eligible:
        for side, pvals in (("out", out_p), ("in", in_p)):
            if np.isfinite(pvals[i]):
                family.append(float(pvals[i]))
                slots.append((side, i))
    qvals = dict(zip(slots, bh_adjust(family), strict=True)) if family else {}

    rows: list[dict[str, Any]] = []
    for i, pk in enumerate(label_ids):
        n_i = int(sizes[i])
        baseline = (n_i - 1) / (n_nodes - 1) if n_nodes > 1 else None
        row: dict[str, Any] = {
            "label_id": pk,
            "label": label_names.get(pk, str(pk)),
            "channels": n_i,
            "baseline_share": _rounded(baseline, 4),
            "ties_sent": int(ties_obs[i].sum()),
            "ties_received": int(ties_obs[:, i].sum()),
            "citations_sent": int(cites_obs[i].sum()),
            "citations_received": int(cites_obs[:, i].sum()),
        }
        for side, share, pvals in (("out", out_share_obs, out_p), ("in", in_share_obs, in_p)):
            h = share[i]
            ih = None
            if i in eligible and baseline is not None and baseline < 1.0 and np.isfinite(h):
                ih = (h - baseline) / (1.0 - baseline)
            row[f"h_{side}"] = _rounded(h, 4)
            row[f"ih_{side}"] = _rounded(ih, 4)
            row[f"ih_{side}_p"] = _rounded(pvals[i], 4) if ih is not None else None
            row[f"ih_{side}_q"] = _rounded(qvals.get((side, i)), 4) if ih is not None else None
        for unit, mixing in (("ties", ties_obs), ("citations", cites_obs)):
            given = float(mixing[i].sum() - mixing[i, i])
            received = float(mixing[:, i].sum() - mixing[i, i])
            row[f"net_exporter_{unit}"] = (
                _rounded((received - given) / (received + given), 4) if received + given else None
            )
        row["out_of_scope_ties_share"] = _rounded(out_scope_ties[i] / sent_ties_all[i], 4) if sent_ties_all[i] else None
        row["out_of_scope_citations_share"] = (
            _rounded(out_scope_cites[i] / sent_cites_all[i], 4) if sent_cites_all[i] else None
        )
        rows.append(row)

    # ── flows ──
    expected = cell_tally.mean()
    tested = np.maximum(ties_obs, np.nan_to_num(expected)) >= FLOW_MIN_TIES
    cell_p = cell_tally.p()
    cell_q = np.full(cell_p.shape, np.nan)
    tested_idx = [
        (i, j) for i in range(n_labels) for j in range(n_labels) if tested[i, j] and np.isfinite(cell_p[i, j])
    ]
    if tested_idx:
        for (i, j), q in zip(tested_idx, bh_adjust([float(cell_p[i, j]) for i, j in tested_idx]), strict=True):
            cell_q[i, j] = q
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(expected > 0, ties_obs / expected, np.nan)
    expected_cites = cites_sum / permutations

    return {
        "group_id": group_id,
        "group": group_name,
        "key": f"labelgroup{group_id}",
        "labels": [label_names.get(pk, str(pk)) for pk in label_ids],
        "channels": n_nodes,
        "ties": n_ties,
        "citations": int(cite_arr.sum()),
        "permutations": permutations,
        "assortativity": {"ties": _test(r_ties_obs, r_ties_null), "citations": _test(r_cites_obs, r_cites_null)},
        "ei_index": _test(ei_obs, ei_null),
        "rows": rows,
        "flows": {
            "ties": ties_obs.astype(int).tolist(),
            "citations": cites_obs.astype(int).tolist(),
            "expected_ties": _matrix(expected, 3),
            "expected_citations": _matrix(expected_cites, 2),
            "ratio": _matrix(ratio, 3),
            "z": _matrix(cell_tally.z(), 2, tested),
            "p": _matrix(cell_p, 4, tested),
            "q": _matrix(cell_q, 4, tested),
        },
    }


def _partition_groups() -> list[tuple[int, str]]:
    """``(id, name)`` of every partition label group, the primary group first."""
    from webapp.models import LabelGroup

    return list(LabelGroup.objects.filter(is_partition=True).order_by("-is_primary", "name").values_list("pk", "name"))


def compute_label_mixing(
    graph: nx.DiGraph, *, permutations: int = LABEL_PERMUTATIONS, seed: int = LABEL_MIXING_SEED
) -> dict[str, Any]:
    """Homophily statistics and label flow matrices of every partition label group (module docstring).

    Labels are the window-resolved ones ``build_graph`` writes to ``node["data"]["group_partitions"]``
    for every partition group, so no ``LABELGROUP<id>`` strategy needs to be selected. Returns
    ``{"permutations": K, "groups": [payload, …]}``, groups with fewer than two labels among the
    observed channels, or without a tie between labelled channels, left out.
    """
    from webapp.models import Label

    dead = dead_leaf_ids(graph)
    observed = {n for n in graph if n not in dead}
    per_group: dict[int, dict[str, int]] = {}
    for node in observed:
        for group_id, resolved in ((graph.nodes[node].get("data") or {}).get("group_partitions") or {}).items():
            if resolved and resolved[0] is not None:
                per_group.setdefault(int(group_id), {})[node] = int(resolved[0])
    if not per_group:
        return {"permutations": permutations, "groups": []}
    label_ids = {pk for labels in per_group.values() for pk in labels.values()}
    label_names = dict(Label.objects.filter(pk__in=label_ids).values_list("pk", "name"))
    groups: list[dict[str, Any]] = []
    for group_id, group_name in _partition_groups():
        node_labels = per_group.get(group_id)
        if not node_labels:
            continue
        payload = _group_mixing(graph, group_id, group_name, node_labels, label_names, permutations, seed)
        if payload is not None:
            groups.append(payload)
    return {"permutations": permutations, "groups": groups}


# ── Flat row layouts shared by the XLSX sheets and label_flows.csv ─────────────────────────────

GROUP_COLUMNS: tuple[str, ...] = (
    "Year",
    "Group",
    "Labelled channels",
    "Ties",
    "Citations",
    "Assortativity r (ties)",
    "Null mean",
    "z",
    "p",
    "Assortativity r (citations)",
    "Null mean",
    "z",
    "p",
    "E-I index (labelled ties)",
    "Expected E-I",
    "z",
    "p",
)
LABEL_COLUMNS: tuple[str, ...] = (
    "Year",
    "Group",
    "Label",
    "Channels",
    "Baseline share w",
    "Internal share of sent ties",
    "Inbreeding homophily (out)",
    "p (out)",
    "q (out)",
    "Internal share of received ties",
    "Inbreeding homophily (in)",
    "p (in)",
    "q (in)",
    "Net exporter (ties)",
    "Net exporter (citations)",
    "Out-of-scope share (ties)",
    "Out-of-scope share (citations)",
    "Ties sent",
    "Ties received",
    "Citations sent",
    "Citations received",
)
FLOW_COLUMNS: tuple[str, ...] = (
    "year",
    "group",
    "citing_label",
    "cited_label",
    "ties",
    "expected_ties",
    "ratio",
    "z",
    "p",
    "q",
    "citations",
    "expected_citations",
)


def group_rows(payload: dict[str, Any], year: str) -> list[list[Any]]:
    """One :data:`GROUP_COLUMNS` row per label group of a :func:`compute_label_mixing` payload."""
    rows = []
    for group in payload.get("groups") or []:
        r_ties, r_cites, ei = group["assortativity"]["ties"], group["assortativity"]["citations"], group["ei_index"]
        rows.append(
            [
                year,
                group["group"],
                group["channels"],
                group["ties"],
                group["citations"],
                *(r_ties[k] for k in ("value", "null_mean", "z", "p")),
                *(r_cites[k] for k in ("value", "null_mean", "z", "p")),
                *(ei[k] for k in ("value", "null_mean", "z", "p")),
            ]
        )
    return rows


def label_rows(payload: dict[str, Any], year: str) -> list[list[Any]]:
    """One :data:`LABEL_COLUMNS` row per label of every group of a :func:`compute_label_mixing` payload."""
    keys = (
        "label",
        "channels",
        "baseline_share",
        "h_out",
        "ih_out",
        "ih_out_p",
        "ih_out_q",
        "h_in",
        "ih_in",
        "ih_in_p",
        "ih_in_q",
        "net_exporter_ties",
        "net_exporter_citations",
        "out_of_scope_ties_share",
        "out_of_scope_citations_share",
        "ties_sent",
        "ties_received",
        "citations_sent",
        "citations_received",
    )
    return [
        [year, group["group"], *(row.get(k) for k in keys)]
        for group in payload.get("groups") or []
        for row in group["rows"]
    ]


def flow_rows(payload: dict[str, Any], year: str) -> list[list[Any]]:
    """One :data:`FLOW_COLUMNS` row per label pair with a tie observed or expected (long format)."""
    rows = []
    for group in payload.get("groups") or []:
        flows, labels = group["flows"], group["labels"]
        for i, citing in enumerate(labels):
            for j, cited in enumerate(labels):
                expected = flows["expected_ties"][i][j]
                if not flows["ties"][i][j] and not expected:
                    continue
                rows.append(
                    [
                        year,
                        group["group"],
                        citing,
                        cited,
                        flows["ties"][i][j],
                        expected,
                        flows["ratio"][i][j],
                        flows["z"][i][j],
                        flows["p"][i][j],
                        flows["q"][i][j],
                        flows["citations"][i][j],
                        flows["expected_citations"][i][j],
                    ]
                )
    return rows

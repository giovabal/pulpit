"""Dominance analysis — who dominates whom in a positive citation network.

Built for a corpus of peer channels (say the local chapters of one organisation) where a forward is
an endorsement: when X forwards Y, X *took up* Y's content, so Y won that interaction. Three
layers, each a function of observed dyads and their raw counts only — no path, walk or flow claim,
so all of it sits inside Pulpit's one-degree attribution model.

**Dyads — two-sided dependence.** Power-dependence theory (Emerson 1962) reads the power of Y over
X as X's dependence on Y, and each side of a citation dyad depends on the other for a different
resource. For a link X→Y with ``c`` citations, X's *content* dependence on Y is
``c / citing(X)`` — the share of X's citing output that goes to Y (the ``PARTIAL_REFERENCES``
weight) — and Y's *reach* dependence on X is ``c / cited(Y)``, the share of Y's received citations
that X supplies. Normalising the same events by each side's own total is the dependence-asymmetry
construction of Bascompte, Jordano & Olesen (2006). A pair's net balance is the difference of the
two sides' dependences (each the mean of its content and reach components); the side that depends
more is the *dependent*, the other the *dominant*. Every link with at
least ``min_events`` citations is also *validated* against a null of heterogeneous activity — the
hypergeometric statistically-validated-networks test (Tumminello et al. 2011; directed form in
Hatzopoulos et al. 2015), Benjamini–Hochberg corrected — and the pair is labelled ``alliance``
(both directions validated), ``dependence`` (one) or ``unvalidated`` (none).

**Nodes — David's score and roles.** David's score (David 1987; Gammell et al. 2003) is the
standard dominance index for groups without formal ranks: it sums a node's dyadic dominance
proportions, adds those of the nodes it dominates, and subtracts the mirror terms. The dyadic
proportion is **read from the pair's dependences, not from raw citation counts**:
``P(i over j) = dependence(j on i) / (dependence(i on j) + dependence(j on i))``, the share of the
pair's dependence that flows toward ``i`` — so the two sides of every pair "split" its citations
in proportion to how much each relies on the other, and a distributor that is a source's only
outlet wins that dyad even though it is the one doing the citing. This is what keeps the ranking
and the roles on the same footing. Each proportion is shrunk toward a draw by the de Vries,
Stevens & Vervaecke (2006) correction ``D = P − (P − 0.5) / (n + 1)`` with ``n`` the pair's
citation count, so sparse dyads barely count. The score is normalised as in de Vries et al.
(2006). SpringRank (De Bacco, Larremore & Moore 2018) gives a second, real-valued ranking of the
same dependence-weighted interactions. Roles come from two transparent
quantities: a node's *satellites* (partners that depend on it for at least ``SATELLITE_SHARE`` of
their content or of their reach and sit clearly on the dependent side of the pair) and its own
largest such dependence on a partner — ``dominant`` has satellites and is nobody's satellite,
``dependent`` is a satellite and has none, ``broker`` is both, ``allied`` is neither but sits in
a validated mutual pair, ``peripheral`` none of these.

**Whole network — is there a hierarchy at all?** Three statistics built for sparse dominance data,
sharing one null: every dyad keeps its counts in both directions — hence its reciprocity — and
which side is on top is drawn at random, so each test asks whether the *arrangement* of dominance
across dyads is more hierarchical than a random orientation of the same dyads (a per-interaction
random-winner null would only certify that citation dyads are one-way, which they nearly always
are). SpringRank's ground-state energy asks whether one ranking explains the interactions;
triangle transitivity (Shizuka & McDonald 2012) — the share of fully known triads that are
transitive rather than cyclic, rescaled so random is 0 and a perfect order 1 — asks whether
dominance is transitive, and unlike Landau's h and de Vries's h′ it is not biased by the unknown
dyads that dominate a sparse network; rank consistency — the share of dependence-weighted
interactions flowing toward the higher-ranked side under the fitted ranking — asks how strictly
the order is respected. Steepness (de Vries et al. 2006) is deliberately not reported: it assumes
a group in which everyone meets everyone, and on the star and tree shapes citation networks take
its slope falls *below* random because equal satellites form plateaus.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from network.parameters import FixedParameter
from network.robustness.null_model import bh_adjust
from network.utils import GraphData

import networkx as nx
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.stats import hypergeom

# FDR level (Benjamini–Hochberg q) under which a directed link counts as validated.
DEFAULT_Q_THRESHOLD = 0.05
# Evidence floor, in citation events. A directed link below it is listed but not tested (on one-off
# citations the hypergeometric test rewards uniqueness rather than preference); a channel with
# fewer citing messages than this gets no content share (its "dependence" would rest on one or two
# forwards); a dyad with fewer interactions than this is left out of the dominance ranking and the
# hierarchy tests, and out of satellite ties.
DEFAULT_MIN_EVENTS = 3
# Orientation-shuffled permutations behind the SpringRank / transitivity / consistency p-values.
DEFAULT_PERMUTATIONS = 200
# An amplifier devoting at least this share of its citing output to one source is that source's
# *satellite* (the majority criterion — tie-free); a node relying that much on one source is dependent.
SATELLITE_SHARE = 0.5
# …and the pair must be clearly one-sided (Bascompte asymmetry of the pair at least this much), so
# that two channels which are each other's main source and outlet read as an alliance, not as two
# dependents.
SATELLITE_ASYMMETRY = 0.25
DOMINANT_MIN_SATELLITES = 2
# Weak spring to the origin (the regularised SpringRank form) — makes the system positive-definite.
SPRINGRANK_ALPHA = 0.01
# SpringRank is refitted on at most this many of the null draws (one sparse solve each).
SPRINGRANK_MAX_NULLS = 100
# Above this many ranked nodes the permutation count is cut (dense N×N null draws) to
# max(LARGE_N_MIN_PERMUTATIONS, permutations // LARGE_N_PERMUTATION_DIVISOR).
LARGE_N = 3000
LARGE_N_PERMUTATION_DIVISOR = 10
LARGE_N_MIN_PERMUTATIONS = 20
# Probability that the orientation-shuffled null swaps a dyad's two counts (a fair coin).
NULL_FLIP_PROBABILITY = 0.5
# Seed of the orientation-shuffled null (``compute_dominance``'s default; the command does not override it).
DOMINANCE_SEED = 42

RELATION_DEPENDENCE = "dependence"
RELATION_ALLIANCE = "alliance"
RELATION_UNVALIDATED = "unvalidated"
RELATIONS: tuple[str, ...] = (RELATION_DEPENDENCE, RELATION_ALLIANCE, RELATION_UNVALIDATED)

ROLE_DOMINANT = "dominant"
ROLE_DEPENDENT = "dependent"
ROLE_BROKER = "broker"
ROLE_ALLIED = "allied"
ROLE_PERIPHERAL = "peripheral"
ROLES: tuple[str, ...] = (ROLE_DOMINANT, ROLE_DEPENDENT, ROLE_BROKER, ROLE_ALLIED, ROLE_PERIPHERAL)

# How the content share is normalised: by each amplifier's citing-message count (stored on the node
# by build_graph) or — when the graph carries no such attribute — by its citation events in the graph.
SHARE_BASIS_CITING = "citing_messages"
SHARE_BASIS_EVENTS = "graph_events"

# Node-attribute key injected into the channel table / map when the analysis is on.
DAVID_SCORE_KEY = "david_score"
DAVID_SCORE_LABEL = "David's score"

_SOURCE = "network/dominance.py"

#: The values fixed in this module that shape the dominance analysis (``PARAMETERS.md``). The
#: evidence floor and the permutation count are run options (``--dominance-min-events`` /
#: ``--dominance-permutations``), not listed here.
FIXED_PARAMETERS: tuple[FixedParameter, ...] = (
    FixedParameter(
        name="Link validation FDR level q",
        value=DEFAULT_Q_THRESHOLD,
        scope="dominance",
        affects="A directed link is validated when its Benjamini–Hochberg-adjusted hypergeometric p-value is "
        "below this; validation decides each pair's relation (alliance / dependence / unvalidated) and the "
        "allied role.",
        source=f"{_SOURCE}: DEFAULT_Q_THRESHOLD",
        note="Statistically validated networks: Tumminello et al. 2011; directed form Hatzopoulos et al. 2015.",
    ),
    FixedParameter(
        name="Satellite share",
        value=SATELLITE_SHARE,
        scope="dominance",
        affects="A partner is a channel's satellite when it depends on it for at least this share of its content "
        "or of its reach; a channel relying that much on one partner is dependent.",
        source=f"{_SOURCE}: SATELLITE_SHARE",
        note="The majority criterion — tie-free (docs/dominance.md).",
    ),
    FixedParameter(
        name="Satellite asymmetry",
        value=SATELLITE_ASYMMETRY,
        scope="dominance",
        affects="A satellite tie also needs the pair's Bascompte asymmetry to reach this, so two channels that "
        "are each other's main source and outlet read as allies, not as two dependents.",
        source=f"{_SOURCE}: SATELLITE_ASYMMETRY",
    ),
    FixedParameter(
        name="Dominant: minimum satellites",
        value=DOMINANT_MIN_SATELLITES,
        scope="dominance",
        affects="A channel needs at least this many satellites to be dominant (or, if itself dependent, a broker).",
        source=f"{_SOURCE}: DOMINANT_MIN_SATELLITES",
    ),
    FixedParameter(
        name="SpringRank regularising spring α",
        value=SPRINGRANK_ALPHA,
        scope="dominance",
        affects="Weak spring pulling every SpringRank score toward 0, which makes the linear system "
        "positive-definite; it slightly shrinks the scores of weakly connected channels.",
        source=f"{_SOURCE}: SPRINGRANK_ALPHA",
        note="The regularised SpringRank form (De Bacco, Larremore & Moore 2018).",
    ),
    FixedParameter(
        name="SpringRank null draws",
        value=SPRINGRANK_MAX_NULLS,
        scope="dominance",
        affects="The SpringRank-energy p-value is computed on at most this many of the orientation-shuffled "
        "null networks; transitivity and rank consistency use all of them.",
        source=f"{_SOURCE}: SPRINGRANK_MAX_NULLS",
    ),
    FixedParameter(
        name="Large-network threshold",
        value=LARGE_N,
        scope="dominance",
        affects="Above this many ranked channels the permutation count of the hierarchy tests is cut.",
        source=f"{_SOURCE}: LARGE_N",
        note="Each null draw is a dense N×N matrix.",
    ),
    FixedParameter(
        name="Large-network permutation divisor",
        value=LARGE_N_PERMUTATION_DIVISOR,
        scope="dominance",
        affects="Above the large-network threshold the hierarchy tests run --dominance-permutations divided by this.",
        source=f"{_SOURCE}: LARGE_N_PERMUTATION_DIVISOR",
    ),
    FixedParameter(
        name="Large-network minimum permutations",
        value=LARGE_N_MIN_PERMUTATIONS,
        scope="dominance",
        affects="Above the large-network threshold the hierarchy tests still run at least this many permutations.",
        source=f"{_SOURCE}: LARGE_N_MIN_PERMUTATIONS",
    ),
    FixedParameter(
        name="Null orientation flip probability",
        value=NULL_FLIP_PROBABILITY,
        scope="dominance",
        affects="In each null network every dyad keeps both of its counts and swaps which side holds the "
        "larger one with this probability.",
        source=f"{_SOURCE}: NULL_FLIP_PROBABILITY",
        note="A fair coin: the orientation-shuffled null of docs/dominance.md.",
    ),
    FixedParameter(
        name="Null-model random seed",
        value=DOMINANCE_SEED,
        scope="dominance",
        affects="Seeds the orientation-shuffled null networks, so the hierarchy-test p-values are reproducible.",
        source=f"{_SOURCE}: DOMINANCE_SEED",
    ),
)


def _edge_count(data: dict) -> int:
    """Raw citation events on an edge: forwards + mentions (+ near-copies when that option is on),
    as build_graph stores them."""
    return int(
        round(
            float(data.get("weight_forwards") or 0)
            + float(data.get("weight_mentions") or 0)
            + float(data.get("weight_copies") or 0)
        )
    )


def _node_ref(node_info: dict[str, dict], nid: str) -> dict[str, Any]:
    node = node_info.get(nid) or {}
    return {"id": nid, "label": node.get("label") or nid, "organization": node.get("organization") or ""}


def _meta_base(q_threshold: float, min_events: int, permutations: int) -> dict[str, Any]:
    return {
        "q_threshold": q_threshold,
        "min_events": int(min_events),
        "permutations": int(permutations),
        "satellite_share": SATELLITE_SHARE,
        "satellite_asymmetry": SATELLITE_ASYMMETRY,
        "dominant_min_satellites": DOMINANT_MIN_SATELLITES,
        "total_events": 0,
        "links": 0,
        "tested_links": 0,
        "validated_links": 0,
        "pairs": 0,
        "relations": dict.fromkeys(RELATIONS, 0),
        "roles": dict.fromkeys(ROLES, 0),
        "share_basis": SHARE_BASIS_CITING,
        "hierarchy": None,
    }


def empty_payload(
    q_threshold: float = DEFAULT_Q_THRESHOLD,
    min_events: int = DEFAULT_MIN_EVENTS,
    permutations: int = DEFAULT_PERMUTATIONS,
) -> dict:
    return {"meta": _meta_base(q_threshold, min_events, permutations), "pairs": [], "nodes": []}


# ── Dominance statistics on a wins matrix ────────────────────────────────────
# ``wins[i, j]`` = interactions i won over j. In ``compute_dominance`` the pair's citations are
# split between its two sides in proportion to the dependence each places on the other (see the
# module docstring); the functions below work on any non-negative wins matrix.


def david_scores(wins: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """David's score (David 1987; Gammell et al. 2003) with the de Vries et al. (2006) dyadic
    correction, plus its normalised form ``(DS + N(N−1)/2) / N``. Non-interacting dyads contribute 0."""
    n_mat = wins + wins.T
    with np.errstate(divide="ignore", invalid="ignore"):
        p_mat = np.where(n_mat > 0, wins / np.where(n_mat > 0, n_mat, 1), 0.0)
    d_mat = np.where(n_mat > 0, p_mat - (p_mat - 0.5) / (n_mat + 1), 0.0)
    w = d_mat.sum(axis=1)
    lose = d_mat.sum(axis=0)
    w2 = d_mat @ w
    l2 = d_mat.T @ lose
    ds = w + w2 - lose - l2
    n = len(ds)
    return ds, (ds + n * (n - 1) / 2.0) / n


def _dominance_digraph(wins: np.ndarray) -> sparse.csr_matrix:
    """0/1 sparse matrix of decided dyads: ``[i, j] = 1`` when i won more of the dyad than j.
    Undecided dyads (exact ties or no interaction) are left out — unknown, in Shizuka & McDonald's terms."""
    return sparse.csr_matrix((wins > wins.T).astype(float))


def triangle_transitivity(wins: np.ndarray) -> tuple[float | None, int]:
    """Shizuka & McDonald (2012) triangle transitivity: among triads whose three dyads are all
    decided, the share that are transitive rather than cyclic, rescaled as ``4·(P_t − 0.75)`` so a
    random orientation scores 0 and a perfect order 1. Returns ``(t_tri, n_triads)``; ``(None, 0)``
    when no triad is fully known. Cycles are counted as ``trace(D³)/3``, triads as ``trace(M³)/6``."""
    d = _dominance_digraph(wins)
    m = d + d.T
    triads = float((m @ m).multiply(m).sum()) / 6.0
    if triads < 0.5:
        return None, 0
    cyclic = float((d @ d).multiply(d.T).sum()) / 3.0
    p_t = 1.0 - cyclic / triads
    return 4.0 * (p_t - 0.75), int(round(triads))


def rank_consistency(wins: np.ndarray, scores: np.ndarray) -> float | None:
    """Share of the wins mass that flows toward the higher-scored side of each pair — how strictly
    the interactions respect the fitted order (0.5 = no order; 1 = every pair's dependence runs
    entirely toward its higher-scored side, so mutual pairs lower it even under a perfect order).
    Equal scores split their dyad's mass. ``None`` on an empty matrix."""
    total = float(wins.sum())
    if total <= 0:
        return None
    above = scores[:, None] > scores[None, :]
    equal = scores[:, None] == scores[None, :]
    np.fill_diagonal(equal, False)
    return float((wins[above].sum() + 0.5 * wins[equal].sum()) / total)


def springrank(wins: np.ndarray, *, alpha: float = SPRINGRANK_ALPHA) -> tuple[np.ndarray, float]:
    """SpringRank (De Bacco, Larremore & Moore 2018): real-valued ranks minimising the spring energy
    ``½ Σ A_ij (s_i − s_j − 1)²`` with ``A = wins``, regularised by a weak spring ``α`` to the
    origin. Returns ``(ranks, energy per interaction)``; higher rank = more dominant."""
    n = wins.shape[0]
    total = float(wins.sum())
    if n == 0 or total <= 0:
        return np.zeros(n), 0.0
    a_mat = sparse.csr_matrix(wins)
    d_out = np.asarray(a_mat.sum(axis=1)).ravel()
    d_in = np.asarray(a_mat.sum(axis=0)).ravel()
    lap = sparse.diags(d_out + d_in + alpha) - (a_mat + a_mat.T)
    s = np.asarray(spsolve(lap.tocsc(), d_out - d_in)).ravel()
    diff = s[:, None] - s[None, :] - 1.0
    energy = 0.5 * float((wins * diff * diff).sum()) / total
    return s, energy


def _null_wins(wins: np.ndarray, iu: tuple[np.ndarray, np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """One orientation-shuffled draw: every dyad keeps both of its counts (so its reciprocity), and
    which side holds the larger one is decided by a fair coin."""
    upper, lower = wins[iu], wins.T[iu]
    flip = rng.random(len(upper)) < NULL_FLIP_PROBABILITY
    out = np.zeros_like(wins)
    out[iu] = np.where(flip, lower, upper)
    out.T[iu] = np.where(flip, upper, lower)
    return out


def _p_value(null: list[float], observed: float, *, upper: bool) -> float | None:
    if not null:
        return None
    hits = sum(1 for x in null if (x >= observed if upper else x <= observed))
    return (hits + 1) / (len(null) + 1)


# ── Main computation ─────────────────────────────────────────────────────────


def compute_dominance(
    graph: nx.DiGraph,
    graph_data: GraphData,
    *,
    q_threshold: float = DEFAULT_Q_THRESHOLD,
    min_events: int = DEFAULT_MIN_EVENTS,
    permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = DOMINANCE_SEED,
) -> dict:
    """Per pair: two-sided dependence, validation, net balance and relation. Per node: David's score
    (raw, normalised, rank), SpringRank, satellites, own dependence, reach concentration, role.
    Whole network: SpringRank energy, triangle transitivity and rank consistency against the
    orientation-shuffled null.
    Returns a JSON-serialisable ``{"meta", "pairs", "nodes"}``; self-loops are ignored."""
    min_events = max(int(min_events), 1)
    permutations = max(int(permutations), 0)
    node_info = {n["id"]: n for n in graph_data["nodes"]}
    counts: dict[tuple[str, str], int] = {}
    for u, v, data in graph.edges(data=True):
        if u == v:
            continue
        c = _edge_count(data)
        if c > 0:
            counts[(u, v)] = c
    if not counts:
        return empty_payload(q_threshold, min_events, permutations)

    out_count: dict[str, int] = defaultdict(int)
    in_count: dict[str, int] = defaultdict(int)
    for (u, v), c in counts.items():
        out_count[u] += c
        in_count[v] += c
    total = sum(counts.values())

    citing = {nid: int((graph.nodes[nid].get("data") or {}).get("citing_messages") or 0) for nid in graph.nodes()}
    basis = SHARE_BASIS_CITING if all(citing.get(u, 0) > 0 for u in out_count) else SHARE_BASIS_EVENTS
    denominator = citing if basis == SHARE_BASIS_CITING else out_count

    # ── directed links: content share, reach share, validation ──
    link_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for (u, v), c in counts.items():
        link_stats[(u, v)] = {
            "count": c,
            # u's content dependence on v — undefined when u's citing base is below the floor.
            "share": c / denominator[u] if denominator.get(u, 0) >= min_events else None,
            "reach": c / in_count[v],  # v's reach dependence on u
            "p": None,
            "q": None,
        }
    tested = [(uv, c) for uv, c in counts.items() if c >= min_events]
    if tested:
        k = np.array([c for _, c in tested], dtype=float)
        successes = np.array([in_count[v] for (_, v), _ in tested], dtype=float)
        draws = np.array([out_count[u] for (u, _), _ in tested], dtype=float)
        p_values = np.clip(hypergeom.sf(k - 1, total, successes, draws), 0.0, 1.0)
        q_values = bh_adjust([float(x) for x in p_values])
        for (uv, _c), p, q in zip(tested, p_values, q_values, strict=True):
            link_stats[uv]["p"] = float(p)
            link_stats[uv]["q"] = float(q)

    def _validated(stat: dict[str, Any] | None) -> bool:
        return stat is not None and stat["q"] is not None and stat["q"] < q_threshold

    def _dependence(content_stat: dict | None, reach_stat: dict | None) -> float:
        # A side's dependence on the other: content via its own citations, reach via the return link.
        content = content_stat["share"] if content_stat and content_stat["share"] is not None else 0.0
        reach = reach_stat["reach"] if reach_stat else 0.0
        return (content + reach) / 2.0

    # ── pairs ──
    pairs: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    relations = dict.fromkeys(RELATIONS, 0)
    for u, v in counts:
        key = frozenset((u, v))
        if key in seen:
            continue
        seen.add(key)
        fwd, rev = link_stats.get((u, v)), link_stats.get((v, u))
        dep_u_on_v = _dependence(fwd, rev)  # content via u→v, reach via v→u
        dep_v_on_u = _dependence(rev, fwd)
        net_v_over_u = dep_u_on_v - dep_v_on_u
        if net_v_over_u > 0 or (net_v_over_u == 0 and (fwd["count"] if fwd else 0) >= (rev["count"] if rev else 0)):
            dependent, dominant, ds, sd, dep_ds, dep_sd, net = u, v, fwd, rev, dep_u_on_v, dep_v_on_u, net_v_over_u
        else:
            dependent, dominant, ds, sd, dep_ds, dep_sd, net = v, u, rev, fwd, dep_v_on_u, dep_u_on_v, -net_v_over_u
        validated_ds, validated_sd = _validated(ds), _validated(sd)
        if validated_ds and validated_sd:
            relation = RELATION_ALLIANCE
        elif validated_ds or validated_sd:
            relation = RELATION_DEPENDENCE
        else:
            relation = RELATION_UNVALIDATED
        relations[relation] += 1
        top = max(dep_ds, dep_sd)
        interactions = (fwd["count"] if fwd else 0) + (rev["count"] if rev else 0)
        pairs.append(
            {
                "dependent": _node_ref(node_info, dependent),
                "dominant": _node_ref(node_info, dominant),
                "relation": relation,
                "mutual": fwd is not None and rev is not None,
                "interactions": interactions,
                "below_floor": interactions < min_events,  # excluded from the ranking and the tests
                "ds": ds,  # the dependent → dominant link (None when the dependent never cites)
                "sd": sd,  # the dominant → dependent link
                "dependence_of_dependent": dep_ds,
                "dependence_of_dominant": dep_sd,
                "net": net,
                "asymmetry": net / top if top > 0 else 0.0,
            }
        )
    pairs.sort(key=lambda r: (-r["net"], -((r["ds"] or {}).get("count", 0))))

    # ── nodes: David's score, SpringRank, satellites, roles ──
    # The wins matrix is dependence-weighted: each pair's citations are split between its sides in
    # proportion to the dependence each places on the other, so the dominant side of a pair (the one
    # the other relies on more) wins the larger part of the dyad — the same orientation the roles
    # use. Dyads below the evidence floor are left out: a one- or two-citation dyad is not evidence
    # of dominance, and the de Vries correction only softens it.
    ranked_pairs = [p for p in pairs if not p["below_floor"]]
    ranked = sorted({p["dependent"]["id"] for p in ranked_pairs} | {p["dominant"]["id"] for p in ranked_pairs})
    if not ranked:
        meta = _meta_base(q_threshold, min_events, permutations)
        meta.update(
            {
                "total_events": int(total),
                "links": len(link_stats),
                "tested_links": len(tested),
                "validated_links": sum(1 for st in link_stats.values() if _validated(st)),
                "pairs": len(pairs),
                "relations": relations,
                "share_basis": basis,
            }
        )
        return {"meta": meta, "pairs": pairs, "nodes": []}
    index = {nid: i for i, nid in enumerate(ranked)}
    n = len(ranked)
    wins = np.zeros((n, n))
    for pair in ranked_pairs:
        d, m = index[pair["dependent"]["id"]], index[pair["dominant"]["id"]]
        total_dependence = pair["dependence_of_dependent"] + pair["dependence_of_dominant"]
        toward_dominant = pair["dependence_of_dependent"] / total_dependence if total_dependence > 0 else 0.5
        wins[m, d] = pair["interactions"] * toward_dominant
        wins[d, m] = pair["interactions"] * (1.0 - toward_dominant)
    ds_vec, norm_vec = david_scores(wins)
    order = sorted(range(n), key=lambda i: (-ds_vec[i], ranked[i]))
    david_rank = {ranked[i]: r + 1 for r, i in enumerate(order)}
    spring, energy = springrank(wins, alpha=SPRINGRANK_ALPHA)
    spring_order = sorted(range(n), key=lambda i: (-spring[i], ranked[i]))
    spring_rank = {ranked[i]: r + 1 for r, i in enumerate(spring_order)}

    # Shared orientation-shuffled null for the three whole-network tests.
    rng = np.random.default_rng(seed)
    effective = (
        permutations if n <= LARGE_N else max(LARGE_N_MIN_PERMUTATIONS, permutations // LARGE_N_PERMUTATION_DIVISOR)
    )
    iu = np.triu_indices(n, 1)
    n_upper = (wins + wins.T)[iu]
    observed_consistency = rank_consistency(wins, ds_vec)
    observed_transitivity, triads = triangle_transitivity(wins)
    null_consistency: list[float] = []
    null_transitivity: list[float] = []
    null_energy: list[float] = []
    for trial in range(effective):
        nw = _null_wins(wins, iu, rng)
        null_ds = david_scores(nw)[0]
        value = rank_consistency(nw, null_ds)
        if value is not None:
            null_consistency.append(value)
        if triads:
            t_null, _ = triangle_transitivity(nw)
            if t_null is not None:
                null_transitivity.append(t_null)
        if trial < SPRINGRANK_MAX_NULLS:
            null_energy.append(springrank(nw, alpha=SPRINGRANK_ALPHA)[1])
    unknown = int((n_upper == 0).sum())
    hierarchy = {
        "n_ranked": n,
        "permutations": effective,
        "unknown_share": unknown / len(n_upper) if len(n_upper) else None,
        "springrank_energy": energy,
        "springrank_p": _p_value(null_energy, energy, upper=False),
        "springrank_null_mean": float(np.mean(null_energy)) if null_energy else None,
        "springrank_nulls": len(null_energy),
        "transitivity": observed_transitivity,
        "transitivity_p": _p_value(null_transitivity, observed_transitivity, upper=True)
        if observed_transitivity is not None
        else None,
        "transitivity_null_mean": float(np.mean(null_transitivity)) if null_transitivity else None,
        "triads": triads,
        "consistency": observed_consistency,
        "consistency_p": _p_value(null_consistency, observed_consistency, upper=True)
        if observed_consistency is not None
        else None,
        "consistency_null_mean": float(np.mean(null_consistency)) if null_consistency else None,
    }

    # Per node: the dependences partners place on it (either resource), the validated links either
    # way, and — read off the oriented pairs — its satellites and its own largest dependence as the
    # *dependent* side of a clearly one-sided pair.
    supplies: dict[str, float] = defaultdict(float)
    reach_conc: dict[str, float] = defaultdict(float)
    dependents_validated: dict[str, int] = defaultdict(int)
    sources_validated: dict[str, int] = defaultdict(int)
    for (u, v), st in link_stats.items():
        supplies[v] += st["share"] or 0.0  # u's content dependence on v
        supplies[u] += st["reach"]  # v's reach dependence on u
        reach_conc[v] = max(reach_conc[v], st["reach"])
        if _validated(st):
            dependents_validated[v] += 1
            sources_validated[u] += 1
    satellite_sets: dict[str, set[str]] = defaultdict(set)
    relies: dict[str, float] = {}
    allied: set[str] = set()
    for pair in pairs:
        dep, dom = pair["dependent"]["id"], pair["dominant"]["id"]
        if pair["relation"] == RELATION_ALLIANCE:
            allied.update((dep, dom))
        if pair["below_floor"] or pair["asymmetry"] < SATELLITE_ASYMMETRY:
            continue
        ds, sd = pair["ds"], pair["sd"]  # dep→dom link, dom→dep link
        content_ok = ds is not None and ds["share"] is not None and ds["count"] >= min_events
        reach_ok = sd is not None and sd["count"] >= min_events and in_count[dep] >= min_events
        if not (content_ok or reach_ok):
            continue
        dep_max = max(ds["share"] if content_ok else 0.0, sd["reach"] if reach_ok else 0.0)
        relies[dep] = max(relies.get(dep, 0.0), dep_max)
        if dep_max >= SATELLITE_SHARE:
            satellite_sets[dom].add(dep)
    satellites = {nid: len(s) for nid, s in satellite_sets.items()}

    roles = dict.fromkeys(ROLES, 0)
    nodes: list[dict[str, Any]] = []
    for nid in ranked:
        i = index[nid]
        rel = relies.get(nid)
        has_satellites = satellites.get(nid, 0) >= DOMINANT_MIN_SATELLITES
        is_dependent = rel is not None and rel >= SATELLITE_SHARE
        if has_satellites and not is_dependent:
            role = ROLE_DOMINANT
        elif is_dependent and not has_satellites:
            role = ROLE_DEPENDENT
        elif has_satellites and is_dependent:
            role = ROLE_BROKER
        elif nid in allied:
            role = ROLE_ALLIED
        else:
            role = ROLE_PERIPHERAL
        roles[role] += 1
        nodes.append(
            {
                **_node_ref(node_info, nid),
                "role": role,
                "david_score": float(ds_vec[i]),
                "david_norm": float(norm_vec[i]),
                "david_rank": david_rank[nid],
                "springrank": float(spring[i]),
                "springrank_rank": spring_rank[nid],
                "cited": int(in_count.get(nid, 0)),
                "citing": int(out_count.get(nid, 0)),
                "partners": int(((wins[i] + wins[:, i]) > 0).sum()),
                "supplies": float(supplies.get(nid, 0.0)),
                "satellites": int(satellites.get(nid, 0)),
                "relies": rel,  # largest dependence (content or reach) as the dependent side of a one-sided pair
                "reach_concentration": float(reach_conc[nid]) if nid in in_count else None,
                "dependents_validated": int(dependents_validated.get(nid, 0)),
                "sources_validated": int(sources_validated.get(nid, 0)),
            }
        )
    nodes.sort(key=lambda r: r["david_rank"])

    meta = _meta_base(q_threshold, min_events, permutations)
    meta.update(
        {
            "total_events": int(total),
            "links": len(link_stats),
            "tested_links": len(tested),
            "validated_links": sum(1 for st in link_stats.values() if _validated(st)),
            "pairs": len(pairs),
            "relations": relations,
            "roles": roles,
            "share_basis": basis,
            "hierarchy": hierarchy,
        }
    )
    return {"meta": meta, "pairs": pairs, "nodes": nodes}


def inject_node_scores(graph_data: GraphData, payload: dict) -> list[tuple[str, str]]:
    """Write each ranked node's David's score onto ``graph_data`` (``None`` for nodes outside the
    interacting set) and return the ``(key, label)`` pair for ``measures_labels``."""
    scores = {row["id"]: row["david_score"] for row in payload.get("nodes", [])}
    for node in graph_data["nodes"]:
        node[DAVID_SCORE_KEY] = scores.get(node["id"])
    return [(DAVID_SCORE_KEY, DAVID_SCORE_LABEL)]


# ── Flat column layouts shared by the XLSX and CSV writers ───────────────────

PAIR_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Dependent", lambda r: r["dependent"]["label"]),
    ("Dependent label", lambda r: r["dependent"]["organization"]),
    ("Dominant", lambda r: r["dominant"]["label"]),
    ("Dominant label", lambda r: r["dominant"]["organization"]),
    ("Relation", lambda r: r["relation"]),
    ("Mutual", lambda r: r["mutual"]),
    ("Dependent→Dominant citations", lambda r: r["ds"]["count"] if r["ds"] else 0),
    ("Dependent content share", lambda r: r["ds"]["share"] if r["ds"] else None),
    ("Dominant reach share", lambda r: r["ds"]["reach"] if r["ds"] else None),
    ("Dependent→Dominant p", lambda r: r["ds"]["p"] if r["ds"] else None),
    ("Dependent→Dominant q", lambda r: r["ds"]["q"] if r["ds"] else None),
    ("Dominant→Dependent citations", lambda r: r["sd"]["count"] if r["sd"] else 0),
    ("Dominant content share", lambda r: r["sd"]["share"] if r["sd"] else None),
    ("Dependent reach share", lambda r: r["sd"]["reach"] if r["sd"] else None),
    ("Dominant→Dependent p", lambda r: r["sd"]["p"] if r["sd"] else None),
    ("Dominant→Dependent q", lambda r: r["sd"]["q"] if r["sd"] else None),
    ("Dependence of dependent", lambda r: r["dependence_of_dependent"]),
    ("Dependence of dominant", lambda r: r["dependence_of_dominant"]),
    ("Net balance", lambda r: r["net"]),
    ("Asymmetry", lambda r: r["asymmetry"]),
)

NODE_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("Channel", lambda r: r["label"]),
    ("Label", lambda r: r["organization"]),
    ("Role", lambda r: r["role"]),
    ("David's score", lambda r: r["david_score"]),
    ("Normalised David's score", lambda r: r["david_norm"]),
    ("David rank", lambda r: r["david_rank"]),
    ("SpringRank", lambda r: r["springrank"]),
    ("SpringRank rank", lambda r: r["springrank_rank"]),
    ("Citations received", lambda r: r["cited"]),
    ("Citations made", lambda r: r["citing"]),
    ("Partners", lambda r: r["partners"]),
    ("Supplies (Σ content shares)", lambda r: r["supplies"]),
    ("Satellites", lambda r: r["satellites"]),
    ("Relies (max content share)", lambda r: r["relies"]),
    ("Reach concentration", lambda r: r["reach_concentration"]),
    ("Validated dependents", lambda r: r["dependents_validated"]),
    ("Validated sources", lambda r: r["sources_validated"]),
)


def flat_pair_rows(payload: dict) -> tuple[list[str], list[list[Any]]]:
    return [h for h, _ in PAIR_COLUMNS], [[fn(p) for _, fn in PAIR_COLUMNS] for p in payload.get("pairs", [])]


def flat_node_rows(payload: dict) -> tuple[list[str], list[list[Any]]]:
    return [h for h, _ in NODE_COLUMNS], [[fn(r) for _, fn in NODE_COLUMNS] for r in payload.get("nodes", [])]

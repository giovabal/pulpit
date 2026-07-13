"""Historical ban-replay validation — predicted vs. observed post-wave structure.

The attack curves and ban-wave scenarios are *counterfactual*: they ask what
*would* happen if a block of channels were removed.  When the corpus records
channels that *actually* disappeared — the analyst's :class:`ChannelVacancy`
closures — the same machinery can be turned into an *out-of-sample prediction*
and scored against what really happened next.  This is the strongest form of
validation this kind of static simulation can get (Rogers 2020 traces the
deplatforming lineage the scenario models; Chandrasekharan et al. 2017, Jhaver
et al. 2021 and Horta Ribeiro et al. 2021 measure the realised gap between
predicted and observed moderation effects).

For each *wave year* Y (a calendar year with recorded closures), the replay:

    1. takes the **pre-wave** graph ``G_{Y-1}`` (the network the year before);
    2. removes the channels that closed during Y and were present in
       ``G_{Y-1}`` — the *predicted* residual, four sizes normalised against
       ``G_{Y-1}`` exactly as :func:`~network.robustness.metrics.residual_sizes`;
    3. compares that against the **equal-q random baseline** (remove the same
       number of channels uniformly at random, averaged over ``n_random_runs``);
    4. compares it against the **observed** post-wave structure: the
       ``G_{Y+1}`` graph restricted to the pre-wave survivors, normalised
       against the same ``G_{Y-1}`` baseline so predicted and observed are on
       one scale.

Reading the three columns together:

    * **observed ≈ predicted** — the static removal captured what happened; the
      network did not rewire around the gap.
    * **observed > predicted** — the ecosystem *healed*: survivors re-wired new
      ties that the static simulation, blind to adaptation, could not foresee
      (the [vacancy analysis](../../docs/vacancy-analysis.md) measures that
      re-wiring channel-by-channel).  ``strength`` can exceed 1 when the
      survivor core grew denser than the whole pre-wave network.
    * **observed < predicted** — the wave triggered *cascading* abandonment
      beyond the banned block itself.

Only *interior* wave years get a full row (``G_{Y-1}`` and ``G_{Y+1}`` must
both exist); the observed column is ``None`` when ``G_{Y+1}`` is missing (Y is
the last year), and the year is skipped entirely when ``G_{Y-1}`` is missing.

References:
    Rogers, R. (2020). Deplatforming: Following extreme Internet celebrities
        to Telegram and alternative social media. *European Journal of
        Communication* 35(3), 213-229. https://doi.org/10.1177/0267323120922066
    Chandrasekharan, E., Pavalanathan, U., Srinivasan, A., Glynn, A.,
        Eisenstein, J. & Gilbert, E. (2017). You Can't Stay Here: The Efficacy
        of Reddit's 2015 Ban Examined Through Hate Speech. *Proc. ACM
        Hum.-Comput. Interact.* 1(CSCW), Article 31.
        https://doi.org/10.1145/3134666
"""

from typing import Any

from network.robustness.metrics import component_sizes, residual_sizes

import networkx as nx
import numpy as np

_METRICS: tuple[str, ...] = ("wcc", "scc", "reach", "strength")


def ban_replay_rows(
    year_graphs: dict[int, nx.DiGraph],
    closures_by_year: dict[int, set],
    *,
    n_random_runs: int = 100,
    reach_sample: int | None = 500,
    rng: np.random.Generator | None = None,
) -> list[dict[str, Any]]:
    """One replay row per interior wave year with closures present in ``G_{Y-1}``.

    *year_graphs* maps a calendar year to its (already backbone-filtered, if
    desired) directed graph; node ids must match those in *closures_by_year*.
    *closures_by_year* maps a year Y to the set of node ids that closed during
    Y.  A wave year needs ``G_{Y-1}`` to produce a row; the observed column is
    filled only when ``G_{Y+1}`` also exists.

    Each row carries ``year``, ``n_pre`` (pre-wave node count), ``n_closed``
    (closed channels actually present in ``G_{Y-1}``), ``fraction`` (their
    share), and three blocks keyed by lowercase metric name:

        ``predicted_<metric>``  residual after removing the closed block
        ``random_<metric>``     equal-q uniform-random baseline (mean)
        ``observed_<metric>``   survivor-induced post-wave structure, or ``None``

    Rows are sorted by year ascending.  Years with no closure present in the
    pre-wave graph are skipped.
    """
    if rng is None:
        rng = np.random.default_rng()

    rows: list[dict[str, Any]] = []
    for year in sorted(closures_by_year):
        pre = year_graphs.get(year - 1)
        if pre is None or pre.number_of_nodes() == 0:
            continue
        pre_nodes = set(pre.nodes())
        closed = {nid for nid in closures_by_year[year] if nid in pre_nodes}
        if not closed:
            continue

        n_pre = pre.number_of_nodes()
        w0 = pre.size(weight="weight")
        q = len(closed)

        predicted = residual_sizes(pre, closed, reach_sample=reach_sample, rng=rng)
        random_sizes = _random_baseline(pre, q, n_random_runs, reach_sample, rng)

        post = year_graphs.get(year + 1)
        observed: dict[str, float] | None = None
        if post is not None and post.number_of_nodes() > 0:
            survivors = (pre_nodes - closed) & set(post.nodes())
            observed = component_sizes(post.subgraph(survivors), n0=n_pre, w0=w0, reach_sample=reach_sample, rng=rng)

        row: dict[str, Any] = {"year": year, "n_pre": n_pre, "n_closed": q, "fraction": q / n_pre}
        for m in _METRICS:
            row[f"predicted_{m}"] = predicted[m]
            row[f"random_{m}"] = random_sizes[m]
            row[f"observed_{m}"] = observed[m] if observed is not None else None
        rows.append(row)

    return rows


def _random_baseline(
    G: nx.DiGraph,
    q: int,
    n_runs: int,
    reach_sample: int | None,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Mean residual sizes after removing *q* uniformly-random nodes, over *n_runs* draws."""
    nodes = list(G.nodes())
    acc: dict[str, list[float]] = {m: [] for m in _METRICS}
    for _ in range(max(1, n_runs)):
        pick = [nodes[i] for i in rng.choice(len(nodes), size=min(q, len(nodes)), replace=False)]
        sizes = residual_sizes(G, pick, reach_sample=reach_sample, rng=rng)
        for m in _METRICS:
            acc[m].append(sizes[m])
    return {m: float(np.mean(acc[m])) for m in _METRICS}

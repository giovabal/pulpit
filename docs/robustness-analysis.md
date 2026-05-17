# Robustness analysis

A *robustness analysis* answers the question: **how well does this network hold up when nodes start disappearing?** Channels go silent for many reasons — platform removal, legal pressure, voluntary shutdown, mere inactivity — and the structural consequences are not uniform. Stripping a peripheral amplifier costs the ecosystem almost nothing; stripping a hub or a bridge between communities can fragment information flow across half the network.

Pulpit's robustness analysis turns this intuition into measurable curves and a single robustness score per attack strategy, with a statistical comparison against a weight-rewiring null model. The whole battery runs on the (optionally disparity-filtered) directed weighted citation graph that the rest of `structural_analysis` already builds, so no extra crawl is needed.

Enable with `--robustness` on the `structural_analysis` command (off by default; see [Workflow § Robustness](workflow.md#robustness-resistance-to-node-removal) for the CLI block and [Configuration § Robustness](../CONFIGURATION.md#structural_analysis--robustness) for the `.analysis-defaults` keys).

---

## Quick reference

| Metric / output | What it surfaces |
| :-------------- | :--------------- |
| `R_wcc`, `R_scc`, `R_reach` | Three robustness indices per attack strategy: the smaller R is, the faster the network fragments under that attack |
| `f_c` (5% threshold) | Fraction of nodes that must be removed before the residual collapses below 5% of its initial size |
| `R` z-score vs null | How extreme the observed R is compared to a network with the *same topology* but reshuffled edge weights |
| Intra/inter community survival | Does the attack strip cross-community ties first (decoupling) or intra-community ties first (eroding cohesion)? |
| Baseline weighted efficiency | A pre-attack characterisation of how easily information traverses the network at full strength |

---

## What gets attacked

Before any attack runs, Pulpit optionally extracts the **disparity-filter backbone** (Serrano, Boguñá & Vespignani, *PNAS* 2009): for every edge it tests whether the edge's weight is statistically more concentrated than chance would predict, against both the source's outgoing-weight distribution and the target's incoming-weight distribution. Edges that pass on either side stay; the rest are pruned. The threshold is `--robustness-alpha` (default `0.05`); set it to `0` to skip filtering and attack the full graph.

The filter throws out edges that are statistically indistinguishable from "noise" — uniform weight spreading across a node's connections. What remains is the *structural skeleton* of the citation network: the edges that carry meaningful weight relative to their nodes' total throughput. Restricting attacks to the backbone separates structural robustness from numerical noise from low-weight casual citations.

Nodes with a single edge in a given direction keep that edge (there is no statistical test to perform on a one-element distribution; discarding it would isolate the node entirely).

---

## Attack strategies

Eight strategies, partitioned into static (one-shot ranking, then remove in that fixed order) and dynamic (recompute the ranking after every deletion). All weighted; all reuse the centrality wrappers already in `network/measures/` where one exists.

| Strategy | Mode | What it models |
| :------- | :--- | :------------- |
| `random` | static (mean of `--robustness-runs`) | Indiscriminate node loss — the baseline against which targeted attacks should look much worse |
| `in_strength` | static | "Take down everything that's heavily cited" — proxy for moderation targeting popular destinations |
| `out_strength` | static | "Take down everything that cites heavily" — proxy for moderation targeting aggregators |
| `pagerank` | static | "Take down the highest-prestige nodes" — moderation aware of the inherited-prestige structure |
| `betweenness` | static | "Take down the brokers" — moderation aimed at fragmenting cross-community flow |
| `in_strength_dyn` | dynamic | Same as `in_strength` but re-ranking after every removal — captures cascading effects on strength |
| `pagerank_dyn` | dynamic | Same as `pagerank` but re-ranking after every removal — more aggressive than static |
| `betweenness_dyn` | dynamic | Same as `betweenness` but re-ranking; usually the most destructive attack but also the most expensive |

Dynamic strategies are opt-in via `--robustness-dynamic`. The cost is real: `O(N²)` for strength, `O(N²·|E|)` for betweenness. For a 1 000-node graph with 10 000 edges expect minutes for static-only, tens of minutes once dynamic betweenness joins in.

Tie-breaking is deterministic (ascending node ID) so every non-`random` strategy is reproducible without an `rng`.

---

## Residual-size curves and the R-index

For every attack strategy and every "size" metric, Pulpit records the residual normalised size `S(q)` after `q = 0, 1, …, N` removals. Three "size" definitions are tracked simultaneously:

- **`R_wcc`** uses the largest residual weakly-connected component. Most permissive: an edge is enough to keep two nodes "connected" regardless of direction.
- **`R_scc`** uses the largest residual *strongly*-connected component. Strictest: requires both A → B and B → A reachability. Captures the mutually-reinforcing core, not the broader ecosystem.
- **`R_reach`** uses the fraction of ordered node pairs still connected by a directed path. The most directly information-flow-relevant measure, since it counts how many sources can still reach how many destinations. On graphs above `--robustness-sample` nodes (default 500), the per-step reachable-pair count is estimated from a uniform random sample of `--robustness-sample` sources drawn fresh at every step; smaller graphs use exact computation.

The single-number robustness index combines a whole curve into:

> **R = (1/N) · Σ_{q=1..N} S(q)**

— the area under `S(q)` divided by `N`, equivalently the average residual size across the entire attack (Schneider et al. 2011; weighted extension in Bellingeri-Cassi-Vincenzi 2014).

Range and interpretation:
- `R = 0` — immediate collapse (e.g. removing the unique articulation point of a chain on the first step).
- `R ≈ 0.5` — typical value for *random failure* on a moderately resilient network. The strongly-connected nodes hold the structure together until the random walk eventually hits them.
- `R close to 1` — extraordinarily resilient: the residual stays large even when most nodes are gone (e.g. a dense clique).

**`R_observed < R_random` is the diagnostic of interest.** When a targeted strategy (PageRank, betweenness) gives a much lower R than random, the network has identifiable critical nodes whose removal disproportionately damages connectivity. When the strategies give similar R values, the network is *homogeneous* — no single class of nodes is uniquely critical.

The companion **critical threshold** `f_c` is the smallest fraction of removed nodes at which `S(f) / S(0)` first drops below 5% (configurable). A network with `f_c = 0.10` under PageRank attack loses 95% of its connectivity after only 10% targeted removals — extreme vulnerability.

---

## Null model and the z-score

A low R from a targeted strategy by itself doesn't say much: maybe the network is just sparse, or just small. The right comparison is "low compared to what?" — and the standard answer in network science is a **null model** that preserves some properties of the network and randomises the rest.

Pulpit uses a *weight-rewiring null*: it keeps the graph's topology and the multiset of edge weights, but randomly permutes weights among the existing edges. Each null draw is the *same* network, redecorated with the same weights in a different arrangement. The runner draws `--robustness-null` independent samples (default 20) and re-runs every attack strategy on each one, producing K null R values per (strategy, metric).

The **z-score** quantifies how extreme the observed R is in this null distribution:

> **z = (R_observed − μ_null) / σ_null**

with σ_null computed as the sample standard deviation (`ddof = 1`). A z-score with magnitude ≥ 2 is the conventional rule-of-thumb threshold for "this didn't happen by chance under the null"; the per-strategy summary table renders such cells in bold colour.

### What this null does *not* control for

Critical methodological caveat: the weight-rewiring null is the *minimum-acceptable* baseline, not the ideal one. It preserves:

- the graph topology (the same `(u, v)` pairs are connected),
- the multiset of edge weights and the total weight,
- each node's binary in/out degree.

It **does not** preserve:

- per-node in-strength and out-strength sequences (only the total),
- reciprocity (the weight of `(u, v)` vs `(v, u)` is reshuffled independently),
- clustering coefficient,
- higher-order motif counts, assortativity correlations.

In other words: any deviation between observed R and null R can be attributed only to the *distribution of weights across edges*, not to the underlying topology or to richer correlations. Networks whose attack response is driven by topology (e.g. a scale-free degree distribution) will show similar R values to their weight-rewired nulls — that is not a "negative result" about robustness, it's a property of the null choice. If you need to test against a stricter null (e.g. one that preserves strengths or reciprocity), generate the appropriate ensemble externally and feed the comparison values manually.

Set `--robustness-null 0` to skip the null model entirely (no z-scores; only the observed R and `f_c` values are reported).

---

## Modular robustness

When at least one community partition is active (`--community-strategies LEIDEN`, `LOUVAIN`, …), Pulpit additionally tracks how the share of *intra*-community and *inter*-community edges evolves under each attack. This answers a second-order structural question: when the network shrinks, does it shrink by *decoupling sub-ecosystems* (inter-community edges go first) or by *eroding cohesion within communities* (intra goes first)?

For every (partition, strategy) the runner stores three normalised curves of length `N + 1`:

- `intra[q] = intra_q / intra_0` — fraction of within-community edges surviving after `q` removals,
- `inter[q] = inter_q / inter_0` — fraction of between-community edges surviving,
- `ratio[q] = intra_q / inter_q` — `null` once `inter_q == 0` (mathematically undefined).

Trivial partitions (every node in the same community) are silently skipped — there are no inter-community edges to track. Edges incident on nodes outside the partition are classified as **inter** (an unassigned node has no community to match).

A useful pattern: under betweenness attack, a network where bridge channels carry most of the betweenness will see `inter` drop to zero very quickly while `intra` decays slowly. The graph fragments into cohesive sub-blobs that no longer talk to each other. The same network under random attack typically shows `intra` and `inter` decaying in proportion — both classes of edges shrink at the same rate.

---

## When the results are interpretable (and when they aren't)

Robustness analysis is most informative on networks that satisfy three conditions:

1. **More than one weakly-connected component** is unusual but not fatal — small isolated components contribute 0 to `R_wcc` from `q = 0`, which is correct but visually flat.
2. **A non-trivial strongly-connected component** — `R_scc` is meaningless if the largest SCC at `q = 0` is a single node. Sparse trees and forests will show `R_scc ≈ 0` regardless of attack strategy. Use `R_wcc` or `R_reach` instead.
3. **Heterogeneous edge weights** — the disparity filter is most useful when some edges carry much more weight than the per-node average. Networks with uniform weights collapse the filter into a near-no-op (every edge has the same α from both sides).

The analysis is **not** meant to predict actual deplatforming outcomes — that depends on which specific channels get banned, on the moderation rules, and on adaptation by the rest of the network. It is meant to characterise *structural* vulnerability: which kinds of removals matter most, and whether the network has identifiable critical nodes at all.

---

## What gets written

When `--robustness` is on, the export receives:

- **`data/robustness.json`** — the full payload (config, graph metadata, per-strategy curves and R/f_c values, optional null model statistics, optional modular curves per partition). Single-file convention, mirrors `data/vacancy_analysis.json`. JSON-serialisable: `None` is used for undefined ratios instead of `Infinity`/`NaN`.
- **`robustness_table.html`** (when `--html` is set) — Chart.js page with the summary table, three `S(f)` line charts (one per metric), and an accordion of intra/inter curves per partition.
- **`robustness_table.xlsx`** (when `--xlsx` is set) — three sheet families: a `Summary` sheet with one row per (strategy, metric), one `Curve <strategy>` sheet per strategy with the raw `S(f)` and optional null-model columns, and one `Modular <partition>` sheet per partition.
- A link card on `index.html`.

The new files honour the existing atomic-publish convention (`exports/<name>.tmp/` → `exports/<name>/`), so an aborted run never corrupts a previous one.

---

## References

- Schneider, C. M., Moreira, A. A., Andrade, J. S., Havlin, S. & Herrmann, H. J. (2011). Mitigation of malicious attacks on networks. *PNAS* 108(10), 3838-3841. [doi:10.1073/pnas.1009440108](https://doi.org/10.1073/pnas.1009440108)
- Bellingeri, M., Cassi, D. & Vincenzi, S. (2014). Efficiency of attack strategies on complex model and real-world networks. *Physica A* 414, 174-180. [doi:10.1016/j.physa.2014.06.079](https://doi.org/10.1016/j.physa.2014.06.079)
- Serrano, M. Á., Boguñá, M. & Vespignani, A. (2009). Extracting the multiscale backbone of complex weighted networks. *PNAS* 106(16), 6483-6488. [doi:10.1073/pnas.0808904106](https://doi.org/10.1073/pnas.0808904106)
- Latora, V. & Marchiori, M. (2001). Efficient behavior of small-world networks. *Phys. Rev. Lett.* 87(19), 198701. [doi:10.1103/PhysRevLett.87.198701](https://doi.org/10.1103/PhysRevLett.87.198701)
- Holme, P., Kim, B. J., Yoon, C. N. & Han, S. K. (2002). Attack vulnerability of complex networks. *Phys. Rev. E* 65(5), 056109. [doi:10.1103/PhysRevE.65.056109](https://doi.org/10.1103/PhysRevE.65.056109)
- Albert, R., Jeong, H. & Barabási, A.-L. (2000). Error and attack tolerance of complex networks. *Nature* 406(6794), 378-382. [doi:10.1038/35019019](https://doi.org/10.1038/35019019)
- Serrano, M. Á. & Boguñá, M. (2005). Weighted configuration model. *AIP Conference Proceedings* 776, 101-107. [doi:10.1063/1.1985381](https://doi.org/10.1063/1.1985381)
- Maslov, S. & Sneppen, K. (2002). Specificity and stability in topology of protein networks. *Science* 296(5569), 910-913. [doi:10.1126/science.1065103](https://doi.org/10.1126/science.1065103)

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

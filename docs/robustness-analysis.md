# Robustness analysis

A *robustness analysis* asks: **how well does this network hold up when channels start disappearing?** Telegram channels go silent for many reasons — platform moderation, legal pressure, voluntary shutdown, sheer inactivity — and the consequences are very uneven. Losing a peripheral amplifier costs the ecosystem almost nothing; losing a hub or a bridge between communities can fragment information flow across half the network.

Pulpit's robustness analysis turns this intuition into measurable curves and a single score per attack strategy, with a statistical sanity check against a randomised version of the same network. The whole battery runs on the directed citation graph that the rest of `structural_analysis` already builds, so no extra crawl is needed.

Enable with `--robustness` on `structural_analysis` (off by default; see [Workflow § Robustness](workflow.md#robustness-resistance-to-node-removal) for the CLI block and [Configuration § Robustness](configuration.md#robustness) for the `[robustness]` section in `.operations-structural`).

---

## Quick reference

| Metric / output | What it surfaces |
| :-------------- | :--------------- |
| `R_wcc`, `R_scc`, `R_reach` | Three robustness indices per attack strategy: the smaller R is, the faster the network fragments under that attack |
| `f_c` (5% threshold) | Fraction of channels that would have to disappear before the residual network collapses below 5% of its initial size |
| `R` z-score vs null | How extreme the observed R is compared to a network with the *same topology* but reshuffled edge weights |
| Intra/inter community survival | Does the attack strip the bridges between communities first (decoupling), or the ties within them first (eroding cohesion)? |
| Baseline weighted efficiency | A pre-attack characterisation of how easily information traverses the network at full strength |

---

## The backbone (disparity filter)

*Before any attack runs, Pulpit can prune edges that carry no meaningful weight — what's left is the structural skeleton of the citation network.*

The filter tests each edge against the null hypothesis that a channel spreads its outgoing weight uniformly across all its connections. Edges whose weight is statistically more concentrated than chance survive; the rest are pruned. The threshold is set with `--robustness-alpha` (default `0.05`); pass `0` to skip the filter and attack the full graph.

**Reference:** Serrano, M. Á., Boguñá, M. & Vespignani, A. (2009) "Extracting the multiscale backbone of complex weighted networks." *PNAS* 106(16). [doi:10.1073/pnas.0808904106](https://doi.org/10.1073/pnas.0808904106)

**In practice:** real Telegram networks are noisy. A channel that occasionally forwards from hundreds of marginal sources looks structurally identical to a channel that forwards from three core sources if you don't account for weight. The disparity filter discards the long tail of casual citations and keeps only the "load-bearing" edges, so the attack analysis answers *"what fails if we knock out the structurally important channels?"* rather than *"what fails if we knock out the most-frequently-mentioned channel by raw count?"*.

**Example.** In a ~700-node nationalist Telegram network with ~9 000 weighted edges, α=0.05 typically retains roughly 1 500 edges (around 15–20% of the original). The pruned edges are almost all very low-weight: occasional cross-mentions that don't represent a genuine propagation relationship. The 1 500 surviving edges are the structural skeleton that the attack analysis actually works on.

Channels with a single edge in a given direction always keep that edge — there is no statistical test to perform on a one-element distribution, and discarding it would needlessly isolate the channel.

---

## Attack strategies

Twenty-one strategies are available, partitioned into *static* (rank the channels once and remove them in that fixed order) and *dynamic* (recompute the ranking after every deletion — `_dyn` suffix). Pick any subset with `--robustness-strategies` (default: `random`, `in_strength`, `out_strength`, `pagerank`, `betweenness`); at least one must be selected.

The five default strategies are described in detail below — they cover the four main "what makes a channel critical?" axes (random / degree / prestige / brokerage). The remaining twelve are summarised compactly in [Other available strategies](#other-available-strategies); see [Network measures](network-measures.md) for the underlying definitions.

| Strategy | Mode | What it models |
| :------- | :--- | :------------- |
| `random` | static (mean of `--robustness-runs`) | Indiscriminate channel loss — the baseline that targeted attacks should look much worse than |
| `in_strength` | static | "Take down everything that's heavily cited" — moderation aimed at popular destinations |
| `out_strength` | static | "Take down everything that cites heavily" — moderation aimed at aggregators |
| `pagerank` | static | "Take down the highest-prestige channels" — moderation aware of inherited prestige |
| `betweenness` | static | "Take down the brokers" — moderation aimed at fragmenting cross-community flow |
| `in_strength_dyn` / `out_strength_dyn` | dynamic | Degree-based attacks with cascade awareness — re-rank after every removal |
| `pagerank_dyn` / `katz_dyn` / `hits_*_dyn` | dynamic | Prestige attacks with cascade awareness |
| `betweenness_dyn` | dynamic | The most destructive attack class; also the most expensive |

The whole point of running multiple strategies is comparison. If they all produce similar R values, the network has no specific weak class of channels — it is *homogeneously* resilient or fragile. If one strategy gives a much lower R than the others, you have found the network's specific vulnerability: an attacker following that strategy would do disproportionate damage.

### Random failure

*The baseline. Indiscriminate channel loss — what every targeted attack is compared against.*

For each random run Pulpit shuffles the channel list and removes channels in that order. The full attack curve is averaged over `--robustness-runs` independent runs (default 100) to smooth out the noise.

**In practice:** random failure is the comparator, not the result. A network that survives random failure but collapses under PageRank attack has a small number of critical channels; a network whose targeted-attack R is barely below random has structural resilience because importance is *distributed* rather than concentrated.

**Example.** A loosely federated network of regional channels might lose 30% of its nodes to random failure and still keep 60% connected. The same network under PageRank attack might lose only 8% of its nodes before fragmenting — revealing that a small handful of channels were carrying the connectivity.

### Degree-based attacks (`in_strength`, `out_strength`)

*Target the most-cited or most-citing channels first.*

`in_strength` ranks channels by the total weight of incoming edges; `out_strength` by the total weight of outgoing edges. Both are weighted: a channel cited 100 times with weight 0.1 ranks above one cited 5 times with weight 1.

**Reference:** Albert, R., Jeong, H. & Barabási, A.-L. (2000) "Error and attack tolerance of complex networks." *Nature* 406(6794). [doi:10.1038/35019019](https://doi.org/10.1038/35019019); Holme, P. et al. (2002) "Attack vulnerability of complex networks." *Phys. Rev. E* 65(5). [doi:10.1103/PhysRevE.65.056109](https://doi.org/10.1103/PhysRevE.65.056109)

**In practice:** these are stand-ins for "most popular destination" and "most active aggregator". Out-strength attacks tend to be less destructive than in-strength on Telegram ecosystems because aggregators are usually replaceable; in-strength attacks remove the channels that everyone forwards.

**Example.** A daily-digest aggregator might rank top under out-strength: it forwards from twenty sources each day, accumulating a high outgoing weight. Removing it under out-strength attack costs the network those twenty outgoing pointers, but the source channels themselves stay. Under in-strength the same network's top target might be a respected commentator that twenty channels forward from — removing it severs the relationship the aggregator and its siblings all depended on.

### Prestige attack (`pagerank`)

*Target the channels that the network's own key players treat as authoritative.*

Uses the same PageRank logic described in [Network measures § PageRank](network-measures.md#pagerank): a high-PageRank channel is one that is forwarded by other high-PageRank channels — prestige flows recursively through the citation graph.

**In practice:** removing a high-PageRank channel strips the network of an *ideological anchor*, a channel whose narratives are picked up and re-amplified. This is different from in-strength: a channel with high in-strength but low PageRank is cited by many *small* peripheral accounts; a channel with high PageRank is cited by other influential channels. The PageRank attack damages the *prestige-distribution structure* of the network, not just the raw citation count.

**Example.** A nationalist commentator whose posts are routinely reposted by the three most-followed party-aligned channels might have a modest in-strength (only three forwarders) but very high PageRank (because those three forwarders are themselves prestigious). PageRank attack removes it first; in-strength attack might leave it untouched until much later.

### Brokerage attack (`betweenness`)

*Target the channels that sit on the bridges between sub-communities.*

Uses weighted betweenness centrality (see [Network measures § Betweenness](network-measures.md#betweenness-centrality)) — channels lying on many of the shortest paths between other channels. Removing a high-betweenness channel lengthens the routes between the communities it used to connect.

**In practice:** the betweenness attack is the one that most directly models *decoupling* scenarios. A moderator targeting bridge channels can fragment an ecosystem into mutually unreachable sub-communities even if every individual community remains internally intact. The modular robustness curves (below) often reveal this most clearly.

**Example.** Two ideological clusters — religious nationalists and economic libertarians — might be connected by just three channels that forward from both sides. Those three would have low PageRank inside either cluster but very high betweenness (every cross-cluster path runs through them). PageRank attack might leave them untouched until late; betweenness attack removes them first, and the two clusters become structurally disconnected.

### Dynamic variants (`*_dyn`)

*The same attacks, but with the ranking recomputed on the residual network after every removal — so cascading effects shape the order of subsequent deletions.*

Static attacks rank once and remove in that fixed order; dynamic attacks ask, after every removal, *who is the most critical now?* This matters because the structurally-second-most-important channel before any removal might become the most-important after the first one is gone — especially under PageRank, where prestige redistributes through the residual.

Pulpit ships seven dynamic variants — one per cheap-to-recompute static strategy: `in_strength_dyn`, `out_strength_dyn`, `pagerank_dyn`, `katz_dyn`, `hits_hub_dyn`, `hits_authority_dyn`, `betweenness_dyn`. Pick whichever ones you want via `--robustness-strategies`; the spreading / reach / brokerage variants (closeness, harmonic, flow betweenness, bridging, spreading) are static-only because their per-step recomputation would dominate runtime even on small graphs.

**In practice:** dynamic attacks are usually strictly more destructive than their static counterparts because they adapt to the network's response. Use them when you want the worst-case scenario, not the average. The cost is real: `O(N · (N+m))` for degree, `O(N · power-iteration)` for PageRank/Katz/HITS, `O(N²·m)` for betweenness. On a 1 000-node graph with 10 000 edges expect minutes for the degree/PageRank dyn variants and tens of minutes once dynamic betweenness joins in.

**Example.** Under static PageRank the first ten removals are the ten highest-PageRank channels at q=0. Under `pagerank_dyn`, after removing #1 PageRank is recomputed: the original #2 might or might not still be #2 (it might have inherited prestige from the removed #1, or lost prestige if its incoming edges came from it). Networks where dynamic gives a much lower R than static are ones whose importance distribution is *fragile* — knocking out one channel makes its neighbours suddenly critical.

### Other available strategies

These nine static strategies don't make the default set but unlock genuinely different vulnerability angles — pick them with `--robustness-strategies` when the question warrants it.

| Strategy | What it models | When to use |
| :------- | :------------- | :---------- |
| `katz` | Path-based prestige with attenuation (see [Katz](network-measures.md#katz-centrality)) | Networks where influence flows through long indirect paths — Katz often diverges from PageRank on horizontal, distributed ecosystems |
| `hits_hub` | Removes the primary *distributors* (see [HITS Hub](network-measures.md#hits-hub-score)) | When the network's distributors and producers play distinct structural roles — `hits_hub` and `hits_authority` together separate "remove the relay layer" from "remove the source layer" cleanly |
| `hits_authority` | Removes the primary *sources* (see [HITS Authority](network-measures.md#hits-authority-score)) | Same as above, opposite side. Often the most informative *prestige* attack on Telegram political networks because authorities are usually the moderation target rather than aggregators |
| `harmonic` | Removes the channels best-positioned to reach the rest of the network (see [Harmonic](network-measures.md#harmonic-centrality)) | When the question is about "who can reach everyone?" rather than "who do they reach through?" |
| `closeness` | Removes the most-easily-reached channels (see [Closeness](network-measures.md#closeness-centrality)) | Reach attacks viewed from the receiving side — different curves than `harmonic` on graphs with asymmetric in/out connectivity |
| `flow_betweenness` | Random-walk betweenness (see [Flow betweenness](network-measures.md#flow-betweenness)) | When information might travel along longer-than-shortest paths; flow betweenness picks up brokers that geodesic betweenness misses |
| `burt_constraint` | **Inverse ranking** — *low* Burt's constraint flags structural-hole brokers (see [Burt's constraint](network-measures.md#burts-constraint)) | Identifies quiet bridges that PageRank/betweenness can miss because they connect *small* otherwise-unconnected groups |
| `bridging` / `bridging(<community-strategy>)` | Betweenness × neighbour-community entropy (see [Bridging](network-measures.md#bridging-centrality)) | When you want a brokerage attack that specifically targets cross-community ties (not within-community hubs). The community basis defaults to `leiden_directed` (its directed null model respects citation direction, which matches the brokerage question); use `bridging(leiden)`, `bridging(louvain)`, `bridging(infomap)`, etc. to pick a different one (it must also be in `--community-strategies`). In the Operations panel the **Bridging basis** dropdown is shared with the [BRIDGING measure](network-measures.md#bridging-centrality) — both pick up the same partition |
| `spreading` | Removes the *dynamical superspreaders* (see [Spreading efficiency](network-measures.md#spreading-efficiency)) | When you care about *what information would reach* in an SIR cascade, not just structural position. **Expensive**: Monte Carlo SIR per ranking computation, scales with `--robustness-runs` |

**In practice for new analyses:** the most informative additions to a default run are usually `hits_authority` (separates producers from prestige), `bridging` (community-aware brokers), and `spreading` (dynamical importance). Adding the three to a default-five run takes you to eight static curves on the chart — still readable, and the three new ones each surface vulnerabilities the original four miss.

---

## Three "size" metrics

The R-index is computed three times per attack strategy, each tracking a different definition of *"how much network is left"* after each removal.

### `R_wcc` — weakly connected component

*The most permissive measure. An edge in either direction is enough to keep two channels "connected".*

After each removal, Pulpit asks: how many channels remain in the largest weakly connected component? Direction is ignored — if A → B exists, A and B are connected whether or not B → A also exists.

**In practice:** `R_wcc` is the right metric for *"is the network still in one piece at all?"*. A low `R_wcc` means the attack is shattering the network into disconnected fragments.

**Example.** In a directed star (one central channel that every other channel cites), `R_wcc` for a centre-first attack drops to 1/N immediately on step 1 — removing the centre leaves every leaf isolated. Centre-last gives a smooth linear decay.

### `R_scc` — strongly connected component

*The strictest measure. Both A → B and B → A reachability are required for two channels to be "connected".*

A strongly connected component is a group of channels that all ultimately cite each other in a closed loop. `R_scc` tracks how much of the network's mutually-reinforcing core survives the attack.

**In practice:** `R_scc` is meaningful when the network has a non-trivial core — an "echo chamber" or "coordinated nucleus" in the sense of [Infomap](community-detection.md#infomap) or the [Strongly Connected Components](community-detection.md#strongly-connected-components-strongcc) partition. On sparse trees or one-way fan-out structures, `R_scc` will be near zero from `q=0` and won't tell you much. Use `R_wcc` or `R_reach` for those.

**Example.** In a coordinated disinformation network where 8 channels repost each other in a cycle (the SCC), `R_scc` drops sharply the moment the first of those 8 is removed — the cycle breaks into chains and no SCC larger than 1 remains. The network's overall information-flow capacity might decay more gradually, which is why `R_scc` is compared against `R_wcc` and `R_reach`.

### `R_reach` — directed reachability

*The fraction of ordered channel pairs (A, B) such that A can still reach B by following citation direction.*

This is the most directly meaningful measure for information flow: it counts how many sources can still reach how many destinations through the (possibly long, possibly indirect) chain of forwards.

**In practice:** `R_reach` answers *"if a story breaks at channel A, can it still reach channel B?"*. On graphs above `--robustness-sample` nodes (default 500), Pulpit estimates the reachable-pair count from a uniform random sample of `--robustness-sample` sources drawn fresh at every step; smaller graphs use exact computation.

**Example.** In a hub-and-spoke network where one central channel routes everything, static reach is high (every source can reach every destination via the hub). Removing the hub via PageRank attack drops `R_reach` from near 1 to near 0 in a single step — even though `R_wcc` might still look healthy because the hub's leaves remain pairwise un-fragmented in undirected terms.

---

## The R-index and the critical threshold

For every attack strategy and every size metric Pulpit records the residual size `S(q)` after `q = 0, 1, …, N` removals — that's the *curve* you see plotted in `robustness_table.html`. The R-index compresses the whole curve into one number:

> **R = (1/N) · Σ_{q=1..N} S(q)**

— the average residual size across the entire attack.

**Reference:** Schneider, C. M., Moreira, A. A., Andrade, J. S., Havlin, S. & Herrmann, H. J. (2011) "Mitigation of malicious attacks on networks." *PNAS* 108(10). [doi:10.1073/pnas.1009440108](https://doi.org/10.1073/pnas.1009440108); Bellingeri, M., Cassi, D. & Vincenzi, S. (2014) "Efficiency of attack strategies on complex model and real-world networks." *Physica A* 414. [doi:10.1016/j.physa.2014.06.079](https://doi.org/10.1016/j.physa.2014.06.079)

Range and rough interpretation:
- **R = 0** — immediate collapse (e.g. removing the unique articulation point of a chain on the first step)
- **R ≈ 0.5** — typical value for *random failure* on a moderately resilient network
- **R close to 1** — extraordinarily resilient: the residual stays large even when most channels are gone (e.g. a dense clique)

The diagnostic of interest is `R_observed < R_random`. When a targeted strategy (PageRank, betweenness) gives a much lower R than random, the network has identifiable critical channels. When all targeted strategies give R values close to random, the network is *homogeneous* — no single class of channels is uniquely critical.

**In practice:** read the per-(strategy, metric) cells in the summary table top-to-bottom. The strategy with the *lowest* R is the one this particular network is most vulnerable to. If PageRank attack and betweenness attack both score very low, the same channels are both prestige-anchors *and* bridges (a common signature of tightly-coordinated propaganda networks). If only betweenness scores low, the prestige is widely distributed but the connectivity is brittle.

**Example.** A research group monitoring a far-right ecosystem might find `R_wcc(random) = 0.45`, `R_wcc(pagerank) = 0.18`, `R_wcc(betweenness) = 0.42`. Interpretation: the network's resilience to *random* attrition is moderate (R ≈ 0.5); it is not particularly sensitive to bridge removal (betweenness R is barely below random); but it is extremely vulnerable to prestige-targeted removal (PageRank R is 2.5× lower than random). The PageRank ranking is structurally a hit list for moderation that wants to fragment this ecosystem.

### Critical threshold `f_c`

*The fraction of channels that have to be removed before the residual collapses below 5% of its initial size.*

A network with `f_c = 0.10` under PageRank attack loses 95% of its connectivity after only 10% of its channels are targeted — extreme vulnerability. `f_c = None` means the threshold is never crossed across the full attack (the residual stays above 5% even at q=N).

**In practice:** `f_c` is the most operationally meaningful number for *deplatforming scenario planning*. It answers, roughly, *"how many specific channels would a moderator have to ban before this network falls apart?"*. Comparing `f_c` across strategies tells you what kind of moderation pressure would actually be effective on this network.

**Example.** Two networks: A has `f_c(pagerank) = 0.08`, B has `f_c(pagerank) = 0.35`. Network A could be effectively dismantled by removing the top 8% of channels by PageRank — perhaps 50–80 channels out of 1 000. Network B would need 35% removed to achieve the same effect — practically infeasible. The structural vulnerability of A is far worse, even if both have similar raw R values.

---

## The null model and the z-score

A low R from a targeted strategy by itself doesn't say much: maybe the network is just sparse, or just small. The right comparison is *"low compared to what?"* — and the standard answer in network science is a **null model** that preserves some properties of the network and randomises the rest.

Pulpit uses a *weight-rewiring null*: it keeps the graph's topology and the multiset of edge weights, but randomly permutes the weights among the existing edges. Each null draw is the same network, redecorated with the same weights in a different arrangement. The runner draws `--robustness-null` independent samples (default 20) and re-runs every attack strategy on each one, producing K null R values per (strategy, metric).

The **z-score** quantifies how extreme the observed R is compared to that null distribution:

> **z = (R_observed − μ_null) / σ_null**

A z-score with magnitude ≥ 2 is the rule-of-thumb threshold for "this didn't happen by chance under the null"; the per-strategy summary table renders such cells in bold colour, with positive z in green (observed *more* robust than null) and negative z in red (observed *more* fragile than null).

**Reference:** Serrano, M. Á. & Boguñá, M. (2005) "Weighted configuration model." *AIP Conference Proceedings* 776. [doi:10.1063/1.1985381](https://doi.org/10.1063/1.1985381); Maslov, S. & Sneppen, K. (2002) "Specificity and stability in topology of protein networks." *Science* 296(5569). [doi:10.1126/science.1065103](https://doi.org/10.1126/science.1065103)

**In practice:** the z-score answers *"is the observed vulnerability a property of the weight distribution, or a property of the topology?"*. If your network has a low R under PageRank attack but |z| is small (say below 1), it means *any* network with the same topology and same multiset of weights would behave similarly — the vulnerability is a property of the connectivity, not anything special about which channels happen to hold the high weights. If z is large and negative, the *specific* arrangement of weights is what makes your network especially vulnerable; reshuffling those weights randomly would help.

**Example.** A coordinated disinformation network typically shows large negative z-scores under PageRank attack — meaning the high weights are concentrated on a specific small set of channels in a way that random reshuffling of those same weights would produce a noticeably more robust network. That's a fingerprint of coordination: weight is non-randomly allocated to a few load-bearing edges. An organically-grown ecosystem on the same topology typically shows z ≈ 0 under the same attack — its vulnerability is generic, not coordinated.

### What this null does *not* control for

The weight-rewiring null is the *minimum-acceptable* baseline, not the ideal one. It preserves the graph topology, the multiset of edge weights, and each channel's binary in/out degree. It does *not* preserve per-channel in-strength / out-strength (only the total), reciprocity, clustering coefficient, or higher-order motifs.

Practical consequence: networks whose attack response is driven by topology (e.g. a scale-free degree distribution) will show R values close to their weight-rewired nulls — that is *not* a "negative result" about robustness, it is a property of the null choice. If you need a stricter null (e.g. one that preserves strengths or reciprocity), generate the appropriate ensemble externally and feed the comparison values manually.

**Topology-only strategies report z = `nan`.** Several attack strategies score channels using only the graph structure (not edge weights): `burt_constraint`, `hits_hub`, `hits_authority`, `harmonic`, and `closeness`. Under this null model these scorers produce *identical* removal orders on every rewired draw — the standard deviation of R collapses to zero and the z-score is reported as `nan`. Read this as "the null model has no signal to give about this strategy" rather than "this strategy doesn't matter". The observed R and `f_c` for those strategies are still meaningful in their own right — and worth comparing against the *random* R for a different baseline.

Set `--robustness-null 0` to skip the null model entirely — only the observed R and `f_c` values get reported, no z-scores.

---

## Modular robustness

*When a community partition is active, Pulpit additionally tracks whether the attack erodes the network from within (intra-community ties go first) or from across (inter-community ties go first).*

For every (partition, strategy) combination, the runner records three normalised curves: the fraction of intra-community edges surviving (`intra`), the fraction of inter-community edges surviving (`inter`), and the ratio of the two (`ratio`). Trivial partitions (where every channel ends up in the same community) are silently skipped.

The partition is whatever you ran with `--community-strategies`. See [Community detection](community-detection.md) for what each strategy detects.

**In practice:** the modular curves tell you whether the attack is *decoupling sub-ecosystems* or *eroding cohesion within them*. Under betweenness attack on a network whose bridge channels carry most of the betweenness, `inter` drops to zero almost immediately while `intra` decays gradually — the network fragments into still-cohesive sub-blobs that no longer communicate. Under random attack on the same network, `intra` and `inter` decay in proportion (no targeting bias). Comparing the two patterns is often the clearest evidence that the network's vulnerability is specifically structural and not just statistical.

**Example.** In a far-right + religious-conservative coalition network, betweenness attack typically takes `inter` from 1.0 down to near 0 within the first 5% of removals (the small handful of channels that bridge the two camps). The `intra` curves stay near 1.0 for much longer — each ideological camp internally survives the attack just fine. Operationally: a moderator targeting brokers would effectively split the coalition without dismantling either side.

---

## When the results are interpretable (and when they aren't)

Robustness analysis is most informative on networks that satisfy three conditions:

1. **More than just isolated dyads.** Very small graphs (fewer than ~30 nodes) produce noisy curves and unstable z-scores because the null sample size is tiny relative to the topology.
2. **A non-trivial strongly-connected component.** `R_scc` is meaningless if the largest SCC at `q = 0` is a single node. Sparse trees and forests will show `R_scc ≈ 0` regardless of attack strategy. Use `R_wcc` or `R_reach` for those.
3. **Heterogeneous edge weights.** The disparity filter is most useful when some edges carry much more weight than the per-channel average. Networks with uniform weights collapse the filter into a near no-op (every edge has the same α from both sides).

The analysis is **not** meant to predict actual deplatforming outcomes — that depends on which specific channels get banned, on the moderation rules, on the network's adaptation. It is meant to characterise *structural* vulnerability: which kinds of removals would matter most, and whether the network has identifiable critical channels at all. Two networks of similar size with very different R profiles will react very differently to any given moderation pressure; one with similar profiles will react similarly. That comparative insight is what the analysis delivers.

---

## What gets written

When `--robustness` is on, the export receives:

- **`data/robustness.json`** — the full payload (config, graph metadata, per-strategy curves and R/f_c values, optional null model statistics, optional modular curves per partition). Mirrors the single-file convention of `data/vacancy_analysis.json`. `None` is used for undefined ratios instead of `Infinity`/`NaN`, so the file is plain JSON.
- **`robustness_table.html`** (when `--html` is set) — Chart.js page with the summary table, three `S(f)` line charts (one per size metric), and an accordion of intra/inter curves per partition.
- **`robustness_table.xlsx`** (when `--xlsx` is set) — three sheet families: a `Summary` sheet with one row per (strategy, metric), one `Curve <strategy>` sheet per strategy with the raw `S(f)` and optional null-model columns, and one `Modular <partition>` sheet per partition.
- A link card on `index.html`.

The new files honour the existing atomic-publish convention (`exports/<name>.tmp/` → `exports/<name>/`), so an aborted run never corrupts a previous one.

### Timeline export

When `--timeline-step year` is active alongside `--robustness`, the analysis runs once on the global graph *and* once per calendar year. Per-year payloads land in `data_YYYY/robustness.json` next to the per-year communities and channels, and the HTML page picks them up via the same "All · 2019 · 2020 · …" navigator used by the channel, network, and community tables. The Excel workbook becomes a single multi-year file: sheets get year suffixes (`"Summary All"`, `"Summary 2019"`, `"Curve pagerank 2019"`, `"Modular leiden 2019"`, etc.). Same RNG seed across years — each per-year graph is different, so the same seed still produces independent null draws.

Cost scales with `K_null × N_strategies × N_years`, so expect noticeably longer runtimes than the global-only case on long time spans. For fast iteration, drop `--robustness-null` to 5–10 (or 0) and re-enable it once the configuration is settled.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

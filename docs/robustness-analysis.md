# Robustness analysis

A *robustness analysis* asks: **how well does this network hold up when channels start disappearing?** Telegram channels go silent for many reasons — platform moderation, legal pressure, voluntary shutdown, sheer inactivity — and the consequences are very uneven. Losing a peripheral amplifier costs the ecosystem almost nothing; losing a hub or a bridge between communities can fragment the citation web across half the network.

Pulpit's robustness analysis turns this intuition into measurable curves and a single score per attack strategy, with a statistical sanity check against a randomised version of the same network. The whole battery runs on the directed citation graph that the rest of `structural_analysis` already builds, so no extra crawl is needed.

Enable with `--robustness` on `structural_analysis` (off by default; see [Workflow § Robustness](workflow.md#robustness-resistance-to-node-removal) for the CLI block and [Configuration § Robustness](configuration.md#robustness) for the `[robustness]` section in `.operations-structural`).

---

## Quick reference

| Metric / output | What it surfaces |
| :-------------- | :--------------- |
| `R_wcc`, `R_scc`, `R_reach`, `R_strength` | Four robustness indices per attack strategy: the smaller R is, the faster the network fragments under that attack |
| `f_c` (5% threshold) | Fraction of channels that would have to disappear before the residual network collapses below 5% of its initial size |
| `R` z-score + empirical p/q vs null | How extreme the observed R is compared to networks with the *same in/out degree and strength sequences* but randomised wiring — the p column makes the K-draw resolution explicit, the q column BH-corrects across the whole strategy×metric grid |
| Weighted efficiency curve `E(f)` | How well the surviving core stays knit as the attack proceeds — weighted damage the size curves can miss |
| Intra/inter community survival | Does the attack strip the bridges between communities first (decoupling), or the ties within them first (eroding cohesion)? |
| Ban-wave scenarios | Residual network after removing each whole community/label block in one step, vs removing the same number of channels at random |
| Ban-replay validation | For each year with recorded closures: predicted residual (remove the channels that actually vanished from the prior-year graph) vs the observed next-year structure — the out-of-sample check |
| Backbone α-sensitivity | R recomputed across several disparity-filter α thresholds, so you can tell a real vulnerability ranking from a backbone artefact |

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

Thirteen strategies are available, partitioned into *static* (rank the channels once and remove them in that fixed order) and *dynamic* (recompute the ranking after every deletion — `_dyn` suffix). Pick any subset with `--robustness-strategies` (default: `random`, `in_strength`, `out_strength`, `pagerank`, `betweenness`); at least one must be selected.

The strategies are described in detail below — they cover six "what makes a channel critical?" axes (random / degree / prestige / bridges / dismantling / visibility); see [Network measures](network-measures.md) for the underlying definitions.

| Strategy | Mode | What it models |
| :------- | :--- | :------------- |
| `random` | static (mean of `--robustness-runs`) | Indiscriminate channel loss — the baseline that targeted attacks should look much worse than |
| `in_strength` | static | "Take down everything that's heavily cited" — moderation aimed at popular destinations |
| `out_strength` | static | "Take down everything that cites heavily" — moderation aimed at aggregators |
| `pagerank` | static | "Take down the highest-prestige channels" — moderation aware of inherited prestige |
| `betweenness` | static | "Take down the bridges" — moderation aimed at the channels whose removal cuts the network apart |
| `collective_influence` | static | "Take down the near-optimal dismantling set" — the worst-case attacker who knows exactly which channels fragment the network fastest |
| `subscribers` | static | "Take down the biggest audiences" — moderation as it actually happens, targeting visibility |
| `in_strength_dyn` / `out_strength_dyn` | dynamic | Degree-based attacks with cascade awareness — re-rank after every removal |
| `pagerank_dyn` | dynamic | Prestige attack with cascade awareness |
| `betweenness_dyn` | dynamic | Bridge attack with cascade awareness — the most destructive order in Holme et al.'s comparison, and by far the costliest |
| `collective_influence_dyn` | dynamic | The canonical adaptive Collective-Influence algorithm — remove the top-CI node, rescore, repeat |
| `fragmentation_dyn` | dynamic | Greedy key-player dismantling — repeatedly remove the channel whose deletion most shatters the network |

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

### Bridge attack (`betweenness`)

*Target the channels sitting on the most weighted shortest paths between other channels — the cut positions of the citation web.*

Channels are ranked by directed betweenness centrality (Freeman 1977) with edge distance `1/w`, so heavily weighted citation ties count as short distances. A high-betweenness channel is one that many of the network's strongest indirect connections run through — remove it and channels that were joined through it fall apart.

**Reference:** Freeman, L. C. (1977) "A set of measures of centrality based on betweenness." *Sociometry* 40(1). [doi:10.2307/3033543](https://doi.org/10.2307/3033543); Holme, P. et al. (2002), cited above, who found *recalculated betweenness* to be the most destructive attack strategy on most topologies.

**In practice:** this is the canonical fragmentation attack, and the one that most directly targets the *brokers* of an ecosystem — the channels bridging otherwise-separate milieus (party-aligned, neo-fascist, conspiracist clusters). A hub can be structurally redundant (its neighbours also cite each other); a bridge by definition is not. Networks whose betweenness-attack R is far below their degree-attack R are held together by a small set of brokers rather than by their hubs.

**Interpretation guardrail (one-degree):** Pulpit's measure catalogue deliberately excludes betweenness as a *per-channel score* — under [one-degree attribution](network-measures.md#what-this-catalogue-covers), multi-hop paths carry no content flow, so "this channel brokers information between A and B" is not a claim the data can support. The attack strategy makes no such claim. It uses betweenness purely as a *topological cut heuristic* — a way of ordering removals — and the result is judged solely by what happens to the S(f) curves, which measure the recorded citation web's connectivity (the same epistemic status as the REACH metric). Read "high betweenness" here as "removing this channel disconnects the recorded structure fastest", never as "content flows through this channel".

**Example.** In a coalition network where the nationalist and the conspiracist camps share only three channels that both sides cite, those three channels top the betweenness ranking even if their degree and PageRank are unremarkable. A betweenness attack removes them first and splits the recorded web into two components within a handful of removals — something the in-strength attack, busy with each camp's internal hubs, might not achieve until much later.

### Dismantling attacks (`collective_influence`, `fragmentation_dyn`)

*Target a near-optimal removal set — the worst case a structural attacker could achieve.*

Every strategy above ranks channels by a *single score* (a degree, a prestige, a cut position). Because they are heuristics, "R under the best of them" only tells you the network is *at least this vulnerable* — it bounds the worst case from **above**. The dismantling strategies come at the problem from the other side: they approximate the *smallest set of channels whose removal fragments the network*, giving a defensible worst-case bound from **below**.

- **`collective_influence`** ranks each channel by its Collective Influence, `CI_ℓ(i) = (k_i − 1) · Σ_{j on the frontier of the radius-ℓ ball} (k_j − 1)` (ball radius ℓ = 2 by default). A channel scores high when it has many connections *and* sits amid other well-connected channels — the signature of a node holding a whole region together. This is the optimal-percolation heuristic of Morone & Makse (2015): minimising the largest surviving component is equivalent to finding the minimal set of these high-CI nodes. The static variant applies the one-shot ranking; **`collective_influence_dyn`** is the canonical adaptive algorithm (remove the top-CI channel, recompute, repeat) and is the single strongest dismantling order Pulpit ships.
- **`fragmentation_dyn`** greedily maximises Borgatti's (2006) key-player fragmentation objective: at each step it removes the channel whose deletion most reduces network cohesion (it shatters components into small pieces, targeting articulation points directly). It is inherently adaptive — there is no static variant, because before any removal almost every channel has the same marginal fragmentation effect.

**References:** Morone, F. & Makse, H. A. (2015) "Influence maximization in complex networks through optimal percolation." *Nature* 524(7563). [doi:10.1038/nature14604](https://doi.org/10.1038/nature14604); Borgatti, S. P. (2006) "Identifying sets of key players in a social network." *Computational & Mathematical Organization Theory* 12(1). [doi:10.1007/s10588-006-7084-x](https://doi.org/10.1007/s10588-006-7084-x). The key-player framing is the network-science lineage counter-extremism analysts already use (Everton, S. F. (2012) *Disrupting Dark Networks*, Cambridge University Press).

**Interpretation guardrail (one-degree):** both dismantling strategies use multi-hop topology, which Pulpit's per-channel measure catalogue excludes under [one-degree attribution](network-measures.md#what-this-catalogue-covers). They are exempt for the same reason `betweenness` is: an attack *order* makes no per-channel content-flow claim — it is judged only by its effect on the S(f) curves. Read "high CI" as "removing this channel fragments the recorded structure fastest", never as "content flows through this channel".

**In practice:** the gap between the dismantling R and the best single-score R is itself a finding. If `pagerank` already gets close to `collective_influence_dyn`, then targeting prestige is nearly optimal — a moderator does not need a graph algorithm, the obvious hit list works. If the dismantling R is far lower, the network's true fragility is hidden from any simple ranking: it takes a coordinated set, not the individually-important channels, to break it.

**Example.** A network with three mid-degree channels that each bridge a different pair of clusters might leave every single-score attack unimpressed (none of the three is a top hub or top bridge alone), yet `collective_influence_dyn` removes exactly those three first and fragments the network in three steps — the coordinated-set vulnerability the one-at-a-time rankings each miss.

### Visibility attack (`subscribers`)

*Target the biggest audiences first — moderation as it actually happens.*

Channels are ranked by their Telegram member count (`participants_count`), highest first; channels whose member count is unknown are removed last. This is the only strategy that ranks on *metadata* rather than network structure.

**Reference:** Rogers, R. (2020) "Deplatforming: Following extreme Internet celebrities to Telegram and alternative social media." *European Journal of Communication* 35(3). [doi:10.1177/0267323120922066](https://doi.org/10.1177/0267323120922066)

**In practice:** real deplatforming does not follow PageRank. Platforms and regulators target the channels that are *visible* — large subscriber counts, media attention, legal exposure. The subscribers attack simulates that pressure, and the gap between its R and the structural attacks' R is itself a finding: it measures how much of the network's structural load is carried by channels that visibility-driven moderation would *not* prioritise. A network whose subscribers-attack R is close to random while its PageRank-attack R is far lower is one where realistic moderation pressure would be structurally ineffective.

**Example.** A monitoring project finds `R_wcc(subscribers) = 0.41` against `R_wcc(random) = 0.45` and `R_wcc(pagerank) = 0.18`. Interpretation: banning the biggest channels barely beats banning channels at random, because the network's connectivity is carried by mid-sized, low-visibility prestige anchors — the ecosystem is structurally robust to exactly the kind of moderation it is most likely to face.

### Dynamic variants (`*_dyn`)

*The same attacks, but with the ranking recomputed on the residual network after every removal — so cascading effects shape the order of subsequent deletions.*

Static attacks rank once and remove in that fixed order; dynamic attacks ask, after every removal, *who is the most critical now?* This matters because the structurally-second-most-important channel before any removal might become the most-important after the first one is gone — especially under PageRank, where prestige redistributes through the residual.

Pulpit ships six dynamic variants: `in_strength_dyn`, `out_strength_dyn`, `pagerank_dyn`, `betweenness_dyn`, `collective_influence_dyn`, and `fragmentation_dyn` (the last is dynamic-only). Pick whichever ones you want via `--robustness-strategies`. (`subscribers` has no dynamic variant: audience size is a node property, so re-ranking after each removal would reproduce the static order.)

**In practice:** dynamic attacks are usually strictly more destructive than their static counterparts because they adapt to the network's response. Use them when you want the worst-case scenario, not the average. The cost is real: `O(N · (N+m))` for degree, `O(N · power-iteration)` for PageRank, and `O(N · (Nm + N² log N))` for betweenness — a full Brandes pass per removal. On a 1 000-node graph with 10 000 edges expect minutes for the degree/PageRank dyn variants and considerably longer for `betweenness_dyn`.

**Example.** Under static PageRank the first ten removals are the ten highest-PageRank channels at q=0. Under `pagerank_dyn`, after removing #1 PageRank is recomputed: the original #2 might or might not still be #2 (it might have inherited prestige from the removed #1, or lost prestige if its incoming edges came from it). Networks where dynamic gives a much lower R than static are ones whose importance distribution is *fragile* — knocking out one channel makes its neighbours suddenly critical.

---

## Four "size" metrics

The R-index is computed four times per attack strategy, each tracking a different definition of *"how much network is left"* after each removal.

### `R_wcc` — weakly connected component

*The most permissive measure. An edge in either direction is enough to keep two channels "connected".*

After each removal, Pulpit asks: how many channels remain in the largest weakly connected component? Direction is ignored — if A → B exists, A and B are connected whether or not B → A also exists.

**In practice:** `R_wcc` is the right metric for *"is the network still in one piece at all?"*. A low `R_wcc` means the attack is shattering the network into disconnected fragments.

**Example.** In a directed star (one central channel that every other channel cites), `R_wcc` for a centre-first attack drops to 1/N immediately on step 1 — removing the centre leaves every leaf isolated. Centre-last gives a smooth linear decay.

### `R_scc` — strongly connected component

*The strictest measure. Both A → B and B → A reachability are required for two channels to be "connected".*

A strongly connected component is a group of channels that all ultimately cite each other in a closed loop. `R_scc` tracks how much of the network's mutually-reinforcing core survives the attack.

**In practice:** `R_scc` is meaningful when the network has a non-trivial core — an "echo chamber" or "coordinated nucleus" of channels that cite each other along closed citation cycles, like the tight nucleus surfaced by the [K-core](community-detection.md#k-core) partition. On sparse trees or one-way fan-out structures, `R_scc` will be near zero from `q=0` and won't tell you much. Use `R_wcc` or `R_reach` for those.

**Example.** In a coordinated disinformation network where 8 channels repost each other in a cycle (the SCC), `R_scc` drops sharply the moment the first of those 8 is removed — the cycle breaks into chains and no SCC larger than 1 remains. The network's overall directed connectivity might decay more gradually, which is why `R_scc` is compared against `R_wcc` and `R_reach`.

### `R_reach` — directed reachability

*The fraction of ordered channel pairs (A, B) such that A can still reach B by following citation direction.*

This is the metric most sensitive to the directed architecture: it counts how many ordered pairs are still joined by an unbroken directed chain of citations. Read it as surviving *connectivity of the citation web* — under one-degree attribution a directed path certifies recorded structure, not a route content takes (see [Measures → what this catalogue covers](network-measures.md#what-this-catalogue-covers)).

**In practice:** `R_reach` answers *"how much of the network's directed connectivity survives?"* — the share of ordered channel pairs still joined by the citation web. On graphs above `--robustness-sample` nodes (default 500), Pulpit estimates the reachable-pair count from a uniform random sample of `--robustness-sample` sources drawn fresh at every step; smaller graphs use exact computation.

**Example.** In a hub-and-spoke network where one central channel links everything, static reach is high (every ordered pair is joined via the hub). Removing the hub via PageRank attack drops `R_reach` from near 1 to near 0 in a single step — even though `R_wcc` might still look healthy because the hub's leaves remain pairwise un-fragmented in undirected terms.

### `R_strength` — surviving citation weight

*The weighted metric. The share of the network's total citation weight still carried inside the heaviest surviving component.*

The three metrics above count nodes and node pairs — they are blind to edge weights, so an attack that leaves the component *large* but guts the citation weight it carries looks harmless to them. `R_strength` closes that gap: after each removal it sums the edge weights inside the heaviest residual weakly-connected component and divides by the graph's original total weight. This is the weighted damage measure of Bellingeri & Cassi (2018) — their central finding is that on real weighted networks, unweighted largest-component curves systematically *understate* attack damage.

**Reference:** Bellingeri, M. & Cassi, D. (2018) "Robustness of weighted networks." *Physica A* 489. [doi:10.1016/j.physa.2017.07.020](https://doi.org/10.1016/j.physa.2017.07.020)

**In practice:** compare `S_strength(f)` against `S_wcc(f)` for the same attack. When the strength curve falls much faster, the attack is stripping the load-bearing citation relationships while the component's node count stays up — the network is still "in one piece" but the piece is hollow.

**Example.** A network where five channels carry 80% of all citation weight inside one big component: an in-strength attack removes those five first. `S_wcc(5/N)` barely moves (the component loses five nodes), but `S_strength(5/N)` collapses below 0.2 — the residual network is a large, weakly knit shell.

### The weighted efficiency curve `E(f)`

Alongside the four size curves, Pulpit samples the **weighted global efficiency** (Latora & Marchiori 2001) of the residual network along each attack — the average inverse weighted distance within the largest strongly-connected core, with edge distance `1/w`. Efficiency weighs *how well* the surviving core is knit rather than how many channels remain, so it is the damage indicator of Bellingeri, Cassi & Vincenzi (2014): it can collapse while every size curve still looks healthy.

Each efficiency evaluation costs an all-pairs shortest-path pass, so the curve is sampled on a coarse grid (21 evaluation points across the attack) rather than per removal, computed on the observed backbone only (no null band), and the `random` strategy's curve is averaged over at most 10 of its orders. The `q = 0` point is the baseline efficiency reported in the page header. Like the baseline, it is a *relative* indicator — compare pre/post attack and across strategies, not across differently weighted networks.

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

The diagnostic of interest is `R_observed < R_random`. When a targeted strategy (PageRank, in-strength) gives a much lower R than random, the network has identifiable critical channels. When all targeted strategies give R values close to random, the network is *homogeneous* — no single class of channels is uniquely critical.

**In practice:** read the per-(strategy, metric) cells in the summary table top-to-bottom. The strategy with the *lowest* R is the one this particular network is most vulnerable to. If PageRank attack and in-strength attack both score very low, the same channels are both prestige-anchors *and* the most-cited destinations (a common signature of tightly-coordinated propaganda networks). If only in-strength scores low, the prestige is widely distributed but the raw citation structure is brittle.

**Example.** A research group monitoring a far-right ecosystem might find `R_wcc(random) = 0.45`, `R_wcc(pagerank) = 0.18`, `R_wcc(in_strength) = 0.42`. Interpretation: the network's resilience to *random* attrition is moderate (R ≈ 0.5); it is not particularly sensitive to removing the most-cited destinations (in-strength R is barely below random); but it is extremely vulnerable to prestige-targeted removal (PageRank R is 2.5× lower than random). The PageRank ranking is structurally a hit list for moderation that wants to fragment this ecosystem.

### Critical threshold `f_c`

*The fraction of channels that have to be removed before the residual collapses below 5% of its initial size.*

A network with `f_c = 0.10` under PageRank attack loses 95% of its connectivity after only 10% of its channels are targeted — extreme vulnerability. `f_c = None` means the threshold is never crossed across the full attack (the residual stays above 5% even at q=N).

**In practice:** `f_c` is the most operationally meaningful number for *deplatforming scenario planning*. It answers, roughly, *"how many specific channels would a moderator have to ban before this network falls apart?"*. Comparing `f_c` across strategies tells you what kind of moderation pressure would actually be effective on this network.

**Example.** Two networks: A has `f_c(pagerank) = 0.08`, B has `f_c(pagerank) = 0.35`. Network A could be effectively dismantled by removing the top 8% of channels by PageRank — perhaps 50–80 channels out of 1 000. Network B would need 35% removed to achieve the same effect — practically infeasible. The structural vulnerability of A is far worse, even if both have similar raw R values.

---

## The null model and the z-score

A low R from a targeted strategy by itself doesn't say much: maybe the network is just sparse, or just small. The right comparison is *"low compared to what?"* — and the standard answer in network science is a **null model** that preserves some properties of the network and randomises the rest.

Pulpit uses a *directed weighted configuration-model null*: it preserves each channel's in/out **degree** (exactly) and in/out **strength** (via iterative proportional fitting) while randomising the wiring. Concretely, each draw applies Maslov–Sneppen degree-preserving edge swaps and then rescales the weights back onto the observed strength sequence. Each null is therefore a network with the same degree and strength profiles as the real one but a randomised topology — so the comparison isolates higher-order structure (clustering, motifs, weight–topology coupling) rather than the degree/strength sequences the attacks already rank on. The runner draws `--robustness-null` independent samples (default 20) and re-runs every attack strategy on each one, producing K null R values per (strategy, metric).

**Choosing the null (`--robustness-null-model`).** Two nulls are available:

- **`configuration`** (default) — the degree/strength-preserving null just described.
- **`reciprocal`** — additionally holds each channel's **reciprocated degree** and the network's **global reciprocity** fixed, by running the Maslov–Sneppen swaps *within dyad classes* (mutual `a⇄b` pairs are only ever swapped against other mutual pairs; single edges only against single edges, under a constraint that never creates or destroys a mutual tie). This is the reciprocal-configuration-model constraint of Squartini & Garlaschelli (2011), realised by rewiring rather than analytically.

Use `reciprocal` when **mutual citation is itself the structure under test**. Echo-chamber cores — clusters of channels that reciprocally repost each other — inflate a network's robustness, and the `configuration` null randomises those mutual ties away. Against the `configuration` null, a reciprocity-heavy network will look "significantly structured" partly *because* it has reciprocated dyads; the `reciprocal` null removes that explanation, so a deviation that survives it is genuinely higher-order (which specific edges carry the load, clustering beyond reciprocity, motifs) and not just "the network has mutual pairs." **Reference:** Squartini, T. & Garlaschelli, D. (2011) "Analytical maximum-likelihood method to detect patterns in real networks." *New Journal of Physics* 13, 083001. [doi:10.1088/1367-2630/13/8/083001](https://doi.org/10.1088/1367-2630/13/8/083001).

The **z-score** quantifies how extreme the observed R is compared to that null distribution:

> **z = (R_observed − μ_null) / σ_null**

A z-score with magnitude ≥ 2 is the rule-of-thumb threshold for "this didn't happen by chance under the null"; the per-strategy summary table renders such cells in bold colour, with positive z in green (observed *more* robust than null) and negative z in red (observed *more* fragile than null).

### The empirical p-value

The z-score has a hidden assumption: that the K null R values are approximately normally distributed, which nobody has checked and which small backbones routinely violate. The **p column** next to it makes the same comparison without that assumption: a **two-sided add-one empirical p-value** — each tail is `(b + 1) / (K + 1)` with `b` the number of null draws at least as extreme as the observed R, the observed value counting as one member of the null distribution, and the two-sided p doubling the smaller tail. This is the standard Monte-Carlo convention (North, Curtis & Sham 2002; Phipson & Smyth 2010 — "permutation p-values should never be zero").

The add-one correction makes the simulation's *resolution* explicit: with K draws the smallest reportable two-sided p is `2 / (K + 1)`. At the default `--robustness-null 20` that floor is ≈ 0.095 — **the default run cannot certify significance at α = 0.05, by construction**. That is not a defect of the p-value; it is the honest statement of what 20 draws can support (the z-score just hid it). For publication-grade claims raise `--robustness-null` to 79 or more (100 is a comfortable round number); for exploratory runs the default is fine — read the p column as a sanity check on the z colouring, and treat any p at its floor as "as extreme as this simulation can measure".

Unlike the z-score, the empirical p also survives a degenerate null: when every rewired draw yields the same R (σ = 0, z = `nan`), an observed R inside the degenerate distribution gets p = 1 and one outside it gets the floor — still informative.

### The q column (multiple-comparison correction)

The runner tests many hypotheses at once: one empirical p per (strategy × metric) cell, so a default five-strategy run produces 5 × 4 = 20 simultaneous tests. At α = 0.05, roughly one of those twenty would clear the bar by chance even if nothing were structured. The **q column** next to p is the Benjamini–Hochberg false-discovery-rate adjustment applied across the whole grid: read q, not p, when you are scanning the table for "which cells are significant?" A per-cell p that looks significant in isolation but whose q does not is exactly the false positive the correction is there to catch. This mirrors the BH step the [vacancy analysis](vacancy-analysis.md) already applies across its candidate list. (Cells whose p is `nan` — a degenerate null — carry a `nan` q and are excluded from the test count.) **Reference:** Benjamini, Y. & Hochberg, Y. (1995) "Controlling the false discovery rate: a practical and powerful approach to multiple testing." *Journal of the Royal Statistical Society B* 57(1). [doi:10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)

**Reference:** North, B. V., Curtis, D. & Sham, P. C. (2002) "A note on the calculation of empirical P values from Monte Carlo procedures." *American Journal of Human Genetics* 71(2). [doi:10.1086/341527](https://doi.org/10.1086/341527); Phipson, B. & Smyth, G. K. (2010) "Permutation P-values should never be zero." *Statistical Applications in Genetics and Molecular Biology* 9(1), Article 39. [doi:10.2202/1544-6115.1585](https://doi.org/10.2202/1544-6115.1585); Serrano, M. Á. & Boguñá, M. (2005) "Weighted configuration model." *AIP Conference Proceedings* 776. [doi:10.1063/1.1985381](https://doi.org/10.1063/1.1985381); Maslov, S. & Sneppen, K. (2002) "Specificity and stability in topology of protein networks." *Science* 296(5569). [doi:10.1126/science.1065103](https://doi.org/10.1126/science.1065103)

**In practice:** the z-score answers *"is the observed vulnerability a generic property of the degree/strength sequences, or of the specific higher-order wiring?"*. If your network has a low R under PageRank attack but |z| is small (say below 1), it means *any* network with the same in/out degree and strength sequences but randomly rewired connections would behave similarly — the vulnerability is generic to those sequences, not to the specific arrangement (which edges carry the weight, clustering, reciprocity, motifs). If z is large and negative, that *specific* higher-order arrangement is what makes your network especially vulnerable relative to a randomly-rewired graph with the same degree/strength profile.

**Example.** A coordinated disinformation network typically shows large negative z-scores under PageRank attack — meaning its higher-order arrangement (which specific edges carry the load, beyond what the degree and strength sequences fix) is what makes it fragile, in a way that rewiring the connections while preserving the same degree and strength sequences would produce a noticeably more robust network. That's a fingerprint of coordination: load is non-randomly concentrated on a few load-bearing edges. An organically-grown ecosystem with a similar degree/strength profile typically shows z ≈ 0 under the same attack — its vulnerability is generic, not coordinated.

### What this null does *not* control for

The directed weighted configuration-model null is the *minimum-acceptable* baseline, not the ideal one. It preserves each channel's in/out degree (exactly), each channel's in/out strength (approximately, via iterative proportional fitting), and the total edge count and total weight. It does *not* hold the topology fixed — the wiring is randomised by Maslov–Sneppen degree-preserving edge swaps — and it does *not* preserve reciprocity, the clustering coefficient, or higher-order motifs.

Practical consequence: networks whose attack response is driven by their degree/strength sequences (e.g. a scale-free degree distribution) will show R values close to their configuration-model nulls — that is *not* a "negative result" about robustness, it is a property of the null choice. If reciprocity is the property you want to hold fixed, switch to `--robustness-null-model reciprocal` (above), which preserves it on top of the degree and strength sequences. For a null that also preserves higher-order motifs, generate the appropriate ensemble externally and feed the comparison values manually.

**Strategies with no null variance report z = `nan`.** The z-score is `(R_observed − μ_null) / σ_null`; when every rewired draw yields the same R for a strategy, its standard deviation collapses to zero and the z-score is reported as `nan` (see `null_model.z_score`). This typically happens only on small or degenerate backbones, where the rewiring has too little freedom to change the residual-size curves. The empirical p column stays defined in that case and is the number to read; the observed R and `f_c` also remain meaningful in their own right and are worth comparing against the *random* R baseline.

Set `--robustness-null 0` to skip the null model entirely — only the observed R and `f_c` values get reported, no z-scores or p-values.

---

## Modular robustness

*When a community partition is active, Pulpit additionally tracks whether the attack erodes the network from within (intra-community ties go first) or from across (inter-community ties go first).*

For every (partition, strategy) combination, the runner records three normalised curves: the fraction of intra-community edges surviving (`intra`), the fraction of inter-community edges surviving (`inter`), and the ratio of the two (`ratio`). Trivial partitions (where every channel ends up in the same community) are silently skipped.

The partition is whatever you ran with `--community-strategies`. See [Community detection](community-detection.md) for what each strategy detects.

**In practice:** the modular curves tell you whether the attack is *decoupling sub-ecosystems* or *eroding cohesion within them*. Under a targeted attack on a network whose cross-camp ties hang off a few high-prestige channels, `inter` can drop to zero well before `intra` does — the network fragments into still-cohesive sub-blobs that no longer communicate. Under random attack on the same network, `intra` and `inter` decay in proportion (no targeting bias). Comparing the two patterns is often the clearest evidence that the network's vulnerability is specifically structural and not just statistical.

**Example.** In a far-right + religious-conservative coalition network, a PageRank attack can take `inter` from 1.0 down sharply within the first removals when the channels bridging the two camps are also the network's highest-prestige ones. The `intra` curves stay near 1.0 for much longer — each ideological camp internally survives the attack just fine. Operationally: a moderator following that ranking would effectively split the coalition without dismantling either side.

---

## Ban-wave scenarios

*What if a whole community — or every channel of one organisation — disappeared at once?*

The attack curves remove channels one at a time, but real moderation on Telegram has repeatedly removed *groups* of channels in one sweep — the January 2021 wave against US far-right channels being the canonical example (Rogers 2020 traces the deplatforming lineage). For every community of every active partition, the ban-wave scenario removes the whole block in a single step and reports the four residual sizes, **next to the damage that removing the same number of channels uniformly at random would cause** (the `random` strategy's mean curve evaluated at the same removal count; computed on demand if `random` was not selected).

The equal-count random baseline is the point of the exercise:

- A block whose residual `S` falls far **below** the baseline is a *load-bearing sub-ecosystem*: banning it damages the network far beyond what its size alone explains. The HTML table marks these cells in red.
- A block at or **above** the baseline is *structurally replaceable in place*: however large it is, the rest of the network holds together without it.

Because Pulpit's partitions include the analyst's own label groups (any `LABELGROUP<id>` selected as a community strategy), *"what if every channel of organisation O were banned?"* is a first-class query — run the label-group partition through `--community-strategies` and its blocks appear in the ban-wave table alongside the algorithmic communities.

**In practice:** on a timeline export this composes with real events. If a documented mass-removal event falls inside the study period, compare the scenario's predicted residual against the observed next-year network — the strongest validation this kind of simulation can get. The **ban-replay validation** below automates exactly that comparison against the analyst's recorded closures. Blocks smaller than 2 channels are skipped, as is any block covering the entire graph.

---

## Ban-replay validation

*The out-of-sample test: did the channels that actually disappeared damage the network the way the simulation predicts?*

Everything above is counterfactual — it asks what *would* happen. When the corpus records channels that *actually* vanished (the analyst's [vacancy](vacancy-analysis.md) closures, entered under Manage → Vacancies), the same machinery becomes an out-of-sample prediction you can score against reality. Enable it with `--robustness-replay` (requires `--timeline-step year`).

For each **wave year** Y — a calendar year with recorded closures — the replay:

1. takes the **pre-wave** graph `G_{Y-1}` (the network the year before);
2. removes the channels that closed during Y and were present in `G_{Y-1}` — the **predicted** residual (four sizes, normalised against `G_{Y-1}` exactly as the ban-wave scenarios are);
3. compares that against the **equal-count random baseline** (remove the same number of channels at random, averaged over `--robustness-runs`);
4. compares it against the **observed** post-wave structure: the `G_{Y+1}` graph restricted to the pre-wave survivors, normalised against the same `G_{Y-1}` baseline so predicted and observed sit on one scale.

Read the three numbers in each cell (`predicted / random / observed`) together:

- **observed ≈ predicted** — the static removal captured what happened; the network did not rewire around the gap.
- **observed > predicted** (green) — the ecosystem *healed*: survivors formed new ties the static simulation, blind to adaptation, could not foresee. This is the re-wiring the [vacancy analysis](vacancy-analysis.md) measures channel by channel. (`strength` can exceed 1 when the survivor core grew denser than the whole pre-wave network.)
- **observed < predicted** (red) — the wave triggered *cascading* abandonment beyond the banned block itself.

Only *interior* wave years get a full row (both `G_{Y-1}` and `G_{Y+1}` must exist); the observed column is blank when Y is the last year, and a wave with no closure present in the pre-wave graph is skipped. The backbone filter (`--robustness-alpha`) is applied to each year graph, so the replay attacks the same skeleton the rest of the battery does.

This is the strongest validation a static removal simulation can get, and it is precisely the gap the deplatforming-effectiveness literature is about — the distance between predicted and realised moderation effects. **References:** Chandrasekharan, E. et al. (2017) "You Can't Stay Here: The Efficacy of Reddit's 2015 Ban Examined Through Hate Speech." *Proc. ACM Hum.-Comput. Interact.* 1(CSCW), Article 31. [doi:10.1145/3134666](https://doi.org/10.1145/3134666); Jhaver, S., Boylston, C., Yang, D. & Bruckman, A. (2021) "Evaluating the Effectiveness of Deplatforming as a Moderation Strategy on Twitter." *Proc. ACM Hum.-Comput. Interact.* 5(CSCW2), Article 381. [doi:10.1145/3479525](https://doi.org/10.1145/3479525); Horta Ribeiro, M. et al. (2021) "Do Platform Migrations Compromise Content Moderation? Evidence from r/The_Donald and r/Incels." *Proc. ACM Hum.-Comput. Interact.* 5(CSCW2), Article 316. [doi:10.1145/3476057](https://doi.org/10.1145/3476057).

---

## Backbone α-sensitivity

*Is a strategy's vulnerability ranking real, or an artefact of the backbone threshold?*

Every R value on this page is conditional on one disparity-filter α (default 0.05). A fair question — and one a methods reviewer will ask — is whether the rankings would survive a different cut-off. `--robustness-alpha-grid` answers it directly: pass a comma-separated list of α values (e.g. `0,0.01,0.05,0.1`, where `0` means the full graph) and Pulpit recomputes R for every strategy and metric at each α, in one extra table. No null model, efficiency curve, or modular pass runs for the sweep — it is a cheap stability check, not a second full battery.

**In practice:** read down each column. If PageRank is the most destructive strategy at α = 0.01, 0.05, *and* 0.1, the finding is robust to the backbone choice — you can report "this network is vulnerable to prestige-targeted removal" without the caveat "at α = 0.05". If the ranking reshuffles as α changes, the vulnerability is entangled with the filtering, and the honest statement is conditional on the threshold. Either way, showing the sweep pre-empts the artefact objection.

---

## Interpretation guardrails: the one-degree assumption

Pulpit's edges record **one-degree** amplification (see [Measures → what this catalogue covers](network-measures.md#what-this-catalogue-covers)): a forward points straight at the origin, so multi-hop paths in the citation graph certify *recorded structure*, not routes content actually travelled. Three consequences for reading this page:

1. **The damage metrics are structural claims, not diffusion claims.** `R_reach` counts ordered pairs joined by directed chains of *citations*; a collapse in reach means the recorded web has fallen apart, not that information can no longer travel (channels can follow each other invisibly).
2. **Attack orders are heuristics, not scores.** A removal ranking — betweenness and the dismantling strategies (`collective_influence`, `fragmentation_dyn`) included — is justified purely by its effect on the S(f) curves. That is why they are legitimate attack strategies here while `BETWEENNESS` is deliberately absent from the per-channel measure catalogue: ordering removals by cut position or fragmentation impact makes no claim that content flows through the removed channel, whereas publishing a per-channel brokerage score would.
3. **The simulation is static.** No strategy models the ecosystem's response — backup channels, rebrands, audience migration. The [vacancy analysis](vacancy-analysis.md) is the empirical counterpart: it measures, on the channels that actually disappeared from this corpus, how quickly and completely the network re-wired around them. Read the two together — structural fragility under static removal, and the measured recovery dynamics that erode it.

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

- **`data/robustness.json`** — the full payload (config, graph metadata, per-strategy curves and R/f_c values, the efficiency curves, optional null model statistics with BH-adjusted q-values, optional modular curves and ban-wave scenarios per partition, the optional α-sensitivity sweep, and the optional ban-replay validation). Mirrors the single-file convention of `data/vacancy_analysis.json`. `None` is used for undefined ratios instead of `Infinity`/`NaN`, so the file is plain JSON.
- **`robustness_table.html`** (when `--html` is set) — Chart.js page with the summary table (including the `q` column), four `S(f)` line charts (one per size metric) plus the `E(f)` efficiency chart, the ban-replay table, the α-sensitivity tables, the ban-wave tables per partition, and an accordion of intra/inter curves per partition.
- **`robustness_table.xlsx`** (when `--xlsx` is set) — the sheet families: a `Summary` sheet with one row per (strategy, metric) (with `p` and `q`), one `Curve <strategy>` sheet per strategy with the raw `S(f)` and optional null-model columns, an `Efficiency` sheet with the coarse `E(f)` grid, an optional `Alpha sensitivity` sheet, an optional `Ban replay` sheet, one `Modular <partition>` sheet per partition, and one `Ban wave <partition>` sheet per partition.
- A link card on `index.html`.

The new files honour the existing atomic-publish convention (`exports/<name>.tmp/` → `exports/<name>/`), so an aborted run never corrupts a previous one.

### Timeline export

When `--timeline-step year` is active alongside `--robustness`, the analysis runs once on the global graph *and* once per calendar year. Per-year payloads land in `data_YYYY/robustness.json` next to the per-year communities and channels, and the HTML page picks them up via the same "All · 2019 · 2020 · …" navigator used by the channel, network, and community tables. The Excel workbook becomes a single multi-year file: sheets get year suffixes (`"Summary All"`, `"Summary 2019"`, `"Curve pagerank 2019"`, `"Modular leiden 2019"`, etc.). Same RNG seed across years — each per-year graph is different, so the same seed still produces independent null draws. The **α-sensitivity sweep and the ban-replay validation are global-only** (they belong to the whole-timeline "All" scope): the sweep would multiply every per-year run's cost by the grid length, and the replay is by construction a cross-year comparison.

Cost scales with `K_null × N_strategies × N_years`, so expect noticeably longer runtimes than the global-only case on long time spans. For fast iteration, drop `--robustness-null` to 5–10 (or 0) and re-enable it once the configuration is settled.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

# Dominance analysis

*Who dominates whom? In a network of peer channels where a forward is an endorsement, every citation dyad has a winner — the channel whose content was taken up — and asymmetric outcomes aggregate into an order even when nobody holds a formal rank. The dominance analysis ranks channels, types them as dominant or dependent, reads each pair's power balance as two-sided dependence, and tests whether the network has a hierarchy at all.*

Enable it with **Dominance** in the Outputs fieldset of the Operations panel or `--dominance` on `structural_analysis`. It writes `data/dominance.json` always, `dominance.html` with `--html`, `dominance.xlsx` with `--xlsx` and `dominance_channels.csv` + `dominance_pairs.csv` with `--csv`; it also adds a **David's score** column to the channel table, the CSV/XLSX/GEXF/GraphML exports and the map's size-by menu. With `--timeline-step year` everything is recomputed per year (`data_YYYY/dominance.json`, per-year sheets, a year switcher on the page).

The analysis assumes **positive citation**: a forward or `t.me/` link is a deferral, not an attack. That holds inside one organisation, a movement family or any milieu where channels cite each other to relay, and fails across rival camps. Scope the run accordingly (the Scope filter, label groups, or a dedicated in-target set).

---

## Dyads: two-sided dependence

Power-dependence theory (Emerson 1962) defines the power of Y over X as X's *dependence* on Y, and the two sides of a citation dyad depend on each other for different resources. When X cites Y, X gets **content** and Y gets **reach**:

```
content(X on Y) = c(X→Y) / citing(X)     # share of X's citing messages that cite Y
reach(Y on X)   = c(X→Y) / cited(Y)      # share of Y's received citations that X supplies
```

`c(X→Y)` counts X's messages that forward Y or link it via `t.me/`; `citing(X)` counts X's messages carrying any citation (the `PARTIAL_REFERENCES` denominator, recorded for every run whatever the edge-weight strategy); `cited(Y)` counts the citations Y receives inside the graph. Normalising the same events by each side's own total is the dependence-asymmetry construction Bascompte, Jordano and Olesen (2006) introduced for mutualistic networks. Each side's overall dependence on the other is the mean of its content and reach components across the two links of the pair, and the pair's **net balance** is the difference:

```
dependence(X on Y) = ( content(X on Y) + reach(X on Y) ) / 2
net                = dependence(dependent on dominant) − dependence(dominant on dependent)
```

The side that depends more is the **dependent**, the other the **dominant**; `net` is therefore non-negative, and the **asymmetry** column normalises it by the larger dependence, the Bascompte index in `[0, 1]`. A satellite that devotes all of its output to a hub which barely notices it scores near the top; two chapters that are each other's main source and main outlet score near zero.

**Validation.** A share cannot tell preference from volume, so each directed link is tested against a null of heterogeneous activity — the statistically-validated-networks scheme (Tumminello et al. 2011), in the directed form Hatzopoulos et al. (2015) used for preferential trading. With `T` citation events in the graph, `K` of them pointing at Y and `n` made by X, the probability of at least `c(X→Y)` events from X to Y under `Hypergeom(T, K, n)` is the p-value; p-values are Benjamini–Hochberg corrected across all tested links and a link is **validated** at `q < 0.05`. The pair's **relation** reads: both links validated → `alliance`; one → `dependence`; none → `unvalidated`.

**The evidence floor.** `--dominance-min-events` (default 3; `computation.dominance_min_events`) is one threshold applied everywhere a count stands in for evidence: a link below it is listed but not tested (on one-off citations the test rewards uniqueness rather than preference); a channel with fewer citing messages than the floor gets no content share (two forwards are not a dependence); a pair with fewer interactions than the floor is flagged `below_floor` and left out of the ranking and the hierarchy tests; and satellite ties need at least that many citations.

## Channels: David's score, SpringRank, roles

**David's score** (David 1987; Gammell et al. 2003) is the standard dominance index for groups without formal ranks. Its input is a dyadic dominance proportion per pair, and here that proportion is read from the pair's two dependences rather than from raw citation counts, so that the ranking and the roles rest on the same orientation:

```
P(i,j) = dependence(j on i) / ( dependence(i on j) + dependence(j on i) )   # share of the pair's dependence flowing toward i
D(i,j) = P(i,j) − (P(i,j) − 0.5) / (n_ij + 1)        # n_ij = the pair's citations; de Vries, Stevens & Vervaecke 2006
DS(i)  = w + w2 − l − l2                              # w = Σ_j D(i,j), w2 = Σ_j w_j D(i,j); l, l2 mirror
```

The two sides of a pair split its citations in proportion to how much each relies on the other: a satellite that devotes its output to a hub which barely notices it hands the hub almost the whole dyad; a source whose only outlet is one distributor hands that distributor the dyad even though the distributor is the one doing the citing; two channels that are each other's main source and outlet split it evenly. Content dominance and gatekeeping therefore count on the same scale. The correction shrinks sparse dyads toward a draw, so three one-way citations count for less than a hundred; dyads below the evidence floor are left out altogether. Scores are antisymmetric around zero — positive dominates its partners, negative is dominated — and the **normalised** form `(DS + N(N−1)/2) / N` places every channel between 0 and N−1. Only channels with at least one dyad above the floor are ranked; the others carry no score.

**SpringRank** (De Bacco, Larremore & Moore 2018) is a second, independent ranking of the same dependence-weighted interactions: every unit of a dyad is a spring pulling the side it flows toward one unit above the other, and the ranks are the positions that minimise the total spring energy (with a weak regularising spring to the origin). Agreement between the two rank orders is the cheap robustness check; the page shows both.

**Roles** come from two transparent quantities rather than from the score. A partner is a channel's **satellite** when it depends on that channel for at least half of its content or half of its reach (`satellite_share = 0.5`, the majority criterion — tie-free — with the same minimum-events floor) *and* sits clearly on the dependent side of the pair (asymmetry at least `satellite_asymmetry = 0.25`): two channels that are each other's main source and main outlet are allies, not two dependents. A channel's **relies** value is its own largest such dependence, in either resource, as the dependent side of a one-sided pair.

| Role | Definition |
| :--- | :--- |
| `dominant` | at least two satellites, and relies on nobody for a majority of content or reach |
| `dependent` | relies on one partner for a majority of its content or its reach, and has fewer than two satellites |
| `broker` | both: it is somebody's satellite and has satellites of its own — a relay position |
| `allied` | neither, but sits in at least one validated mutual pair — a peer pact |
| `peripheral` | none of these |

Two further columns describe the position: **supplies**, the sum of the dependences partners place on the channel, and **reach concentration**, the largest share of its received citations that one amplifier supplies — a dominant channel with high reach concentration depends on a single outlet for its visibility.

## Whole network: is there a hierarchy at all?

A ranking always exists; whether it means anything is a separate question, and the one a "leaderless" claim needs. Three statistics, built for sparse dominance data, answer it against one null model: every dyad keeps its citation counts in both directions — hence its degree of reciprocity — and which side is on top is decided by a fair coin. The tests therefore ask whether the *arrangement* of dominance across dyads is more hierarchical than a random orientation of the same dyads. (A per-interaction random-winner null would only certify that citation dyads are one-way, which they nearly always are.) The number of null networks is `--dominance-permutations` (default 200; `computation.dominance_permutations`; `0` skips the tests); the cost grows with the square of the ranked channels, and above three thousand ranked channels the count is cut to a tenth.

| Question | Statistic | Reading |
| :--- | :--- | :--- |
| Is there a ranking? | **SpringRank energy** (De Bacco et al. 2018) — the spring energy per interaction of the fitted ranking | Lower = the interactions are better explained by one order; the p-value is the share of null networks with energy at least as low |
| Is it transitive? | **Triangle transitivity** (Shizuka & McDonald 2012) — among triads whose three dyads are all decided, the share that are transitive rather than cyclic, rescaled as `4·(P_t − 0.75)` | 0 = what random orientations give, 1 = a perfect order; `n/a` when no triad is fully known, which is common in a sparse network and is reported with the number of triads |
| How strict is it? | **Rank consistency** — the share of dependence-weighted interactions flowing toward the higher-ranked side under the fitted David's ranking | 50% = no order; 100% = every pair's dependence runs entirely toward its higher-ranked side, so mutual pairs pull it down even when the order is perfect |

Two classic statistics are deliberately *not* reported. Landau's h and de Vries's h′ measure linearity, but Shizuka and McDonald (2012) showed they are biased by unknown relationships, and in a citation network most pairs never interact; triangle transitivity is their replacement for exactly that situation. Steepness (de Vries, Stevens & Vervaecke 2006), the slope of normalised David's scores over rank, assumes a group in which everyone meets everyone: on the star and tree shapes citation networks take, many equal satellites form plateaus in the score-over-rank curve and the slope falls *below* random, which reads as "no hierarchy" when the ranking is in fact clean.

Read the three together. A leaderless milieu typically shows a significant SpringRank energy and high rank consistency next to few or no fully known triads: dominance relations exist and are respected locally, but the network is too sparse for anything like a chain of command to be visible. A movement with a de facto centre and layered relays shows all three significant, with transitive triads where relays and their satellites both cite the centre.

## Reading the page

- Start from the **Channels** table sorted by rank: the top rows with role `dominant` are the channels the milieu relies on, whether as sources or as outlets; `dependent` rows are the satellites. Sort by *cited* and *citing* to see which of the two a channel's standing comes from, by *supplies* for the raw sum of dependences placed on it, and by *reach concentration* to find dominant channels that are themselves captive to one outlet.
- The **Pairs** table, on validated pairs by default, shows the relations behind the ranking. High net with `dependence` is a satellite and its hub; low net with `alliance` is a peer pact; a heavy share that is `unvalidated` is a low-activity channel citing a popular one at the rate its popularity predicts.
- On the map, size nodes by **David's score** to see the dominant channels against the peer mass.

`data/dominance.json` holds `{"meta", "nodes", "pairs"}`: `meta` carries the thresholds, link and relation counts, role counts, `share_basis` (`citing_messages`, or `graph_events` when the graph carries no citing-message counts) and the `hierarchy` block; `nodes` one row per ranked channel; `pairs` one row per connected pair with the two channel references, `relation`, `mutual`, the `ds` / `sd` link statistics (`count`, `share`, `reach`, `p`, `q`), both dependences, `net` and `asymmetry`. `None` replaces every undefined value so the file is strict JSON.

## Interpretation guardrails

- **One-degree.** Every quantity is a function of observed dyads and their raw counts; no path, walk or flow is asserted, so the analysis sits inside Pulpit's [one-degree attribution model](network-measures.md#what-this-catalogue-covers).
- **Dominance is dependence, not command.** A dominant channel is one the others rely on — for content, for reach, or both. That is the closest observable thing to power in a leaderless network; it is not command, and it is not agenda-setting in the temporal sense — the [diffusion lag](network-measures.md#diffusion-lag) and [coordination](coordination-analysis.md) layers hold the timing evidence.
- **Positive citation is an assumption, not a finding.** Hostile or monitoring forwards invert the reading. Restrict the scope to a milieu where the assumption holds, and split within-organisation from cross-organisation pairs with the label groups when in doubt.
- **Mandated relaying is not deference.** If chapters are instructed to relay a central channel, its dominance is a rule; only the discretionary layer of peer citations carries information about informal power. Compare the ranking with and without the central channel in scope.
- **Counts are overdispersed and coverage is a floor.** Albums forward as several messages, forwarding is bursty, and unresolved or deleted citations vanish non-uniformly; validation p-values run small and shares are lower bounds. Read differences, not decimals.
- **Productivity still shows.** A channel that posts more forwardable material collects more dependence; the shares correct for the citer's activity, not for the cited channel's output. Read the ranking next to the amplification factor when output volumes differ widely.

## References

- Bascompte, J., Jordano, P. & Olesen, J.M. (2006) "Asymmetric coevolutionary networks facilitate biodiversity maintenance." *Science* 312(5772):431–433. [doi:10.1126/science.1123412](https://doi.org/10.1126/science.1123412) — dependence of each partner as the fraction of its own interactions, and the asymmetry of a pair.
- Benjamini, Y. & Hochberg, Y. (1995) "Controlling the false discovery rate: a practical and powerful approach to multiple testing." *Journal of the Royal Statistical Society B* 57(1):289–300. [doi:10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)
- Cook, K.S., Emerson, R.M., Gillmore, M.R. & Yamagishi, T. (1983) "The distribution of power in exchange networks: theory and experimental results." *American Journal of Sociology* 89(2):275–305. [doi:10.1086/227866](https://doi.org/10.1086/227866) — power accrues to actors whose partners lack alternatives, not to the most central.
- David, H.A. (1987) "Ranking from unbalanced paired-comparison data." *Biometrika* 74(2):432–436. [doi:10.1093/biomet/74.2.432](https://doi.org/10.1093/biomet/74.2.432) — the original score.
- De Bacco, C., Larremore, D.B. & Moore, C. (2018) "A physical model for efficient ranking in networks." *Science Advances* 4(7):eaar8260. [doi:10.1126/sciadv.aar8260](https://doi.org/10.1126/sciadv.aar8260) — SpringRank.
- de Vries, H., Stevens, J.M.G. & Vervaecke, H. (2006) "Measuring and testing the steepness of dominance hierarchies." *Animal Behaviour* 71(3):585–592. [doi:10.1016/j.anbehav.2005.05.015](https://doi.org/10.1016/j.anbehav.2005.05.015) — the dyadic correction and the normalised David's scores (their steepness statistic is not used here; see above).
- Emerson, R.M. (1962) "Power-dependence relations." *American Sociological Review* 27(1):31–41. [doi:10.2307/2089716](https://doi.org/10.2307/2089716)
- Gammell, M.P., de Vries, H., Jennings, D.J., Carlin, C.M. & Hayden, T.J. (2003) "David's score: a more appropriate dominance ranking method than Clutton-Brock et al.'s index." *Animal Behaviour* 66(3):601–605. [doi:10.1006/anbe.2003.2226](https://doi.org/10.1006/anbe.2003.2226)
- Hatzopoulos, V., Iori, G., Mantegna, R.N., Miccichè, S. & Tumminello, M. (2015) "Quantifying preferential trading in the e-MID interbank market." *Quantitative Finance* 15(4):693–710. [doi:10.1080/14697688.2014.969889](https://doi.org/10.1080/14697688.2014.969889) — the directed, weighted form of the hypergeometric link validation.
- Shizuka, D. & McDonald, D.B. (2012) "A social network perspective on measurements of dominance hierarchies." *Animal Behaviour* 83(4):925–934. [doi:10.1016/j.anbehav.2012.01.011](https://doi.org/10.1016/j.anbehav.2012.01.011) — triangle transitivity as the linearity measure for sparse dominance networks with many unknown relationships.
- Pfeffer, J. & Salancik, G.R. (1978) *The External Control of Organizations: A Resource Dependence Perspective.* Harper & Row — dependence operationalised as the proportion of an actor's inputs supplied by one partner.
- Tumminello, M., Miccichè, S., Lillo, F., Piilo, J. & Mantegna, R.N. (2011) "Statistically validated networks in bipartite complex systems." *PLoS ONE* 6(3):e17994. [doi:10.1371/journal.pone.0017994](https://doi.org/10.1371/journal.pone.0017994)

---

← [Robustness analysis](robustness-analysis.md) · [Coordination analysis](coordination-analysis.md) →

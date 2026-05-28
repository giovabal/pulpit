# Network measures

A network measure assigns a numerical score to each channel based on its position in the directed citation graph. Pulpit constructs edges from forwards and `t.me/` references: a directed edge from channel A to channel B means A regularly amplifies B's content, weighted by frequency relative to A's total output.

All measures can be used to size nodes in the graph viewer, making the most significant channels visually prominent.

<figure>
<img src="../webapp_engine/static/screenshot_01.jpg" alt="Channel table with network measures">
<figcaption><em>Channel table: 18 measures as sortable columns. Click any header to rank channels by that measure.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Measure | CLI key | Question it answers |
| :------ | :------ | :------------------ |
| PageRank | `PAGERANK` | Which channels do the network's key players treat as authoritative? |
| HITS Hub | `HITSHUB` | Which channels actively amplify others — the distributors? |
| HITS Authority | `HITSAUTH` | Which channels are the original sources that distributors spread? |
| Betweenness centrality | `BETWEENNESS` | Which channels sit on the bridges between sub-networks? |
| In-degree centrality | `INDEGCENTRALITY` | Which channels are cited by the largest fraction of others? |
| Out-degree centrality | `OUTDEGCENTRALITY` | Which channels cite the largest fraction of others? |
| Harmonic centrality | `HARMONICCENTRALITY` | Which channels can reach the rest of the network in the fewest hops? |
| Burt's constraint | `BURTCONSTRAINT` | Which channels bridge structural holes between otherwise separate groups? |
| Local clustering | `LOCALCLUSTERING` | Does this channel itself form closed citation cycles with its neighbours? |
| K-core coreness | `CORENESS` | Is this channel in the densely interconnected nucleus, or a peripheral amplifier? |
| Trophic level | `TROPHICLEVEL` | Where does this channel sit on the structural source→sink axis? |
| Within-module role | `MODULEROLE` | Is this channel a within-community hub or a cross-community connector? |
| Amplification factor | `AMPLIFICATION` | Whose content spreads furthest relative to its output volume? |
| Content originality | `CONTENTORIGINALITY` | Which channels produce original content vs. redistribute others'? |
| Diffusion lag | `DIFFUSIONLAG` | When this channel forwards a narrative, is it an early adopter or a late amplifier? |
| Spreading efficiency | `SPREADING` | If this channel starts spreading a message, what fraction of the network eventually receives it? |
| Bridging centrality | `BRIDGINGCENTRALITY` | Which channels are topological bridges wedged between high-degree regions (Hwang et al. 2008)? |
| Community bridging | `BRIDGING` / `BRIDGING(STRATEGY)` | Which channels bridge distinct communities AND lie on structurally important paths? |

<figure>
<img src="../webapp_engine/static/screenshot_05.jpg" alt="Measure comparison scatter plot">
<figcaption><em>Measure comparison: drag any two measures onto the axes to compare their distributions across channels.</em></figcaption>
</figure>
<br>

---

## PageRank

*PageRank scores a channel by the importance of the channels that amplify it, not just by how many do.*

The score is the stationary distribution of a damped random walk on the citation graph: a channel inherits prestige from its forwarders, who inherit it from theirs, and a forward from a well-connected, influential channel counts for more than a forward from a marginal one. Pulpit builds edges in the citing→cited (amplifier→source) orientation that Brin & Page originally defined PageRank on, so the iteration `PR(v) = (1 − α)/N + α · Σᵤ PR(u) · w(u→v) / Σ_w w(u→w)` flows prestige toward sources by construction — no orientation tricks. The damping factor α defaults to the canonical 0.85; edge weights (fraction of the amplifier's own output dedicated to the source) row-normalise into transition probabilities, so the PageRank scoring is *weighted* and a single high-volume bond between two channels matters more than ten incidental mentions. The whole iteration is scale-invariant to the global edge-weight rescaling `build_graph` applies, so the rankings only depend on the *relative* tie strengths.

**References:**
- Brin, S. & Page, L. (1998) "The anatomy of a large-scale hypertextual web search engine." *Computer Networks and ISDN Systems* 30(1–7). [doi:10.1016/S0169-7552(98)00110-X](https://doi.org/10.1016/S0169-7552(98)00110-X)
- Page, L., Brin, S., Motwani, R. & Winograd, T. (1999) "The PageRank citation ranking: Bringing order to the Web." Stanford Tech. Rep. [http://ilpubs.stanford.edu:8090/422/](http://ilpubs.stanford.edu:8090/422/) — the canonical reference for PageRank applied to a *citation* network, which is exactly what Pulpit builds.

**Edge-weight choice.** PageRank rankings are **invariant** to `--edge-weight-strategy` `TOTAL` / `PARTIAL_MESSAGES` / `PARTIAL_REFERENCES`: NetworkX's `pagerank` row-normalises internally and the three differ only by a per-row constant, so they collapse to the same stochastic matrix. `NONE` is the only strategy that materially changes the PageRank ranking (it flattens each row to uniform out-distribution). See [Edge-weight strategies](configuration.md#edge-weight-strategies) for the full picture — the choice still affects HITS, betweenness/harmonic, Burt's constraint, communities, spreading efficiency, and trophic level.

**In practice:** a mid-sized channel consistently forwarded by the ten most connected outlets in a network will score higher than a large channel referenced only by peripheral accounts. PageRank identifies the channels that the network's own key players treat as authoritative — the sources that shape the agenda. It complements raw in-degree, which counts citations without discounting the cited-by-noise contribution from peripheral channels.

**Example.** In a network of nationalist Telegram channels, PageRank tends to surface the two or three outlets whose frames and narratives are picked up and redistributed by everyone else — the ideological anchors of the ecosystem, even if they don't have the largest subscriber counts.

---

## HITS Hub score

*A high hub score means this channel actively amplifies others — it is a distributor, not a producer.*

The HITS algorithm (Hyperlink-Induced Topic Search) of Kleinberg (1999) assigns two mutually reinforcing scores to every node — a **hub** score `h` and an **authority** score `a` — by jointly solving `a = Aᵀ h`, `h = A a`, the principal eigenvectors of `AᵀA` and `AAᵀ`. In Pulpit's amplifier→source orientation (the same citing→cited convention PageRank is built on), `A[u,v] = w(u→v)` is the tie strength from a citing channel `u` to a cited channel `v`, so a channel's hub score is the *weighted sum of the authority scores of the channels it forwards or references*: a node scores high as a hub only if its outgoing ties land on channels that are themselves recognised authorities. Pulpit runs the **weighted variant** (Kleinberg discusses weighting in §4 of the JACM paper; Borodin et al. 2005 surveys the formal extension) — edge weights enter the iteration directly, so a single dense forwarding relationship outweighs many incidental mentions. The implementation iterates the two updates with per-step max-rescaling for numerical stability and a final sum-to-1 normalisation, matching `nx.hits(normalized=True)`; Pulpit ships its own iteration so the same routine can be reused by the robustness attack module and so it degrades gracefully on the near-empty residual graphs that show up during attack simulations.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140) — the canonical reference; defines hub and authority on a directed link graph, exactly the structure of Pulpit's citation graph.
- Borodin, A., Roberts, G.O., Rosenthal, J.S. & Tsaparas, P. (2005) "Link analysis ranking: algorithms, theory, and experiments." *ACM Transactions on Internet Technology* 5(1). [doi:10.1145/1052934.1052942](https://doi.org/10.1145/1052934.1052942) — surveys the weighted extension Pulpit uses and its convergence behaviour.

**Edge-weight choice.** Unlike PageRank, HITS rankings *do* depend on the choice of `--edge-weight-strategy`: the iteration uses the raw weights (no row-normalisation), so `TOTAL`, `PARTIAL_MESSAGES`, `PARTIAL_REFERENCES` and `NONE` produce materially different hub orderings. See [Edge-weight strategies](configuration.md#edge-weight-strategies).

**In practice:** hub score answers the question Pulpit's whole pipeline is built around — *who are the distributors?* It complements PageRank (which ranks the network's authoritative *targets*) and content originality (a behavioural signal from message content rather than link structure): high hub + low content originality = pure relay channel. Removing a top-ranked hub fragments information flow across the network without silencing any original source. Pair with [HITS Authority](#hits-authority-score) to read off the producer/distributor split as a single two-axis snapshot.

**Example.** In an Italian far-right Telegram ecosystem, a daily-digest aggregator with 8 000 subscribers forwards from twenty consistently-cited commentators. PageRank puts it in the middle of the pack because few channels cite *it back*; in-degree is low for the same reason. Its hub score, however, is the highest in the network: it links outward to the channels that the rest of the ecosystem treats as authorities, so the eigenvector iteration concentrates hub mass on it. Read alongside PageRank, the pair correctly diagnoses this channel as the network's main *redistribution layer* — a structurally critical node that classical prestige measures miss.

---

## HITS Authority score

*A high authority score means this channel is one of the original sources that the network's main distributors choose to spread.*

The counterpart to Hub from the same Kleinberg (1999) co-eigenvector system. Authority and hub are jointly defined by `a = Aᵀ h` and `h = A a` on the weighted adjacency `A[u,v] = w(u→v)`; iterating these updates converges `a` to the principal eigenvector of `AᵀA` (and `h` to that of `AAᵀ`). In Pulpit's amplifier→source orientation (the same citing→cited convention PageRank is built on), a channel's authority score is the *weighted sum of the hub scores of the channels that forward or mention it* — formally, of its predecessors in the citation graph — so a node ranks high as an authority only when it is cited by channels that are themselves recognised distributors. Prestige carries provenance: *who* you are cited by matters as much as how many cite you, and a citation from a top hub counts for more than one from a peripheral aggregator. Computation is shared with [HITS Hub](#hits-hub-score) — same weighted power iteration on the same `A` (Kleinberg discusses weighting in §4 of the JACM paper; Borodin et al. 2005 surveys the formal extension), same per-step max-rescaling for numerical stability, same final sum-to-1 normalisation matching `nx.hits(normalized=True)` — so the hub and authority columns on the channel table are always read off the same iteration.

**References:**
- Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140) — defines hub and authority on a directed link graph, exactly the structure of Pulpit's citation graph; gives the iterative formulation and the convergence-to-principal-eigenvector proof.
- Borodin, A., Roberts, G.O., Rosenthal, J.S. & Tsaparas, P. (2005) "Link analysis ranking: algorithms, theory, and experiments." *ACM Transactions on Internet Technology* 5(1). [doi:10.1145/1052934.1052942](https://doi.org/10.1145/1052934.1052942) — surveys the weighted extension Pulpit uses and the convergence behaviour of HITS variants relative to PageRank.
- Cha, M., Haddadi, H., Benevenuto, F. & Gummadi, K. P. (2010) "Measuring user influence in Twitter: the million follower fallacy." *ICWSM* 2010. [aaai.org/ojs/index.php/ICWSM/article/view/14033](https://ojs.aaai.org/index.php/ICWSM/article/view/14033) — the social-media-network argument for why hub-weighted indegree (≈ authority) is informative *beyond* raw follower count and degree; Pulpit's [authority-weighted reach D](interesting-messages.md#authority-weighted-reach-d) uses HITS authority as its fallback weight on exactly this basis.

**Edge-weight choice.** Like Hub and unlike PageRank, HITS Authority rankings *do* depend on `--edge-weight-strategy`: the iteration consumes the raw weights without row-normalisation, so `TOTAL`, `PARTIAL_MESSAGES`, `PARTIAL_REFERENCES` and `NONE` produce materially different authority orderings. See [Edge-weight strategies](configuration.md#edge-weight-strategies).

**In practice:** authority is the prestige-side answer to *who is the source?* It complements PageRank — both reward being cited by central channels, but HITS authority specifically rewards being cited by good *hubs*, while PageRank rewards being cited by anyone with high PageRank (a node need not be a hub at all to vote). When authority and PageRank diverge sharply on a node, the divergence is itself informative: a channel with very high authority but middling PageRank is a niche source the broader network reaches only through the distribution layer; the opposite pattern signals a source cited broadly but rarely by the network's main relays. The same score is reused in two other places in Pulpit, and pulling those into a single analysis is usually how authority earns its keep: as the per-message [authority-weighted reach D](interesting-messages.md#authority-weighted-reach-d) when PageRank is not in `--measures`, and as a [robustness attack strategy](robustness-analysis.md#attack-strategies) that removes the network's primary sources first — typically the most informative *prestige* attack on Telegram political networks, because authorities are usually the moderation target rather than aggregators. Pair with [HITS Hub](#hits-hub-score) for the canonical producer/distributor two-axis snapshot.

**Example.** A political strategist's channel with 5 000 subscribers ranks as the top authority in a network because fifteen high-traffic aggregator channels — all of them top-ten hubs — forward its posts daily. Subscriber count would mislead an analyst into ignoring it; PageRank would rank it high but not first; HITS authority puts it at the top because the channels that cite it are precisely those whose hub scores are highest. Read together with the daily-digest aggregator from the Hub example above, this is the canonical producer/distributor pair: low authority + high hub on one side, high authority + low hub on the other.

---

## Betweenness centrality

*A high betweenness score means this channel sits on many of the shortest paths connecting other channels — it is a broker.*

Betweenness centrality (Freeman 1977) scores each channel by the fraction of all directed shortest paths that route through it: `C_B(v) = Σ_{s ≠ v ≠ t} σ_st(v) / σ_st`, where `σ_st` is the number of shortest paths from `s` to `t` and `σ_st(v)` the number that pass through `v`. Pulpit computes it on the directed citation graph (paths follow the amplifier→source orientation `build_graph` writes) via Brandes' (2001) `O(NM + N² log N)` weighted algorithm, the NetworkX implementation behind `nx.betweenness_centrality`. Edge weights enter as **distances**, with tie strength inverted to proximity (`distance = 1 / weight`, Opsahl, Agneessens & Skvoretz 2010): every shortest-path routine minimises the distance attribute, so passing strength straight through would route paths *around* the strongest ties — the lightly-trafficked channel would score as the broker. With `1/weight`, heavily-forwarded edges become *short*, paths preferentially follow real flow, and the betweenness measure, the harmonic centrality measure, and the brokerage robustness attack all agree on what "close" means. NetworkX's default normalisation is left on, so scores are divided by `(n−1)(n−2)` for directed graphs and stay in `[0, 1]`.

**References:**
- Freeman, L.C. (1977) "A set of measures of centrality based on betweenness." *Sociometry* 40(1). [doi:10.2307/3033543](https://doi.org/10.2307/3033543) — the canonical reference; defines betweenness as the shortest-path traversal count and gives the broker interpretation Pulpit relies on.
- Brandes, U. (2001) "A faster algorithm for betweenness centrality." *Journal of Mathematical Sociology* 25(2). [doi:10.1080/0022250X.2001.9990249](https://doi.org/10.1080/0022250X.2001.9990249) — the practical algorithm Pulpit uses via NetworkX, replacing the naive `O(N³)` accumulation with the now-standard shortest-path-dependency back-propagation.
- Opsahl, T., Agneessens, F. & Skvoretz, J. (2010) "Node centrality in weighted networks: Generalizing degree and shortest paths." *Social Networks* 32(3). [doi:10.1016/j.socnet.2010.03.006](https://doi.org/10.1016/j.socnet.2010.03.006) — the standard treatment of the strength→proximity (`1/weight`) inversion shared with harmonic centrality.

**Edge-weight choice.** Like HITS and unlike PageRank, betweenness rankings depend on `--edge-weight-strategy`: the `1/weight` distance is consumed directly, so `TOTAL`, `PARTIAL_MESSAGES`, `PARTIAL_REFERENCES` and `NONE` (which collapses paths to plain hop counts) produce materially different orderings. See [Edge-weight strategies](configuration.md#edge-weight-strategies).

**In practice:** betweenness is Pulpit's primary measure for cross-community dynamics. A channel that bridges two ideological camps will score high even without having high prestige within either camp — and prestige measures (PageRank, HITS) routinely miss such brokers because they may be cited by few others and themselves cite many. The same computation feeds three derived constructs that the orchestrator shares across calls: **Bridging Centrality** (Hwang et al. 2008, `BRIDGINGCENTRALITY`) up-weights brokers wedged between *high-degree* regions; **Community Bridging** (`BRIDGING`) up-weights brokers spanning *detected communities*; and the [**brokerage robustness attack**](robustness-analysis.md#brokerage-attack-betweenness) ranks channels by removal-time fragmentation impact, typically the most destructive class of attack on Telegram political networks because such ecosystems are often held together by a small number of bridge channels.

**Example.** A channel that regularly references both a cluster of religious nationalist outlets and a cluster of economic libertarian outlets — groups that don't directly cross-reference — appears as the bridge between two otherwise separate ecosystems. Its in-degree is modest and its PageRank ordinary, because neither cluster cites it heavily; yet every shortest path between the two ecosystems runs through it, so its betweenness is among the highest in the network. It is the main vector through which narratives migrate from one community to the other, and precisely the kind of channel whose removal under the [betweenness robustness attack](robustness-analysis.md#brokerage-attack-betweenness) would fragment the coalition.

---

## In-degree centrality

*The simplest prestige measure: what fraction of the network's other channels cite this one?*

In-degree centrality is the canonical degree centrality of a directed graph, normalised for cross-network comparability: `C_in(v) = deg_in(v) / (n − 1)`, where `deg_in(v)` is the number of *distinct* predecessors of `v` in the citation graph (channels that forward from or reference `v`) and `n − 1` is the maximum achievable — the score the centre of a star graph would reach. Freeman (1978) introduced the `(n − 1)` normalisation precisely so degree scores live on a `[0, 1]` scale independent of network size; Wasserman & Faust (1994, §5) place in-degree and out-degree on the *prestige* and *expansiveness* axes of a directed graph, the framing Pulpit adopts. Pulpit's edges are oriented amplifier→source (citing→cited), so a channel's in-degree counts how many *distinct* channels treat it as a source — independent of how often each does so.

The implementation calls `nx.in_degree_centrality`, which is **unweighted by design**: every predecessor counts once, regardless of how many forwards or references that predecessor sent. The weighted counterpart, the in-strength `Σ_u w(u→v)` (column **In-strength** in the channel table, key `in_deg`), is reported separately by `apply_base_node_measures` and aggregates tie *intensity* rather than tie *count* — so a channel cited by ten outlets once each has the same in-degree centrality as one cited by the same ten outlets a hundred times each (the in-strength differs by 100×). The two are not redundant. Because the unweighted, normalised in-degree hits exactly `1.0` on a star graph's hub — the textbook theoretical maximum — Freeman's centralisation formula is well-defined for it, and it is one of the measures the [CENTRALIZATION group](whole-network-statistics.md#freeman-centralisation-per-measure) reports; in-strength is deliberately excluded, since strength has no star-based maximum and the generic Freeman normaliser would be too loose to be informative.

**References:**
- Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7) — the canonical reference; defines degree, betweenness and closeness centrality and the `(n − 1)` normalisation that places degree scores on `[0, 1]`.
- Wasserman, S. & Faust, K. (1994) *Social Network Analysis: Methods and Applications*. Cambridge University Press. [doi:10.1017/CBO9780511815478](https://doi.org/10.1017/CBO9780511815478) — chapter 5: the textbook treatment of in-degree and out-degree as the *prestige* and *expansiveness* components on a directed graph, the reading Pulpit follows.

**Edge-weight choice.** In-degree centrality is **invariant** to `--edge-weight-strategy`: NetworkX's implementation discards edge weights and counts distinct predecessors, so `TOTAL`, `PARTIAL_MESSAGES`, `PARTIAL_REFERENCES` and `NONE` all produce identical orderings. Use the **In-strength** column, PageRank or HITS Authority for a weighted prestige measure. See [Edge-weight strategies](configuration.md#edge-weight-strategies).

**In practice:** in-degree centrality answers the most direct question Pulpit's pipeline can ask of the citation graph — *which channels are the most-cited sources?* It is the only purely descriptive prestige measure (no random walks, no eigenvector iteration, no shortest paths), which makes it the appropriate baseline to read alongside PageRank and HITS Authority. The informative cases are the disagreements: a channel high on in-degree but middling on PageRank or authority is *broadly* cited — often by peripheral accounts whose own prestige is low — whereas a channel high on PageRank or authority but middling on in-degree is cited *selectively* by the network's main hubs. Reading the two together separates "popular" from "prestigious".

**Example.** The official channel of a political party often tops the in-degree ranking — it is a routine reference point for many small accounts across the network. Its PageRank may be only middling, however, because most of those citations come from peripheral channels that themselves carry little prestige. A second channel — say, a strategist's commentary feed with a fraction of the in-degree — may sit much higher on PageRank and HITS Authority because the few channels that cite it are precisely the network's main hubs. In-degree alone correctly identifies the party channel as the most-cited reference point; only the comparison with PageRank reveals which of the two is *strategically* central.

---

## Out-degree centrality

*The outbound counterpart: what fraction of all other channels does this channel forward or reference?*

A high out-degree score means a channel casts a wide net — pointing outward to many different sources.

**In practice:** out-degree centrality answers: *which channels are the most active amplifiers?* Paired with in-degree, it distinguishes pure producers (high in, low out), pure distributors (high out, low in), and true network hubs (high on both). A channel that runs daily roundups linking to dozens of sources will score very high on out-degree even if almost no one forwards its own content.

---

## Harmonic centrality

*A high harmonic centrality score means this channel can reach the rest of the network quickly — along short, strongly-tied paths.*

Harmonic centrality sums the reciprocals of shortest path lengths to every other reachable channel, then normalises by the number of other channels. Path length is measured over weighted distance `1/weight` (a strong forwarding tie counts as *short*, following Opsahl, Agneessens & Skvoretz 2010), consistent with betweenness. Unreachable channels contribute zero, making it robust in the sparse, partially disconnected networks typical of political Telegram ecosystems. Unlike betweenness, it does not require a channel to sit on paths others use; it only asks how short those paths are from its own vantage point. Because a weighted distance can be below 1, the normalised score is not bounded to `[0, 1]` — read it relatively.

**In practice:** harmonic centrality surfaces structurally well-positioned channels that are invisible to betweenness-based rankings — channels that are structurally close to everyone without being a bottleneck.

---

## Burt's constraint

*A low Burt's constraint score means this channel sits at a structural hole — its neighbours do not connect to each other, making it the only bridge between them.*

The score ranges from 0 to 1. A low score means the channel's contacts belong to separate groups that do not interact; the channel is the only link between them, giving it control over information flowing between those groups. A high score means the channel is embedded in a dense clique where all contacts know each other — well-supported, but with limited reach across the broader network.

**Reference:** Burt, R.S. (1992) *Structural Holes: The Social Structure of Competition*. Harvard University Press. [doi:10.4159/9780674038714](https://doi.org/10.4159/9780674038714)

**In practice:** Burt's constraint surfaces the quiet brokers that betweenness might miss. A channel with low betweenness yet low constraint is a peripheral node connecting two small, otherwise unrelated groups. Removing it fractures a local connection that global betweenness analysis would overlook.

**Example.** In a mapped Italian political network, a channel with modest PageRank and a modest follower count has a Burt's constraint of 0.08 — the lowest in the network. Investigation reveals it is run by a political operative who curates content from both far-right and religious nationalist ecosystems, forwarding selectively to each. It is the only link between two communities that otherwise share zero direct contact.

---

## Local clustering

*A high local clustering score means this channel participates directly in closed citation cycles — it is embedded in a loop of mutual amplification.*

Local clustering coefficient (Fagiolo 2007) counts the directed triangles that pass through the channel itself, normalised by the number of possible directed triads centred on it. A directed triangle exists when A forwards from B, B forwards from C, and C forwards from A — a closed loop. A score of 1.0 means every pair of the channel's neighbours that could form a triangle does. A score of 0.0 means no such loops exist.

**Reference:** Fagiolo, G. (2007) "Clustering in complex directed networks." *Physical Review E* 76(2). [doi:10.1103/PhysRevE.76.026107](https://doi.org/10.1103/PhysRevE.76.026107)

**In practice:** local clustering pinpoints channels that are *active participants* in mutual-amplification loops, not mere pass-throughs. A channel with high betweenness but near-zero local clustering bridges groups without being woven into any citation cycle; a channel with high local clustering sits inside a tight reciprocal-citation cluster — often a coordinated or echo-chamber core. Pair it with `BURTCONSTRAINT` (low constraint = broker spanning structural holes) to separate the loop-embedded cores from the brokers between them.

**Example.** An internal channel within a tightly coordinated disinformation network — one that forwards from the network's seeder and is cited back by it — has high local clustering (0.67) because it participates in a clear citation cycle. A mainstream aggregator with the same number of connections but drawing from independent, mutually unrelated sources scores near 0 on clustering even if some of those sources have connections to each other.

---

## Amplification factor

*Amplification factor = forwards received from other channels ÷ own message count. It measures how efficiently a channel's content is redistributed.*

A value of 1.0 means each published message is forwarded, on average, once by other channels in the network. Values above 1.0 indicate viral reach exceeding production rate. Only forwards from channels currently in the graph are counted.

**In practice:** amplification separates content producers from content amplifiers in a way that subscriber count and in-degree do not. A high amplification factor combined with a modest subscriber count signals a channel punching above its weight — small but its content travels widely.

**Example.** A researcher with 3,000 subscribers publishes detailed analyses that ten mainstream aggregators routinely forward. Its amplification factor is 4–5, meaning each post is forwarded four to five times on average. A party's official channel with 50,000 subscribers may have an amplification factor of 0.2 — widely followed, but its content stays with its own audience without being redistributed. The first channel drives more narrative spread despite being far smaller.

---

## Content originality

*Content originality = 1 − (forwarded messages / total messages). A value of 1.0 means every published message is original; a value of 0.0 means every message is a forward.*

**In practice:** content originality is the most direct way to distinguish producers from distributors. Combined with amplification factor, it produces a two-axis characterisation of each channel's role: high on both (original content that spreads widely) signals a primary source; low on both (mostly forwards that nobody re-shares) signals a peripheral amplifier.

---

## Diffusion lag

*A low diffusion lag means this channel picks up forwarded content soon after it is first published — an early adopter. A high lag means it echoes narratives days or weeks later — a late amplifier.*

Diffusion lag is the **median** number of hours between the original publication date of a forwarded message and the moment this channel forwarded it. Telegram exposes the original post timestamp on every forwarded message, so the lag is observed directly per forward; the channel-level score aggregates across all forwards the channel published. The median is used in preference to the mean because forwarding lags are heavy-tailed: a small number of anniversary posts or archival re-shares would otherwise dominate a mean and obscure the channel's typical reaction time.

An optional **reaction window** (`--diffusion-window DAYS`, default 30; set to 0 to disable) excludes forwards whose lag exceeds the window. This keeps the measure focused on contemporaneous amplification rather than retrospective re-circulation. Channels with no dated forwards in scope receive `null`.

**Reference:** Kwon, S., Cha, M., Jung, K., Chen, W. & Wang, Y. (2013) "Prominent features of rumor propagation in online social media." *2013 IEEE 13th International Conference on Data Mining* (ICDM). [doi:10.1109/ICDM.2013.61](https://doi.org/10.1109/ICDM.2013.61). Cheng, J., Adamic, L., Dow, P.A., Kleinberg, J. & Leskovec, J. (2014) "Can cascades be predicted?" *Proceedings of the 23rd International Conference on World Wide Web* (WWW). [doi:10.1145/2566486.2567997](https://doi.org/10.1145/2566486.2567997).

**In practice:** diffusion lag answers a question structural measures cannot: *when* does a channel typically react? Two channels with identical PageRank and amplification factor can differ sharply on diffusion lag — one operating in near-real time, the other consistently lagging by half a day. Early adopters with high reach are agenda-setters within their community; late amplifiers with high reach extend the half-life of a narrative beyond its acute phase. Pair with `AMPLIFICATION` to separate channels by both reach and timing.

**Example.** Within a network of nationalist commentators, two channels each forward roughly 60% of a primary broadcaster's posts and have comparable in-degree. Their diffusion lags are 1.8 hours and 17 hours respectively. The first is part of the broadcaster's same-day distribution chain; the second appears to be a slower aggregator that re-posts after the news cycle has moved on. The structural roles look identical; the temporal roles are not.

---

## Spreading efficiency

*If this channel were the first to publish a piece of information, what fraction of the network would eventually receive it?*

Spreading efficiency runs a **SIR epidemic simulation** on the directed citation graph. The channel is set as the only initial infective. At each step, every infected node transmits to each susceptible successor with a probability equal to the edge weight (clipped to [0,1]), and independently recovers with probability γ = 0.3. The simulation runs until no infected nodes remain. Spreading efficiency is the mean fraction of other nodes ever infected, averaged over `SPREADING_RUNS` independent Monte Carlo runs (default 200).

The SIR model is the standard epidemiological model for rumour propagation and meme spread in social networks. Unlike structural measures, spreading efficiency directly captures the *dynamics* of information flow: a channel with high PageRank but embedded in a tight, insular cluster may spread less widely than a lower-ranked channel that bridges several communities.

**Computational cost:** O(runs × N × mean outbreak size) per export. For a 500-node network with 200 runs, expect 10–60 seconds depending on network density.

**In practice:** use spreading efficiency to find channels whose structural position makes them efficient propagators regardless of their raw follower count. A channel with spreading efficiency 0.3 seeds processes that eventually reach 30% of the network on average.

---

## Bridging centrality (Hwang et al. 2008)

*A high bridging centrality score means this channel is a topological bridge — a low-degree node wedged between high-degree regions, whose removal would most fragment the network.*

This is the **Bridging Centrality** of Hwang, Kim, Ramanathan & Zhang (*Bridging Centrality: Graph Mining from Element Level to Group Level*, KDD 2008): the product of betweenness centrality and a **bridging coefficient** `Ψ(v) = (1 / d(v)) / Σ_{i ∈ N(v)} (1 / d(i))`, where `d(v)` is the (undirected, unweighted) degree of channel `v` and `N(v)` its neighbours. The bridging coefficient is large when a channel has *few* links of its own yet those links reach *high-degree* nodes — i.e. it is the narrow waist between otherwise busy regions. Multiplying by betweenness keeps only those waists that actually carry shortest-path traffic.

Crucially this is **purely topological** — it uses no community partition, so it needs no `--community-strategies` basis. It answers a different question from [community bridging](#community-bridging): "is this a bridge between *dense regions of the graph*?" rather than "is this a broker between *detected communities*?".

**In practice:** bridging centrality separates true bottlenecks from mere hubs. A hub with many neighbours can have very high betweenness yet a low bridging coefficient (its neighbours are mostly low-degree leaves), so it scores *lower* than a modest channel that quietly connects two large clusters — the one whose disappearance fractures the network.

**Example.** A channel with only two ties — one into a 200-channel nationalist cluster, one into a 200-channel religious cluster — has low degree but an enormous bridging coefficient. A central aggregator *inside* the nationalist cluster has higher betweenness but a low bridging coefficient. Plain betweenness ranks the aggregator first; bridging centrality ranks the two-tie bridge first, correctly flagging it as the single point of failure between the two clusters.

---

## Community bridging

*A high community bridging score means this channel is both structurally central AND bridges genuinely distinct communities.*

Community bridging is a composite measure combining betweenness centrality (how often a channel sits on the shortest paths between others) and the **participation coefficient** of its immediate neighbours' community memberships (Guimerà & Amaral, *Nature* 2005) — `P = 1 − Σ_c (w_c / W)²`, which is 0 when every neighbour belongs to one community and approaches 1 as the channel's ties spread evenly across many. The final score is the product of the two. A channel scores high only if it is simultaneously on important paths *and* those paths cross ideological or topical boundaries. (The participation coefficient replaced an earlier unbounded Shannon-entropy factor; being bounded in `[0, 1]` it keeps the product on betweenness' own scale.)

> **Naming note.** This composite (betweenness × community participation coefficient) was previously labelled "Bridging centrality", but that name properly belongs to the degree-based measure of Hwang et al. (2008) described above — now exposed separately as `BRIDGINGCENTRALITY`. This measure was therefore renamed **Community bridging** (node key `community_bridging`); the question it answers ("does this broker span *distinct communities*?") is the Guimerà–Amaral one.

The community basis for the participation coefficient is set by the strategy name in parentheses — for example, `BRIDGING(LOUVAIN)` uses the Louvain partition. Without a strategy name, `LEIDEN_DIRECTED` is used (the directed null model respects citation direction, which matches the brokerage question). The chosen strategy must also appear in `--community-strategies`. In the Operations panel the basis is picked from the **Bridging basis** dropdown in the *Linked parameters* fieldset; the same dropdown also drives the community-bridging robustness attack strategy, so both pick up the same partition.

**In practice:** community bridging fills a gap left by betweenness alone. A channel can rank highly on betweenness simply because it sits in a densely connected region of the network, even if all its neighbours belong to the same ideological cluster. Community bridging penalises that: the participation-coefficient factor discounts intra-community connectors and elevates genuine cross-community bridges.

**Example.** Two channels have identical betweenness scores. The first connects channels that all belong to the same nationalist bloc; the second connects channels from four distinct communities — nationalist, religious conservative, mainstream right, and state media. Standard betweenness ranks them equal. Community bridging gives the second channel a substantially higher score, identifying it as the more strategically significant node for understanding how narratives migrate across the broader information ecosystem.

---

## K-core coreness

*A high coreness number means this channel sits in the densely interconnected nucleus of the network; a low number means it is a peripheral amplifier shed in the first peeling rounds.*

The k-core decomposition repeatedly strips away every node with fewer than *k* neighbours until only nodes with at least *k* surviving neighbours remain; a channel's **coreness** is the largest *k* whose core still contains it. It is computed on the symmetrised, self-loop-free citation graph (matching the [K-core community strategy](community-detection.md#k-core)), so it measures topological depth rather than tie strength. Coreness is one of the most robust predictors of spreading influence: Kitsak et al. (2010) showed the most effective spreaders are the channels in the network's core, often outranking both degree and betweenness, and the measure stays well-behaved on the sparse, partially disconnected graphs typical of Telegram ecosystems.

**Reference:** Kitsak, M., Gallos, L.K., Havlin, S., Liljeros, F., Muchnik, L., Stanley, H.E. & Makse, H.A. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746)

**In practice:** a channel with high in-degree but low coreness is cited by many peripheral accounts yet sits outside the mutually-reinforcing nucleus — its reach is shallower than its raw citation count suggests. A channel with modest degree but high coreness is wired into the dense core, a position that predicts efficient onward spread. Pair coreness with PageRank to separate "popular but peripheral" from "core and influential".

---

## Trophic level

*A low trophic level means this channel is a structural source that others draw from; a high level means it is a terminal amplifier downstream of the content it carries.*

Trophic level places every channel on a single source→sink axis derived purely from the direction of citation flow. Pulpit uses the **hierarchical levels** of MacKay, Johnson & Sansom (2020): the levels `h` solve the Laplacian system `(diag(u) − (W + Wᵀ)) h = (w_in − w_out)`, where `w_in` / `w_out` are weighted in-/out-strength and `u = w_in + w_out`. Unlike the classic Levine (1980) trophic level — undefined on graphs without basal nodes — this formulation stays finite on the cyclic citation graphs Pulpit builds. Levels are shifted so the lowest channel in each weakly-connected component reads 0.

**Reference:** MacKay, R.S., Johnson, S. & Sansom, B. (2020) "How directed is a directed network?" *Royal Society Open Science* 7(9). [doi:10.1098/rsos.201138](https://doi.org/10.1098/rsos.201138). Levine, S. (1980) "Several measures of trophic structure applicable to complex food webs." *Journal of Theoretical Biology* 83(2). [doi:10.1016/0022-5193(80)90288-X](https://doi.org/10.1016/0022-5193(80)90288-X)

**In practice:** trophic level is the structural counterpart of [content originality](#content-originality). Content originality asks whether a channel's *messages* are original; trophic level asks whether its *position in the citation flow* is upstream — regardless of how original any single post is. A channel can repost heavily (low content originality) yet still sit upstream of an even more derivative downstream cluster. Reading the two together separates genuine sources from mid-chain relays.

---

## Within-module role

*Is this channel a hub inside its own community, a bridge between communities, or a peripheral member? The within-module role names the position directly.*

Following Guimerà & Amaral (2005), each channel is characterised by two quantities measured against the community partition (the [bridging basis](#community-bridging), defaulting to Leiden Directed): the **within-module degree z-score** `z` — how many more intra-community neighbours it has than its community's average — and the **participation coefficient** `P` — how evenly its ties spread across communities. The (z, P) pair maps to one of seven canonical roles: ultra-peripheral, peripheral, connector, and kinless non-hubs (`z < 2.5`); and provincial, connector, and kinless hubs (`z ≥ 2.5`). The numeric `z` is the sortable **Within-module z** column; the categorical label is the **Role** column.

**Reference:** Guimerà, R. & Amaral, L.A.N. (2005) "Functional cartography of complex metabolic networks." *Nature* 433(7028). [doi:10.1038/nature03288](https://doi.org/10.1038/nature03288)

**In practice:** the role taxonomy turns a community partition into a per-channel job description. A *provincial hub* is a kingpin within a single community — central but inward-facing. A *connector hub* is both central and spans communities: the most strategically significant brokers, whose removal both fragments a community and severs cross-community flow. A (non-hub) *connector* is a low-profile bridge. `MODULEROLE` needs at least one `--community-strategies` partition to define the modules.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

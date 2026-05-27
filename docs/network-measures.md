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

The score is iterative: a channel inherits prestige from its forwarders, who inherit it from theirs. A forward from a well-connected, influential channel counts for more than a forward from a marginal one. Brin & Page (1998) introduced PageRank to rank web pages by link structure; the same logic applies to forwarding networks.

**Reference:** Brin, S. & Page, L. (1998) "The anatomy of a large-scale hypertextual web search engine." *Computer Networks and ISDN Systems* 30(1–7). [doi:10.1016/S0169-7552(98)00110-X](https://doi.org/10.1016/S0169-7552(98)00110-X)

**In practice:** a mid-sized channel consistently forwarded by the ten most connected outlets in a network will score higher than a large channel referenced only by peripheral accounts. PageRank identifies the channels that the network's own key players treat as authoritative — the sources that shape the agenda.

**Example.** In a network of nationalist Telegram channels, PageRank tends to surface the two or three outlets whose frames and narratives are picked up and redistributed by everyone else — the ideological anchors of the ecosystem, even if they don't have the largest subscriber counts.

---

## HITS Hub score

*A high hub score means this channel actively amplifies others — it is a distributor, not a producer.*

The HITS algorithm (Hyperlink-Induced Topic Search) assigns two scores simultaneously: hubs and authorities. A channel scores high as a hub if it forwards content from many authoritative channels. Hubs are the connective tissue of a political network: they produce little original content but ensure that content from producers reaches a broad audience.

**Reference:** Kleinberg, J. (1999) "Authoritative sources in a hyperlinked environment." *Journal of the ACM* 46(5). [doi:10.1145/324133.324140](https://doi.org/10.1145/324133.324140)

**In practice:** hub channels answer the question: *who are the distributors?* A channel running as a daily digest — forwarding from a dozen political commentators without adding much commentary — will score very high as a hub. Its removal would fragment information flow across the network.

---

## HITS Authority score

*A high authority score means this channel is one of the original sources that distributors choose to spread.*

The counterpart to Hub. A channel scores high as an authority if it is pointed to by many good hubs. Authorities are the primary content producers whose material circulates widely because the network's distributors have chosen to amplify it.

**Reference:** Kleinberg (1999), as above.

**In practice:** authority score is particularly useful for identifying propaganda sources. A channel with a modest following may function as the primary content farm for a large distribution network. Its actual reach — through the hubs — is far larger than its subscriber count suggests.

**Example.** A political strategist's channel with 5,000 subscribers might rank as the top authority in a network because fifteen high-traffic aggregator channels forward its posts daily.

---

## Betweenness centrality

*A high betweenness score means this channel sits on many of the shortest paths connecting other channels — it is a broker.*

Channels that bridge communities or sub-networks that would otherwise be weakly connected score high on betweenness. Removing a high-betweenness channel increases the distance between the communities it connects.

**Reference:** Freeman, L.C. (1977) "A set of measures of centrality based on betweenness." *Sociometry* 40(1). [doi:10.2307/3033543](https://doi.org/10.2307/3033543)

**In practice:** betweenness is the measure most useful for understanding cross-community dynamics. A channel that bridges two ideological camps will score high even without having high prestige within either camp.

**Example.** A channel that regularly references both a cluster of religious nationalist outlets and a cluster of economic libertarian outlets — groups that don't directly cross-reference — appears as the bridge between two otherwise separate ecosystems. It may be the main vector through which narratives migrate from one community to the other.

---

## In-degree centrality

*The simplest measure: what fraction of all other channels in the network forward or reference this channel?*

No weighting by importance — just the normalised count of other channels that cite this one.

**In practice:** in-degree centrality directly answers: *which channels are the most-cited sources?* It correlates with visibility and reach, but unlike PageRank it does not discount citations from peripheral channels. A channel forwarded by a hundred small accounts scores higher than one forwarded by ten major ones.

**Example.** The official channel of a political party will often top the in-degree ranking because it is a routine reference point for many channels across the network — even if the party itself is not particularly central to the informal influence dynamics that PageRank or HITS would surface.

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

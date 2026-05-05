# Network measures

A network measure assigns a numerical score to each channel based on its position in the directed citation graph. Pulpit constructs edges from forwards and `t.me/` references: a directed edge from channel A to channel B means A regularly amplifies B's content, weighted by frequency relative to A's total output.

All measures can be used to size nodes in the graph viewer, making the most significant channels visually prominent.

<figure>
<img src="../webapp_engine/static/screenshot_01.jpg" alt="Channel table with network measures">
<figcaption><em>Channel table: 14 measures as sortable columns. Click any header to rank channels by that measure.</em></figcaption>
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
| Flow betweenness | `FLOWBETWEENNESS` | Which channels are brokers that standard betweenness misses? |
| In-degree centrality | `INDEGCENTRALITY` | Which channels are cited by the largest fraction of others? |
| Out-degree centrality | `OUTDEGCENTRALITY` | Which channels cite the largest fraction of others? |
| Harmonic centrality | `HARMONICCENTRALITY` | Which channels can reach the rest of the network in the fewest hops? |
| Katz centrality | `KATZ` | Which channels are most accessible through all paths, direct and indirect? |
| Burt's constraint | `BURTCONSTRAINT` | Which channels bridge structural holes between otherwise separate groups? |
| Ego network density | `EGODENSITY` | How deeply is this channel embedded in a tight, mutually referencing cluster? |
| Amplification factor | `AMPLIFICATION` | Whose content spreads furthest relative to its output volume? |
| Content originality | `CONTENTORIGINALITY` | Which channels produce original content vs. redistribute others'? |
| Spreading efficiency | `SPREADING` | If this channel starts spreading a message, what fraction of the network eventually receives it? |
| Bridging centrality | `BRIDGING` / `BRIDGING(STRATEGY)` | Which channels bridge distinct communities AND lie on structurally important paths? |

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

## Flow betweenness

*A high flow betweenness score means this channel is an important relay point for diffusing information — even when standard betweenness misses it.*

Standard betweenness assumes information travels along the single shortest path. Flow betweenness, introduced by Newman (2005), relaxes that assumption: it models information as a random walk diffusing through the network along all paths simultaneously, with each path weighted by its probability. The score for a channel is the fraction of all such random-walk flows that pass through it. The graph is symmetrised to undirected before computation; channels outside the largest connected component receive 0.0.

**Reference:** Newman, M.E.J. (2005) "A measure of betweenness centrality based on random walks." *Social Networks* 27(1). [doi:10.1016/j.socnet.2004.11.009](https://doi.org/10.1016/j.socnet.2004.11.009)

**In practice:** flow betweenness and shortest-path betweenness identify different kinds of brokers. A channel that ranks high on flow betweenness but low on standard betweenness is structurally important to diffusion but not a bottleneck in the geodesic sense. The two measures are most informative when compared.

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

*A high harmonic centrality score means this channel can reach the rest of the network quickly — in few hops.*

Harmonic centrality sums the reciprocals of shortest path lengths to every other reachable channel, then normalises by the number of other channels. Unreachable channels contribute zero, making it robust in the sparse, partially disconnected networks typical of political Telegram ecosystems. Unlike betweenness, it does not require a channel to sit on paths others use; it only asks how short those paths are from its own vantage point.

**In practice:** harmonic centrality surfaces structurally well-positioned channels that are invisible to betweenness-based rankings — channels that are structurally close to everyone without being a bottleneck.

---

## Katz centrality

*A high Katz score means this channel is deeply embedded in the network — reachable from many directions through many indirect paths.*

Katz centrality extends PageRank by counting all paths of any length, with longer paths discounted by an attenuation factor α. Unlike PageRank, every channel receives a baseline score regardless of how important its predecessors are.

**Reference:** Katz, L. (1953) "A new status index derived from sociometric analysis." *Psychometrika* 18(1). [doi:10.1007/BF02289026](https://doi.org/10.1007/BF02289026)

**In practice:** Katz is particularly informative in distributed, horizontal networks where influence is not concentrated in a few dominant hubs. A regional channel receiving forwards from dozens of small local outlets — none individually prestigious — will rank low on PageRank but high on Katz, revealing that it is a genuine reference point for a wide slice of the network.

---

## Burt's constraint

*A low Burt's constraint score means this channel sits at a structural hole — its neighbours do not connect to each other, making it the only bridge between them.*

The score ranges from 0 to 1. A low score means the channel's contacts belong to separate groups that do not interact; the channel is the only link between them, giving it control over information flowing between those groups. A high score means the channel is embedded in a dense clique where all contacts know each other — well-supported, but with limited reach across the broader network.

**Reference:** Burt, R.S. (1992) *Structural Holes: The Social Structure of Competition*. Harvard University Press. [doi:10.4159/9780674038714](https://doi.org/10.4159/9780674038714)

**In practice:** Burt's constraint surfaces the quiet brokers that betweenness might miss. A channel with low betweenness yet low constraint is a peripheral node connecting two small, otherwise unrelated groups. Removing it fractures a local connection that global betweenness analysis would overlook.

**Example.** In a mapped Italian political network, a channel with modest PageRank and a modest follower count has a Burt's constraint of 0.08 — the lowest in the network. Investigation reveals it is run by a political operative who curates content from both far-right and religious nationalist ecosystems, forwarding selectively to each. It is the only link between two communities that otherwise share zero direct contact.

---

## Ego network density

*A high ego density score means this channel's immediate neighbours are all strongly connected to each other — it is embedded in a closed echo chamber. A low score means the channel's neighbours are isolated from each other, with all connections flowing through this channel.*

Ego network density measures how densely the immediate neighbourhood (predecessors ∪ successors) of a channel is connected among itself, excluding the channel. A value of 1.0 means the neighbourhood is a fully connected clique — every neighbour cites every other. A value of 0.0 means neighbours share no connections at all — the channel is a hub between completely disconnected sources. Channels with fewer than two neighbours receive no score.

**In practice:** use ego density in combination with PageRank or betweenness to distinguish structural roles. A channel with high betweenness and low ego density is a genuine bridge between disconnected groups. A channel with high betweenness and high ego density is a central node in a tight cluster — it appears to bridge because it is highly connected, but its neighbourhood is a single coherent echo chamber.

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

## Spreading efficiency

*If this channel were the first to publish a piece of information, what fraction of the network would eventually receive it?*

Spreading efficiency runs a **SIR epidemic simulation** on the directed citation graph. The channel is set as the only initial infective. At each step, every infected node transmits to each susceptible successor with a probability equal to the edge weight (clipped to [0,1]), and independently recovers with probability γ = 0.3. The simulation runs until no infected nodes remain. Spreading efficiency is the mean fraction of other nodes ever infected, averaged over `SPREADING_RUNS` independent Monte Carlo runs (default 200).

The SIR model is the standard epidemiological model for rumour propagation and meme spread in social networks. Unlike structural measures, spreading efficiency directly captures the *dynamics* of information flow: a channel with high PageRank but embedded in a tight, insular cluster may spread less widely than a lower-ranked channel that bridges several communities.

**Computational cost:** O(runs × N × mean outbreak size) per export. For a 500-node network with 200 runs, expect 10–60 seconds depending on network density.

**In practice:** use spreading efficiency to find channels whose structural position makes them efficient propagators regardless of their raw follower count. A channel with spreading efficiency 0.3 seeds processes that eventually reach 30% of the network on average.

---

## Bridging centrality

*A high bridging centrality score means this channel is both structurally central AND bridges genuinely distinct communities.*

Bridging centrality is a composite measure combining betweenness centrality (how often a channel sits on the shortest paths between others) and the Shannon entropy of its immediate neighbours' community memberships. The final score is the product of the two. A channel scores high only if it is simultaneously on important paths *and* those paths cross ideological or topical boundaries.

The community basis for the entropy calculation is set by the strategy name in parentheses — for example, `BRIDGING(LOUVAIN)` uses the Louvain partition. Without a strategy name, `LEIDEN` is used. The chosen strategy must also appear in `--community-strategies`.

**In practice:** bridging centrality fills a gap left by betweenness alone. A channel can rank highly on betweenness simply because it sits in a densely connected region of the network, even if all its neighbours belong to the same ideological cluster. Bridging centrality penalises that: the entropy factor discounts intra-community connectors and elevates genuine cross-community bridges.

**Example.** Two channels have identical betweenness scores. The first connects channels that all belong to the same nationalist bloc; the second connects channels from four distinct communities — nationalist, religious conservative, mainstream right, and state media. Standard betweenness ranks them equal. Bridging centrality gives the second channel a substantially higher score, identifying it as the more strategically significant node for understanding how narratives migrate across the broader information ecosystem.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

# Network measures and community strategies

This document explains the analytical tools available in Pulpit — what they measure, how they work, and what they reveal when applied to political Telegram networks.

---

## Quick reference

### Measures

Configured via `--measures` on `structural_analysis`. Use `ALL` to enable everything.

| Measure | Key | Question it answers |
| :------ | :-- | :------------------ |
| PageRank | `PAGERANK` | Which channels do the network's key players treat as authoritative? |
| HITS Hub | `HITSHUB` | Which channels actively amplify others — the distributors? |
| HITS Authority | `HITSAUTH` | Which channels are the original sources that distributors spread? |
| Betweenness centrality | `BETWEENNESS` | Which channels sit on the bridges between sub-networks? |
| Flow betweenness | `FLOWBETWEENNESS` | Which channels are brokers that standard betweenness misses — important to random-walk diffusion, not just shortest paths? |
| In-degree centrality | `INDEGCENTRALITY` | Which channels are cited by the largest fraction of others? |
| Out-degree centrality | `OUTDEGCENTRALITY` | Which channels cite the largest fraction of others? |
| Harmonic centrality | `HARMONICCENTRALITY` | Which channels can reach the rest of the network in the fewest hops? |
| Katz centrality | `KATZ` | Which channels are most accessible through all paths, direct and indirect? |
| Burt's constraint | `BURTCONSTRAINT` | Which channels bridge structural holes between otherwise separate groups? |
| Amplification factor | `AMPLIFICATION` | Whose content spreads furthest relative to its output volume? |
| Content originality | `CONTENTORIGINALITY` | Which channels produce original content vs. redistribute others'? |
| Spreading efficiency | `SPREADING` | If this channel starts spreading a message, what fraction of the network eventually receives it? (SIR simulation; slow) |
| Bridging centrality | `BRIDGING` / `BRIDGING(STRATEGY)` | Which channels bridge distinct communities AND lie on structurally important paths? |

### Community detection strategies

Configured via `--community-strategies` on `structural_analysis`. Use `ALL` to run everything simultaneously.

| Strategy | Key | What it reveals |
| :------- | :-- | :-------------- |
| Organization | `ORGANIZATION` | Your own domain-knowledge groupings, defined in the admin |
| Louvain | `LOUVAIN` | Data-driven modularity clusters |
| Leiden | `LEIDEN` | Sharper, more cohesive modularity clusters |
| Leiden (directed) | `LEIDEN_DIRECTED` | Like Leiden, but modularity uses in/out-degree null model — direction-aware |
| Leiden CPM coarse | `LEIDEN_CPM_COARSE` | Resolution-parameter clustering without the modularity resolution limit; few, large communities |
| Leiden CPM fine | `LEIDEN_CPM_FINE` | Same as above with a higher resolution parameter; more, smaller communities |
| K-core | `KCORE` | Hierarchy: the innermost ideological core vs. peripheral amplifiers |
| Infomap | `INFOMAP` | Echo chambers: groups where information circulates in closed loops |
| Memory Infomap | `INFOMAP_MEMORY` | Like Infomap but second-order: where you came from changes where you go — detects context-dependent flow communities |
| MCL | `MCL` | Directed-graph-native flow clustering via matrix inflation; good at circulation-pattern communities |
| Walktrap | `WALKTRAP` | Random-walk distance clustering with a full dendrogram; good at shared-neighbourhood communities |
| Weakly connected components | `WEAKCC` | Structural islands with no path to the rest of the network |
| Strongly connected components | `STRONGCC` | Mutually reinforcing cores: channels in closed directed loops |

---

## Network measures

A network measure assigns a numerical score to each channel based on its position in the graph. Pulpit computes edges from forwards and `t.me/` references: a directed edge from channel A to channel B means A regularly amplifies B's content. Edge weights reflect how often, relative to A's total output.

All measures can be used to size nodes in the graph viewer, making the most significant channels visually prominent.

---

### PageRank

PageRank scores a channel by the importance of the channels that amplify it, not just by how many do. A forward from a well-connected, influential channel counts for more than a forward from a marginal one. The algorithm works iteratively: a channel inherits prestige from its forwarders, who in turn inherit it from theirs.

**In practice:** a mid-sized channel that is consistently forwarded by the top ten most connected outlets in a network will score higher than a large channel that is only referenced by peripheral accounts. PageRank is good at identifying the channels that the network's own key players treat as authoritative — the sources that shape the agenda.

**Example:** in a network of nationalist Telegram channels, PageRank tends to surface the two or three outlets whose frames and narratives get picked up and redistributed by everyone else — the ideological anchors of the ecosystem, even if they don't have the largest subscriber counts.

---

### HITS Hub score

The HITS algorithm (Hyperlink-Induced Topic Search) separates two distinct roles: hubs and authorities. A channel scores high as a **hub** if it forwards content from many authoritative channels. Hubs are amplifiers and aggregators — their value lies in what they point to, not in what they originate.

**In practice:** hub channels are often the connective tissue of a political network. They may produce little original content but play a crucial role in making sure that content from producers reaches a broad audience. Identifying hubs helps answer the question: *who are the distributors?*

**Example:** a channel that runs as a daily digest — forwarding posts from a dozen different political commentators without adding much commentary of its own — will score very high as a hub. It is a node that connects its followers to the sources it curates, and its removal would fragment information flow across the network.

---

### HITS Authority score

The counterpart to Hub. A channel scores high as an **authority** if it is pointed to by many good hubs. Authorities are the original content producers whose material circulates widely because the network's distributors have chosen to amplify it.

**In practice:** high authority channels are the ones setting the conversation. They produce the posts that get forwarded, the framings that get reproduced. Authority score is particularly useful for identifying propaganda sources: a channel may have a modest direct following but function as the primary content farm for a large distribution network.

**Example:** a political strategist's channel with 5 000 subscribers might score as the top authority in a network because fifteen high-traffic aggregator channels forward its posts daily. Its actual reach — through the hubs — is far larger than its subscriber count suggests.

---

### Betweenness centrality

A channel scores high on betweenness if it sits on many of the shortest paths connecting other channels in the network. These are the **brokers and bridges** — channels that link communities or sub-networks that would otherwise be weakly connected or disconnected.

**In practice:** betweenness centrality is the measure most useful for understanding cross-community dynamics. A channel that bridges two ideological camps — say, mainstream conservative media and the far right — will score high even if it does not have particularly high prestige within either camp. Removing a high-betweenness channel from the network would increase the distance between the communities it connects.

**Example:** a channel that regularly references both a cluster of religious nationalist outlets and a cluster of economic libertarian outlets — groups that don't directly cross-reference much — will appear as a bridge between two otherwise separate ecosystems. It may be the main vector through which narratives migrate from one community to the other.

---

### Flow betweenness

Standard betweenness centrality assumes that information travels along shortest paths. Flow betweenness (Newman 2005, *Physical Review E* 71, 036111) relaxes that assumption: it models information as a random walk that diffuses through the network along *all* paths, with each path weighted by its probability under a random-walk process. The score for a node is the fraction of all such random-walk flows that pass through it.

The graph is symmetrised to undirected before computation (the random-walk model assumes current can flow in both directions along any edge). Edge weights are preserved. Because the algorithm requires a connected graph, nodes outside the largest connected component receive 0.0.

**In practice:** flow betweenness and shortest-path betweenness identify different kinds of brokers. In dense, richly interconnected networks where many near-shortest paths exist, shortest-path betweenness underestimates nodes whose importance comes from being passively traversed by diffusing content rather than lying on the single optimal route. Flow betweenness surfaces those passive brokers. The two measures are most informative when compared: a channel that ranks high on flow betweenness but low on shortest-path betweenness is a node that standard betweenness misses — structurally important to diffusion but not a bottleneck in the geodesic sense.

**Example:** two large ideological clusters are loosely connected through several mid-tier channels that all roughly share the same shortest-path betweenness. One of those channels, however, is embedded in a denser local sub-graph where many short cycles exist: random walks frequently pass through it simply because it has many slightly longer alternative paths converging on it. Flow betweenness assigns it a higher score than its peers, flagging it as the de-facto relay point for information diffusing between the two clusters — even though no single shortest-path analysis would single it out.

---

### In-degree centrality

The simplest measure: the normalized fraction of all other channels in the network that forward or reference this channel. No weighting by importance — just raw count.

**In practice:** in-degree centrality is the most legible measure for non-technical audiences. It directly answers: *which channels are the most cited sources in this network?* It correlates with visibility and reach, but unlike PageRank it does not discount references from peripheral channels. A channel forwarded by a hundred small accounts will score higher than one forwarded by ten major ones.

**Example:** the official channel of a political party will often top the in-degree ranking because it is a routine reference point for many channels across the network — forwarded by allies, quoted by critics, linked in news roundups — even if the party itself is not particularly central to the informal influence dynamics that PageRank or HITS would surface.

---

### Out-degree centrality

The outbound counterpart to in-degree: the normalized fraction of all other channels in the network that this channel forwards or references. It measures how broadly a channel distributes its attention across the network.

**In practice:** out-degree centrality answers: *which channels are the most active amplifiers?* A high score means a channel casts a wide net — pointing outward to many different sources. This can indicate a broad-spectrum aggregator, a channel trying to build alliances across ideological lines, or a node that acts as a gateway between distinct communities. Paired with in-degree, it helps distinguish pure producers (high in, low out) from pure distributors (high out, low in) from true network hubs (high on both).

**Example:** a channel that runs daily roundups of posts from across the political spectrum — linking to nationalist outlets, mainstream media, and independent commentators alike — will score very high on out-degree centrality even if almost no one forwards its own content. Its influence is in the connections it maintains, not in the audience it attracts.

---

### Harmonic centrality

A variant of closeness centrality designed to handle disconnected graphs. For each channel, it sums the reciprocals of the shortest path lengths to every other reachable channel, then normalizes by the number of other nodes. Unreachable nodes contribute zero rather than causing the score to collapse entirely.

**In practice:** harmonic centrality measures how quickly a channel can reach the rest of the network through the chain of forwards and references. A high score means the channel is structurally close to everyone else — able to receive or propagate information with few hops. Unlike betweenness, it does not require a channel to sit on the paths others use; it only asks how short those paths are from its own vantage point. It is more robust than standard closeness centrality in the sparse, partially disconnected networks typical of political Telegram ecosystems.

**Example:** a mid-sized channel that sits at the junction of two dense sub-clusters — say, regional nationalist outlets and a broader pan-national movement — may not lie on many shortest paths between others (low betweenness) but can itself reach almost every channel in the network within two or three hops. Harmonic centrality surfaces exactly this kind of structurally well-positioned node, which would be invisible to betweenness-based rankings.

---

### Katz centrality

Katz centrality extends the idea behind PageRank by counting not just direct connections but all paths of any length — with longer paths discounted by an attenuation factor (α). A channel scores high if it receives many connections from many channels, but also if it is reachable from the rest of the network through many indirect paths. Unlike PageRank, Katz gives every channel a baseline score regardless of whether its predecessors are influential, making it less sensitive to the sparse regions of the network.

**In practice:** Katz centrality is useful for surfacing channels that are deeply embedded in the network fabric — not just the channels that receive prestige from influential forwarders, but the channels that are structurally accessible from many directions. In networks where the most influential nodes have few predecessors (top-level agenda-setters rarely cited by anyone), PageRank can undervalue channels that are heavily referenced by a large number of mid-tier nodes. Katz corrects for this.

**Example:** a regional channel that receives forwards from dozens of small local outlets — none of which are individually prestigious — will rank low on PageRank but high on Katz. Katz reveals that it is a genuine reference point for a wide slice of the network, even if none of those slices carry much individual weight. It is particularly informative in distributed, horizontal networks where influence is not concentrated in a few dominant hubs.

---

### Burt's constraint

Burt's constraint measures how much a node's contacts are themselves connected to each other. The score ranges from 0 to 1. A low score (close to 0) means the node sits at a **structural hole** — its neighbours belong to separate groups that do not interact with each other, so the node is the only bridge between them. A high score (close to 1) means the node is embedded in a dense, redundant clique where all contacts know each other and there is little to broker.

The measure is local: it only examines the immediate neighbourhood of each node, not the full network topology. This makes it complementary to betweenness centrality, which is global. A channel can have low betweenness yet low constraint (a peripheral node connecting two small, otherwise unrelated groups) or high betweenness yet moderate constraint (a central hub that is also well-embedded in its own community). Isolated nodes — channels with no connections — receive no score.

**In practice:** in a political channel network, low-constraint channels are the quiet brokers. They maintain ties to channels from different ideological clusters without being fully embedded in any single one. They may not lie on many shortest paths (low betweenness) but structurally they are the only link between two otherwise separate communities. Removing a low-constraint channel fractures a local connection that betweenness analysis might miss. High-constraint channels are the opposite: deeply integrated into a single community, well-supported by redundant ties, but with limited reach across the broader network.

**Example:** a channel that forwards content from both a nationalist cluster and a religious conservative cluster — two communities that otherwise have little contact — will score low on constraint even if the network's major hubs don't use it as a path. It is a niche bridge, not a highway. Constraint surfaces it; betweenness might not.

---

### Amplification factor

Amplification factor = **forwards received from other channels ÷ own message count**. It measures how much a channel's content is redistributed by others, normalised by the channel's output volume. A value of 1.0 means each published message is forwarded, on average, exactly once by other channels in the network. Values above 1.0 indicate viral reach exceeding production rate: the channel's content spreads more than it is produced. Only forwards from channels currently in the graph are counted, keeping the measure consistent with its edge structure. When `DRAW_DEAD_LEAVES=False` (the default) this means only channels marked `is_interesting=True`; when `DRAW_DEAD_LEAVES=True`, dead-leaf channels that appear in the graph contribute their forwards too.

The normalisation by message count is what makes this measure distinct from raw in-degree. A channel that publishes rarely but whose every post gets forwarded by dozens of others scores far higher than a prolific channel that is occasionally forwarded. It isolates *efficiency of spread* from *volume of output*.

**In practice:** amplification factor separates content producers from content amplifiers in a way that subscriber count and in-degree do not. A high amplification factor combined with a modest subscriber count signals a channel punching above its weight: it is small but its content travels. These channels are often primary sources — fringe outlets, specialist commentators, or operational channels in information campaigns — whose material enters the mainstream only because aggregators pick it up. Paired with HITS authority score, it helps distinguish structurally cited channels (high authority, formal prestige) from channels that are actually re-shared (high amplification, real-world reach).

**Example:** a researcher with 3 000 subscribers publishes detailed analyses that ten mainstream aggregators routinely forward. Its amplification factor may be 4–5, meaning each post is forwarded four to five times on average. A party's official channel with 50 000 subscribers may have an amplification factor of 0.2 — widely followed, but its content mostly stays with its own audience without being redistributed. The first channel drives more narrative spread despite being far smaller.

---

### Content originality

Content originality = **1 − (forwarded messages / total messages)**. A value of 1.0 means every message published by the channel is original content; a value of 0.0 means every message is a forward from another channel. Channels with no messages receive no score.

**In practice:** content originality separates **producers** from **distributors** in the most direct way possible. High-originality channels write their own material; low-originality channels are pure relay nodes — their value is in their audience and distribution reach, not in what they create. Combined with amplification factor, it produces a two-axis characterisation of each channel's role: a channel that is high on both (original content that spreads widely) is a primary source; a channel low on both (mostly forwards that nobody re-shares) is a peripheral amplifier with limited influence in both directions.

**Example:** the official channel of a political party will typically score near 1.0 — almost all posts are original statements, press releases, or commentary. A news aggregator channel will score near 0.0 — it exists to curate and forward, producing little of its own. A hybrid channel — say, a political commentator who writes daily analysis but also regularly forwards breaking news from wire channels — will score somewhere in the middle, and the exact value reveals how much of its identity is commentary versus aggregation.

---

### Spreading efficiency

Spreading efficiency answers a direct question: **if this channel were the first to publish a piece of information, what fraction of the network would eventually receive it?**

The measure runs a **SIR epidemic simulation** on the directed citation graph. The channel is set as the only initial infective. At each step, every infected node transmits to each susceptible successor with a probability equal to the edge weight (clipped to [0, 1]), and independently recovers with a fixed probability of 0.3. The simulation repeats until no infected nodes remain. The spreading efficiency is the mean fraction of other nodes ever infected, averaged over `SPREADING_RUNS` independent Monte Carlo runs (default 200).

The SIR model is the standard epidemiological model for rumour propagation and meme spread in social networks. Unlike structural measures (degree, betweenness), spreading efficiency directly captures the *dynamics* of information flow: a channel with high PageRank but embedded in a tight, insular cluster may spread less widely than a lower-ranked channel that bridges several communities.

**Parameters:** transmission probability = edge weight; recovery probability γ = 0.3 per step (mean infectious period ≈ 3 steps). The number of Monte Carlo runs is set by `SPREADING_RUNS` in `.env`. Higher values increase precision but scale linearly with runtime.

**Computational cost:** O(runs × N × mean outbreak size) per export. For a 500-node network with 200 runs, expect 10–60 seconds depending on network density.

**In practice:** use `SPREADING` to find channels whose structural position in the citation graph makes them efficient propagators — independent of their raw follower count or message volume. A channel with spreading efficiency 0.3 seeds processes that eventually reach 30% of the network on average.

**Example:** a mid-tier channel with few followers and modest PageRank turns out to bridge three large ideological clusters. Its spreading efficiency is 0.45 — higher than several prominent channels — because information starting there can flow into all three clusters rather than circulating within one. Amplification factor measures how much it was forwarded; spreading efficiency measures how far its information can reach.

---

### Bridging centrality

Bridging centrality is a composite measure that combines two independent signals: how often a channel sits on the shortest paths between other channels (betweenness), and how diverse the community membership of its immediate neighbours is (Shannon entropy). The final score is the product of the two. A channel scores high only if it is both structurally central *and* community-diverse — that is, it sits on important paths *and* those paths cross ideological or topical boundaries.

The measure is based on the multi-dimensional bridging metric introduced by Ranka et al. (2024) in a study of Telegram disinformation networks, where removal of the top bridge nodes produced a 33% rise in the number of disconnected communities. The implementation in Pulpit computes betweenness centrality on the weighted graph, then for each node accumulates the edge weights to neighbours grouped by their community assignment, and derives the Shannon entropy H = −Σ p_i · ln(p_i) over those proportions. Nodes whose neighbours all belong to the same community score zero on entropy regardless of their betweenness; only channels that actively bridge distinct communities receive a non-zero bridging score.

The community basis for the entropy calculation is set by the strategy name in parentheses — for example `BRIDGING(LOUVAIN)` uses the Louvain partition. When no strategy is specified (bare `BRIDGING`), `LEIDEN` is used by default. The chosen strategy must also appear in `COMMUNITY_STRATEGIES` so that the partition is computed before bridging centrality is applied. Bridging centrality is most meaningful when the community basis reflects substantive groupings — either the manually defined `ORGANIZATION` communities or an algorithmically detected partition that captures real ideological structure.

**In practice:** bridging centrality fills a gap left by betweenness alone. A channel can rank highly on betweenness simply because it sits in a densely connected region of the network, even if all its neighbours belong to the same ideological cluster. Bridging centrality penalises that: the entropy factor discounts intra-community connectors and elevates genuine cross-community bridges. It is particularly useful for identifying channels that actively mediate between otherwise separate ecosystems — mainstream and fringe, domestic and foreign, one political movement and another.

**Example:** consider two channels with identical betweenness scores. The first connects channels that all belong to the same nationalist bloc; the second connects channels from four distinct communities — nationalist, religious conservative, mainstream right, and state media. Standard betweenness ranks them equal. Bridging centrality gives the second channel a substantially higher score, identifying it as the more strategically significant node for understanding how narratives migrate across the broader information ecosystem. In empirical studies of Telegram networks, these bridge nodes have proven to be disproportionately important: disrupting them fragments the network far more than their betweenness alone would suggest.

---

## Community detection strategies

A community detection strategy divides the network into groups (communities) of channels that are more densely connected to each other than to the rest of the network. Each strategy uses a different definition of what "connected" means, and reveals a different structural layer of the same data.

Multiple strategies can be computed simultaneously and switched between in the graph viewer.

---

### Organization

The simplest strategy: communities are defined by the **Organizations** you have created in the admin interface. Each organization corresponds to one community, and its color comes directly from the color you assigned in the admin.

**In practice:** this is the most interpretable strategy because the groupings reflect your own domain knowledge. You decide what the categories are — by political orientation, country, topic, funding source, or any other criterion. The graph then shows how your categories relate spatially: are channels from the same organization clustered together? Do organizations form tight blocs or are they interspersed?

**Example:** you group channels into five organizations: far-right, mainstream right, centrist, left, and state media. The resulting map shows that far-right and mainstream right channels are adjacent and heavily cross-referenced, while state media channels form an isolated cluster with few outbound connections to the others — suggesting that official outlets are cited but do not cite back.

---

### Louvain

An automatic algorithm that maximises **modularity** — a measure of how much more densely channels are connected within a group compared to what you would expect by chance. It requires no prior knowledge of the communities and produces no fixed number of groups: the algorithm finds however many communities best fit the data.

**In practice:** Louvain is the most commonly used community detection algorithm in network analysis. It is good at finding unexpected sub-structure — communities that cut across your predefined categories, or that split a group you thought was unified.

**Example:** you have grouped a set of channels under "populist right." Louvain may split them into two distinct communities: one centred on economic grievances (anti-immigration framed as a labour issue) and one centred on cultural identity (language, religion, tradition). The cross-referencing patterns reveal that these two sub-movements are more internally coherent than their shared political label suggests, and that a handful of channels act as bridges between them.

---

### Leiden

Leiden is a refinement of the Louvain algorithm that addresses one of its known weaknesses: Louvain can produce communities that are internally disconnected — where some nodes are loosely attached to a group they do not actually belong in. Leiden adds a local refinement phase after each merge step, breaking apart poorly integrated communities and reassigning nodes until every community is guaranteed to be well-connected internally. Like `LOUVAIN`, it operates on a **symmetrized** (undirected) view of the graph, so an edge A→B and an edge B→A are treated as equivalent. Use `LEIDEN_DIRECTED` when citation direction matters.

**In practice:** Leiden tends to produce sharper, more cohesive communities than Louvain, particularly in larger or noisier networks. The communities it finds are not just modular — they are structurally compact. It is a good default choice when Louvain's results feel fragmented or include suspiciously large catch-all communities.

**Example:** in a network where a mainstream news aggregator forwards content from dozens of ideologically diverse channels, Louvain may lump several distinct sub-movements into a single broad community anchored by that aggregator. Leiden's refinement step will pull apart these loosely connected sub-groups, revealing the underlying ideological clusters that the aggregator happens to span.

---

### Leiden (directed)

`LEIDEN_DIRECTED` runs the same Leiden optimisation as `LEIDEN` but with a **directed null model** (Leicht & Newman 2008). Standard modularity partitions assume that, by chance, edges form in proportion to total degree. The directed version refines this: the expected weight of an edge from channel A to channel B is proportional to A's **out-degree** multiplied by B's **in-degree**, divided by the total edge mass. A channel that cites many others (high out-degree) but is rarely cited back (low in-degree) contributes differently to the null model than one that is heavily cited without citing back, producing communities that reflect asymmetric citation roles.

**In practice:** use `LEIDEN_DIRECTED` when the distinction between who cites and who is cited matters for your research question. In political Telegram networks, where direction carries semantic weight — amplification flows from small channels toward influential ones — the directed null model tends to produce communities that align better with observed information flow than the symmetric alternative. Communities found by `LEIDEN_DIRECTED` can differ meaningfully from `LEIDEN` when the network contains strong asymmetries (hub-and-spoke structures, one-way amplifiers, or coordinated source channels that are cited far more often than they cite back).

**Example:** a cluster of regional nationalist channels all cite a single national aggregator but are never cited by it. Under standard Leiden they may be merged with the aggregator because the undirected edge density is high. With the directed null model the asymmetry is penalised: the aggregator's high in-degree inflates the expected citations toward it, so receiving many citations from the cluster is less surprising — and the cluster is more likely to be split away as its own community.

---

### K-core (k-shell decomposition)

K-core peels the network like an onion. It repeatedly removes the least-connected nodes, exposing progressively denser cores. The **innermost core** (displayed as community 1 in Pulpit) contains only channels that are all mutually connected to each other above a certain threshold — the tightest, most integrated nucleus of the network. Outer shells contain channels that are connected to the core but not tightly enough to be part of it.

**In practice:** k-core is uniquely useful for identifying the **ideological engine** of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating. Unlike Louvain, k-core does not split the network into peer communities; it reveals hierarchy and centrality.

**Example:** in a disinformation network of 300 channels, k-core decomposition may reveal an innermost core of just eight channels. These eight all forward each other regularly, share a consistent narrative frame, and are the first to publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors. The outer shells may be large and visible, but the core is where the content originates.

---

### Infomap

Infomap uses **information theory** to find communities based on how a random walk moves through the network. Channels end up in the same community if information — modelled as a random walker following edges — tends to circulate within that group rather than escaping to the rest of the network. A community in Infomap is essentially a **trap**: once you enter it, you tend to stay.

**In practice:** Infomap is the best strategy for identifying genuine echo chambers. A group of channels where content circulates in a closed loop — forwarding each other, rarely linking outside — will be detected as a single community regardless of how the channels are superficially categorised. It reveals functional insularity rather than just topical similarity.

**Example:** a cluster of regional separatist channels may look, from their content, like a loose collection of locally focused outlets. Infomap reveals that they form a tight closed loop: content produced by any one of them propagates rapidly through the others and almost never reaches the mainstream political channels in the network. They are not merely thematically similar — they are structurally isolated, constituting a self-contained information environment.

---

### Weakly Connected Components (WEAKCC)

Two channels belong to the same weakly connected component if there is a path between them **ignoring edge direction** — that is, if you can travel from one to the other by following forwards or references in either direction.

**In practice:** WEAKCC reveals the **broadest structural islands** in the network. Channels in different components have no relationship at all — they are genuinely isolated from each other. Within a single component, channels are at least indirectly linked, even if the relationship is asymmetric (A references B, but B never references A). This is the coarsest possible partition: most real-world networks collapse into one or a few large components with many small satellite islands.

**Example:** a monitoring project covering two politically unrelated media ecosystems — say, domestic far-right channels and foreign-language diaspora channels — may produce a network where these two ecosystems form separate weakly connected components, with no cross-referencing links between them. WEAKCC makes this structural disconnection immediately visible.

---

### Strongly Connected Components (STRONGCC)

Two channels belong to the same strongly connected component if there is a **directed path in both directions** between them — A can reach B and B can reach A by following the actual direction of forwards and references.

**In practice:** STRONGCC reveals the **mutually reinforcing cores** of the network. A large SCC is a group of channels that all ultimately cite each other in a closed directed loop — a genuine echo chamber in the strictest sense. Channels outside the large SCC either feed into it (they are cited but do not cite back) or drain from it (they amplify but are not amplified). In most real-world networks, STRONGCC produces one or a few large components and many singleton components (isolated nodes or channels with only one-way connections).

**Example:** in a disinformation campaign, the coordinating accounts may form a large SCC — they all repost each other in a deliberate cycle to create the appearance of organic consensus. Downstream amplifier channels, which forward the content but are never referenced back, form singletons or small components. STRONGCC lets you distinguish between the coordinated nucleus and the unwitting (or witting) amplifiers at the periphery.

---

### Leiden CPM (coarse and fine)

`LEIDEN_CPM_COARSE` and `LEIDEN_CPM_FINE` use the same Leiden optimisation engine as `LEIDEN` but replace the modularity objective with the **Constant Potts Model (CPM)** — Traag et al., *Physical Review E* 83, 016114 (2011).

The CPM quality function is:

> Q = Σ_c [ m_c − γ · C(n_c, 2) ]

where m_c is the number of internal edges in community c, n_c is its size, C(n, 2) = n(n−1)/2 is the number of possible pairs, and **γ** is the resolution parameter. A community is stable when its internal edge density p_c = m_c / C(n_c, 2) exceeds γ, independently of the community's size. This removes modularity's **resolution limit**: modularity cannot reliably detect communities smaller than roughly √(m/2) edges, whereas CPM can detect communities of any size as long as their internal density is above γ.

The two variants differ only in their default γ:

| Key | Default γ | Effect |
|:----|:--------|:-------|
| `LEIDEN_CPM_COARSE` | 0.01 | Few, large communities — groups channels that share even weak citation ties |
| `LEIDEN_CPM_FINE` | 0.05 | More, smaller communities — only groups channels with strong mutual citation density |

The resolution can be adjusted at export time with `--leiden-coarse-resolution` and `--leiden-fine-resolution`. Both strategies symmetrise the graph to undirected before optimisation (same as `LEIDEN`).

**In practice:** run both variants alongside `LEIDEN` to probe the network at multiple resolution scales. Communities that appear consistently across all three Leiden variants are the most structurally robust. Communities that appear only at fine resolution but not coarse correspond to tight local clusters embedded within larger blocs — useful for identifying the specific coordinated cores inside broader ideological movements. A partition that is stable across a range of γ values (revealed by running the two variants and comparing) represents genuine density structure in the data rather than a modularity artefact.

**Example:** a broad "populist right" community detected by standard Leiden splits under LEIDEN_CPM_FINE into three tighter sub-communities — economic nationalists, religious conservatives, and an anti-immigration activist cluster — revealing that what looked like a unified bloc is actually three distinct echo chambers that merely share some cross-referencing channels at the periphery.

---

### MCL (Markov Clustering)

*van Dongen, SIAM Journal on Matrix Analysis and Applications 22(4), 2000*

MCL treats the network as a Markov chain and iterates two operations on the stochastic adjacency matrix:

1. **Expansion**: raise the matrix to a power (default 2), spreading probability mass to multi-hop paths and mixing the random walk.
2. **Inflation**: raise each entry to the power r (the inflation parameter) and renormalise by column, amplifying strong connections and suppressing weak ones.

After convergence, the matrix is nearly block-diagonal: each block corresponds to a community. Higher inflation → more contrast → smaller, tighter communities. MCL works natively on the **directed weighted** graph without any symmetrisation, so the asymmetric forwarding patterns of Telegram channels are preserved end to end.

The inflation parameter r is set by `--mcl-inflation` (default 2.0). Typical values for political networks are 1.5–2.5 for coarse partitions and 2.5–4.0 for fine ones.

**In practice:** MCL is particularly effective at finding communities based on actual **circulation patterns** rather than on edge density alone. Two channels that forward each other heavily will be co-clustered even if they share few common neighbours — a pattern that modularity-based methods can miss. Because it operates on directed edges, MCL can detect asymmetric clusters: a set of channels that all forward from a common source but do not reference each other directly can still be grouped together if the resulting flow is sufficiently concentrated.

**Example:** five regional channels all heavily forward from a single national outlet and rarely cite channels outside that flow. Under Louvain or Leiden they may be dispersed across two or three communities because their pairwise edge density is low. MCL groups them together because the shared flow pattern — all five channels funnel traffic through the same source — produces a characteristic matrix block after inflation converges.

---

### Memory Infomap (second-order)

*Rosvall, Esquivel, Lancichinetti, West & Lambiotte, Nature Communications 5, 4630 (2014)*

Standard Infomap (`INFOMAP`) models information as a **first-order** random walk: where the walker goes next depends only on its current position. Memory Infomap extends this to a **second-order** walk: the next step also depends on where the walker came from. This is implemented via a **state network**:

- Each directed edge A→B in the original graph becomes a state node representing the context "currently at B, having arrived from A."
- A link from state (A→B) to state (B→C) represents continuing the walk along the path A→B→C, with weight proportional to the outgoing edge weight w(B→C).
- Channels with no incoming edges receive a virtual entry state so they participate in the clustering.

After the state network is built, the standard map equation is minimised on it. The community of a physical channel is determined by plurality vote across all its state nodes.

**In practice:** first-order Infomap can merge two channels into the same community simply because both are regularly cited by a third channel — even if the channels that cite A and the channels that cite B are completely different audiences. Memory Infomap separates them: the state nodes distinguish "arrived at A from the tech-commentary cluster" from "arrived at A from the military-commentary cluster", and if those two contexts behave differently in their onward flow, A's state nodes may be assigned to different communities. This is particularly relevant for Telegram forwarding chains, where the same channel may serve as a relay for multiple ideologically separate audiences simultaneously.

**Example:** a channel that aggregates content from both a pro-government cluster and an independent journalism cluster is assigned to one community by standard Infomap. Memory Infomap detects that readers arriving via the pro-government path tend to continue to other pro-government channels, while those arriving via the journalism path tend to continue to other independent outlets. The channel's state nodes are split between two communities, correctly identifying it as a bridge rather than a member of either bloc.

---

### Walktrap

*Pons & Latapy, Journal of Graph Algorithms and Applications 10(2), 2006*

Walktrap computes a **random-walk distance** between each pair of channels: two channels are considered similar if a random walk of fixed length (4 steps) starting at one tends to reach the same set of channels as a walk starting at the other. Ward's agglomerative clustering is then applied to these distances, building a complete **dendrogram** from the bottom up. The dendrogram is cut at the partition that maximises modularity.

The graph is symmetrised to undirected before clustering (same as `LEIDEN`). Edge weights are preserved throughout.

**In practice:** Walktrap's random-walk distance captures a different notion of similarity than modularity optimisation. Two channels that never reference each other directly can still be close in Walktrap distance if they are embedded in the same dense neighbourhood — because random walks starting at either tend to visit the same channels within a few hops. This makes Walktrap good at finding communities based on **shared context** rather than direct connections. It is particularly informative for networks with strong hub-and-spoke structure, where many channels share a common aggregator without referencing each other: modularity-based methods may split them across communities, while Walktrap groups them by their common neighbourhood.

The primary analytical output is the dendrogram itself: it shows which communities are most similar to each other and at what level of granularity sub-communities merge. In the current implementation the optimal cut (maximising modularity) is used automatically, but the hierarchy can be inspected to understand the multi-scale structure of the network.

**Example:** two communities detected by Leiden — a far-right cluster and a religious conservative cluster — appear as adjacent branches in the Walktrap dendrogram: they merge at a relatively low distance, indicating that the two clusters share a substantial common neighbourhood of cross-referencing channels. A third community, a state-media cluster, merges only at a much higher level, indicating structural distance. This hierarchical information is not visible in Leiden's flat partition.

---

## Community analysis views

Beyond listing per-community metrics, Pulpit generates two additional outputs that compare how different community detection strategies relate to your manual organisation groupings and to each other.

---

### Organisation × Community distribution

For each non-ORGANIZATION community detection strategy, the Community Statistics table includes a collapsible **Organisation × community distribution** panel with two cross-tabulation tables. Both tables share the same rows (organisations) and columns (detected community groups).

- **% of organisation nodes per community** (rows sum to 100%): for each organisation, what fraction of its channels ended up in each detected community? A row concentrated in one column means that organisation maps cleanly to a single algorithmic cluster; a spread-out row means its channels were split across multiple communities.
- **% of community nodes per organisation** (columns sum to 100%): for each detected community, what fraction of its channels comes from each organisation? A column dominated by one organisation means that community is organisation-pure; a mixed column means the algorithm grouped channels from different organisations together.

Columns are sorted so that each organisation's dominant community falls as close to a diagonal as possible (Hungarian algorithm assignment), making it easy to read the alignment at a glance. Communities where no organisation reaches the configured threshold (default 10%, set with `--community-distribution-threshold`) are hidden, and a note below the table reports how many were suppressed. The panel is only shown when the graph contains channels from more than one organisation.

**In practice:** compare the two tables to understand mismatches between your domain-knowledge groupings and the algorithm's output. A high-purity column (one organisation dominates a community) with a concentrated row (that organisation maps cleanly to that community) means strong alignment — the algorithm confirmed your manual partition. A spread-out row for one organisation paired with mixed columns across several communities signals that the algorithm sees structure *within* what you treated as a single bloc — a prompt to investigate whether the organisation should be split, or whether the algorithm is picking up noise.

---

### Consensus matrix

Generated with `structural_analysis --consensus-matrix` (or the matching checkbox in the Operations panel). Requires at least one non-ORGANIZATION community detection strategy to be active.

The consensus matrix (`consensus_matrix.html`) answers: **across all non-ORGANIZATION strategies, how consistently is each pair of channels placed in the same community?** For every pair of channels, the count of strategies that co-assign them to the same community is computed. The result is displayed as a lower-triangle balloon plot where:

- **Radius** grows with agreement count — the more strategies agree, the larger the circle.
- **Colour** shifts from blue (low agreement) to red (full agreement), making high-consensus pairs immediately visible.

Channels are sorted by plurality community assignment (the community a channel is most often placed in across all non-ORGANIZATION strategies) and then by name within each plurality group, so pairs from the same detected community tend to cluster along the diagonal.

A legend shows one circle per distinct agreement level (1/K … K/K, where K is the number of non-ORGANIZATION strategies). Hovering a cell shows a tooltip: "Channel A × Channel B: N/K partitions agree."

**In practice:** the consensus matrix reveals which channel groupings are robust and which are algorithm-dependent. A pair of channels with near-full agreement (large red balloon) is co-clustered by every algorithm you ran — that grouping is stable regardless of which detection method you trust. A pair with low agreement (small blue balloon or no balloon at all) is split differently by each algorithm, signalling that their community relationship is structurally ambiguous — the network evidence for placing them together or apart is genuinely weak. Pairs in the same manual Organisation that consistently appear in different algorithmic communities are candidates for review: the citation patterns may not support the grouping you assumed.

---

## Whole-network measures

Whole-network measures summarise the structure of the entire graph as a single number. They do not score individual channels; they characterise the network as a system. These values appear in the **Whole network** summary panel at the top of `community_table.html` and in the **Network Summary** sheet of `community_table.xlsx`.

The measures are organised into selectable groups controlled by `--network-stat-groups` (CLI) or the **Network stat groups** checkboxes in the Operations panel. Available groups: `SIZE`, `PATHS`, `COHESION`, `COMPONENTS`, `DEGCORRELATION`, `CENTRALIZATION`, `CONTENT`; default `ALL`. Deselecting `PATHS` and `COHESION` skips the expensive O(n·m) path-length and eigendecomposition calculations, which can be slow on large networks.

---

### Nodes and Edges

The raw count of channels (nodes) and directed connections (edges) in the graph. An edge from A to B represents that A has forwarded content from B or referenced B's username, weighted by frequency relative to A's total output. These counts depend on the `DRAW_DEAD_LEAVES` setting and any date range filters applied at export time.

---

### Density

The fraction of all possible directed edges that actually exist. For a directed graph with *n* nodes the maximum number of edges is *n(n−1)*; density is the observed edge count divided by that maximum.

**In practice:** density is low in almost all real-world networks, and political Telegram ecosystems are no exception — most channels do not directly reference most other channels. What matters is the comparative value across exports or sub-networks. A rising density over time suggests a network becoming more tightly integrated; a very low density combined with high betweenness scores for a few nodes indicates a sparse network held together by a small number of critical bridges.

---

### Reciprocity

The fraction of edges that are mutual — if A→B exists, does B→A also exist? Computed as (number of mutual pairs) / (total number of edges).

**In practice:** reciprocity measures how symmetric information exchange is in the network. A low reciprocity means the network is predominantly hierarchical: content flows from producers to distributors in one direction. A high reciprocity suggests peer-like mutual amplification — channels that all forward each other. In political networks, high reciprocity within a community often signals coordinated behaviour or tight ideological cohesion; very low reciprocity at the network level points to a clear source-amplifier hierarchy.

---

### Average Clustering Coefficient

For each node, the clustering coefficient measures how interconnected its immediate neighbours are — do the channels that reference A also reference each other? The average is taken over all nodes. Computed using NetworkX's `average_clustering` on the directed graph.

**In practice:** a high average clustering coefficient means the network is locally dense — channels tend to form tight triangles of mutual reference. This is characteristic of ideologically homogeneous clusters where everyone in a group cites everyone else. A low clustering coefficient indicates a more tree-like or hub-and-spoke structure, where channels funnel content toward central hubs without forming dense lateral connections.

---

### Average Path Length

The mean of the shortest directed path lengths between all reachable pairs of nodes. Because the full graph is often disconnected, this is computed on the **largest weakly connected component** (treated as undirected), and the footnote in the output marks it accordingly.

**In practice:** average path length is the network's "diameter in practice" — how many hops it takes, on average, for content to travel from one channel to another. Short average path lengths indicate a well-connected, small-world network where information can spread quickly; long paths suggest a fragmented ecosystem where content circulates only within isolated sub-networks.

---

### Diameter

The longest shortest path in the network — the maximum number of hops required to get from one node to another, computed on the largest weakly connected component (undirected).

**In practice:** the diameter sets an upper bound on how far a piece of content can travel. A small diameter (common in social networks) means any channel is reachable from any other within a few hops. A large diameter indicates a more linear or chain-like topology, where influence propagates slowly from one end of the network to the other.

---

### Directed Avg Path Length

The mean of all directed shortest-path distances between node pairs in the **largest strongly connected component** (SCC), following edge direction. Where path length and diameter use the undirected LCC, this metric respects the arrow of citation: the distance from A to B is the minimum number of directed hops needed to reach B from A, not just any path ignoring direction. A footnote (‡) is shown when the SCC is smaller than the full graph.

**In practice:** the directed path length answers the question *how many forwarding steps does content need to travel between two arbitrary channels?* A short directed path length means information can reach most channels quickly via the citation graph; a long one means propagation paths are stretched. Comparing this to the undirected average path length reveals how much directionality constrains information flow: a large gap between the two suggests many edges are one-way bridges that slow directed propagation significantly.

---

### Directed Diameter

The longest directed shortest path in the largest strongly connected component — the worst-case number of directed hops between any two reachable channels within that component.

**In practice:** the directed diameter bounds the delay for content to traverse the network's core along the citation graph. Because the SCC is by definition fully mutually reachable, a large directed diameter indicates that the core contains some long directed chains despite overall mutual connectivity.

---

### WCC count (Weakly Connected Components)

The total number of weakly connected components in the graph — groups of channels that are connected to each other by some path ignoring edge direction, with no path to channels outside the group.

**In practice:** most real-world networks have one large component and many small satellite islands. A high WCC count means the network is fragmented: many channels have no relationship at all to the main ecosystem. This is common in early-stage monitoring projects where the crawl has not yet discovered all the links, or in networks that genuinely consist of multiple unrelated ecosystems.

---

### Largest WCC fraction

The share of all nodes that belong to the single largest weakly connected component — a number between 0 and 1.

**In practice:** a value close to 1 means nearly all channels in the dataset are part of one connected ecosystem. A low value signals genuine fragmentation. This fraction is more informative than the raw WCC count because it tells you how much of the network is actually reachable from a typical node.

---

### SCC count (Strongly Connected Components)

The total number of strongly connected components — groups where every channel can reach every other channel by following directed edges.

**In practice:** in most directed networks, the SCC decomposition produces one large component (the "bow-tie core") and many singleton or small components. A high SCC count means few channels are involved in mutual directed loops. Channels outside the large SCC either feed into it (they are cited but do not cite back) or receive from it (they amplify without being amplified).

---

### Largest SCC fraction

The share of all nodes in the largest strongly connected component.

**In practice:** the largest SCC is the network's mutually reinforcing core — the set of channels that all ultimately cite each other through directed chains. A large SCC fraction indicates strong circular amplification at the heart of the network; a small fraction means influence is predominantly one-directional. Comparing this to the largest WCC fraction reveals the ratio of the network that is connected but asymmetric versus genuinely mutually reinforcing.

---

### Transitivity

The fraction of all connected triples in the graph that form closed triangles: triples where A→B, A→C, and B→C (or B→A, etc.) all exist. Also called the *global clustering coefficient*. Ranges from 0 (no triangles) to 1 (every triple is closed). Computed by NetworkX's `transitivity()` on the directed graph (Luce & Perry 1949; Watts & Strogatz 1998).

Unlike **Avg Clustering**, which averages the local clustering coefficient of each node separately, transitivity is a single global fraction that gives more weight to high-degree nodes — it answers *what fraction of all potential triangles in the network actually close?* rather than *how triangulated is the typical node's neighbourhood?* The two measures can diverge substantially in heterogeneous networks.

**In practice:** high transitivity means channels that both reference a third channel tend to reference each other as well — information loops are closed, ideas circulate within the same group, and the network is echo-chamber-like. Low transitivity indicates a more open, tree-like structure where connections radiate outward without looping back. Tracking transitivity alongside reciprocity reveals whether closure is symmetric (mutual citation loops) or hierarchical (closed chains in one direction).

---

### Global Efficiency

The mean reciprocal directed shortest-path length over all ordered pairs of nodes in the graph, following edge direction. Unreachable pairs contribute 0, so the measure handles disconnected graphs without restricting to a component. Ranges from 0 (every pair unreachable) to 1 (all pairs at distance 1). Defined by Latora & Marchiori (2001, *Physical Review Letters* 87).

*E = (1 / n(n−1)) × Σ_{i≠j} 1/d(i,j)*

**In practice:** global efficiency is the single most direct summary of how well information can flow across the entire network, including its disconnected parts. A high value means content can travel from any channel to most others in few hops; a low value means the network is fragmented or contains long detours. Because it averages *inverse* distances, it is dominated by short paths rather than long ones — a few very short connections raise the score substantially. Global efficiency is particularly useful for comparing network snapshots over time: a rising value indicates the ecosystem is becoming better integrated and information can spread more widely; a falling value signals fragmentation or the emergence of isolated sub-communities.

Note: computation requires all-pairs shortest paths (O(n*(n+m))); for large graphs (n > 3 000) this is the most expensive metric in the summary.

---

### Algebraic Connectivity (Fiedler value)

The second-smallest eigenvalue λ₂ of the graph Laplacian, computed on the undirected projection. This is the *Fiedler value* (Fiedler 1973, *Czechoslovak Mathematical Journal* 23). It equals 0 exactly when the graph is disconnected (multiple components each contribute a zero eigenvalue to the Laplacian). For connected graphs it is strictly positive; larger values indicate stronger, more robust cohesion. Approximated using the LOBPCG algorithm to avoid full eigendecomposition.

Two fundamental relationships make λ₂ particularly meaningful:
- **Cheeger inequality**: λ₂/2 ≤ edge expansion ≤ √(2λ₂). It lower-bounds the edge connectivity (minimum cut) of the graph.
- **Spectral gap**: λ₂ determines the mixing time of a random walk on the graph — how quickly a random walker forgets its starting position. Larger λ₂ → faster mixing → faster diffusion of information.

**In practice:** algebraic connectivity answers the question *how robustly cohesive is this network?* A value near 0 means the network is on the verge of fragmentation — a small number of edge removals would disconnect it. A high value means the network has many redundant pathways and is hard to partition. Unlike component counts (which detect existing disconnection), λ₂ detects *imminent* fragmentation: a network can have a single component yet be close to breaking apart, which the Fiedler value reveals while WCC count does not. Comparing λ₂ across time or across network snapshots reveals whether an information ecosystem is consolidating or developing structural fault lines.

---

### Degree CV (In-degree and Out-degree Coefficient of Variation)

The coefficient of variation (σ/μ) of the in-degree and out-degree distributions, computed separately. CV = standard deviation / mean; it normalises the spread of the distribution by its centre so that networks of different sizes or densities can be compared directly (Pastor-Satorras & Vespignani 2001, *Physical Review Letters* 86).

- **In-degree CV**: measures how unevenly citations are distributed. Low values mean all channels attract roughly equal attention; high values mean a few channels dominate incoming reference traffic (hub concentration).
- **Out-degree CV**: measures how unevenly forwarding/citing activity is distributed. Low values mean all channels are roughly equally active forwarders; high values mean a few channels are responsible for most of the network's references.

Scale-free networks (CV >> 1) have a few super-hubs that attract disproportionate traffic; random or lattice-like networks (CV ≈ 0) have uniform degree distributions.

**In practice:** degree CV is the quickest diagnostic for the presence of hub structure. In political Telegram networks, high in-degree CV reveals a few central channels that are cited by many others — potential amplification bottlenecks or agenda-setters. High out-degree CV reveals a few channels that drive most of the citation activity — potential coordinating accounts or news aggregators. Comparing in- and out-degree CV together characterises the asymmetry of influence: if in-degree CV >> out-degree CV, the network has a receptive core but a distributed citation base; the reverse indicates a few dominant forwarders pointing at many diverse targets.

---

### Directed degree assortativity (four coefficients)

Assortativity measures whether channels tend to connect to channels with similar degree. For directed graphs there are four variants, each a Pearson correlation coefficient computed over all edges:

| Coefficient | Source property | Target property |
| :---------- | :-------------- | :-------------- |
| **in→in**   | in-degree of source | in-degree of target |
| **in→out**  | in-degree of source | out-degree of target |
| **out→in**  | out-degree of source | in-degree of target |
| **out→out** | out-degree of source | out-degree of target |

Values range from −1 to +1. Positive values indicate homophily (high-degree nodes connect to high-degree nodes); negative values indicate disassortativity (high-degree nodes connect to low-degree nodes); values near zero indicate no systematic degree correlation.

**In practice:** most information networks are disassortative on in-degree — popular channels (high in-degree) tend to be referenced by channels that are themselves not widely referenced. This is the expected signature of a broadcast hierarchy. Strong disassortativity on out→in (high-out-degree channels point to low-in-degree targets) can indicate hub-and-spoke amplification of marginal content. Positive assortativity on out→out (active amplifiers reference other active amplifiers) may signal coordinated distribution rings. All four coefficients are reported as `N/A` when all nodes share the same degree value (zero variance).

---

### Mean Burt's Constraint

The average Burt's constraint score across all nodes. Ranges from 0 to 1. A low mean indicates a network with many structural holes and active brokerage — channels are not tightly embedded in closed cliques and information can flow through diverse paths. A high mean indicates a network dominated by dense, redundant clusters where most channels are firmly anchored within a single community.

**In practice:** mean constraint gives a single-number answer to the question *how open is this network's information architecture?* It complements density (which measures raw edge count) and clustering coefficient (which measures local triangles) by specifically characterising the brokerage structure. Two networks with identical density can have very different mean constraint values if one is organised as many loose bridges and the other as a few dense silos. Reported only when `BURTCONSTRAINT` is included in `NETWORK_MEASURES`.

---

### Content Originality

The fraction of all messages across interesting channels that are original (not forwarded from another channel): total non-forwarded messages / total messages. Ranges from 0 to 1.

**In practice:** this single number characterises the network as a production system. A value near 1.0 means the network is primarily a content-creation ecosystem; a value near 0.0 means it is primarily a redistribution and amplification machine. Tracking this over time or across different network snapshots reveals whether a political information ecosystem is becoming more or less dependent on external sources. Reported when `CONTENTORIGINALITY` is included in `NETWORK_MEASURES` or always if channel data is available.

---

### Amplification Ratio

The total number of forwards received by interesting channels, divided by the total number of messages published by those channels. Measures how many times, on average, each published message gets re-shared somewhere else in the network.

**In practice:** amplification ratio is the network's overall virality rate. A value of 0.2 means roughly one in five messages gets forwarded at least once; a value above 1.0 means the network produces more redistribution events than original publications. Combined with content originality, it reveals the two sides of information flow: how much is produced originally, and how hard each piece is pushed through the network by others. Reported when `AMPLIFICATION` is included in `NETWORK_MEASURES` or always if channel data is available.

---

### Freeman centralization (per measure)

For each configured node-level centrality measure, Freeman centralization summarises how unequally that centrality is distributed across the network. It is computed as:

> H = Σᵢ (C_max − Cᵢ) / [(n − 1) · C_max]

where C_max is the highest centrality score observed, Cᵢ is each node's score, and *n* is the number of nodes. The result is between 0 and 1. A value of 1 means all centrality is concentrated in a single node (star graph); a value of 0 means all nodes share the same centrality score (perfectly egalitarian). Reported as `N/A` when fewer than two nodes are present or when C_max is zero.

**In practice:** Freeman centralization transforms a node ranking into a single network-level verdict. Two networks with identical top-ranked channels can differ radically in centralization: one may have a dominant node that dwarfs all others, while the other has a gentle gradient. High PageRank centralization signals a network controlled by a small number of agenda-setting channels; low centralization indicates a more distributed information ecosystem. Centralization is computed for every measure active in `NETWORK_MEASURES`, so the output includes a separate score for PageRank centralization, betweenness centralization, and so on.

---

### Modularity (per strategy)

Modularity measures the quality of a community partition. For a given assignment of nodes to communities, it computes the fraction of edges that fall within communities minus the fraction that would fall within them in a random graph with the same degree sequence. Values range from −0.5 to 1; values above roughly 0.3 are conventionally considered evidence of meaningful community structure.

Modularity is reported for each active community detection strategy in `network_table.html` and `network_table.xlsx`.

**In practice:** modularity answers *how well does this partition fit the data?* A high modularity for the Leiden partition confirms that the algorithmic communities correspond to real density structure in the graph. Comparing modularity across strategies is informative: if the Organization partition (based on your domain knowledge) has a modularity close to that of Leiden, your manual categorisation captures most of the network's structural community organisation. If Leiden's modularity is substantially higher, there is structural community organisation that your categorisation does not capture.

---

### Inter-community Edge Ratio (per strategy)

The fraction of all directed edges whose source and target belong to different communities under a given partition. Formally: (edges crossing community boundaries) / (total edges). Range 0–1.

Reported alongside modularity in the strategy table in `network_table.html` and `network_table.xlsx`.

**In practice:** while modularity measures partition quality relative to a random null model, the inter-community edge ratio is a raw, directly interpretable quantity. A ratio near 0 means almost all links stay within communities — a tightly cohesive ecosystem where groups amplify each other internally. A ratio near 1 means most links cross boundaries — a fragmented or competitive structure where channels reference opponents or different circles more than their own. Comparing this ratio across snapshots or between networks reveals whether cross-community interaction is growing or shrinking over time. Comparing it across strategies tells you whether your manual Organisation partition produces more or less boundary-crossing than the algorithmic one.

---

### E-I Index (per community and strategy)

Krackhardt & Stern (1988) defined the E-I Index for a group as:

> E-I = (E − I) / (E + I)

where E = external ties (connections from community members to non-members) and I = internal ties (connections between community members). Range −1 (fully cohesive: no external ties) to +1 (fully competitive: no internal ties).

Per-community E-I is shown in `community_table.html` and `community_table.xlsx`. The **Mean E-I Index** in the strategy table (`network_table.html`) is a weighted average across communities, using each community's total connection volume as the weight.

**In practice:** the E-I index directly captures the cohesion-versus-competition distinction at the community level. A community with E-I ≈ −1 is self-referential: its members primarily cite and forward each other, consistent with a tight ideological or organisational cluster. A community with E-I ≈ +1 is outward-facing: its members mainly reference channels outside the group, which can indicate peripheral actors, cross-ideological bridges, or monitoring behaviour. The mean E-I across all communities summarises the overall balance: a network of tightly inward-looking groups has a strongly negative mean E-I; a network of loosely affiliated channels that mostly cite rivals or external sources has a near-zero or positive mean E-I.

Use E-I index together with reciprocity and inter-community edge ratio for a composite reading:
- **High reciprocity + negative mean E-I**: peer-like mutual amplification within cohesive camps.
- **Low reciprocity + positive mean E-I**: hierarchical cross-community citation, typical of competitive or monitoring dynamics.
- **Mixed**: intermediate communities with both internal amplification and active external engagement.

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Workflow](WORKFLOW.md) · [Configuration](CONFIGURATION.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

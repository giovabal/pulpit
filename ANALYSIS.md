# Network measures and community strategies

This document explains the analytical tools available in Pulpit — what they measure, how they work, and what they reveal when applied to political Telegram networks.

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

### Bridging centrality

Bridging centrality is a composite measure that combines two independent signals: how often a channel sits on the shortest paths between other channels (betweenness), and how diverse the community membership of its immediate neighbours is (Shannon entropy). The final score is the product of the two. A channel scores high only if it is both structurally central *and* community-diverse — that is, it sits on important paths *and* those paths cross ideological or topical boundaries.

The measure is based on the multi-dimensional bridging metric introduced by Ranka et al. (2024) in a study of Telegram disinformation networks, where removal of the top bridge nodes produced a 33% rise in the number of disconnected communities. The implementation in Pulpit computes betweenness centrality on the weighted graph, then for each node accumulates the edge weights to neighbours grouped by their community assignment, and derives the Shannon entropy H = −Σ p_i · ln(p_i) over those proportions. Nodes whose neighbours all belong to the same community score zero on entropy regardless of their betweenness; only channels that actively bridge distinct communities receive a non-zero bridging score.

The community basis used for the entropy calculation is the first strategy listed in `COMMUNITIES_STRATEGY`. Bridging centrality is therefore most meaningful when that strategy reflects substantive groupings — either the manually defined `ORGANIZATION` communities or an algorithmically detected partition that captures real ideological structure.

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

Leiden is a refinement of the Louvain algorithm that addresses one of its known weaknesses: Louvain can produce communities that are internally disconnected — where some nodes are loosely attached to a group they do not actually belong in. Leiden adds a local refinement phase after each merge step, breaking apart poorly integrated communities and reassigning nodes until every community is guaranteed to be well-connected internally.

**In practice:** Leiden tends to produce sharper, more cohesive communities than Louvain, particularly in larger or noisier networks. The communities it finds are not just modular — they are structurally compact. It is a good default choice when Louvain's results feel fragmented or include suspiciously large catch-all communities.

**Example:** in a network where a mainstream news aggregator forwards content from dozens of ideologically diverse channels, Louvain may lump several distinct sub-movements into a single broad community anchored by that aggregator. Leiden's refinement step will pull apart these loosely connected sub-groups, revealing the underlying ideological clusters that the aggregator happens to span.

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

← [README](README.md)

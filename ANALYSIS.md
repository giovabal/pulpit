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

### K-core (k-shell decomposition)

K-core peels the network like an onion. It repeatedly removes the least-connected nodes, exposing progressively denser cores. The **innermost core** (displayed as community 1 in Pulpit) contains only channels that are all mutually connected to each other above a certain threshold — the tightest, most integrated nucleus of the network. Outer shells contain channels that are connected to the core but not tightly enough to be part of it.

**In practice:** k-core is uniquely useful for identifying the **ideological engine** of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating. Unlike Louvain, k-core does not split the network into peer communities; it reveals hierarchy and centrality.

**Example:** in a disinformation network of 300 channels, k-core decomposition may reveal an innermost core of just eight channels. These eight all forward each other regularly, share a consistent narrative frame, and are the first to publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors. The outer shells may be large and visible, but the core is where the content originates.

---

### Infomap

Infomap uses **information theory** to find communities based on how a random walk moves through the network. Channels end up in the same community if information — modelled as a random walker following edges — tends to circulate within that group rather than escaping to the rest of the network. A community in Infomap is essentially a **trap**: once you enter it, you tend to stay.

**In practice:** Infomap is the best strategy for identifying genuine echo chambers. A group of channels where content circulates in a closed loop — forwarding each other, rarely linking outside — will be detected as a single community regardless of how the channels are superficially categorised. It reveals functional insularity rather than just topical similarity.

**Example:** a cluster of regional separatist channels may look, from their content, like a loose collection of locally focused outlets. Infomap reveals that they form a tight closed loop: content produced by any one of them propagates rapidly through the others and almost never reaches the mainstream political channels in the network. They are not merely thematically similar — they are structurally isolated, constituting a self-contained information environment.

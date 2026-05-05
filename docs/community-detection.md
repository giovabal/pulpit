# Community detection

Community detection divides a network into groups of channels that are more densely connected to each other than to the rest of the network. Each algorithm uses a different definition of what "connected" means, and reveals a different structural layer of the same data.

Imagine you have a map of 400 channels. Community detection is the algorithm that automatically draws the borders between neighbourhoods — without you having to decide in advance where the lines are.

Multiple strategies can be computed simultaneously and switched between in the graph viewer and table outputs.

<figure>
<img src="../webapp_engine/static/screenshot_00.jpg" alt="2D graph coloured by communities">
<figcaption><em>2D graph coloured by Leiden directed communities, ~600 nodes. Each colour cluster is one detected community.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Strategy | CLI key | Type | Preserves direction? |
| :------- | :------ | :--- | :------------------- |
| Organisation | `ORGANIZATION` | Domain knowledge | — |
| Louvain | `LOUVAIN` | Modularity | No |
| Leiden | `LEIDEN` | Modularity | No |
| Leiden (directed) | `LEIDEN_DIRECTED` | Modularity | Yes |
| Leiden CPM coarse | `LEIDEN_CPM_COARSE` | Constant Potts Model | No |
| Leiden CPM fine | `LEIDEN_CPM_FINE` | Constant Potts Model | No |
| K-core | `KCORE` | Structural hierarchy | No |
| Infomap | `INFOMAP` | Information-theoretic | Yes |
| Memory Infomap | `INFOMAP_MEMORY` | Information-theoretic (2nd order) | Yes |
| MCL | `MCL` | Flow-based | Yes |
| Walktrap | `WALKTRAP` | Random-walk distance | No |
| Weakly connected components | `WEAKCC` | Connectivity | No |
| Strongly connected components | `STRONGCC` | Connectivity | Yes |

---

## Organisation

*Communities are the Organisations you defined in the admin interface.*

This is the most interpretable strategy because the groupings reflect your own domain knowledge. You decide what the categories are — by political orientation, country, topic, funding source, or any other criterion. The resulting map shows how your categories relate spatially: are channels from the same organisation clustered together? Do organisations form tight blocs or are they interspersed?

**Example.** You group channels into five organisations: far-right, mainstream right, centrist, left, and state media. The map shows that far-right and mainstream right channels are adjacent and heavily cross-referenced, while state media channels form an isolated cluster with few outbound connections to the others — suggesting that official outlets are cited but do not cite back.

---

## Louvain

*Louvain finds unexpected sub-structure by maximising modularity — a measure of how much more densely channels are connected within a group than you would expect by chance.*

The algorithm produces no fixed number of groups: it finds however many communities best fit the data. It requires no prior knowledge and is the most widely used community detection algorithm in network analysis.

**Reference:** Blondel, V.D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E. (2008) "Fast unfolding of communities in large networks." *Journal of Statistical Mechanics* 2008(10). [doi:10.1088/1742-5468/2008/10/P10008](https://doi.org/10.1088/1742-5468/2008/10/P10008)

**In practice:** Louvain is good at finding unexpected sub-structure — communities that cut across your predefined categories, or that split a group you thought was unified.

**Example.** You have grouped channels under "populist right." Louvain may split them into two distinct communities: one centred on economic grievances and one centred on cultural identity. The cross-referencing patterns reveal that these two sub-movements are more internally coherent than their shared political label suggests.

---

## Leiden

*Leiden is a refinement of Louvain that guarantees each community is internally well-connected.*

Louvain can produce internally disconnected communities — nodes loosely attached to a group they don't actually belong in. Leiden adds a local refinement phase after each merge step, breaking apart poorly integrated communities and reassigning nodes until every community is guaranteed to be well-connected. Like `LOUVAIN`, it operates on a symmetrised (undirected) view of the graph. Use `LEIDEN_DIRECTED` when citation direction matters.

**Reference:** Traag, V.A., Waltman, L. & van Eck, N.J. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z)

**In practice:** Leiden produces sharper, more cohesive communities than Louvain, particularly in larger or noisier networks. It is a good default choice when Louvain's results feel fragmented or include suspiciously large catch-all communities.

---

## Leiden (directed)

*`LEIDEN_DIRECTED` runs the same Leiden optimisation but with a directed null model — it respects the asymmetry of citation direction.*

Standard modularity partitions assume edges form in proportion to total degree. The directed version refines this: the expected weight of an edge from channel A to channel B is proportional to A's **out-degree** multiplied by B's **in-degree**. A channel that cites many others but is rarely cited back contributes differently to the null model than one that is heavily cited without citing back.

**Reference:** Leicht, E.A. & Newman, M.E.J. (2008) "Community structure in directed networks." *Physical Review Letters* 100. [doi:10.1103/PhysRevLett.100.118703](https://doi.org/10.1103/PhysRevLett.100.118703)

**In practice:** use `LEIDEN_DIRECTED` when the distinction between who cites and who is cited matters for your research question. In political Telegram networks, where direction carries semantic weight — amplification flows from small channels toward influential ones — the directed null model tends to produce communities that align better with observed information flow.

**Example.** A cluster of regional nationalist channels all cite a single national aggregator but are never cited by it. Under standard Leiden they may be merged with the aggregator because undirected edge density is high. With the directed null model the asymmetry is penalised and the cluster is more likely to be assigned its own community.

---

## Leiden CPM (coarse and fine)

*The Constant Potts Model replaces modularity's objective with a direct edge-density threshold — removing the "resolution limit" that prevents modularity from detecting small communities.*

The CPM quality function is:

> Q = Σ_c [ m_c − γ · C(n_c, 2) ]

where m_c is the number of internal edges in community c, n_c is its size, C(n,2) = n(n−1)/2 is the number of possible pairs, and γ is the resolution parameter. A community is stable when its internal edge density exceeds γ, independently of size. This removes modularity's resolution limit: modularity cannot reliably detect communities smaller than roughly √(m/2) edges, whereas CPM can detect communities of any size as long as their internal density is above γ.

**Reference:** Traag, V.A., Van Dooren, P. & Nesterov, Y. (2011) "Narrow scope for resolution-limit-free community detection." *Physical Review E* 83. [doi:10.1103/PhysRevE.83.016114](https://doi.org/10.1103/PhysRevE.83.016114)

| Key | Default γ | Effect |
|:----|:---------|:-------|
| `LEIDEN_CPM_COARSE` | 0.01 | Few, large communities — groups channels that share even weak citation ties |
| `LEIDEN_CPM_FINE` | 0.05 | More, smaller communities — only groups channels with strong mutual citation density |

Both can be adjusted at export time with `--leiden-coarse-resolution` and `--leiden-fine-resolution`.

**In practice:** run both alongside `LEIDEN` to probe the network at multiple resolution scales. Communities that appear consistently across all three Leiden variants are the most structurally robust. Communities appearing only at fine resolution are tight local clusters embedded within larger blocs — useful for identifying specific coordinated cores inside broader ideological movements.

---

## K-core

*K-core peels the network like an onion, revealing the tight inner nucleus versus the peripheral amplifiers.*

The algorithm repeatedly removes the least-connected nodes, exposing progressively denser cores. The innermost core (displayed as community 1) contains only channels that are all mutually connected to each other above a certain threshold. Outer shells contain channels that are connected to the core but not tightly enough to be part of it.

**Reference:** Seidman, S.B. (1983) "Network structure and minimum degree." *Social Networks* 5(3). [doi:10.1016/0378-8733(83)90028-X](https://doi.org/10.1016/0378-8733(83)90028-X)

**In practice:** k-core is uniquely useful for identifying the ideological engine of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating.

**Example.** In a disinformation network of 300 channels, k-core decomposition reveals an innermost core of just eight channels. These eight all forward each other regularly, share a consistent narrative frame, and publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors.

---

## Infomap

*Infomap finds communities by detecting where information circulates in closed loops rather than escaping — it identifies genuine echo chambers.*

Infomap uses information theory to find communities based on how a random walk moves through the network. Channels end up in the same community if information — modelled as a random walker following edges — tends to circulate within that group rather than escaping to the rest of the network. A community in Infomap is essentially a trap: once you enter it, you tend to stay.

**Reference:** Rosvall, M. & Bergstrom, C.T. (2008) "Maps of random walks on complex networks reveal community structure." *PNAS* 105(4). [doi:10.1073/pnas.0706851105](https://doi.org/10.1073/pnas.0706851105)

**In practice:** Infomap is the best strategy for identifying genuine echo chambers. A group of channels where content circulates in a closed loop — forwarding each other, rarely linking outside — will be detected as a single community regardless of how the channels are superficially categorised.

**Example.** An NGO monitors anti-vaccine channels. Infomap reveals that 28 form a closed loop: content circulates through all 28 and almost never escapes. The E-I index for this community is −0.87 — nearly fully internal. A network comparison shows this tightened from −0.72 to −0.87 over six months after a vaccine rollout.

---

## Memory Infomap (second-order)

*Memory Infomap detects context-dependent flow communities: where you came from changes where you go.*

Standard Infomap models information as a first-order random walk — the next step depends only on the current position. Memory Infomap extends this to a second-order walk: the next step also depends on where the walker came from. This is implemented via a state network where each directed edge A→B becomes a state node representing "currently at B, having arrived from A."

**Reference:** Rosvall, M., Esquivel, A.V., Lancichinetti, A., West, J.D. & Lambiotte, R. (2014) "Memory in network flows and its effects on spreading dynamics and community detection." *Nature Communications* 5. [doi:10.1038/ncomms5630](https://doi.org/10.1038/ncomms5630)

**In practice:** first-order Infomap can merge two channels into the same community simply because both are regularly cited by a third channel — even if the channels that cite A and those that cite B are completely different audiences. Memory Infomap separates them by distinguishing the arrival context.

**Example.** A channel aggregates content from both a pro-government cluster and an independent journalism cluster. Standard Infomap assigns it to one community. Memory Infomap detects that readers arriving via the pro-government path continue to other pro-government channels, while those arriving via the journalism path continue to other independent outlets. The channel's state nodes are split between two communities, correctly identifying it as a bridge.

---

## MCL (Markov Clustering)

*MCL detects communities based on actual circulation patterns in the directed graph — without any symmetrisation.*

MCL treats the network as a Markov chain and iterates two operations on the stochastic adjacency matrix: expansion (spreading probability mass to multi-hop paths) and inflation (amplifying strong connections, suppressing weak ones). After convergence, the matrix is nearly block-diagonal — each block corresponds to a community. MCL works natively on the directed weighted graph without symmetrisation, preserving the asymmetric forwarding patterns of Telegram channels.

The inflation parameter r is set by `--mcl-inflation` (default 2.0). Higher values produce smaller, tighter communities.

**Reference:** van Dongen, S. (2000) "Graph clustering by flow simulation." *SIAM Journal on Matrix Analysis* 22(4). [doi:10.1137/040608635](https://doi.org/10.1137/040608635)

**In practice:** MCL is particularly effective when two channels forward each other heavily even if they share few common neighbours — a pattern that modularity-based methods can miss.

**Example.** Five regional channels all heavily forward from a single national outlet and rarely cite channels outside that flow. Under Louvain they may be dispersed across two or three communities because their pairwise edge density is low. MCL groups them together because the shared flow pattern produces a characteristic matrix block after inflation converges.

---

## Walktrap

*Walktrap groups channels by shared neighbourhood context — two channels without direct connections can still be close if they are embedded in the same dense local area.*

Walktrap computes a random-walk distance between each pair of channels: two channels are considered similar if a random walk of fixed length (4 steps) starting at one tends to visit the same channels as a walk from the other. Ward's agglomerative clustering is then applied to these distances, building a complete dendrogram. The dendrogram is cut at the partition that maximises modularity.

**Reference:** Pons, P. & Latapy, M. (2005) "Computing communities in large networks using random walks." *Lecture Notes in Computer Science* 3733. [doi:10.1007/11569596_31](https://doi.org/10.1007/11569596_31)

**In practice:** the dendrogram is the primary analytical output — it shows which communities are most similar to each other and at what scale sub-communities merge. Walktrap is particularly informative for networks with strong hub-and-spoke structure: many channels sharing a common aggregator without referencing each other are grouped by their common neighbourhood rather than split by low pairwise connectivity.

**Example.** Two communities detected by Leiden — a far-right cluster and a religious conservative cluster — appear as adjacent branches in the Walktrap dendrogram, merging at a relatively low distance. A third community, a state-media cluster, merges only at a much higher level. This hierarchical information is invisible in Leiden's flat partition.

---

## Weakly Connected Components (WEAKCC)

*Two channels belong to the same weakly connected component if there is any path between them — ignoring edge direction.*

Most real-world networks collapse into one or a few large components with many small satellite islands. WEAKCC makes structural disconnection immediately visible.

**In practice:** WEAKCC reveals the broadest structural islands. Channels in different components have no relationship at all — they are genuinely isolated from each other. This is the coarsest possible partition.

**Example.** A monitoring project covering two politically unrelated media ecosystems — domestic far-right channels and foreign-language diaspora channels — produces a network where these two ecosystems form separate weakly connected components with no cross-referencing links. WEAKCC makes this structural disconnection immediately visible.

---

## Strongly Connected Components (STRONGCC)

*Two channels belong to the same strongly connected component only if there is a directed path in both directions — A can reach B and B can reach A by following the actual direction of forwards.*

STRONGCC reveals the mutually reinforcing cores. A large SCC is a group of channels that all ultimately cite each other in a closed directed loop — a genuine echo chamber in the strictest sense.

**In practice:** in most real-world networks, STRONGCC produces one or a few large components and many singletons (isolated nodes or channels with only one-way connections). It lets you distinguish between the coordinated nucleus and the amplifiers at the periphery.

**Example.** In a coordinated disinformation campaign, the coordinating accounts form a large SCC — they all repost each other in a deliberate cycle to create the appearance of organic consensus. Downstream amplifier channels, which forward the content but are never referenced back, form singletons or small components. STRONGCC distinguishes the coordinated nucleus from the unwitting amplifiers.

---

## Cross-strategy analysis

<figure>
<img src="../webapp_engine/static/screenshot_03.jpg" alt="Community table">
<figcaption><em>Community table: structural metrics per community for each detection strategy side by side.</em></figcaption>
</figure>
<br>

### Organisation × community distribution

For each non-ORGANIZATION strategy, the community table includes a collapsible **Organisation × community distribution** panel with two cross-tabulation tables:

- **% of organisation channels per community** (rows sum to 100%): for each organisation, what fraction of its channels ended up in each detected community? A row concentrated in one column means that organisation maps cleanly to a single algorithmic cluster; a spread-out row means the organisation was split across multiple communities.
- **% of community channels per organisation** (columns sum to 100%): for each detected community, what fraction comes from each organisation? A column dominated by one organisation means the community is organisation-pure; a mixed column means the algorithm grouped channels from different organisations together.

Columns are sorted so that each organisation's dominant community falls as close to a diagonal as possible (Hungarian algorithm), making alignment easy to read at a glance.

**In practice:** compare the two tables to understand mismatches between your domain-knowledge groupings and the algorithm's output. High purity on both sides confirms the algorithm. A spread-out row for one organisation signals that the algorithm sees structure *within* what you treated as a single bloc — a prompt to investigate whether that organisation should be split.

### Consensus matrix

Generated with `--consensus-matrix` (requires at least two non-ORGANIZATION strategies active).

<figure>
<img src="images/community-consensus-matrix.png" alt="Community consensus matrix">
<figcaption><em>Consensus matrix: larger red circles indicate channel pairs co-assigned to the same community by more algorithms.</em></figcaption>
</figure>
<br>

> **[PLACEHOLDER: `images/community-consensus-matrix.png`]** Consensus matrix: larger red circles indicate channel pairs co-assigned to the same community by more algorithms.

The consensus matrix answers: **across all non-ORGANIZATION strategies, how consistently is each pair of channels placed in the same community?** For every pair, the count of strategies that co-assign them is computed and displayed as a lower-triangle balloon plot:

- **Radius** grows with agreement count
- **Colour** shifts from blue (low agreement) to red (full agreement)

Channels are sorted by plurality community assignment so that pairs from the same detected community cluster along the diagonal.

**In practice:** the consensus matrix reveals which groupings are robust and which are algorithm-dependent. A pair of channels with near-full agreement (large red balloon) is co-clustered by every algorithm — that grouping is stable regardless of which method you trust. A pair with low agreement is structurally ambiguous: the network evidence for placing them together or apart is genuinely weak. Pairs in the same manual Organisation that consistently appear in different algorithmic communities are candidates for review.

---

## Choosing a strategy

| Research goal | Recommended strategy |
| :------------ | :------------------- |
| Use your own domain knowledge as the baseline | `ORGANIZATION` |
| Find all community structure, no prior knowledge | `LEIDEN` or `LEIDEN_DIRECTED` |
| Direction of citation matters | `LEIDEN_DIRECTED`, `MCL`, `INFOMAP` |
| Identify echo chambers and information traps | `INFOMAP` |
| Detect context-dependent flows | `INFOMAP_MEMORY` |
| Find the ideological core vs. periphery | `KCORE` |
| Probe at multiple granularities | `LEIDEN` + `LEIDEN_CPM_COARSE` + `LEIDEN_CPM_FINE` |
| Detect coordinated circular amplification | `STRONGCC` |
| Find isolated sub-ecosystems | `WEAKCC` |
| Compare algorithms for robustness | `ALL` + `--consensus-matrix` |

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

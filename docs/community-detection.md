# Community detection

Community detection divides a network into groups of channels that are more densely connected to each other than to the rest of the network. Each algorithm uses a different definition of what "connected" means, and reveals a different structural layer of the same data.

Imagine you have a map of 400 channels. Community detection is the algorithm that automatically draws the borders between neighbourhoods — without you having to decide in advance where the lines are.

Multiple strategies can be computed simultaneously and switched between in the graph viewer and table outputs.

<figure>
<img src="../webapp_engine/static/screenshot_00.jpg" alt="2D graph coloured by communities">
<figcaption><em>2D graph coloured by Leiden directed communities, print layout Each colour cluster is one detected community.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Strategy | CLI key | Type | Preserves direction? |
| :------- | :------ | :--- | :------------------- |
| Organization | `ORGANIZATION` | Domain knowledge | — |
| Louvain | `LOUVAIN` | Modularity | No |
| Label propagation | `LABELPROPAGATION` | Label consensus | No |
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

## Organization

*Communities are the Organizations you defined in the admin interface.*

This is the most interpretable strategy because the groupings reflect your own domain knowledge. You decide what the categories are — by political orientation, country, topic, funding source, or any other criterion. The resulting map shows how your categories relate spatially: are channels from the same organization clustered together? Do organizations form tight blocs or are they interspersed?

**Example.** You group channels into five organizations: far-right, mainstream right, centrist, left, and state media. The map shows that far-right and mainstream right channels are adjacent and heavily cross-referenced, while state media channels form an isolated cluster with few outbound connections to the others — suggesting that official outlets are cited but do not cite back.

---

## Louvain

*Louvain partitions the network by greedy maximisation of modularity — a measure of how much more densely channels are connected within a group than would be expected at random.*

Modularity compares the observed weight of edges inside each community to what a degree-preserving null model would produce: `Q = (1/2m) Σ_ij [A_ij − k_i k_j / (2m)] δ(c_i, c_j)`. Louvain hill-climbs Q in two alternating phases — single-node moves between neighbouring communities, then aggregation of communities into super-nodes — until no further single move can improve the objective. It requires no prior knowledge, produces no fixed number of groups, and runs in near-linear time, which has made it the de-facto baseline for community detection in large networks.

Pulpit runs Louvain on the symmetrised view of the citation graph: each pair of channels with reciprocal forwards is collapsed to a single undirected edge whose weight is the **sum** of the two directional weights (`w(u→v) + w(v→u)`). Edge weights are honoured, so the chosen `--edge-weight-strategy` does affect the partition — the unweighted case (`NONE`) and the weighted ones can disagree. The random seed is fixed at 0 so repeated exports of the same graph produce identical partitions.

Two well-known limitations are worth keeping in mind. First, modularity has a **resolution limit** (Fortunato & Barthélemy 2007): communities smaller than roughly √(m/2) edges tend to be merged into larger ones even when they are well-separated structurally — run `LEIDEN_CPM_FINE` alongside Louvain to probe at higher resolution if you suspect this. Second, Louvain can produce **internally disconnected communities** because its node-move phase doesn't verify post-move connectivity — this is the defect that `LEIDEN` (Traag, Waltman & van Eck 2019) was designed to repair; prefer Leiden when partition quality matters more than the marginal runtime saving.

**References:**
- Blondel, V.D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E. (2008) "Fast unfolding of communities in large networks." *Journal of Statistical Mechanics* 2008(10). [doi:10.1088/1742-5468/2008/10/P10008](https://doi.org/10.1088/1742-5468/2008/10/P10008) — the algorithm.
- Newman, M.E.J. & Girvan, M. (2004) "Finding and evaluating community structure in networks." *Physical Review E* 69. [doi:10.1103/PhysRevE.69.026113](https://doi.org/10.1103/PhysRevE.69.026113) — definition of modularity, the objective Louvain optimises.
- Fortunato, S. & Barthélemy, M. (2007) "Resolution limit in community detection." *PNAS* 104(1). [doi:10.1073/pnas.0605965104](https://doi.org/10.1073/pnas.0605965104) — proof of the resolution limit that affects every modularity-based method.

**In practice:** Louvain is the cheapest way to surface unexpected sub-structure — communities that cut across analyst-defined `ORGANIZATION` groupings, or that split a category you treated as unified. In Pulpit it is most useful as a **structurally cheap baseline**: a partition that takes a fraction of a second to compute and that you can compare against `ORGANIZATION` (via the Organization × community panel) or against `LEIDEN` / `LEIDEN_DIRECTED` (via the consensus matrix). If a grouping appears under both Louvain and Leiden, it is likely a genuine structural feature; if Louvain merges what Leiden splits, the resolution limit is a plausible culprit; if a Louvain community looks suspiciously sprawling, it may be one of the internally-disconnected partitions that motivated the Leiden refinement.

**Example.** You have grouped 40 channels under the analyst label "populist right". Louvain returns two distinct communities of comparable size: one cluster forwards mostly economic-grievance content from a single national aggregator, the other cross-references religious-conservative outlets and identitarian channels. The Organization × community panel shows the analyst label spread across both detected communities; the consensus matrix shows the two halves are also separated by Leiden and Infomap. The split is structurally robust: the "populist right" label is, at this snapshot, two distinguishable sub-movements that happen to share a banner.

---

## Leiden

*Leiden refines Louvain by guaranteeing every detected community is internally well-connected — no node is left stranded in a group it does not actually belong to.*

The Leiden algorithm replaces Louvain's two-phase local-move + aggregation cycle with three phases: local moves, a **refinement** step that subdivides poorly connected communities, and aggregation. The refinement is the load-bearing addition: after each merge the algorithm verifies that every community is internally connected and reassigns nodes that fail the test. The result is a partition that maximises modularity *and* guarantees that, within each community, every node is reachable from every other along internal edges only — a property Louvain's hill-climb does not preserve.

Pulpit's `LEIDEN` runs the standard undirected modularity quality function `Q = (1/2m) Σᵢⱼ [Aᵢⱼ − kᵢkⱼ/(2m)] δ(σᵢ, σⱼ)` on the symmetrised view of the citation graph: each pair of channels with reciprocal forwards is collapsed to a single undirected edge whose weight is the **sum** of the two directional weights (`w(u→v) + w(v→u)`). Edge weights are honoured, so the chosen `--edge-weight-strategy` does affect the partition. The random seed is fixed at 0, so repeated exports of the same graph produce identical partitions. When citation direction is what carries the meaning, use [`LEIDEN_DIRECTED`](#leiden-directed) instead.

**References:**
- Traag, V.A., Waltman, L. & van Eck, N.J. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the Leiden refinement and the connectivity guarantee.
- Newman, M.E.J. & Girvan, M. (2004) "Finding and evaluating community structure in networks." *Physical Review E* 69, 026113. [doi:10.1103/PhysRevE.69.026113](https://doi.org/10.1103/PhysRevE.69.026113) — the modularity objective Leiden optimises.

**In practice:** Leiden is the recommended default whenever you don't have a specific reason to honour citation direction. It produces sharper, more cohesive communities than `LOUVAIN` — particularly in larger or noisier networks where Louvain's internally-disconnected partitions become a concrete worry — and it is the reliable baseline against which `INFOMAP` (flow-based), `MCL` (matrix-based), and the CPM variants are compared in the consensus matrix and the Organization × community panel. When Leiden splits a category you treated as a single bloc, the network is telling you the bloc has internal substructure worth investigating.

**Example.** A researcher monitors 200 channels labelled in the admin interface as "national press". Leiden returns three communities of comparable size. The Organization × community panel shows the analyst label spread across all three. Inspection reveals one community is centred on a regional aggregator hub, another on foreign-correspondent outlets, and the third on opinion-style channels. The split is reproduced by Louvain, Infomap, and the consensus matrix — strong evidence that "national press" is, at this snapshot, three distinguishable sub-networks operating under one banner.

---

## Leiden (directed)

*`LEIDEN_DIRECTED` runs the same Leiden optimisation as [`LEIDEN`](#leiden), but with the directed null model — it respects the asymmetry of who cites whom.*

Standard modularity assumes edges form in proportion to total degree, so it cannot distinguish "A is widely cited" from "A widely cites others". The directed formulation of Leicht & Newman (2008) replaces the `kᵢkⱼ/(2m)` null term with `kᵢᵒᵘᵗ · kⱼⁱⁿ / m` — the expected weight of an edge from A to B is the product of A's out-degree and B's in-degree, not total degree squared. A channel that cites widely without being cited back, and a channel widely cited without citing back, contribute differently to the null and are therefore allowed to live in different communities even when their undirected edge density would have merged them.

Pulpit's `LEIDEN_DIRECTED` builds the igraph directly from the directed citation graph — no symmetrisation — and calls `leidenalg.ModularityVertexPartition`, which automatically applies the Leicht-Newman directed-modularity quality function on directed input. Edge weights are honoured, so the chosen `--edge-weight-strategy` shapes the partition. The Leiden refinement (the connectivity guarantee inherited from `LEIDEN`) still runs. The seed is fixed at 0 for reproducibility.

This is also the default community basis for the [Community-bridging measure](network-measures.md#community-bridging) and for the [`bridging` robustness attack](robustness-analysis.md) — both interpret communities through a directional brokerage lens that pairs naturally with the directed null model.

**References:**
- Leicht, E.A. & Newman, M.E.J. (2008) "Community structure in directed networks." *Physical Review Letters* 100, 118703. [doi:10.1103/PhysRevLett.100.118703](https://doi.org/10.1103/PhysRevLett.100.118703) — the directed modularity quality function.
- Traag, V.A., Waltman, L. & van Eck, N.J. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the Leiden refinement, the same one used by `LEIDEN`.

**In practice:** use `LEIDEN_DIRECTED` when the distinction between *who cites* and *who is cited* carries semantic weight — which it almost always does on Telegram political networks, where amplification flows asymmetrically from smaller channels toward influential sources. Picking `LEIDEN_DIRECTED` also keeps Pulpit's downstream chain — community-bridging measure, within-module-role classification, the brokerage robustness attack — consistent in their treatment of direction, since they all default to this same basis.

**Example.** A cluster of seven regional nationalist channels all forward content from a single national aggregator but are never cited by it. Under `LEIDEN` (undirected projection) the seven plus the aggregator are merged into one community because the undirected edge density is high. Under `LEIDEN_DIRECTED` the asymmetry of the citations is penalised by the directed null: the seven form their own community while the aggregator joins a separate group whose other members it cites symmetrically. The hub-and-spoke amplification pattern becomes visible at a glance — what looked like a single bloc is actually one broadcaster and seven amplifiers.

---

## Leiden CPM (coarse and fine)

*The Constant Potts Model swaps modularity's degree-based null for a direct edge-density threshold — communities are kept (or split) according to whether their internal density exceeds a chosen γ, which removes modularity's resolution limit.*

Modularity (the objective optimised by `LEIDEN` and `LOUVAIN`) is provably blind to communities smaller than roughly √(m/2) edges — the **resolution limit** of Fortunato & Barthélemy (2007). No matter how clear the sub-structure is, a modularity optimiser will merge sufficiently small communities into bigger ones. The Constant Potts Model (CPM) avoids this by switching to an absolute, size-independent criterion:

> Q = Σ_c [ m_c − γ · C(n_c, 2) ]

where `m_c` is the number of internal edges in community c (weighted when the graph is weighted), `n_c` its size, `C(n,2) = n(n−1)/2` the number of possible pairs, and γ a resolution parameter. A community is stable when its internal edge density exceeds γ, independently of size: small dense groups are preserved when γ is high enough; weakly bound clumps merge when γ is low enough.

Pulpit runs CPM through the same Leiden machinery as `LEIDEN` — same `leidenalg` backend, same W+Wᵀ undirected projection (reciprocal forwards collapsed to one edge whose weight is `w(u→v) + w(v→u)`), same connectivity refinement, same seed=0. Edge weights are honoured, so the chosen `--edge-weight-strategy` does affect the partition and also rescales the meaningful range of γ — denser-weight strategies (`TOTAL`, `NONE`) want larger γ than sparser fractional ones (`PARTIAL_REFERENCES`, `PARTIAL_MESSAGES`).

Two presets ship with Pulpit, chosen as sensible starting points for the fractional weights of the default `PARTIAL_REFERENCES` strategy:

| Key | Default γ | Effect |
|:----|:---------|:-------|
| `LEIDEN_CPM_COARSE` | 0.01 | Few, large communities — groups channels that share even weak citation ties |
| `LEIDEN_CPM_FINE` | 0.05 | More, smaller communities — only groups channels with strong mutual citation density |

Both can be tuned at export time via `--leiden-coarse-resolution` and `--leiden-fine-resolution`; tune γ upward when switching to `--edge-weight-strategy TOTAL` or `NONE`.

**References:**
- Traag, V.A., Van Dooren, P. & Nesterov, Y. (2011) "Narrow scope for resolution-limit-free community detection." *Physical Review E* 84, 016114. [doi:10.1103/PhysRevE.84.016114](https://doi.org/10.1103/PhysRevE.84.016114) — the CPM quality function and its resolution-limit-free property.
- Fortunato, S. & Barthélemy, M. (2007) "Resolution limit in community detection." *PNAS* 104(1). [doi:10.1073/pnas.0605965104](https://doi.org/10.1073/pnas.0605965104) — the resolution limit of modularity that motivates CPM.

**In practice:** run `LEIDEN`, `LEIDEN_CPM_COARSE` and `LEIDEN_CPM_FINE` side by side for a three-scale view of the same network. Communities that survive across all three are the most structurally robust — dense enough to pass the fine-resolution threshold *and* well-separated enough to surface under the modularity-based grouping. Communities appearing only at fine resolution are tight local cores embedded inside broader blocs — useful for identifying small coordinated nuclei within bigger ideological movements. The CPM variants are the right tool whenever you suspect modularity has merged sub-communities you can see by eye.

**Example.** A 600-channel anti-vaccine network is partitioned by `LEIDEN` into six communities. `LEIDEN_CPM_FINE` returns 14 — eight of which sit *inside* a single Leiden community and turn out, on inspection, to be language- or country-specific cores of coordinated activity (one Italian, one French, one Brazilian Portuguese, etc.). The Leiden partition revealed the broad movement; the CPM-fine partition revealed the operational coordination cells that share content within their language community before it crosses over to the others.

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

## Label propagation

*Label propagation finds communities by spreading labels through the network until each node carries the label held by the majority of its neighbours — no parameters, no matrix operations, near-linear time.*

Each node starts with a unique label. At every step, each node adopts the label that the largest number of its neighbours carry. This continues until no node would change its label on the next step; nodes sharing a label at convergence form a community. The NetworkX implementation uses the semi-synchronous variant (Cordasco & Gargano 2010), which partitions nodes into colour classes before each sweep to ensure the algorithm terminates and produces consistent results.

The graph is symmetrised to undirected before running. Edge weights are not used — all citation links are treated equally regardless of frequency.

**References:** Raghavan, U.N., Albert, R. & Kumara, S. (2007) "Near linear time algorithm to detect community structures in large-scale networks." *Physical Review E* 76(3). [doi:10.1103/PhysRevE.76.036106](https://doi.org/10.1103/PhysRevE.76.036106)
Cordasco, G. & Gargano, L. (2010) "Community detection via semi-synchronous label propagation algorithms." *IEEE BASNA*. [doi:10.1109/BASNA.2010.5730298](https://doi.org/10.1109/BASNA.2010.5730298)

**In practice:** label propagation is the fastest algorithm in the set and requires no tuning. Its main value is as a parameter-free baseline: if a grouping appears in both Leiden and label propagation, it is unlikely to be an artefact of algorithmic choices or resolution settings. It is also the best option for very large graphs where Infomap, MCL, or Walktrap are too slow. The main limitation is that it ignores edge weights and direction, so it can miss fine-grained structure that frequency-sensitive algorithms (Leiden, MCL) detect.

**Example.** A monitoring project collects 1,200 channels. Leiden directed takes several minutes; label propagation runs in under a second and produces a coarser partition with 8 communities instead of 14. Six of those eight communities align well with Leiden's output. The two that don't — a mixed cluster merging two Leiden communities — are exactly where the two Leiden communities share many bidirectional links, and edge weights are what separates them. The comparison reveals that the two-community split is weight-driven, not structural.

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

### Organization × community distribution

For each non-ORGANIZATION strategy, the community table includes a collapsible **Organization × community distribution** panel with two cross-tabulation tables:

- **% of organization channels per community** (rows sum to 100%): for each organization, what fraction of its channels ended up in each detected community? A row concentrated in one column means that organization maps cleanly to a single algorithmic cluster; a spread-out row means the organization was split across multiple communities.
- **% of community channels per organization** (columns sum to 100%): for each detected community, what fraction comes from each organization? A column dominated by one organization means the community is organization-pure; a mixed column means the algorithm grouped channels from different organizations together.

Columns are sorted so that each organization's dominant community falls as close to a diagonal as possible (Hungarian algorithm), making alignment easy to read at a glance.

**In practice:** compare the two tables to understand mismatches between your domain-knowledge groupings and the algorithm's output. High purity on both sides confirms the algorithm. A spread-out row for one organization signals that the algorithm sees structure *within* what you treated as a single bloc — a prompt to investigate whether that organization should be split.

### Consensus matrix

Generated with `--consensus-matrix` (requires at least two non-ORGANIZATION strategies active).

<figure>
<img src="../webapp_engine/static/screenshot_14.jpg" alt="Community consensus matrix">
<figcaption><em>Consensus matrix: larger red circles indicate channel pairs co-assigned to the same community by more algorithms.</em></figcaption>
</figure>
<br>

The consensus matrix answers: **across all non-ORGANIZATION strategies, how consistently is each pair of channels placed in the same community?** For every pair, the count of strategies that co-assign them is computed and displayed as a lower-triangle balloon plot:

- **Radius** grows with agreement count
- **Colour** shifts from blue (low agreement) to red (full agreement)

Channels are sorted by plurality community assignment so that pairs from the same detected community cluster along the diagonal.

**In practice:** the consensus matrix reveals which groupings are robust and which are algorithm-dependent. A pair of channels with near-full agreement (large red balloon) is co-clustered by every algorithm — that grouping is stable regardless of which method you trust. A pair with low agreement is structurally ambiguous: the network evidence for placing them together or apart is genuinely weak. Pairs in the same manual Organization that consistently appear in different algorithmic communities are candidates for review.

---

## Choosing a strategy

| Research goal | Recommended strategy |
| :------------ | :------------------- |
| Use your own domain knowledge as the baseline | `ORGANIZATION` |
| Find all community structure, no prior knowledge | `LEIDEN` or `LEIDEN_DIRECTED` |
| Fast parameter-free baseline for large graphs | `LABELPROPAGATION` |
| Direction of citation matters | `LEIDEN_DIRECTED`, `MCL`, `INFOMAP` |
| Identify echo chambers and information traps | `INFOMAP` |
| Detect context-dependent flows | `INFOMAP_MEMORY` |
| Find the ideological core vs. periphery | `KCORE` |
| Probe at multiple granularities | `LEIDEN` + `LEIDEN_CPM_COARSE` + `LEIDEN_CPM_FINE` |
| Detect coordinated circular amplification | `STRONGCC` |
| Find isolated sub-ecosystems | `WEAKCC` |
| Compare algorithms for robustness | `ALL` + `--consensus-matrix` |

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

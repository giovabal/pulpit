# Whole-network statistics

If network measures score individual channels, whole-network statistics score the ecosystem as a whole. They do not rank individual channels; they characterise the network as a system.

"Reciprocity" answers: is this an ecosystem of peers who cite each other, or a hierarchy where content flows one way from producers to amplifiers? "Algebraic Connectivity" answers: how many edges would need to be removed before the network fragments? These are questions about the information environment itself, not about any single actor within it.

<figure>
<img src="../webapp_engine/static/screenshot_04.jpg" alt="Whole-network statistics table">
<figcaption><em>Whole-network statistics table: density, reciprocity, clustering, Freeman centralisation, E-I index, and more.</em></figcaption>
</figure>
<br>

---

## Metric groups

Metrics are organized into selectable groups. Controlled via `--network-stat-groups` on the CLI, or the checkboxes in the Operations panel.

| Group | Metrics | Cost |
| :---- | :------ | :--- |
| `SIZE` | Nodes, Edges, Density | Low |
| `PATHS` | Reciprocity, Avg Clustering, Avg Path Length, Diameter, Directed variants | Medium–High |
| `COHESION` | Transitivity, Global Efficiency, Algebraic Connectivity, Degree CV | High |
| `COMPONENTS` | WCC count, Largest WCC, SCC count, Largest SCC | Low |
| `DEGCORRELATION` | Directed assortativity (4 coefficients) | Low |
| `CENTRALIZATION` | Freeman centralisation per measure, Mean Burt's Constraint | Low–Medium |
| `CONTENT` | Content Originality, Amplification Ratio | Low |
| `HOMOPHILY` | Per partition label group: assortativity, E-I against its expectation, inbreeding homophily and net-exporter index per label, label → label citation flows — all tested against label permutations | Low (seconds) |
| `SIGNIFICANCE` | z and p of the other selected groups' tie statistics against three random-graph baselines | High (minutes); **not included in `ALL`** |

> Deselect `PATHS` and `COHESION` to skip the expensive O(n·m) path-length and eigendecomposition calculations on large networks. `SIGNIFICANCE` must be named explicitly (`--network-stat-groups ALL,SIGNIFICANCE`); the panel's *All* button leaves it unticked.

---

## SIZE

### Nodes and Edges

The raw count of channels (nodes) and directed connections (edges) in the graph. An edge from A to B means A has forwarded content from B or referenced B's username, weighted by frequency relative to A's total output. These counts depend on the `DRAW_DEAD_LEAVES` setting and any date range filters applied at export time.

**Dead leaves.** With dead leaves drawn, a **Dead leaves (own citations not observed)** row counts them. A dead leaf is in the graph only because a monitored channel cited it; its own messages are never read, so its outgoing citations are unknown rather than absent. The statistics that read a channel's own citations — **Reciprocity**, **Average Clustering**, **Transitivity**, the **out-degree CV** and the **degree assortativity** coefficients — therefore describe the observed channels only (reciprocity on the subgraph among them, clustering and transitivity over the triangles centred on them, assortativity over the ties between them). Counting dead leaves would add one-way ties and zero out-degrees by construction. Path lengths, efficiency, components and density keep every node. Self-citations (`--self-references`) never enter these statistics either.

### Density

The fraction of all possible directed edges that actually exist. For a directed graph with *n* nodes, the maximum number of edges is *n(n−1)*; density is the observed edge count divided by that maximum.

**In practice:** density is low in almost all real-world networks. What matters is the comparative value across exports or sub-networks. A rising density over time suggests a network becoming more tightly integrated; a very low density combined with low Burt's-constraint scores for a few nodes indicates a sparse network held together by a small number of critical brokers.

---

## PATHS

> Path-based statistics appear in Pulpit only here, at the network level, as **shape descriptors** of the citation topology — how compact or fragmented the recorded web of attribution is — and they are best read comparatively, across exports or over time. No per-channel path measure exists (see [Measures → what this catalogue covers](network-measures.md#what-this-catalogue-covers)): under one-degree attribution a multi-hop path is a chain of attributions, not a route content travelled, so no individual channel is credited for sitting on one. Read "distance" below as *degrees of citation separation*, not as hops content takes.

### Average Path Length

The mean of the shortest path lengths between all reachable pairs of nodes, computed on the **largest weakly connected component** (treated as undirected).

**In practice:** average path length is the network's "diameter in practice" — the typical number of citation steps separating two channels. Short values indicate a compact, small-world citation topology; long values suggest a fragmented ecosystem of loosely connected sub-networks. Read it as compactness of the recorded structure, not as a transit time for content.

### Diameter

The longest shortest path in the network, computed on the largest weakly connected component (undirected).

**In practice:** the diameter is the network's span — the longest chain of citation separation it contains. A small diameter (common in social networks) means every channel sits within a few citation steps of every other.

### Directed Average Path Length

The mean of all directed shortest-path distances between node pairs in the **largest strongly connected component** (SCC), following edge direction. Where the undirected path length ignores direction, this metric measures separation when only the citation direction is followed.

**In practice:** comparing directed and undirected path lengths reveals how much directionality constrains the structure. A large gap means many links are one-way — channels that cite without being cited back — so the mutually-citing core is far smaller than the connected whole.

### Directed Diameter

The longest directed shortest path in the largest strongly connected component.

### Reciprocity

The fraction of edges that are mutual — if A→B exists, does B→A also exist? Computed as (number of mutual pairs) / (total number of edges), over the ties between observed channels (dead leaves and self-citations excluded — see [Dead leaves](#nodes-and-edges)).

**In practice:** reciprocity measures how symmetric information exchange is. A low reciprocity means the network is predominantly hierarchical: content flows from producers to distributors in one direction. A high reciprocity suggests peer-like mutual amplification. In political networks, high reciprocity within a community usually signals tight ideological cohesion; it is also a natural place to *look* for arranged mutual amplification, though the static graph alone cannot tell arrangement from affinity — that distinction lives in message-level timing, which the [coordination analysis](coordination-analysis.md) tests directly.

### Average Clustering Coefficient

For each channel, the clustering coefficient measures how interconnected its immediate neighbours are — do the channels that reference A also reference each other? The average is taken over all observed channels (every channel but the dead leaves).

**In practice:** a high average clustering coefficient means channels tend to form tight triangles of mutual reference — characteristic of ideologically homogeneous clusters. A low clustering coefficient indicates a more tree-like or hub-and-spoke structure.

---

## COHESION

### Transitivity

The fraction of all connected triples in the graph that form closed triangles — `3 × triangles / connected triples` — computed on the **undirected** projection (a tie in either direction connects two channels), so the value is comparable with the transitivity reported in the literature. Also called the global clustering coefficient. Unlike Avg Clustering (which averages each channel's local coefficient separately), transitivity is a global fraction that gives more weight to high-degree channels. With dead leaves drawn it counts the triples centred on observed channels.

*Correction (2026):* earlier releases computed it with NetworkX's `transitivity` on the directed graph, which only follows outgoing ties and so measured something narrower — how often two channels cited by the same channel cite each other (a directed 3-cycle scored 0). On one 313-channel export that read 0.225 where the global clustering coefficient is 0.386.

**References:** Newman, M.E.J. (2003) "The structure and function of complex networks." *SIAM Review* 45(2). [doi:10.1137/S003614450342480](https://doi.org/10.1137/S003614450342480); Watts, D.J. & Strogatz, S.H. (1998) "Collective dynamics of 'small-world' networks." *Nature* 393. [doi:10.1038/30918](https://doi.org/10.1038/30918)

**In practice:** high transitivity means channels that both reference a third channel tend to reference each other — information loops are closed and the network is echo-chamber-like. Low transitivity indicates a more open, tree-like structure.

### Global Efficiency

The mean reciprocal directed shortest-path length over all ordered pairs of channels, including disconnected pairs (which contribute 0). Ranges from 0 (no pairs reachable) to 1 (all pairs at distance 1).

*E = (1 / n(n−1)) × Σ_{i≠j} 1/d(i,j)*

**Reference:** Latora, V. & Marchiori, M. (2001) "Efficient behavior of small-world networks." *Physical Review Letters* 87. [doi:10.1103/PhysRevLett.87.198701](https://doi.org/10.1103/PhysRevLett.87.198701)

**In practice:** global efficiency is the single most direct one-number summary of how compact and integrated the citation topology is, disconnected parts included. A rising value over time indicates the ecosystem is becoming better integrated; a falling value signals fragmentation. Because it averages *inverse* distances, it is dominated by short paths rather than long ones.

> Note: computation requires all-pairs shortest paths (O(n·(n+m))); for large graphs (n > 3,000) this is the most expensive metric in the summary.

### Algebraic Connectivity (Fiedler value)

The second-smallest eigenvalue λ₂ of the graph Laplacian, computed on the undirected projection. This is the *Fiedler value* (Fiedler 1973). It equals 0 exactly when the graph is disconnected. For connected graphs it is strictly positive; larger values indicate stronger cohesion. Approximated using the trace-minimization algorithm (`tracemin_pcg`).

Two fundamental properties make λ₂ particularly meaningful:
- **Cheeger inequality:** λ₂/2 ≤ edge expansion ≤ √(2λ₂) — it lower-bounds the edge connectivity (minimum cut)
- **Spectral gap:** λ₂ determines the mixing time of a random walk — how quickly a random walker forgets its starting position. Larger λ₂ → faster mixing → a more integrated topology.

**In practice:** algebraic connectivity answers *how robustly cohesive is this network?* A value near 0 means the network is on the verge of fragmentation. Unlike component counts (which detect existing disconnection), λ₂ detects *imminent* fragmentation — a network can have a single component yet be close to breaking apart.

**Example.** Before a platform content-moderation wave: Fiedler value = 0.14. After: 0.03. The network is now one targeted removal away from splitting into disconnected fragments.

### Degree CV (In-degree and Out-degree Coefficient of Variation)

The coefficient of variation (σ/μ) of the in-degree and out-degree distributions. CV normalises the spread of the distribution by its centre, allowing networks of different sizes or densities to be compared directly. The out-degree CV runs over observed channels only: a dead leaf's out-degree is unknown, and counting it as 0 would inflate the spread.

**Reference:** Pastor-Satorras, R. & Vespignani, A. (2001) "Epidemic spreading in scale-free networks." *Physical Review Letters* 86. [doi:10.1103/PhysRevLett.86.3200](https://doi.org/10.1103/PhysRevLett.86.3200)

**In practice:** degree CV is the quickest diagnostic for the presence of hub structure. High in-degree CV reveals a few central channels cited by many others — potential amplification bottlenecks. High out-degree CV reveals a few channels driving most of the citation activity — a concentrated aggregator layer. Comparing in- and out-degree CV characterises the asymmetry of influence.

---

## COMPONENTS

### WCC count

The total number of weakly connected components. Most real-world networks have one large component and many small satellite islands. A high WCC count means the network is fragmented: many channels have no relationship at all to the main ecosystem.

### Largest WCC fraction

The share of all channels belonging to the single largest weakly connected component. A value close to 1 means nearly all channels are part of one connected ecosystem.

### SCC count

The total number of strongly connected components. In most directed networks, the SCC decomposition produces one large component (the "bow-tie core") and many singleton or small components.

### Largest SCC fraction

The share of all channels in the largest strongly connected component — the network's mutually reinforcing core. Comparing this to the Largest WCC fraction reveals the ratio of the network that is connected but asymmetric versus genuinely mutually reinforcing.

---

## DEGCORRELATION

### Directed degree assortativity (four coefficients)

Assortativity measures whether channels tend to connect to channels with similar degree. For directed graphs there are four Pearson correlation coefficients, computed over all edges between observed channels (a tie to a dead leaf would pair a degree with an unobserved out-degree):

| Coefficient | Source property | Target property |
| :---------- | :-------------- | :-------------- |
| **in→in** | in-degree of source | in-degree of target |
| **in→out** | in-degree of source | out-degree of target |
| **out→in** | out-degree of source | in-degree of target |
| **out→out** | out-degree of source | out-degree of target |

Values range from −1 (disassortative: high-degree nodes connect to low-degree nodes) to +1 (assortative: high-degree nodes connect to high-degree nodes).

**Reference:** Newman, M.E.J. (2003) "Mixing patterns in networks." *Physical Review E* 67. [doi:10.1103/PhysRevE.67.026126](https://doi.org/10.1103/PhysRevE.67.026126)

**In practice:** most information networks are disassortative on in-degree — popular channels (high in-degree) tend to be referenced by channels that are themselves not widely referenced. Strong disassortativity on out→in (high-out-degree channels point to low-in-degree targets) can indicate hub-and-spoke amplification of marginal content. Positive assortativity on out→out means the busiest citers tend to cite one another — a distribution layer that watches itself; whether by arrangement or by shared habit is a timing question the static graph does not settle.

---

## CENTRALIZATION

### Freeman centralisation (per measure)

For each configured node-level measure, Freeman centralisation summarises how unequally that centrality is distributed across the network:

> H = Σᵢ (C_max − Cᵢ) / [(n − 1) · C_max]

A value of 1 means all centrality is concentrated in a single channel (star graph); a value of 0 means all channels share the same score.

**Reference:** Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)

**In practice:** Freeman centralisation transforms a channel ranking into a single network-level verdict. High PageRank centralisation signals a network controlled by a small number of agenda-setting channels; low centralisation indicates a more distributed information ecosystem. A separate score is computed for every active measure.

### Mean Burt's constraint

The average Burt's constraint score across all channels. A low mean indicates a network rich in structural holes — most channels keep citation portfolios that are not redundant with their contacts' — while a high mean indicates an ecosystem of dense, mutually citing clusters.

---

## CONTENT

### Content originality (network-level)

The fraction of all messages across in-target channels that are original, meaning they carry no Telegram forward header: total non-forwarded messages / total messages. As with the per-channel [content originality](network-measures.md#content-originality), a forward counts whatever its source: a stored channel, a private channel, a hidden user account or a source not yet resolved.

**In practice:** this single number characterises the network as a production system. A value near 1.0 means the network is primarily a content-creation ecosystem; a value near 0.0 means it is primarily a redistribution and amplification machine.

### Amplification ratio

The total number of forwards received by in-target channels, divided by the total number of messages published by those channels. Measures how many times, on average, each published message gets re-shared somewhere else in the network.

**In practice:** amplification ratio is the network's overall virality rate. A value above 1.0 means the network produces more redistribution events than original publications.

---

## HOMOPHILY

*Do citations stay inside the analyst's labels — nation, region, organisation — more than the labels' sizes predict?*

The raw readings of that question mislead whenever the labels differ in size. A label holding half the channels keeps about half its ties inside by pure chance, so its E-I looks inward-looking; a label of one channel cannot cite inside at all, so its E-I is +1 by construction. The `HOMOPHILY` group answers the question for **every partition label group** (no `LABELGROUP<id>` strategy has to be selected) with statistics that carry their own chance baseline, and tests each against one null: **label permutation**. The labels are shuffled over the labelled channels while the graph stays fixed (the node-label permutation of the quadratic assignment procedure; Hubert & Schultz 1976; Krackhardt 1988; the test Krackhardt & Stern 1988 propose for E-I). Group sizes and every channel's ties are kept, so all the citations of a channel move together: the null controls for activity, popularity and the overdispersion of citation counts, and asks only whether *which label a channel carries* predicts whom it cites. 10,000 permutations per group, two-sided add-one p (floor ≈ 0.0002), Benjamini–Hochberg q within the group.

Only **observed** channels holding a label in the group take part, and only the ties between two of them (dead leaves' own citations are never read, self-citations are left out). Ties to unlabelled or out-of-target channels are reported separately as the *out-of-scope share* — not counted as "external", as the community-table E-I counts them.

### Assortativity and E-I (network table, *Homophily* rows)

- **Nominal assortativity r** (Newman 2003, directed form), on ties and on citations: (Σ e_ii − Σ a_i b_i) / (1 − Σ a_i b_i) on the label mixing matrix. 1 = every tie stays inside its label, 0 = labels unrelated to ties, negative = ties prefer other labels. Unlike modularity it is normalised by its own maximum, so it compares across groups with different numbers of labels.
- **E-I index, labelled ties**, next to its **expected value** under the permutations. The gap between the two is the size-corrected reading.

The rows sit in the *Homophily* group of the whole-network table; their *vs label permutation* column gives z and p.

### Per label (network table, *Homophily by label group* section)

- **Inbreeding homophily** IH = (H − w) / (1 − w) (Coleman 1958; Currarini, Jackson & Pin 2009), for the label's **sent** ties ("citing": the share of its citations of labelled channels that stay inside) and its **received** ties ("cited"). The baseline w = (n − 1)/(N − 1) is the share of partners inside the label when they are chosen regardless of label. 0 = no preference beyond its size, 1 = cites only its own label, negative = avoids it. Undefined for a one-channel label.
- **Net-exporter index** (cross-label ties received − given) / (received + given): positive = channels of other labels cite this one more than it cites them — the label exports its content.
- **Out-of-scope share**: the share of the label's citations that go to channels holding no label in the group, or to out-of-target channels. Out-of-target sources are in the graph only with dead leaves drawn (`--draw-dead-leaves`) or the environment admitted (`--environment-depth`); without them the share counts only in-target channels unlabelled in the group, often none.

### Citation flows between labels

The label × label matrix of ties (and citations), its permutation expectation and the observed / expected ratio. A cell is tested when its observed or expected tie count reaches 3; the tested cells of a group share one Benjamini–Hochberg correction. In the heat map (rows cite columns) red cells are over-represented flows, blue under-represented ones; `*` marks q < 0.05. The same data is in the *Label flows* sheet of `network_table.xlsx` and in `label_flows.csv` (with `--csv`), one row per label pair, for the full range and every timeline year.

**In practice:** on a transnational network labelled by nation, a clearly positive r with a strongly negative E-I-minus-expected says national scenes are real; per-label IH then tells *which* nations are inward-looking once their size is discounted, the net-exporter index which ones supply content across borders, and the significant off-diagonal flows which national pairs are tied beyond chance. A small label's statistics rest on few ties — read its q, not its point value. For a model that holds activity, audience and reciprocity fixed while estimating the same-nation effect, see the [dyadic regression](dyadic-models.md).

**References:** Coleman, J.S. (1958) "Relational analysis: the study of social organizations with survey methods." *Human Organization* 17(4). Currarini, S., Jackson, M.O. & Pin, P. (2009) "An economic model of friendship: homophily, minorities, and segregation." *Econometrica* 77(4). [doi:10.3982/ECTA7528](https://doi.org/10.3982/ECTA7528). Hubert, L.J. & Schultz, J. (1976) "Quadratic assignment as a general data analysis strategy." *British Journal of Mathematical and Statistical Psychology* 29. Krackhardt, D. (1988) "Predicting with networks: nonparametric multiple regression analysis of dyadic data." *Social Networks* 10(4). Newman, M.E.J. (2003) "Mixing patterns in networks." *Physical Review E* 67, 026126. [doi:10.1103/PhysRevE.67.026126](https://doi.org/10.1103/PhysRevE.67.026126).

---

## SIGNIFICANCE

*Is the network more reciprocal, more clustered, more centralised than a random network would be?*

A whole-network statistic on its own says little: sparse citation graphs have low clustering and heavy-tailed ones high centralisation, whatever their organisation. With `SIGNIFICANCE` selected, every statistic of the other selected groups that a random graph can move is set against three baselines, 100 random graphs each, and the network table gains a column per baseline showing **z (p)** (two-sided add-one p, floor ≈ 0.02; hover for the null mean).

| Baseline | What the random graphs keep | Reads as |
| :-- | :-- | :-- |
| **vs configuration** | every channel's in/out-degree exactly, in/out-strength approximately (Maslov–Sneppen rewiring + strength fitting — the null of the [robustness analysis](robustness-analysis.md)) | structure beyond the degree sequence |
| **vs reciprocal** | the same, plus every channel's reciprocated ties (Squartini & Garlaschelli 2011) | structure beyond the degrees *and* mutual citation — e.g. clustering that reciprocity alone does not explain |
| **vs random digraph** | only the number of channels and ties: ties placed uniformly, each from an observed channel (dead leaves never cite) | the baseline of the degree statistics the two rewirings hold fixed |

Tested: reciprocity and average clustering (`PATHS`), transitivity and the in/out-degree CV (`COHESION`), the largest WCC and SCC fractions (`COMPONENTS`), the four degree assortativities (`DEGCORRELATION`), and the centralisation of PageRank, HITS and in/out-degree centrality (`CENTRALIZATION`, for the measures selected). A statistic a baseline holds fixed by construction — the degree CV and degree centralisation under both rewirings, reciprocity under the reciprocal null — shows *held fixed*, not a p of 1. Path lengths, efficiency and algebraic connectivity stay descriptive: they are expensive on every random graph and are shape descriptors rather than claims. The observed values are recomputed with the very functions applied to the random graphs. The cost is dominated by the rewiring: about 2–3 minutes on a graph of a few thousand ties, plus each timeline year.

**In practice:** for a "leaderless" reading, the relevant pattern is high reciprocity and clustering vs configuration (peers citing each other) with PageRank centralisation *not* above the configuration baseline (no more concentrated than the degree sequence forces). A centralisation far above it says prestige concentrates on a few channels beyond what their degrees explain.

**References:** Maslov, S. & Sneppen, K. (2002) "Specificity and stability in topology of protein networks." *Science* 296. Squartini, T. & Garlaschelli, D. (2011) "Analytical maximum-likelihood method to detect patterns in real networks." *New Journal of Physics* 13. Erdős, P. & Rényi, A. (1959) "On random graphs I." *Publicationes Mathematicae* 6. Phipson, B. & Smyth, G.K. (2010) "Permutation p-values should never be zero." *Statistical Applications in Genetics and Molecular Biology* 9(1).

---

## Per-community statistics

Beyond the whole-network level, community statistics appear in `community_table.html` for each active strategy. Key metrics per community:

### Modularity (per strategy)

Modularity measures the quality of a community partition — the fraction of edges that fall within communities minus the fraction that would fall within them in a random graph with the same degree sequence. A "0.3 or above" rule of thumb circulates, but it is not evidence on its own: sparse, tree-like networks — hub-and-spoke citation graphs above all — reach high modularity even when random (Guimerà, Sales-Pardo & Amaral 2004). Read it with the significance columns below.

#### Modularity significance

For the strategies that maximise modularity — `LEIDEN`, `LEIDEN_DIRECTED` and `LOUVAIN` — the network table's *Modularity by strategy* section adds **Modularity z** and **p (random)**, and the community table states them next to *Network modularity Q*. Pulpit builds 20 random versions of the graph the partition was detected on. Each keeps every channel's in- and out-degree exactly and its in- and out-strength approximately (degree-preserving Maslov–Sneppen rewiring, then strength fitting — the configuration null of the [robustness analysis](robustness-analysis.md)). It then takes the best modularity Leiden reaches on each, with the same objective, directed or undirected. **z** is how many standard deviations the partition's modularity lies above that null mean; **p** is the one-sided Monte-Carlo p-value `(random graphs at least as modular + 1) / 21`, whose floor is ≈ 0.048. A large positive z means the network has community structure that random graphs with its degrees cannot imitate; z near 0 means the partition is no more modular than chance. Each random graph's best modularity comes from 5 Leiden runs, slightly fewer than the 50 behind the reported partition, so z is a little optimistic.

The other strategies get no z: CPM, the SBM family, K-core, the consensus partition and the label groups optimise (or encode) something other than modularity, so setting their modularity against the random graphs' *best* would always make them look insignificant. Their modularity remains a descriptive figure.

On one far-right Telegram export of 313 monitored channels, directed Leiden reached Q = 0.69 — but random graphs with the same degrees and strengths already reached 0.58 on average, so the structure beyond chance is the gap (z ≈ 9). With the 1,649 dead leaves drawn, Q = 0.66 against a random-graph mean of 0.61 (z ≈ 3.8): most of the larger graph's apparent modularity is the star shape of its citations, not communities.

**References:** Guimerà, R., Sales-Pardo, M. & Amaral, L.A.N. (2004) "Modularity from fluctuations in random graphs and complex networks." *Physical Review E* 70, 025101. [doi:10.1103/PhysRevE.70.025101](https://doi.org/10.1103/PhysRevE.70.025101); Reichardt, J. & Bornholdt, S. (2006) "When are networks truly modular?" *Physica D* 224. [doi:10.1016/j.physd.2006.09.009](https://doi.org/10.1016/j.physd.2006.09.009); Maslov, S. & Sneppen, K. (2002) "Specificity and stability in topology of protein networks." *Science* 296. [doi:10.1126/science.1065103](https://doi.org/10.1126/science.1065103).

Some partitions leave channels without a community. A label-group partition, for example, has no label for dead leaves, environment channels or channels never labelled in that group. When that happens, each channel left out counts as a community of its own, which is the standard convention. It keeps its degree in the random-graph baseline, and its edges count as edges between communities. The rule is the same for the directed and the undirected modularity. The table's per-community contributions list only the real communities, so when some channels are left out the contributions no longer add up exactly to the headline figure. The difference is the left-out channels' own terms, which are zero or negative unless a channel cites itself.

**In practice:** if your Organization partition's modularity is close to that of Leiden, your manual categorisation captures most of the network's structural organization. If Leiden's modularity is substantially higher, there is structure your categorisation does not capture.

### Inter-community edge ratio (per strategy)

The fraction of all directed edges whose source and target belong to different communities. Range 0–1.

**In practice:** a ratio near 0 means almost all links stay within communities — a cohesive ecosystem. A ratio near 1 means most links cross boundaries. Comparing this across snapshots reveals whether cross-community interaction is growing or shrinking over time.

### E-I Index (per community and strategy)

Krackhardt & Stern's E-I Index for a group:

> E-I = (E − I) / (E + I)

where E = external ties (to non-members) and I = internal ties (between members). Range −1 (fully cohesive: no external ties) to +1 (fully competitive: no internal ties).

**Reference:** Krackhardt, D. & Stern, R.N. (1988) "Informal networks and organizational crises: An experimental simulation." *Social Psychology Quarterly* 51(2). [doi:10.2307/2786835](https://doi.org/10.2307/2786835)

**In practice:** E-I index directly captures the cohesion-versus-competition distinction at the community level. A community with E-I ≈ −1 is self-referential; a community with E-I ≈ +1 is outward-facing. The mean E-I across all communities summarises the overall balance.

**Label groups.** For a label-group partition this E-I counts every tie to a channel without a label in the group — including dead leaves and out-of-target sources — as external, and it is not corrected for the label's size. For "how inward-looking is this nation?", read the [HOMOPHILY](#homophily) statistics instead: labelled ties only, the size discounted, a permutation test attached.

Use E-I index together with reciprocity and inter-community edge ratio for a composite reading:
- **High reciprocity + negative mean E-I:** peer-like mutual amplification within cohesive camps
- **Low reciprocity + positive mean E-I:** hierarchical cross-community citation, typical of competitive or monitoring dynamics
- **Mixed:** intermediate communities with both internal amplification and active external engagement

### Partition comparison matrices (ARI, AMI, NMI, VI)

The **Partition comparison** block appears on `community_table.html` (and in the `Network` sheet of the network-statistics XLSX) whenever two or more comparable partitions are active. It renders **four** strategy × strategy heat-maps — one per index — that quantify, from complementary angles, how much any two partitions of the channels agree. On a year-timeline export it carries its own **year selector** (*All years* or a single year), so you can compare the partitions of the full-range analysis or of any one year in isolation.

**What the rows and columns are.** Every active **community-detection strategy** (LEIDEN, LEIDEN_DIRECTED, LEIDEN_CPM, LOUVAIN, SBM, CONSENSUS, …) *and* every **label-group partition** (each partition `LabelGroup` — the primary one is the analyst's organisation grouping). `KCORE` is excluded: it is a shell decomposition, not a community detection, so partition similarity against it is uninformative (the [consensus matrix](export-formats.md#consensus_matrixhtml--cross-strategy-agreement) excludes it for the same reason). Including the label groups is the point: it turns the block into a validation of the algorithms' structural communities against the analyst's manual labels — and including the [consensus partition](community-detection.md#consensus) lets you read how much of each input strategy (and of the manual labels) survives cross-method agreement.

**What each cell measures.** Build the contingency table of the two partitions over the channels each pair shares (see *intersection* below), then:

| Index | Formula | Range | Identical | Independent | Chance-corrected |
| :---- | :------ | :---- | :-------- | :---------- | :--------------: |
| **ARI** — Adjusted Rand Index | (RI − E[RI]) / (max RI − E[RI]) | ≤ 1 (can be < 0) | 1 | 0 | ✓ |
| **AMI** — Adjusted Mutual Information | (I − E[I]) / (mean(H) − E[I]) | ≤ 1 (can be < 0) | 1 | ≈ 0 | ✓ |
| **NMI** — Normalised Mutual Information | 2 · I(U; V) / (H(U) + H(V)) | [0, 1] | 1 | 0 | ✗ |
| **VI** — Variation of Information | H(U) + H(V) − 2 · I(U; V) | [0, log₂ N] bits | 0 | H(U)+H(V) | — (a distance) |

where I(U; V) is the mutual information of the two partitions and H(·) is Shannon entropy. ARI counts agreeing channel **pairs** (do U and V put the same two channels together / apart?); AMI, NMI and VI are information-theoretic (how much does knowing a channel's community under U tell you about its community under V?). All four are invariant to how the communities are *labelled* — only the grouping matters.

- **ARI / AMI are chance-corrected** — they subtract the agreement two *random* partitions with the same cluster sizes would score, so they do not reward partitions merely for having many clusters. Prefer them when the two partitions have very different numbers of communities (e.g. a fine LEIDEN_CPM scan vs a coarse label group). A value near 0 means "no better than chance"; a negative value means "worse than chance".
- **NMI is *not* chance-corrected** — it is the familiar [0, 1] score, but it is biased upward when either partition has many small clusters. It is kept for comparability with the large body of literature that reports NMI.
- **VI is a true metric** on the space of partitions (it satisfies the triangle inequality; Meilă 2007), reported here in **bits**. It is a *distance*: **0 means identical** and larger means more different, bounded above by log₂ N for N co-assigned channels. In the heat-map its colour scale is therefore inverted (darker = smaller VI = more agreement) and normalised within the matrix; because VI is unnormalised, compare VI values cautiously across pairs whose channel coverage differs a lot.

**Intersection.** Each pair is computed on the **intersection** of channels assigned by *both* partitions. This matters for label-group partitions, which only assign the channels that carry one of the group's labels; channels missing from a group are silently excluded from that group's pairs but not from others. Channels with **no tie** in the graph the detections ran on are left out of every pair: each algorithm parks them in one shared residual community, so including them would count as agreement between any two algorithms.

**References:** Hubert, L. & Arabie, P. (1985) "Comparing partitions." *Journal of Classification* 2. [doi:10.1007/BF01908075](https://doi.org/10.1007/BF01908075) (ARI). Vinh, N.X., Epps, J. & Bailey, J. (2010) "Information theoretic measures for clusterings comparison." *JMLR* 11. (AMI). Kvalseth, T.O. (1987) "Entropy and correlation: Some comments." *IEEE Transactions on Systems, Man and Cybernetics* 17(3). [doi:10.1109/TSMC.1987.4309069](https://doi.org/10.1109/TSMC.1987.4309069) (NMI). Meilă, M. (2007) "Comparing clusterings — an information based distance." *Journal of Multivariate Analysis* 98(5). [doi:10.1016/j.jmva.2006.11.013](https://doi.org/10.1016/j.jmva.2006.11.013) (VI). The chance-corrected indices are computed with [scikit-learn](https://scikit-learn.org/stable/modules/clustering.html#clustering-performance-evaluation).

**In practice:** read each **label-group row** against the algorithmic columns. High agreement (ARI/AMI > ~0.5, NMI > ~0.7, VI near 0) means the analyst's manual grouping captures most of the structure the algorithm finds on its own — the network really does split along those lines. Low agreement (ARI/AMI near 0, NMI < ~0.3, VI large) means the structural communities cut across the labels: channels sharing a label are scattered across several structural clusters, or one structural cluster spans several labels. Comparing two **algorithmic** strategies (e.g. LEIDEN vs LEIDEN_DIRECTED, or successive LEIDEN_CPM resolutions) instead measures how *robust* the partition is: agreement across methods validates the finding; disagreement flags an ambiguous or resolution-sensitive community structure. When the four indices disagree, trust the chance-corrected pair (ARI/AMI): a high NMI with a near-zero AMI is the classic signature of an over-fragmented partition.

## Structural equivalence matrix

Generated with `--structural-similarity`. Available as a standalone page `structural_similarity.html` (the filename is kept for compatibility; the page shows structural equivalence — see [Export formats](export-formats.md#structural_similarityhtml--structural-equivalence-matrix)).

Each cell (i, j) shows the **structural equivalence** (Lorrain & White 1971) of channels i and j: the cosine similarity between their weighted *tie profiles*. A channel's profile is its weighted out-citations to every other channel concatenated with its weighted in-citations from every other channel (self-ties dropped). When i and j are compared, the entries for the tie between them are left out of both profiles (Burt 1976; Wasserman & Faust 1994 §9.4). They sit at different positions in the two profiles, so they could only lower the similarity: two channels that cite each other and share every other neighbour score 1.0.

> **What this measures.** Two channels score 1.0 when they cite — and are cited by — the *same* channels with the *same relative intensity*, i.e. they occupy interchangeable positions in the citation network. This is genuinely relational: it depends on *who* a channel connects to, not on its centrality scores. (It need not require the two channels to cite each other.) For "channels that behave alike by the numbers" see the [behavioural equivalence matrix](#behavioural-equivalence-matrix) instead.

**Computation:**
1. The weighted directed adjacency `A` is built over the channels (self-loops zeroed).
2. Each channel's profile is the row of `A` (out-ties) concatenated with the column of `A` (in-ties): `P = [A | Aᵀ]`.
3. `S_ij = P_i · P_j / (‖P_i‖ ‖P_j‖)`, where both norms leave out the pair's own tie (`‖P_i‖² − A_ij² − A_ji²`); the dot product already skips it. Clipped to [0, 1] with the diagonal forced to 1.0. Built with sparse linear algebra so it scales to large graphs.

**Range:** 0 (no shared neighbours) to 1 (identical neighbourhood with identical tie strengths).

The heatmap colours cells from white (low similarity) to steel-blue (high similarity). The diagonal is marked in grey (always 1.0 by definition). Only the lower triangle is rendered; the upper triangle is masked.

## Behavioural equivalence matrix

Generated with `--behavioural-equivalence`. Available as a standalone page `behavioural_equivalence.html` (see [Export formats](export-formats.md#behavioural_equivalencehtml--behavioural-equivalence-matrix)).

Each cell (i, j) shows the **Gower similarity** (Gower 1971) between channels i and j's **behavioural-measure profiles** — built from the behavioural measures that were computed: amplification factor, content originality, diffusion lag, plus audience/activity volume (followers, message count).

> **What this measures.** Two channels score 1.0 when they *behave* alike — originate vs amplify, fast vs slow, narrow vs wide reach, similar audience size — regardless of their position in the citation network. It is the behavioural counterpart of structural equivalence: a channel can be structurally equivalent to another (same neighbours) yet behaviourally very different, or vice versa.

**Computation:**
1. A raw n × m matrix is built (n channels, m behavioural measures). Missing values — `None`, e.g. diffusion lag for a channel with no dated forwards — are imputed to the **column median** (a neutral "unknown"), not 0.
2. The heavy-tailed volume measures (followers, message count) are log-scaled (`log1p`), so a few very large channels do not squeeze everyone else into one corner.
3. Each column is min-max normalised to [0, 1] so every measure contributes equally regardless of scale.
4. `S_ij = 1 − mean_k |x_ik − x_jk|`, in [0, 1], diagonal 1.0.

**Range:** 0 (opposite ends of every measure) to 1 (identical behavioural profile). Earlier releases used the cosine of the normalised profiles, which compares only their *direction*. A channel low on every measure then scored 1.0 against one high on every measure, and an all-zero profile scored 0 against everyone; Gower's similarity reads 1 only when the measures themselves match.

**References:** Gower, J.C. (1971) "A general coefficient of similarity and some of its properties." *Biometrics* 27(4). [doi:10.2307/2528823](https://doi.org/10.2307/2528823).

The heatmap rendering matches the structural equivalence matrix (white → steel-blue, grey diagonal, lower triangle only).

**Sorting:** A dropdown above the matrix controls the row/column order. "Community" groups channels by their plurality community assignment across all strategies (revealing a block-diagonal structure if the network has clear clusters); any individual measure (e.g. PageRank) sorts channels descending by that score.

**In practice:** channels that share a similar structural profile are likely to be functionally equivalent in the network — they occupy the same role (hub, bridge, peripheral consumer) even if their content differs. A dense dark block along the diagonal after community-sorting confirms that communities are also structurally cohesive; scattered dark cells off the diagonal reveal structurally equivalent channels that the community partition placed in different groups. Channels with no similarity to anyone else (entire pale row/column) are structural outliers whose combination of measures is unique in the network.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

# Graph layouts

A graph layout is an algorithm that assigns a spatial position to every channel node so that the resulting picture carries analytical meaning. Two channels placed close together in the layout are structurally similar; two channels placed far apart are structurally distant — according to whatever definition of distance the algorithm uses.

Layouts to compute are selected with `--layouts-2d` (2D) and `--layouts-3d` (3D). When neither flag is passed, only **ForceAtlas2** (FA2) is computed. Pass a comma-separated list to compute multiple layouts; they become selectable from a dropdown in the graph viewer with smooth animated transitions — no re-export required.

Every layout answers a different question about the same network. Switching between them on the same graph is a rapid way to triangulate structure: patterns that survive across multiple layouts are more likely to be genuine, while patterns that appear only in one layout may be artefacts of that layout's assumptions.

---

## Quick reference

| Layout | Availability | Key question |
| :----- | :----------- | :----------- |
| ForceAtlas2 | 2D · 3D (default) | Which channels naturally cluster together by citation strength? |
| Kamada-Kawai | 2D · 3D | How far apart are channels in the actual citation network? |
| Spectral | 3D | What is the main axis of variation in this network's structure? |
| Spring (Fruchterman-Reingold) | 3D | Does the clustering pattern hold without FA2's hub-biased gravity? |
| Circular | 2D | Are there hidden ordering patterns when position has no meaning? |
| Community shells | 2D | Where do community boundaries fall as concentric spatial zones? |
| t-SNE | 2D · 3D | What fine-grained sub-clusters exist within the broad communities? |
| UMAP | 2D · 3D | Which channels are topologically isolated from the rest of the network? |
| Hyperbolic | 2D | What is the core-periphery structure — who drives the network vs. who merely echoes? |

---

## ForceAtlas2

*Channels that cite each other heavily are pulled together; channels that ignore each other are pushed apart — producing spatial blobs that correspond to the ideological communities in the data.*

ForceAtlas2 is a continuous force-directed layout. Every node repels every other node (like charged particles), and every edge pulls its two endpoint nodes together with a force proportional to edge weight. The simulation runs until forces balance. Pulpit seeds each run with a Kamada-Kawai initial placement to improve reproducibility.

Pulpit uses **log-linear mode** (`linLogMode`), which replaces the usual linear attraction with a logarithmic one. This is specifically designed for scale-free networks — networks where a small number of hubs have orders of magnitude more connections than the majority of nodes. Without log-linear mode, hubs drag everything so strongly toward themselves that the rest of the network collapses into undifferentiated mass around them. Log-linear mode lets the peripheral channels spread out while still anchoring hubs visually.

**Reference:** Jacomy, M., Venturini, T., Heymann, S. & Bastian, M. (2014) "ForceAtlas2, a Continuous Graph Layout Algorithm for Handy Network Visualization Designed for the Gephi Software." *PLOS ONE* 9(6). [doi:10.1371/journal.pone.0098679](https://doi.org/10.1371/journal.pone.0098679)

**In practice:** FA2 is the most interpretable general-purpose layout for political Telegram networks. Communities tend to appear as convex spatial blobs, hub channels sit near the dense centres of their clusters, and channels that bridge communities appear between those blobs. The layout is not the same across re-exports — it converges to a similar structure but can rotate or mirror between runs. Use `--layouts-3d FA2` to include it in the 3D viewer's dropdown.

**Example.** A network of ~600 channels produces five FA2 clusters that closely match the five organizations assigned in the admin interface, with two small "bridge" channels sitting in the white space between the far-right and mainstream-right blobs — channels that the algorithm, without any organizational information, identifies as inter-community connectors.

---

## Kamada-Kawai

*Every pair of channels is placed at a geometric distance proportional to how many hops separate them in the citation network — the most faithful translation of graph topology into spatial coordinates.*

The Kamada-Kawai algorithm minimises a **stress function**: the sum of squared differences between the graph-theoretic shortest-path distance and the Euclidean distance for every pair of nodes. When the stress is zero, geometric distance perfectly mirrors network distance. In practice, stress is never zero (embedding a graph into a plane is mathematically impossible without distortion), but the algorithm finds the placement that distorts it least.

Pulpit uses KK as the **seed layout for ForceAtlas2** in both 2D and 3D, giving FA2 a principled starting point. KK is also available as a standalone extra layout — it shows you the "ground truth" topology before FA2 applies its aesthetic refinements.

**Reference:** Kamada, T. & Kawai, S. (1989) "An algorithm for drawing general undirected graphs." *Information Processing Letters* 31(1). [doi:10.1016/0020-0190(89)90102-6](https://doi.org/10.1016/0020-0190(89)90102-6)

**In practice:** Kamada-Kawai is slower than FA2 — expect a few seconds for networks above 300 nodes — but gives a purer picture of topological distances. Channels that appear isolated in FA2 because they are attached to a large cluster are placed at their true geodesic distance from other nodes. Use it to double-check whether the spatial separation you see in FA2 is real or a force-balance artefact.

---

## Spectral

*Channels are positioned along axes derived from the network's own mathematics — revealing the main structural fault lines.*

Spectral layout places channels using the eigenvectors of the **normalised Laplacian matrix** of the undirected graph. The Laplacian encodes the network's connectivity: its smallest non-trivial eigenvector (the Fiedler vector) cuts the graph into its two most loosely connected halves with the minimum number of edge cuts. Successive eigenvectors reveal progressively finer structure.

In 3D, Pulpit uses the three smallest non-trivial eigenvectors as the three spatial coordinates. This is mathematically equivalent to computing the graph's principal spectral decomposition.

**Reference:** Koren, Y. (2005) "Drawing graphs by eigenvectors: theory and practice." *Computers & Mathematics with Applications* 49(11–12). [doi:10.1016/j.camwa.2004.08.015](https://doi.org/10.1016/j.camwa.2004.08.015)

**In practice:** spectral layout is the cleanest way to see the network's main axis of variation. In politically polarised networks, the first spectral axis often runs from one pole to the other — channels on the left of the layout cite the left pole's anchors; channels on the right cite the right pole's anchors. The layout is **deterministic** (same result on every export) and does not depend on random seeds.

**Example.** A network of 400 Ukrainian channels arranges itself along a clear left-right axis in the spectral view, with pro-government channels at one end and opposition channels at the other, even though no political labels were provided to the algorithm. The Fiedler vector has recovered the primary ideological divide from citation patterns alone.

---

## Spring (Fruchterman-Reingold)

*A force-directed layout that distributes nodes more evenly than ForceAtlas2, trading hub emphasis for visual balance.*

The Fruchterman-Reingold algorithm applies the same attract/repel mechanics as ForceAtlas2 but with linear (rather than log-linear) forces. This means hubs do not disproportionately attract their neighbours — every edge contributes the same attractive force regardless of a node's total degree. The result is a more spatially balanced picture in which peripheral channels are not compressed into the hub's shadow.

In Pulpit, Spring is computed in **3D** with 200 iterations. Because it does not apply log-linear attenuation, it is better suited for networks with flatter degree distributions where no single hub dominates.

**Reference:** Fruchterman, T.M.J. & Reingold, E.M. (1991) "Graph drawing by force-directed placement." *Software: Practice and Experience* 21(11). [doi:10.1002/spe.4380211102](https://doi.org/10.1002/spe.4380211102)

**In practice:** switch to Spring when FA2 produces layouts where the periphery appears as an undifferentiated cloud around a few dense hubs. Spring's even distribution of repulsive force gives peripheral channels room to reveal their own substructure.

---

## Circular

*All channels are placed at equal intervals on a ring — removing spatial meaning so that only the edge patterns remain visible.*

The circular layout assigns positions purely by rank along a circle, with no information about network structure determining who ends up next to whom. It is a **neutral baseline**: because positions carry no meaning, the only information visible in the picture is the edge connections themselves. Crossing patterns, arc lengths, and edge bundles become the primary signals.

**In practice:** circular is useful when you want to confirm that a pattern in FA2 or t-SNE is driven by edge structure rather than by the layout algorithm's own assumptions. If two channels appear spatially close in FA2 and also have a dense bundle of edges between them in the circular view, the similarity is real. If the FA2 proximity disappears in circular, the spatial grouping may have been a layout artefact.

---

## Community shells

*Channels are placed in concentric rings, one ring per detected community — making community membership the primary organizing principle.*

Community shells uses NetworkX's `shell_layout` algorithm with community assignments as input. The largest community occupies the outermost ring, progressively smaller communities fill inner rings, and isolated nodes sit in the centre. Each ring's nodes are arranged at equal angular intervals around their shell.

Pulpit picks the community strategy in this order of preference: **LEIDEN → LEIDEN_DIRECTED → CONSENSUS → LOUVAIN → first available strategy**. If no community strategy has been computed, it falls back to a plain shell layout without community grouping.

**In practice:** community shells is the most *presentation-ready* layout. It makes community boundaries spatially unambiguous in a way that force-directed layouts cannot guarantee — communities that appear as overlapping blobs in FA2 are cleanly separated as distinct rings. Use it for reports, publications, or any situation where the audience needs to immediately understand which channels belong to which group.

**Example.** A presentation showing how a disinformation campaign recruited amplifiers from five distinct political communities uses community shells: each ring corresponds to one community, and the density of edges crossing between rings is immediately visible without needing to explain the graph structure.

---

## t-SNE

*A non-linear embedding that preserves local neighbourhood structure — revealing fine-grained sub-clusters and outliers that linear spectral methods compress into undifferentiated mass.*

t-SNE (t-distributed Stochastic Neighbour Embedding) converts high-dimensional similarity between data points into 2D or 3D positions, optimising so that nodes that are similar are placed close together and dissimilar nodes are placed far apart. Unlike spectral methods, t-SNE can represent complex curved or non-convex cluster geometry: communities that curve around each other, or clusters within clusters, are faithfully preserved.

Pulpit feeds t-SNE the **top-10 normalised Laplacian eigenvectors** of the undirected graph as input features. These eigenvectors capture the spectral community structure; t-SNE then non-linearly compresses them into 2D or 3D. Perplexity is set to `min(30, max(5, n÷4), n−1)` and a fixed random seed (`random_state=42`) ensures reproducible results.

**Reference:** van der Maaten, L. & Hinton, G. (2008) "Visualizing data using t-SNE." *Journal of Machine Learning Research* 9. [http://jmlr.org/papers/v9/vandermaaten08a.html](http://jmlr.org/papers/v9/vandermaaten08a.html)

**In practice:** t-SNE is best at revealing **local structure** — the existence of sub-communities that FA2 and spectral methods merge into a single blob. A broad "mainstream right" cluster in FA2 may split into three distinct sub-groups in t-SNE: regional channels, youth-oriented channels, and channels focused on a specific political figure. The separation reflects genuine differences in citation micro-patterns that force-directed methods smooth over.

**Important caveat:** global distances in t-SNE are not meaningful. Two clusters being far apart in the t-SNE view does not necessarily mean they are far apart in the network. Use t-SNE for within-cluster structure; use UMAP or Kamada-Kawai for global topology.

---

## UMAP

*A topology-preserving embedding that maps global network distances — channels many hops apart in the citation network are placed far apart in the map.*

UMAP (Uniform Manifold Approximation and Projection) builds a graph of approximate nearest neighbours in the input space and then optimises a low-dimensional layout to preserve its topology. Unlike t-SNE, UMAP preserves both local *and* global structure: clusters that are genuinely far apart in the source data remain far apart in the embedding.

Pulpit feeds UMAP the **all-pairs shortest-path distance matrix** of the undirected graph (with `metric='precomputed'`). This means the input to UMAP is network hop-distance — how many citation steps separate each pair of channels — rather than spectral features. Channels that cannot reach each other at all are assigned the maximum distance (network order n). This gives UMAP a fundamentally different perspective from t-SNE: the embedding reflects raw topological geography, not spectral community membership.

**Reference:** McInnes, L., Healy, J. & Melville, J. (2018) "UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction." *arXiv* 1802.03426. [https://arxiv.org/abs/1802.03426](https://arxiv.org/abs/1802.03426)

**In practice:** UMAP is best for understanding **which channels are topologically isolated** from the main network. Channels that sit in disconnected components or are reachable only via very long paths are placed at the periphery of the UMAP embedding, clearly separated from the central mass. Use UMAP when you need to identify structural outliers — channels that are nominally part of the dataset but are not meaningfully integrated into the citation ecosystem.

**Example.** A set of 50 newly discovered channels, added to the database after the main network was well-established, appear as a scattered halo in the UMAP view while the original 500 channels form a dense central mass. The UMAP distance reveals that the new channels have not yet formed citation ties into the existing ecosystem — they exist in isolation despite posting similar content.

---

## Hyperbolic

*Hub channels are placed at the centre; peripheral channels radiate outward — mapping the hierarchical core-periphery structure of the information ecosystem.*

This layout approximates the **Poincaré-disk model** of hyperbolic space, where the "distance from the centre" represents a node's depth in the network hierarchy. In hyperbolic geometry, the space near the edge of the disk expands exponentially: there is room for vastly more nodes at the periphery than near the centre, which naturally accommodates scale-free networks where hubs have far fewer connections than the total peripheral mass.

Pulpit implements the approximation without external dependencies: **angular position** comes from a 2D spring layout seed (preserving rough neighbourhood relationships), and **radial position** is derived from the node's log-scaled total degree. Formally:

> r = (1 − log(1 + degree) / log(1 + max_degree)) × scale

A channel with the highest total degree (in + out) lands at r = 0 — the centre of the disk. A channel with degree 0 lands at r = scale — the outermost edge. Intermediate nodes are placed logarithmically between the two.

This is an approximation of the exact maximum-likelihood hyperbolic embedding (Mercator algorithm). The exact algorithm requires an external library and is substantially slower; the approximation produces the same qualitative result — hierarchical core-periphery structure — for the analytical questions Pulpit addresses.

**Reference:** Krioukov, D., Papadopoulos, F., Kitsak, M., Vahdat, A. & Boguñá, M. (2010) "Hyperbolic geometry of complex networks." *Physical Review E* 82. [doi:10.1103/PhysRevE.82.036106](https://doi.org/10.1103/PhysRevE.82.036106)

**In practice:** the hyperbolic layout answers one question particularly clearly: *who is at the centre of the information ecosystem and who merely echoes at its edge?* Channels with many bidirectional citations land near the centre; single-purpose amplifiers with high out-degree but low in-degree land toward the periphery. The radial distance is an independent signal from community membership — a peripheral channel may still belong to a politically central community, and the combination of colour (community) and radial distance (centrality) encodes two structural dimensions simultaneously.

**Example.** In a right-wing Telegram network, the hyperbolic view places three channels at the absolute centre — a news aggregator, a political commentator, and a meme channel — surrounded by rings of regional channels, then single-issue channels, then foreign-language reposters at the outermost edge. The visual immediately answers the editorial question: *which three channels would you need to monitor to track almost all original content entering this ecosystem?*

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

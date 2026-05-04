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

Metrics are organised into selectable groups. Controlled via `--network-stat-groups` on the CLI, or the checkboxes in the Operations panel.

| Group | Metrics | Cost |
| :---- | :------ | :--- |
| `SIZE` | Nodes, Edges, Density | Low |
| `PATHS` | Avg Path Length, Diameter, Directed variants | Medium–High |
| `COHESION` | Transitivity, Global Efficiency, Algebraic Connectivity, Degree CV | High |
| `COMPONENTS` | WCC count, Largest WCC, SCC count, Largest SCC | Low |
| `DEGCORRELATION` | Directed assortativity (4 coefficients) | Low |
| `CENTRALIZATION` | Freeman centralisation per measure, Mean Burt's Constraint | Low–Medium |
| `CONTENT` | Content Originality, Amplification Ratio | Low |

> Deselect `PATHS` and `COHESION` to skip the expensive O(n·m) path-length and eigendecomposition calculations on large networks.

---

## SIZE

### Nodes and Edges

The raw count of channels (nodes) and directed connections (edges) in the graph. An edge from A to B means A has forwarded content from B or referenced B's username, weighted by frequency relative to A's total output. These counts depend on the `DRAW_DEAD_LEAVES` setting and any date range filters applied at export time.

### Density

The fraction of all possible directed edges that actually exist. For a directed graph with *n* nodes, the maximum number of edges is *n(n−1)*; density is the observed edge count divided by that maximum.

**In practice:** density is low in almost all real-world networks. What matters is the comparative value across exports or sub-networks. A rising density over time suggests a network becoming more tightly integrated; a very low density combined with high betweenness scores for a few nodes indicates a sparse network held together by a small number of critical bridges.

---

## PATHS

### Average Path Length

The mean of the shortest path lengths between all reachable pairs of nodes, computed on the **largest weakly connected component** (treated as undirected).

**In practice:** average path length is the network's "diameter in practice" — how many hops it takes, on average, for content to travel from one channel to another. Short average path lengths indicate a well-connected small-world network where information spreads quickly; long paths suggest a fragmented ecosystem where content circulates only within isolated sub-networks.

### Diameter

The longest shortest path in the network, computed on the largest weakly connected component (undirected).

**In practice:** the diameter sets an upper bound on how far a piece of content can travel. A small diameter (common in social networks) means any channel is reachable from any other in a few hops.

### Directed Average Path Length

The mean of all directed shortest-path distances between node pairs in the **largest strongly connected component** (SCC), following edge direction. Where the undirected path length ignores direction, this metric answers: *how many forwarding steps does content need to travel between two channels?*

**In practice:** comparing directed and undirected path lengths reveals how much directionality constrains information flow. A large gap between the two suggests many edges are one-way bridges that slow directed propagation significantly.

### Directed Diameter

The longest directed shortest path in the largest strongly connected component.

---

## COHESION

### Reciprocity

The fraction of edges that are mutual — if A→B exists, does B→A also exist? Computed as (number of mutual pairs) / (total number of edges).

**In practice:** reciprocity measures how symmetric information exchange is. A low reciprocity means the network is predominantly hierarchical: content flows from producers to distributors in one direction. A high reciprocity suggests peer-like mutual amplification. In political networks, high reciprocity within a community often signals tight ideological cohesion or coordinated behaviour.

### Average Clustering Coefficient

For each channel, the clustering coefficient measures how interconnected its immediate neighbours are — do the channels that reference A also reference each other? The average is taken over all channels.

**In practice:** a high average clustering coefficient means channels tend to form tight triangles of mutual reference — characteristic of ideologically homogeneous clusters. A low clustering coefficient indicates a more tree-like or hub-and-spoke structure.

### Transitivity

The fraction of all connected triples in the graph that form closed triangles. Also called the global clustering coefficient. Unlike Avg Clustering (which averages each channel's local coefficient separately), transitivity is a global fraction that gives more weight to high-degree channels.

**Reference:** Watts, D.J. & Strogatz, S.H. (1998) "Collective dynamics of 'small-world' networks." *Nature* 393. [doi:10.1038/30918](https://doi.org/10.1038/30918)

**In practice:** high transitivity means channels that both reference a third channel tend to reference each other — information loops are closed and the network is echo-chamber-like. Low transitivity indicates a more open, tree-like structure.

### Global Efficiency

The mean reciprocal directed shortest-path length over all ordered pairs of channels, including disconnected pairs (which contribute 0). Ranges from 0 (no pairs reachable) to 1 (all pairs at distance 1).

*E = (1 / n(n−1)) × Σ_{i≠j} 1/d(i,j)*

**Reference:** Latora, V. & Marchiori, M. (2001) "Efficient behavior of small-world networks." *Physical Review Letters* 87. [doi:10.1103/PhysRevLett.87.198701](https://doi.org/10.1103/PhysRevLett.87.198701)

**In practice:** global efficiency is the single most direct summary of how well information can flow across the entire network, including disconnected parts. A rising value over time indicates the ecosystem is becoming better integrated; a falling value signals fragmentation. Because it averages *inverse* distances, it is dominated by short paths rather than long ones.

> Note: computation requires all-pairs shortest paths (O(n·(n+m))); for large graphs (n > 3,000) this is the most expensive metric in the summary.

### Algebraic Connectivity (Fiedler value)

The second-smallest eigenvalue λ₂ of the graph Laplacian, computed on the undirected projection. This is the *Fiedler value* (Fiedler 1973). It equals 0 exactly when the graph is disconnected. For connected graphs it is strictly positive; larger values indicate stronger cohesion. Approximated using the LOBPCG algorithm.

Two fundamental properties make λ₂ particularly meaningful:
- **Cheeger inequality:** λ₂/2 ≤ edge expansion ≤ √(2λ₂) — it lower-bounds the edge connectivity (minimum cut)
- **Spectral gap:** λ₂ determines the mixing time of a random walk — how quickly a random walker forgets its starting position. Larger λ₂ → faster mixing → faster information diffusion.

**In practice:** algebraic connectivity answers *how robustly cohesive is this network?* A value near 0 means the network is on the verge of fragmentation. Unlike component counts (which detect existing disconnection), λ₂ detects *imminent* fragmentation — a network can have a single component yet be close to breaking apart.

**Example.** Before a platform content-moderation wave: Fiedler value = 0.14. After: 0.03. The network is now one targeted removal away from splitting into disconnected fragments.

### Degree CV (In-degree and Out-degree Coefficient of Variation)

The coefficient of variation (σ/μ) of the in-degree and out-degree distributions. CV normalises the spread of the distribution by its centre, allowing networks of different sizes or densities to be compared directly.

**Reference:** Pastor-Satorras, R. & Vespignani, A. (2001) "Epidemic spreading in scale-free networks." *Physical Review Letters* 86. [doi:10.1103/PhysRevLett.86.3200](https://doi.org/10.1103/PhysRevLett.86.3200)

**In practice:** degree CV is the quickest diagnostic for the presence of hub structure. High in-degree CV reveals a few central channels cited by many others — potential amplification bottlenecks. High out-degree CV reveals a few channels driving most of the citation activity — potential coordinating accounts. Comparing in- and out-degree CV characterises the asymmetry of influence.

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

Assortativity measures whether channels tend to connect to channels with similar degree. For directed graphs there are four Pearson correlation coefficients, computed over all edges:

| Coefficient | Source property | Target property |
| :---------- | :-------------- | :-------------- |
| **in→in** | in-degree of source | in-degree of target |
| **in→out** | in-degree of source | out-degree of target |
| **out→in** | out-degree of source | in-degree of target |
| **out→out** | out-degree of source | out-degree of target |

Values range from −1 (disassortative: high-degree nodes connect to low-degree nodes) to +1 (assortative: high-degree nodes connect to high-degree nodes).

**Reference:** Newman, M.E.J. (2003) "Mixing patterns in networks." *Physical Review E* 67. [doi:10.1103/PhysRevE.67.026126](https://doi.org/10.1103/PhysRevE.67.026126)

**In practice:** most information networks are disassortative on in-degree — popular channels (high in-degree) tend to be referenced by channels that are themselves not widely referenced. Strong disassortativity on out→in (high-out-degree channels point to low-in-degree targets) can indicate hub-and-spoke amplification of marginal content. Positive assortativity on out→out may signal coordinated distribution rings.

---

## CENTRALIZATION

### Freeman centralisation (per measure)

For each configured node-level measure, Freeman centralisation summarises how unequally that centrality is distributed across the network:

> H = Σᵢ (C_max − Cᵢ) / [(n − 1) · C_max]

A value of 1 means all centrality is concentrated in a single channel (star graph); a value of 0 means all channels share the same score.

**Reference:** Freeman, L.C. (1978) "Centrality in social networks: Conceptual clarification." *Social Networks* 1(3). [doi:10.1016/0378-8733(78)90021-7](https://doi.org/10.1016/0378-8733(78)90021-7)

**In practice:** Freeman centralisation transforms a channel ranking into a single network-level verdict. High PageRank centralisation signals a network controlled by a small number of agenda-setting channels; low centralisation indicates a more distributed information ecosystem. A separate score is computed for every active measure.

### Mean Burt's constraint

The average Burt's constraint score across all channels. A low mean indicates a network with many structural holes and active brokerage — channels are not tightly embedded in closed cliques and information can flow through diverse paths. A high mean indicates a network dominated by dense, redundant clusters.

---

## CONTENT

### Content originality (network-level)

The fraction of all messages across interesting channels that are original (not forwarded from another channel): total non-forwarded messages / total messages.

**In practice:** this single number characterises the network as a production system. A value near 1.0 means the network is primarily a content-creation ecosystem; a value near 0.0 means it is primarily a redistribution and amplification machine.

### Amplification ratio

The total number of forwards received by interesting channels, divided by the total number of messages published by those channels. Measures how many times, on average, each published message gets re-shared somewhere else in the network.

**In practice:** amplification ratio is the network's overall virality rate. A value above 1.0 means the network produces more redistribution events than original publications.

---

## Per-community statistics

Beyond the whole-network level, community statistics appear in `community_table.html` for each active strategy. Key metrics per community:

### Modularity (per strategy)

Modularity measures the quality of a community partition — the fraction of edges that fall within communities minus the fraction that would fall within them in a random graph with the same degree sequence. Values above roughly 0.3 are conventionally considered evidence of meaningful community structure.

**In practice:** if your Organisation partition's modularity is close to that of Leiden, your manual categorisation captures most of the network's structural organisation. If Leiden's modularity is substantially higher, there is structure your categorisation does not capture.

### Inter-community edge ratio (per strategy)

The fraction of all directed edges whose source and target belong to different communities. Range 0–1.

**In practice:** a ratio near 0 means almost all links stay within communities — a cohesive ecosystem. A ratio near 1 means most links cross boundaries. Comparing this across snapshots reveals whether cross-community interaction is growing or shrinking over time.

### E-I Index (per community and strategy)

Krackhardt & Stern's E-I Index for a group:

> E-I = (E − I) / (E + I)

where E = external ties (to non-members) and I = internal ties (between members). Range −1 (fully cohesive: no external ties) to +1 (fully competitive: no internal ties).

**Reference:** Krackhardt, D. & Stern, R.N. (1988) "Informal networks and organizational crises: An experimental simulation." *Social Psychology Quarterly* 51(2). [doi:10.2307/2786835](https://doi.org/10.2307/2786835)

**In practice:** E-I index directly captures the cohesion-versus-competition distinction at the community level. A community with E-I ≈ −1 is self-referential; a community with E-I ≈ +1 is outward-facing. The mean E-I across all communities summarises the overall balance.

Use E-I index together with reciprocity and inter-community edge ratio for a composite reading:
- **High reciprocity + negative mean E-I:** peer-like mutual amplification within cohesive camps
- **Low reciprocity + positive mean E-I:** hierarchical cross-community citation, typical of competitive or monitoring dynamics
- **Mixed:** intermediate communities with both internal amplification and active external engagement

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

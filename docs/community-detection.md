# Community detection

Community detection finds groups of channels that interact more with each other than with the rest of the network. Each algorithm uses a different notion of "interact" — citing each other, sharing sources, forming closed loops — and reveals a different facet of the same data.

Imagine you have a map of 400 channels. Community detection automatically draws the borders between neighbourhoods, without you having to decide in advance where the lines should fall.

Multiple strategies can be computed simultaneously and switched between in the graph viewer and table outputs.

> **Read this first.** Pulpit records *one-degree* amplification, which makes the **flow-based** strategies (Infomap, Memory Infomap, MCL, Walktrap) and `STRONGCC` theoretically misaligned with the data. The density-based and domain strategies are unaffected. See [Interpretation guardrails](#interpretation-guardrails-density-vs-flow) for the split.

<figure>
<img src="../webapp_engine/static/screenshot_00.jpg" alt="2D graph coloured by communities">
<figcaption><em>2D graph coloured by Leiden directed communities, print layout. Each colour cluster is one detected community.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Strategy | CLI key | Type | Preserves direction? |
| :------- | :------ | :--- | :------------------- |
| Organization | `ORGANIZATION` | Domain knowledge | — |
| Leiden | `LEIDEN` | Modularity | No |
| Leiden (directed) | `LEIDEN_DIRECTED` | Modularity | Yes |
| Leiden CPM | `LEIDEN_CPM(resolution=γ)` | Constant Potts Model | No |
| K-core | `KCORE` | Structural hierarchy | No |
| Infomap | `INFOMAP` | Information-theoretic | Yes |
| Memory Infomap | `INFOMAP_MEMORY` | Information-theoretic (2nd order) | Yes |
| MCL | `MCL` | Flow-based | Yes |
| Walktrap | `WALKTRAP` | Random-walk distance | No |
| Label propagation | `LABELPROPAGATION` | Label consensus | No |
| Strongly connected components | `STRONGCC` | Connectivity | Yes |

---

## Interpretation guardrails: density vs. flow

Pulpit records **one-degree amplification**: every forward is attributed to the original source, so a real A → B → C chain is stored as the star {B→A, C→A}, and any 2-path that survives in the graph is two unrelated citations rather than a transmission route (the full argument is in [Network measures → Interpretation guardrails](network-measures.md#interpretation-guardrails-the-one-degree-assumption)). For community detection this draws one bright line:

- **Density / structural methods** define a community by how much its members *cite each other* — a property of single, observed edges. They read one-degree structure directly and are **valid**.
- **Flow methods** define a community by where a *random walker* lingers as it traverses the network over many hops. That walker is the fictitious multi-hop flow one-degree forbids, so these methods optimise for a process the data does not contain.

There is even a flow-theoretic way to see why modularity survives and the walk-based methods do not: modularity is equivalent to a random walk at Markov time *t* = 1 — a *single* step (Lambiotte, Delvenne & Barahona 2014) — which is exactly one-degree amplification, whereas Infomap, MCL and Walktrap integrate the walker over *many* steps.

### Verdict by strategy

| Strategy | Verdict | Why under one-degree |
| :------- | :------ | :------------------- |
| Organization (`ORGANIZATION`) | **Valid** | Exogenous analyst labels — no flow assumption at all. |
| Leiden (`LEIDEN`) | **Valid** | Modularity compares within-group citation *density* to a degree null (Newman & Girvan 2004) — a structural criterion, not a flow one. |
| Leiden directed (`LEIDEN_DIRECTED`) | **Valid** | Directed modularity (Leicht & Newman 2008): the same density-vs-null logic, respecting citation direction. The canonical Pulpit partition. |
| Leiden CPM (`LEIDEN_CPM`) | **Valid** | Constant Potts Model (Traag et al. 2011): internal density against a constant resolution γ. Density criterion, no flow. |
| Label propagation (`LABELPROPAGATION`) | **Valid** (heuristic) | Local majority-label consensus (Raghavan et al. 2007): each node joins its densest local neighbourhood. No flow quality function — but fast and unstable; read it as a rough density grouping. |
| K-core (`KCORE`) | **Valid** (structural) | k-core degeneracy (Seidman 1983): a core-periphery nestedness stratification. Structural, *not* a spreading hierarchy — do not import the Kitsak (2010) spreader reading. |
| Infomap (`INFOMAP`) | **Undermined** | The map equation minimises the description length of a *random walker's multi-hop trajectory* (Rosvall & Bergstrom 2008): communities = where flow gets trapped. That flow does not traverse a one-degree graph. |
| Memory Infomap (`INFOMAP_MEMORY`) | **Undermined** (most) | Second-order Markov flow (Rosvall et al. 2014): the walker's next step depends on the previous one — it encodes exactly the i→j→k 2-paths one-degree forbids. The most flow-dependent method here. |
| MCL (`MCL`) | **Undermined** | Markov Clustering *is* flow simulation (van Dongen 2000): expansion is a multi-step random walk, and communities are where simulated flow pools. Fictitious under one-degree. |
| Walktrap (`WALKTRAP`) | **Undermined** | Groups nodes by multi-step random-walk transition similarity (Pons & Latapy 2005). Often recovers density-like partitions in practice (walk proximity tracks density), but its justification is multi-hop flow. |
| Strongly connected components (`STRONGCC`) | **Undermined** | SCCs require mutual reachability via *directed paths* (Tarjan 1972). Only 2-cycles (genuine reciprocal citation) are real; larger SCCs rest on multi-hop reachability that does not transmit. |

### Reading the catalogue below

Each strategy's own section — and the *Choosing a strategy* table at the bottom — describes its textbook use. Where the verdict above reads *Undermined*, treat that section as background on the algorithm: the echo-chamber, information-trap, context-dependent-broker, shared-source and circular-amplification framings all presuppose the multi-hop flow that a one-degree graph does not carry.

### The default selection

The Operations-panel default ships the strategies that read one-degree structure directly: `ORGANIZATION` (your baseline) + `LEIDEN_DIRECTED` (the canonical directed-modularity partition, and the default community basis for the bridging / role measures and the bridging robustness attack). The other density / structural methods — `LEIDEN`, `LEIDEN_CPM`, `LABELPROPAGATION`, `KCORE` — are equally valid and one click away when you want alternative partitions to compare. The flow methods (`INFOMAP`, `INFOMAP_MEMORY`, `MCL`, `WALKTRAP`) and `STRONGCC` remain fully available but are off by default. This governs the **web form only**; a bare `structural_analysis` CLI run detects no communities unless you pass `--community-strategies`.

---

## Organization

*Communities are the groupings you defined yourself in the admin interface — your own categories, used as a baseline.*

This is the only strategy in Pulpit that is not an algorithm: the communities are the analyst-defined Organizations attached to each channel — a political affiliation, a country, an editorial group, a funding source, whatever categorisation fits your investigation. Because the labels come from you, this strategy is the most interpretable and the natural baseline against which to read every algorithmic result. A channel's Organization can change over time (through time-bounded attribution periods); for each analysis window, the "representative" Organization is the one that covers the most days of the window for that channel.

**In practice:** use Organization as your reference grid. When an algorithmic community cuts across one of your Organization labels — splitting one bloc into two, or merging two into one — the network is telling you something your labels do not capture, and that disagreement is where the most actionable findings tend to live. The Organization × community panel and the consensus matrix are designed exactly for this comparison.

**Example.** You categorise 200 channels into five organizations: far-right, mainstream right, centrist, left, and state media. The map coloured by Organization shows that far-right and mainstream right channels sit close together and cross-reference heavily, while state media forms an isolated cluster that gets cited but rarely cites back. This already tells you something about who is amplifying whom — and gives you the baseline against which the algorithmic strategies below can be compared.

---

## Leiden

*Leiden groups channels that connect to each other more than chance would predict, and guarantees every detected community is internally well-connected — no channel stranded in a group it doesn't really belong to.*

Leiden looks for partitions where the density of connections inside each group is significantly higher than what would be expected if edges were placed at random. It runs a fast greedy search and then adds a refinement step that checks, after every merge, that every community is genuinely cohesive on the inside — so no channel ends up stranded in a group it isn't really connected to. The result is a clean, reliable partition that has become the standard modularity-based community detector across network science. Pulpit runs Leiden on the symmetrised view of the citation graph: direction is dropped but edge weights from `--edge-weight-strategy` shape the partition. When citation direction carries the meaning, use [Leiden (directed)](#leiden-directed) instead; when small dense clusters need to survive merging, see [Leiden CPM](#leiden-cpm).

**References:**
- Traag, V.A., Waltman, L. & van Eck, N.J. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the algorithm and the connectivity guarantee.
- Fortunato, S. & Barthélemy, M. (2007) "Resolution limit in community detection." *PNAS* 104(1). [doi:10.1073/pnas.0605965104](https://doi.org/10.1073/pnas.0605965104) — the resolution-limit result that the CPM variants escape.

**In practice:** Leiden is the recommended default whenever you don't have a specific reason to honour citation direction. It is the reliable baseline against which the more specialised strategies (Infomap, MCL, the CPM variants) are read in the consensus matrix. When Leiden splits a category you treated as a single bloc, the network is telling you the bloc has internal substructure worth investigating.

**Example.** A researcher monitors 200 channels labelled as "national press". Leiden returns three communities of similar size, spread across the analyst's single "national press" label. Inspection reveals one community centred on a regional aggregator hub, another on foreign-correspondent outlets, and a third on opinion-style channels. The same split also appears under Infomap — strong evidence that "national press" is, at this snapshot, three distinguishable sub-networks operating under one banner.

---

## Leiden (directed)

*Leiden (directed) works like Leiden but treats "who cites" and "who gets cited" as different signals — for when the direction of forwards carries meaning.*

Standard Leiden treats every forward the same regardless of direction, which can blur the picture when a network has a hub-and-spoke shape — many small channels forwarding from a single popular source without being forwarded back. The directed variant takes that asymmetry seriously: it expects A→B and B→A to mean different things, so a one-way forwarding pattern doesn't automatically force two channels into the same community. Pulpit runs this variant on the original directed citation graph, with edge weights from `--edge-weight-strategy`. It is also the default community basis for the [Community-bridging measure](network-measures.md#community-bridging) and the [bridging robustness attack](robustness-analysis.md) — both interpret communities through a directional brokerage lens.

**References:**
- Leicht, E.A. & Newman, M.E.J. (2008) "Community structure in directed networks." *Physical Review Letters* 100, 118703. [doi:10.1103/PhysRevLett.100.118703](https://doi.org/10.1103/PhysRevLett.100.118703) — the directed-modularity formulation.
- Traag, V.A. et al. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the Leiden refinement, inherited from [`LEIDEN`](#leiden).

**In practice:** use Leiden (directed) when the distinction between "who cites" and "who is cited" carries meaning — which on Telegram political networks it almost always does, since amplification flows asymmetrically from smaller amplifiers toward influential sources. Picking it also keeps Pulpit's downstream chain — community-bridging measure, within-module-role classification, brokerage robustness attack — consistent in their treatment of direction, since they all default to this basis.

**Example.** Seven regional nationalist channels all forward content from a single national aggregator but are never cited by it. Under undirected Leiden the seven plus the aggregator are merged into one community, because the undirected edge density is high. Under Leiden (directed), the seven form their own community while the aggregator joins a different group whose other members it actually cites both ways. The hub-and-spoke amplification pattern becomes visible at a glance — what looked like a single bloc is one broadcaster and seven amplifiers.

---

## Leiden CPM

*A tunable-granularity Leiden variant — useful for surfacing small, tight clusters that other strategies would merge into bigger ones. Set its resolution per instance, and add it more than once for a multi-scale view.*

Standard Leiden compares each candidate group against what would be expected at random, which has the side effect of absorbing small dense clusters into bigger ones (the resolution limit). The Constant Potts Model replaces that comparison with a tunable threshold γ: a community is kept only if its internal connection density exceeds γ. Higher γ produces more, smaller communities; lower γ produces fewer, larger ones — and either choice escapes the modularity resolution limit. The internal machinery is the same as standard Leiden: same symmetrised projection, same connectivity guarantee, edge weights honoured.

`LEIDEN_CPM` carries its resolution as a per-instance parameter, so you set it on the chip (Operations panel) or in the token (CLI) — and you can request it **more than once** at different resolutions for a multi-scale view, each producing its own partition column (e.g. `leiden_cpm_resolution_0_01`):

| Token | γ | Effect |
|:------|:--|:-------|
| `LEIDEN_CPM(resolution=0.01)` | 0.01 | Few, large communities — groups channels that share even weak citation ties |
| `LEIDEN_CPM(resolution=0.05)` | 0.05 | More, smaller communities — only groups channels with strong mutual citation density |

A bare `LEIDEN_CPM` starts at γ = 0.05; override per instance, or change the default with `--leiden-cpm-resolution`. (Earlier releases shipped two fixed presets, `LEIDEN_CPM_COARSE` / `LEIDEN_CPM_FINE`; saved configs upgrade to the parameterised form automatically.)

**References:**
- Traag, V.A., Van Dooren, P. & Nesterov, Y. (2011) "Narrow scope for resolution-limit-free community detection." *Physical Review E* 84, 016114. [doi:10.1103/PhysRevE.84.016114](https://doi.org/10.1103/PhysRevE.84.016114) — the CPM quality function and its resolution-limit-free property.

**In practice:** run Leiden, Leiden CPM coarse, and Leiden CPM fine side by side for a three-scale view of the same network. Communities that survive across all three are the most structurally robust. Communities appearing only at fine resolution are tight local cores embedded inside broader blocs — useful for identifying small coordinated nuclei within bigger ideological movements.

**Example.** A 600-channel anti-vaccine network is partitioned by Leiden into six communities. Leiden CPM fine returns 14 — eight of them sitting *inside* a single Leiden community. Inspection reveals these eight are language- or country-specific cores of coordinated activity (one Italian, one French, one Brazilian Portuguese, etc.). The Leiden partition revealed the broad movement; the CPM-fine partition revealed the operational coordination cells that share content within their language before it crosses over.

---

## K-core

*K-core peels the network like an onion, revealing the tight inner nucleus versus the peripheral amplifiers.*

K-core decomposition repeatedly removes channels with too few internal connections, exposing progressively denser cores. A channel's "coreness" is the deepest layer it survives in: high coreness means it sits inside a tightly interconnected nucleus where every member is similarly embedded; low coreness means it gets shed in the first peeling rounds and lives on the periphery. Research has shown that coreness predicts a channel's spreading influence better than simpler measures like degree. Pulpit's K-core is computed on the symmetrised view of the citation graph and is **unweighted** — it depends only on whether citations exist, not on how often. The partition is therefore invariant to the choice of `--edge-weight-strategy`. Communities are numbered from the innermost shell outwards, not by size: community 1 is the deepest core, community 2 the next shell out, and so on — the shell index *is* the information being reported.

**References:**
- Seidman, S.B. (1983) "Network structure and minimum degree." *Social Networks* 5(3). [doi:10.1016/0378-8733(83)90028-X](https://doi.org/10.1016/0378-8733(83)90028-X) — the k-core decomposition.
- Kitsak, M. et al. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746) — empirical evidence that coreness identifies the most influential spreaders.

**In practice:** K-core is uniquely useful for identifying the ideological engine of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating. Because the partition is unweighted, a grouping that survives k-core peeling *and* modularity-based detection is structurally cohesive on two independent grounds. The matching per-channel [`CORENESS`](network-measures.md#k-core-coreness) measure exposes the same shell index as a sortable column.

**Example.** In a disinformation network of 300 channels, k-core decomposition reveals an innermost core of just eight channels. These eight regularly forward each other, share a consistent narrative frame, and publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors.

---

## Infomap

*Infomap finds groups where attention tends to circulate internally rather than leak out — the closest formal definition of an echo chamber.*

Infomap imagines a random walker hopping from channel to channel along forwarding ties and looks for groups where the walker tends to get trapped. If a set of channels keep citing each other heavily, a walker dropped into one of them will rarely leave — those channels form a **flow module**. Unlike density-based methods like Leiden, Infomap is not affected by the resolution limit and can surface small flow traps that Leiden would merge into larger groups. Pulpit runs Infomap on the original directed citation graph — direction matters, and so do the edge weights from `--edge-weight-strategy`. The algorithm is configured for a flat partition (no nested hierarchy) so it can be compared like-for-like against the other detectors. It has its own characteristic biases — most notably a preference for tight reciprocal cores — so reading it next to [Leiden (directed)](#leiden-directed) and [STRONGCC](#strongly-connected-components-strongcc) tends to be the most informative cross-check.

**References:**
- Rosvall, M. & Bergstrom, C.T. (2008) "Maps of random walks on complex networks reveal community structure." *PNAS* 105(4). [doi:10.1073/pnas.0706851105](https://doi.org/10.1073/pnas.0706851105) — the original algorithm and the directed-random-walk framing Pulpit uses.

**In practice:** Infomap is the right tool when you want to surface **information-flow communities** — sets of channels whose mutual citations trap the random walker, irrespective of your Organization labels. On a Telegram forwarding network this is the closest formal operationalisation of an echo chamber. Read Infomap against Leiden (directed) and STRONGCC in the consensus matrix: groupings present under all three are genuinely closed loops; groupings only in Infomap are flow traps that do not require strict reciprocity; groupings only in Leiden (directed) are density-cohesive but not flow-confined.

**Example.** An NGO monitors 220 channels in an anti-vaccine ecosystem. Leiden (directed) returns six communities that align loosely with the analyst's regional groupings. Infomap returns nine: six overlap, but three are smaller and structurally tighter — 12 to 18 channels each. The same channels also form their own strongly connected component under STRONGCC. Infomap has surfaced the operational coordination cells inside the broader movement — the flow traps that Leiden's density-based grouping merged into bigger blocs.

---

## Memory Infomap

*Memory Infomap is a variant of Infomap that pays attention to which neighbours feed a hub — useful for surfacing brokers whose incoming and outgoing attention come from different places.*

Standard Infomap places each channel into one community. Memory Infomap goes further: when a hub channel is reached from two different groups, the algorithm can place the *incoming flow* from each group into a different module. A hub still gets one final label (by plurality vote across its incoming flows), but the way that label is decided is sensitive to who feeds the hub. This makes Memory Infomap useful for identifying brokerage hubs — channels whose incoming attention pulls them into one community while their outgoing citations point elsewhere. Pulpit builds the input by treating each edge A→B as a "context" (currently at B, came from A); since Pulpit has no observed three-step sequences, the outgoing transitions from this context use the first-order weights. The variant therefore captures *structural context-sensitivity at hubs*, not a true higher-order random walk.

**References:**
- Rosvall, M., Esquivel, A.V., Lancichinetti, A., West, J.D. & Lambiotte, R. (2014) "Memory in network flows and its effects on spreading dynamics and community detection." *Nature Communications* 5, 4630. [doi:10.1038/ncomms5630](https://doi.org/10.1038/ncomms5630) — the higher-order framework Pulpit approximates with a synthetic state network.

**In practice:** the realistic expectation is that Memory Infomap differs from first-order Infomap mainly at **brokerage hubs** — channels whose incoming citations come from communities the outgoing citations do not point back to. On purely cohesive blocs the two partitions usually agree. Run the two side by side and read the disagreement: a channel placed in different modules by the two strategies is a candidate context-dependent broker. Pair with the [`BRIDGINGCENTRALITY`](network-measures.md) and [`BURTCONSTRAINT`](network-measures.md) measures to triangulate the signal.

**Example.** A press-monitoring project tracks 180 channels. Standard Infomap returns seven communities, with one large "mainstream press" community containing an aggregator routinely forwarded by both reformist and conservative outlets. Memory Infomap returns the same seven communities, except the aggregator is now placed in the conservative community — its incoming forwards are dominated by conservative outlets even though its own posts get cited across the spectrum. The disagreement is the actionable signal: editorially the aggregator looks neutral, but the audience driving its visibility is one-sided.

---

## MCL (Markov Clustering)

*MCL surfaces tight reciprocal cores — small groups of channels where everyone forwards everyone else's content.*

MCL simulates a diffusion process on the citation network: information flow is concentrated along strong reciprocal ties and diluted along weak or one-way ones. After enough rounds, the channels condense into clearly separated attractor blocks — the communities. MCL has no resolution limit and no null model, so a four-channel reciprocal cell will survive intact even when Leiden would merge it into a larger community. MCL's inflation (set per instance, e.g. `MCL(inflation=3.0)`; default 2.0, typical range 1.5–4.0, and repeatable to compare values) controls how sharply the contrast is enhanced; higher inflation produces smaller, tighter communities. Pulpit runs MCL on the original directed citation graph, with edge weights from `--edge-weight-strategy` shaping the partition. The flip side of MCL's strength: it **fragments hub-and-spoke** structures, where many amplifiers cite a common source without citing each other. For those patterns, Leiden is the right tool.

**References:**
- van Dongen, S. (2008) "Graph clustering via a discrete uncoupling process." *SIAM Journal on Matrix Analysis and Applications* 30(1), 121–141. [doi:10.1137/040608635](https://doi.org/10.1137/040608635) — the formal treatment of the expansion/inflation algorithm and the structural argument for why MCL concentrates on tight reciprocal cores.

**In practice:** MCL is the right tool for surfacing **tight reciprocal cores** — small sets of channels (often three to ten) where every member regularly forwards every other member. These show up in coordinated amplification cells, in-group editorial networks, and aggregator pools. Read MCL alongside Leiden (directed) and Infomap in the consensus matrix: pairs co-clustered by MCL *and* one of the others are reciprocal structural cores; pairs only in Leiden are denser-but-not-reciprocal regions; pairs only in Infomap are flow traps that don't need strict reciprocity. Avoid MCL whenever the question is "which amplifiers share a common source" — use Leiden instead.

**Example.** A monitoring project tracks 180 channels in a disinformation ecosystem. Leiden (directed) returns nine communities aligned roughly with the analyst's regional groupings. MCL returns thirteen — including three tight 4-to-6 channel clusters where every member mutually forwards every other member. Each of these three is also a strongly connected component under STRONGCC. Inspection confirms they correspond to known coordinated-amplification cells where members reciprocally repost each other to manufacture the appearance of organic consensus. The same cells could not have surfaced under Leiden (resolution limit absorbs them into larger groups) or label propagation (no weight sensitivity).

---

## Walktrap

*Walktrap groups channels with similar neighbourhoods, even when they don't cite each other directly — shared sources, not just direct ties, drive the grouping.*

Walktrap is built on the intuition that short random walks on a graph tend to stay inside their starting community. For each channel it works out where a short walk is likely to land, then groups channels whose walks tend to converge on the same neighbours. The distinctive property — the reason to pick Walktrap over Leiden — is that two channels with **no direct edge** between them can still cluster together when they share the same set of forwarding targets. Pulpit runs Walktrap on the symmetrised view of the citation graph with the library default walk length of 4 steps. Direction is dropped but edge weights from `--edge-weight-strategy` shape both the walk distributions and the final grouping. The algorithm chooses the partition that maximises modularity at the end, so it inherits Leiden's resolution limit at the final cut.

**References:**
- Pons, P. & Latapy, M. (2006) "Computing communities in large networks using random walks." *Journal of Graph Algorithms and Applications* 10(2), 191–218. [doi:10.7155/jgaa.00124](https://doi.org/10.7155/jgaa.00124) — the algorithm with full formal analysis of the random-walk distance and the modularity cut.

**In practice:** Walktrap is the right tool when you suspect channels in the same community are linked **transitively through shared sources** rather than by direct citations. A common Telegram pattern: many small amplifiers that all forward from the same set of larger sources without forwarding each other — Walktrap groups them by their shared targets, while density-based methods may scatter them because their pairwise edge density is low. Read Walktrap alongside Leiden in the consensus matrix: pairs co-clustered by Walktrap but not by Leiden are linked by shared-neighbourhood structure rather than mutual citation, and the disagreement itself is the signal.

**Example.** A monitoring project tracks 220 channels in an anti-vaccine ecosystem. Leiden returns six communities largely aligned with the analyst's regional groupings. Walktrap returns five — one of which fuses two of Leiden's smaller regional groupings into a single cluster. Inspection shows the two fused groupings share the same handful of international "scientific authority" channels they all forward from, but rarely forward each other directly. Walktrap groups them because a short random walk from any member converges on the same external sources; Leiden splits them because their direct edge density is too low. The two regional groupings are operationally distinct amplifiers tapping a shared source pool.

---

## Label propagation

*Label propagation groups channels by local consensus — every channel adopts the most common label among its neighbours, until everyone agrees.*

Each channel starts with a unique label. At each step every channel adopts the label that is most common among its neighbours; the process stops when no channel would change on the next pass. The result is a fully automatic partition with no parameters to tune and no quality function to maximise — communities emerge from purely local consensus. The algorithm is dramatically faster than every other strategy in this list, which makes it a useful cheap baseline. Pulpit runs the **semi-synchronous variant**, which guarantees the algorithm terminates and produces the same partition every time on the same graph (no random seed needed). The input is the symmetrised citation graph, and edge weights are **ignored** by NetworkX's implementation — the partition is invariant to `--edge-weight-strategy` and to direction. This is the coarsest possible view of the citation graph: pure unweighted connectivity.

**References:**
- Raghavan, U.N., Albert, R. & Kumara, S. (2007) "Near linear time algorithm to detect community structures in large-scale networks." *Physical Review E* 76(3), 036106. [doi:10.1103/PhysRevE.76.036106](https://doi.org/10.1103/PhysRevE.76.036106) — the foundational asynchronous algorithm.
- Cordasco, G. & Gargano, L. (2010) "Community detection via semi-synchronous label propagation algorithms." [doi:10.1109/BASNA.2010.5730298](https://doi.org/10.1109/BASNA.2010.5730298) — the deterministic semi-synchronous variant Pulpit uses.

**In practice:** label propagation is by far the cheapest community detector in Pulpit's suite, which makes it the right choice for very large networks where Infomap, MCL, or Walktrap would be too slow, or as a parameter-free baseline in the consensus matrix. Because it ignores weights and direction, a grouping that appears under both label propagation *and* Leiden is unlikely to be an artefact of weighting choices or directionality — it is robust on the bare topology. Watch for one well-known failure mode: on dense networks the consensus dynamic can run away and produce a single giant community absorbing most of the network. If that happens, switch to Leiden.

**Example.** A monitoring project tracks 1,200 channels. Leiden (directed) takes several minutes and returns 14 communities; label propagation runs in well under a second and returns 8. Six of the eight label-propagation communities each absorb a pair of Leiden communities; the remaining two correspond one-to-one with Leiden. Inspection reveals the merged pairs are exactly the hub-and-spoke patterns — one aggregator and a constellation of amplifiers that don't cite each other. Leiden (directed) splits broadcaster from audience; label propagation, blind to direction, sees one densely connected blob. The disagreement is the actionable signal — it separates "shared neighbourhood" from "shared editorial role".

---

## Strongly Connected Components (STRONGCC)

*Two channels belong to the same strongly connected group only when each can reach the other along actual citation chains — strict mutual reachability.*

A strongly connected component is the maximal set of channels in which every member can reach every other member by following actual forwarding directions — both A reaches B *and* B reaches A. On Pulpit's citation graph, a non-trivial SCC requires reciprocal citation chains: at minimum two channels each forwarding the other; more typically a closed loop A → B → C → … → A formed by transitive reciprocity. This is a structural decomposition, not a density-based community detector — there is no notion of "more connected than expected", only whether a closed citation cycle passes through the pair. Pulpit's STRONGCC is **unweighted** and **direction-aware** by construction; components are numbered by size, isolated channels become singletons. STRONGCC is excluded from the consensus matrix because its size distribution would distort comparisons with the genuine community detectors. The same SCC structure feeds the [`SCC count` and `Largest SCC fraction`](whole-network-statistics.md#components) headline statistics and the [`R_scc` robustness curve](robustness-analysis.md#r_scc--strongly-connected-component).

**References:**
- Tarjan, R. (1972) "Depth-first search and linear graph algorithms." *SIAM Journal on Computing* 1(2), 146–160. [doi:10.1137/0201010](https://doi.org/10.1137/0201010) — the linear-time SCC algorithm NetworkX implements.
- Broder, A. et al. (2000) "Graph structure in the Web." *Computer Networks* 33(1–6), 309–320. [doi:10.1016/S1389-1286(00)00083-9](https://doi.org/10.1016/S1389-1286(00)00083-9) — the canonical bow-tie decomposition.

**In practice:** treat STRONGCC as a **strict-reciprocity diagnostic**, not a general community label. On Pulpit's citation graph, a large non-trivial SCC is the strictest possible operationalisation of "coordinated nucleus" or "echo chamber" — channels that all mutually cite each other along closed cycles, not merely densely co-cited. Read it alongside Infomap (flow-confined modules, looser than strict reciprocity) and Leiden (directed) (dense directional groups, tolerating one-way ties): a grouping that is *also* an SCC is the strict mutual-citation core inside the flow trap. If every channel is a singleton, the network has no reciprocal cycles at all — a pure broadcast tree, a project at very early crawl stage, or a structurally tree-like ecosystem.

**Example.** A monitoring project tracks 320 channels in a coordinated disinformation operation. STRONGCC returns one component of size 12 plus 308 singletons. Inspection of the 12-node component reveals a tight coordination ring: each member forwards every other member's content within hours of publication, and at least one closed cycle can be traced through every pair — the textbook pattern for manufactured organic consensus. Infomap independently identifies the same 12 channels as a couple of flow modules; Leiden (directed) merges them into a larger 31-channel community that also pulls in the most active one-way amplifiers. The 12-channel intersection — present under all three lenses *and* a single SCC — is the actionable target.

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
| Detect context-dependent brokers | `INFOMAP_MEMORY` |
| Find the ideological core vs. periphery | `KCORE` |
| Probe at multiple granularities | `LEIDEN` + `LEIDEN_CPM(resolution=0.01)` + `LEIDEN_CPM(resolution=0.05)` |
| Surface tight reciprocal amplification cores | `MCL` |
| Group channels by shared sources (not direct ties) | `WALKTRAP` |
| Detect coordinated circular amplification | `STRONGCC` |
| Compare algorithms for robustness | `ALL` + `--consensus-matrix` |

> Several rows above recommend flow-based strategies (`INFOMAP`, `INFOMAP_MEMORY`, `MCL`, `WALKTRAP`, `STRONGCC`) — for information traps, context-dependent brokers, shared-source grouping, circular amplification. Under Pulpit's one-degree data model these are theoretically misaligned; see [Interpretation guardrails](#interpretation-guardrails-density-vs-flow) before relying on them, and prefer a density-based strategy where one answers the same question.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

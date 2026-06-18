# Community detection

Community detection finds groups of channels that interact more with each other than with the rest of the network. Each algorithm uses a different notion of "interact" — citing each other, sharing sources, forming closed loops — and reveals a different facet of the same data.

Imagine you have a map of 400 channels. Community detection automatically draws the borders between neighbourhoods, without you having to decide in advance where the lines should fall.

Multiple strategies can be computed simultaneously and switched between in the graph viewer and table outputs.

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
| Louvain | `LOUVAIN` | Modularity (classic baseline) | No |
| K-core | `KCORE` | Structural hierarchy | No |
| Label propagation | `LABELPROPAGATION` | Label consensus | No |
| Stochastic block model | `SBM(mode=NESTED\|FLAT)` | Generative block model | Yes |

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

**In practice:** Leiden is the recommended default whenever you don't have a specific reason to honour citation direction. It is the reliable baseline against which the more specialised strategies (Leiden (directed), the CPM variants) are read in the consensus matrix. When Leiden splits a category you treated as a single bloc, the network is telling you the bloc has internal substructure worth investigating.

**Example.** A researcher monitors 200 channels labelled as "national press". Leiden returns three communities of similar size, spread across the analyst's single "national press" label. Inspection reveals one community centred on a regional aggregator hub, another on foreign-correspondent outlets, and a third on opinion-style channels. The same split also appears under Leiden (directed) — strong evidence that "national press" is, at this snapshot, three distinguishable sub-networks operating under one banner.

---

## Leiden (directed)

*Leiden (directed) works like Leiden but treats "who cites" and "who gets cited" as different signals — for when the direction of forwards carries meaning.*

Standard Leiden treats every forward the same regardless of direction, which can blur the picture when a network has a hub-and-spoke shape — many small channels forwarding from a single popular source without being forwarded back. The directed variant takes that asymmetry seriously: it expects A→B and B→A to mean different things, so a one-way forwarding pattern doesn't automatically force two channels into the same community. Pulpit runs this variant on the original directed citation graph, with edge weights from `--edge-weight-strategy`. It is also the default community basis for the [within-module role measure](network-measures.md#within-module-role) — the role formula itself is direction-blind (it counts neighbours on both sides), so this choice of basis is where direction enters the role classification.

**References:**
- Leicht, E.A. & Newman, M.E.J. (2008) "Community structure in directed networks." *Physical Review Letters* 100, 118703. [doi:10.1103/PhysRevLett.100.118703](https://doi.org/10.1103/PhysRevLett.100.118703) — the directed-modularity formulation.
- Traag, V.A. et al. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the Leiden refinement, inherited from [`LEIDEN`](#leiden).

**In practice:** use Leiden (directed) when the distinction between "who cites" and "who is cited" carries meaning — which on Telegram political networks it almost always does, since amplification flows asymmetrically from smaller amplifiers toward influential sources. Picking it also matches the default basis of Pulpit's within-module-role classification, which resolves to this partition when no explicit basis is given.

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

## Louvain

*Louvain groups channels that connect to each other more than chance would predict — the classic, field-standard community detector. Kept mainly for comparison with the large body of older studies that report Louvain results; for new analyses, [Leiden](#leiden) (or [Leiden (directed)](#leiden-directed)) is the better choice.*

Louvain looks for partitions where the density of connections inside each group is much higher than what would be expected if edges were placed at random, and finds them with a fast greedy procedure that needs no prior guess at how many groups exist. Published in 2008, it became the de-facto baseline for community detection across network science, which is the one reason to keep it in Pulpit: when you are replicating or comparing against a study that reports Louvain communities, running the same algorithm removes "different method" as an explanation for any difference you see. Pulpit runs Louvain on the symmetrised view of the citation graph (forwards in both directions collapsed into one tie, so direction is dropped) with edge weights from `--edge-weight-strategy` honoured, and a fixed seed so the partition is reproducible.

**Why prefer Leiden.** [Leiden](#leiden) optimises the *same* modularity objective on the *same* symmetrised graph, so it is a drop-in upgrade, and it fixes Louvain's two well-known weaknesses. First, Louvain can occasionally return a community that is **not internally connected** — a channel can be stranded in a group it has no real link to — whereas Leiden adds a refinement step that guarantees every community is internally well-connected (Traag et al. 2019). Second, both inherit the **resolution limit** (Fortunato & Barthélemy 2007) — the tendency to absorb small dense clusters into bigger ones — but Leiden's cleaner optimisation exposes it less sharply, and the [CPM variants](#leiden-cpm) escape it entirely. Unless you specifically need a Louvain partition for comparability, reach for Leiden; when citation direction carries the meaning, reach for [Leiden (directed)](#leiden-directed).

**References:**
- Blondel, V.D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E. (2008) "Fast unfolding of communities in large networks." *Journal of Statistical Mechanics* 2008(10), P10008. [doi:10.1088/1742-5468/2008/10/P10008](https://doi.org/10.1088/1742-5468/2008/10/P10008) — the original algorithm.
- Fortunato, S. & Barthélemy, M. (2007) "Resolution limit in community detection." *PNAS* 104(1). [doi:10.1073/pnas.0605965104](https://doi.org/10.1073/pnas.0605965104) — the resolution-limit result.
- Traag, V.A., Waltman, L. & van Eck, N.J. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — why Leiden supersedes Louvain.

**In practice:** select Louvain when you are reproducing or benchmarking against external work that used it, or when a reviewer expects the familiar baseline. Read it next to Leiden in the consensus matrix: groupings that survive both are robust; a group Leiden splits that Louvain keeps whole is usually the resolution limit at work, and a Louvain community that turns out to be internally disconnected is exactly the failure mode Leiden was built to remove. For everything else, treat Leiden as the default and Louvain as the legacy cross-check.

**Example.** A team is extending a published study that reported eight Louvain communities in a far-right Telegram ecosystem. Re-crawling the network and running Louvain in Pulpit reproduces eight comparable communities, confirming the earlier finding still holds on fresh data. Switching to Leiden on the same graph splits one of the eight into two tightly-knit halves that Louvain had merged — a substructure the original study missed. Reporting both keeps the result comparable to the literature *and* surfaces the finer split.

---

## K-core

*K-core peels the network like an onion, revealing the tight inner nucleus versus the peripheral amplifiers.*

K-core decomposition repeatedly removes channels with too few internal connections, exposing progressively denser cores. A channel's "coreness" is the deepest layer it survives in: high coreness means it sits inside a tightly interconnected nucleus where every member is similarly embedded; low coreness means it gets shed in the first peeling rounds and lives on the periphery. Research has shown that coreness predicts a channel's spreading influence better than simpler measures like degree. Pulpit's K-core is computed on the symmetrised view of the citation graph and is **unweighted** — it depends only on whether citations exist, not on how often. The partition is therefore invariant to the choice of `--edge-weight-strategy`. Communities are numbered from the innermost shell outwards, not by size: community 1 is the deepest core, community 2 the next shell out, and so on — the shell index *is* the information being reported.

**References:**
- Seidman, S.B. (1983) "Network structure and minimum degree." *Social Networks* 5(3). [doi:10.1016/0378-8733(83)90028-X](https://doi.org/10.1016/0378-8733(83)90028-X) — the k-core decomposition.
- Kitsak, M. et al. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746) — empirical evidence that coreness identifies the most influential spreaders.

**In practice:** K-core is uniquely useful for identifying the ideological engine of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating. Because the partition is unweighted, a grouping that survives k-core peeling *and* modularity-based detection is structurally cohesive on two independent grounds.

**Example.** In a disinformation network of 300 channels, k-core decomposition reveals an innermost core of just eight channels. These eight regularly forward each other, share a consistent narrative frame, and publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors.

---

## Label propagation

*Label propagation groups channels by local consensus — every channel adopts the most common label among its neighbours, until everyone agrees.*

Each channel starts with a unique label. At each step every channel adopts the label that is most common among its neighbours; the process stops when no channel would change on the next pass. The result is a fully automatic partition with no parameters to tune and no quality function to maximise — communities emerge from purely local consensus. The algorithm is dramatically faster than every other strategy in this list, which makes it a useful cheap baseline. Pulpit runs the **semi-synchronous variant**, which guarantees the algorithm terminates and produces the same partition every time on the same graph (no random seed needed). The input is the symmetrised citation graph, and edge weights are **ignored** by NetworkX's implementation — the partition is invariant to `--edge-weight-strategy` and to direction. This is the coarsest possible view of the citation graph: pure unweighted connectivity.

**References:**
- Raghavan, U.N., Albert, R. & Kumara, S. (2007) "Near linear time algorithm to detect community structures in large-scale networks." *Physical Review E* 76(3), 036106. [doi:10.1103/PhysRevE.76.036106](https://doi.org/10.1103/PhysRevE.76.036106) — the foundational asynchronous algorithm.
- Cordasco, G. & Gargano, L. (2010) "Community detection via semi-synchronous label propagation algorithms." [doi:10.1109/BASNA.2010.5730298](https://doi.org/10.1109/BASNA.2010.5730298) — the deterministic semi-synchronous variant Pulpit uses.

**In practice:** label propagation is by far the cheapest community detector in Pulpit's suite, which makes it the right choice for very large networks where the modularity-based strategies would be too slow, or as a parameter-free baseline in the consensus matrix. Because it ignores weights and direction, a grouping that appears under both label propagation *and* Leiden is unlikely to be an artefact of weighting choices or directionality — it is robust on the bare topology. Watch for one well-known failure mode: on dense networks the consensus dynamic can run away and produce a single giant community absorbing most of the network. If that happens, switch to Leiden.

**Example.** A monitoring project tracks 1,200 channels. Leiden (directed) takes several minutes and returns 14 communities; label propagation runs in well under a second and returns 8. Six of the eight label-propagation communities each absorb a pair of Leiden communities; the remaining two correspond one-to-one with Leiden. Inspection reveals the merged pairs are exactly the hub-and-spoke patterns — one aggregator and a constellation of amplifiers that don't cite each other. Leiden (directed) splits broadcaster from audience; label propagation, blind to direction, sees one densely connected blob. The disagreement is the actionable signal — it separates "shared neighbourhood" from "shared editorial role".

---

## Stochastic block model

*The SBM asks a different question from every other strategy here: not "where are the dense clusters?" but "which channels play the same role in the citation web?" — grouping channels that cite, and are cited by, the rest of the network in the same way.*

Every other detector in this list looks for **assortative** structure: groups that are dense inside and sparse outside. The stochastic block model drops that assumption. It is a *generative* model — it asks which assignment of channels to blocks best explains the observed pattern of citations, where the probability of a citation depends only on the two channels' blocks. Because the block-to-block citation rates are free to take any values, the SBM recovers structure the modularity family is blind to: not just assortative communities, but **disassortative** groups (channels that avoid each other), **core-periphery** layers, and the **bipartite source / amplifier** pattern that dominates a forward-attribution network — a set of amplifiers that all cite the same sources but never cite each other is a perfectly good block, even though it has zero internal density.

Pulpit fits a **directed, degree-corrected** SBM via [graph-tool](https://graph-tool.skewed.de/) (Peixoto). *Directed*: citation direction is preserved, so the block-affinity matrix is asymmetric — "block A cites block B" is distinct from the reverse, which is exactly the source-vs-amplifier signal. *Degree-corrected* (Karrer & Newman 2011): the model accounts for each channel's degree, so the blocks reflect citation structure **beyond** the raw in-degree heterogeneity of the star topology rather than simply lumping all the high-in-degree hubs together. The fit is **unweighted** (binary citation structure), so the partition is invariant to `--edge-weight-strategy`. Inference is by minimum description length, which is **self-regularising**: unlike modularity, the SBM will not invent blocks the data don't support, so it does not hallucinate community structure in a near-random graph.

`mode` selects the inference variant and may be added once per mode:
- **`NESTED`** (default) — the nested SBM (Peixoto 2017) fits a hierarchy of blocks and Pulpit reports the partition at the finest level. Better model selection on large graphs; avoids the underfitting the flat model suffers on big networks.
- **`FLAT`** — a single-level SBM.

> **Interpretation guardrail — blocks are roles, not cohesive groups.** An SBM block is a set of channels that are *stochastically equivalent* — they connect to the rest of the network the same way — i.e. a **citation-role / structural-equivalence class** (Lorrain & White 1971). It is **not** necessarily a community of mutually-citing channels: two channels can share a block while having no tie between them, simply because they cite the same sources and are cited by the same amplifiers. Read an SBM block as "these channels occupy the same structural position in the citation ecosystem", never as "these channels talk to each other". Likewise, a block-affinity entry is a one-step, group-to-group **direct citation rate** — not a claim that content flows from one block through to another. This keeps the SBM consistent with Pulpit's one-degree attribution model (see [Measures → interpretation guardrails](network-measures.md)), where multi-hop flow is not recoverable from the data.

**Dependency.** The SBM requires the `graph-tool` package, which is **not installable from pip** (it is a compiled C++ library). Install it via conda-forge (`conda install -c conda-forge graph-tool`) or your system package manager (Debian/Ubuntu: `apt install python3-graph-tool` from the maintainer's repository; a virtualenv must then be created with `--system-site-packages` to see it). If `graph-tool` is missing, requesting `SBM` fails with a clear error and the other strategies are unaffected.

**References:**
- Karrer, B. & Newman, M.E.J. (2011) "Stochastic blockmodels and community structure in networks." *Physical Review E* 83(1), 016107. [doi:10.1103/PhysRevE.83.016107](https://doi.org/10.1103/PhysRevE.83.016107) — the degree-corrected SBM.
- Peixoto, T.P. (2014) "Efficient Monte Carlo and greedy heuristic for the inference of stochastic block models." *Physical Review E* 89(1), 012804. [doi:10.1103/PhysRevE.89.012804](https://doi.org/10.1103/PhysRevE.89.012804) — the MDL inference Pulpit calls.
- Peixoto, T.P. (2017) "Nonparametric Bayesian inference of the microcanonical stochastic block model." *Physical Review E* 95(1), 012317. [doi:10.1103/PhysRevE.95.012317](https://doi.org/10.1103/PhysRevE.95.012317) — the nested SBM.
- Lorrain, F. & White, H.C. (1971) "Structural equivalence of individuals in social networks." *Journal of Mathematical Sociology* 1(1). [doi:10.1080/0022250X.1971.9989788](https://doi.org/10.1080/0022250X.1971.9989788) — the structural-equivalence notion that a block operationalises.

**In practice:** reach for the SBM when modularity-based detection feels like it is fighting the data — when you suspect the network is hub-and-spoke or two-mode rather than a set of cohesive cliques. Because it separates *role* from *cohesion*, the SBM is the natural complement to Leiden: where Leiden tells you which channels cluster together, the SBM tells you which channels are interchangeable in the citation structure (e.g. "these forty amplifiers are structurally the same actor, pointed at the same three sources"). Compare it against `LEIDEN_DIRECTED` and `ORGANIZATION` in the consensus matrix — but remember the partitions answer different questions, so disagreement is expected and informative, not a failure.

**Example.** A network of 500 channels yields six tidy Leiden communities. The SBM, on the same graph, returns a block of 120 channels with almost no internal edges — channels Leiden had scattered across all six communities. Inspection shows they are pure amplifiers: each forwards from the same handful of source channels and is never cited by anyone. Leiden, hunting for density, distributed them by which source-neighbourhood they sat nearest; the SBM, hunting for role, recognised them as a single structural class — the network's audience, distinct from its producers.

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

Generated with `--consensus-matrix` (requires at least two partition-based strategies — i.e. excluding ORGANIZATION and K-core — active).

<figure>
<img src="../webapp_engine/static/screenshot_14.jpg" alt="Community consensus matrix">
<figcaption><em>Consensus matrix: larger red circles indicate channel pairs co-assigned to the same community by more algorithms.</em></figcaption>
</figure>
<br>

The consensus matrix answers: **across the partition-based strategies (every detection strategy except ORGANIZATION and the K-core shell decomposition), how consistently is each pair of channels placed in the same community?** For every pair, the count of strategies that co-assign them is computed and displayed as a lower-triangle balloon plot:

- **Radius** grows with agreement count
- **Colour** shifts from blue (low agreement) to red (full agreement)

Channels are sorted by plurality community assignment so that pairs from the same detected community cluster along the diagonal.

**In practice:** the consensus matrix reveals which groupings are robust and which are algorithm-dependent. A pair of channels with near-full agreement (large red balloon) is co-clustered by every algorithm — that grouping is stable regardless of which method you trust. A pair with low agreement is structurally ambiguous: the network evidence for placing them together or apart is genuinely weak. Pairs in the same manual Organization that consistently appear in different algorithmic communities are candidates for review.

---

## Community flow across years

When the export was built with a year timeline (`--timeline-step year`; see [Workflow § Timeline export](workflow.md#timeline-export)), the community table's full-range (**All**) view shows, beneath each strategy's table, a **Community flow** alluvial diagram — one column per year, that year's communities stacked as boxes, and ribbons carrying the channels that moved from one year's community into the next. Ribbon thickness is proportional to the number of channels; hovering a ribbon or box gives the exact count.

**Read continuity from the ribbons, not the colours.** Each year is partitioned *independently*, so a community's label, colour, and position carry no meaning across years — "community 3" in 2021 has nothing to do with "community 3" in 2022. What is meaningful is how a year's box flows into the next:

- **One thick ribbon** leaving a box → that cohort stayed together (whatever it was re-labelled). The community persisted.
- **A box fanning into several ribbons** → the community fragmented; its members dispersed into different clusters the following year.
- **Several ribbons converging on one box** → previously separate cohorts merged.
- **A box taller than the ribbons touching it** → churn: the unfilled part is channels that were not in the adjacent year's graph (they entered, left, or fell outside the in-target set that year). Ribbons stack from the top of each box, so this slack sits at the bottom.

Box colours come from each year's own community palette; a ribbon takes its **source** community's colour, so you can follow where one community's members disperse to. Communities within a column are ordered (and ribbons stacked) to minimise crossings, so straighter, more horizontal bands indicate a more stable partition over time. A year in which the strategy produced no communities is omitted, and the diagram is drawn only for strategies present in at least two timeline years.

**In practice:** a strategy whose alluvial is mostly straight, thick bands describes a stable community structure — the same blocs persist year over year. Heavy criss-crossing and fragmentation means the partition is volatile: either the underlying network is genuinely reorganising, or the strategy is resolution-sensitive on this data (compare against a steadier strategy, or against [Leiden CPM](#leiden-cpm) at a coarser resolution). Manual label-group partitions (e.g. an organisation axis) should flow almost perfectly straight — visible turbulence there points to channels whose attribution changed over the period.

---

## Choosing a strategy

| Research goal | Recommended strategy |
| :------------ | :------------------- |
| Use your own domain knowledge as the baseline | `ORGANIZATION` |
| Find all community structure, no prior knowledge | `LEIDEN` or `LEIDEN_DIRECTED` |
| Fast parameter-free baseline for large graphs | `LABELPROPAGATION` |
| Direction of citation matters | `LEIDEN_DIRECTED` |
| Find the ideological core vs. periphery | `KCORE` |
| Group channels by structural *role* (incl. source/amplifier, non-cohesive groups) | `SBM` |
| Probe at multiple granularities | `LEIDEN` + `LEIDEN_CPM(resolution=0.01)` + `LEIDEN_CPM(resolution=0.05)` |
| Reproduce / compare against an older study's classic modularity baseline | `LOUVAIN` (prefer `LEIDEN` for new work) |
| Compare algorithms for robustness | `ALL` + `--consensus-matrix` |

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

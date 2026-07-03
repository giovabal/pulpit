# Community detection

Community detection finds groups of channels that interact more with each other than with the rest of the network. Each algorithm uses a different notion of "interact" — citing each other, sharing sources, forming closed loops — and reveals a different facet of the same data.

Imagine you have a map of 400 channels. Community detection automatically draws the borders between neighbourhoods, without you having to decide in advance where the lines should fall.

Multiple strategies can be computed simultaneously and switched between in the graph viewer and table outputs.

<figure>
<img src="../webapp_engine/static/screenshot_00.jpg" alt="Structural 2D map coloured by communities">
<figcaption><em>Structural 2D map coloured by Leiden directed communities, print layout. Each colour cluster is one detected community.</em></figcaption>
</figure>
<br>

---

## Quick reference

| Strategy | CLI key | Type | Preserves direction? |
| :------- | :------ | :--- | :------------------- |
| Label groups | `LABELGROUP<id>` | Domain knowledge | — |
| Leiden | `LEIDEN` | Modularity | No |
| Leiden (directed) | `LEIDEN_DIRECTED` | Modularity | Yes |
| Leiden CPM | `LEIDEN_CPM(resolution=γ)` | Constant Potts Model | No |
| Louvain | `LOUVAIN` | Modularity (classic baseline) | No |
| K-core | `KCORE` | Structural hierarchy | No |
| Stochastic block model | `SBM(mode=…, weights=…, refine=…)` | Generative block model | Yes |
| Consensus | `CONSENSUS(threshold=τ)` | Cross-method agreement | Inherited from inputs |

(`LABELPROPAGATION` was removed in v0.27: it ignored both edge weights *and* direction, had a documented runaway-to-one-giant-community failure mode on dense cores, and its cheap-baseline role is better served by `CONSENSUS`. Old saved configurations that still name it load cleanly — the token is dropped on read.)

All algorithmic strategies can optionally run on the **disparity-filter backbone** of the citation graph instead of the full graph — see [Detection on a noise-filtered backbone](#detection-on-a-noise-filtered-backbone).

---

## Label groups

*Communities are the groupings you defined yourself — your own label-group partitions, used as a baseline.*

This is the only strategy family in Pulpit that is not an algorithm: the communities come from the **labels** you attach to channels in **Manage → Labels**. Labels live in *groups*, and any group you mark as a **partition** (a channel holds at most one of its labels at a time) can be carried into the analysis as a baseline — a political affiliation, a country, an editorial group, a funding source, whatever axis fits your investigation. Each partition group is selected on the CLI by the token `LABELGROUP<id>` (its database id; the Operations panel and the viewer show it by name). Because the labels come from you, this baseline is the most interpretable reference against which to read every algorithmic result.

One group is the **primary** group (conventionally named *Organization*): it supplies the node colour, the "Label" export column, and the vacancy-analysis actor identity. Label memberships are **time-bounded**, so a channel can hold different labels over different date intervals and its grouping can change over the study period; for each analysis window, a channel's "representative" label is the one whose periods cover the most days of the window.

**In practice:** use a partition label group as your reference grid. When an algorithmic community cuts across one of your labels — splitting one bloc into two, or merging two into one — the network is telling you something your labels do not capture, and that disagreement is where the most actionable findings tend to live. The label-group × community panel and the [partition-comparison matrices](whole-network-statistics.md#partition-comparison-matrices-ari-ami-nmi-vi) are designed exactly for this comparison.

**Example.** You sort 200 channels into five labels in your *Organization* group: far-right, mainstream right, centrist, left, and state media. The map coloured by that group shows that far-right and mainstream right channels sit close together and cross-reference heavily, while state media forms an isolated cluster that gets cited but rarely cites back. This already tells you something about who is amplifying whom — and gives you the baseline against which the algorithmic strategies below can be compared.

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

*Leiden (directed) works like Leiden but scores partitions against a null model that knows who cites and who gets cited. A worthwhile sensitivity check — but a weaker use of direction than its name suggests; for genuinely direction-driven grouping, reach for the [SBM](#stochastic-block-model).*

Standard Leiden compares each candidate community's internal density against what a random, direction-blind network would produce. The directed variant (Leicht & Newman 2008) refines only the *comparison*: the expected weight of an edge A→B becomes proportional to A's out-degree times B's in-degree, so a group of channels whose density is fully explained by "prolific citers pointing at popular targets" no longer scores as a community. Pulpit runs it on the original directed citation graph, with edge weights from `--edge-weight-strategy`. It is also the default community basis for the [within-module role measure](network-measures.md#within-module-role) — the role formula itself is direction-blind (it counts neighbours on both sides), so this choice of basis is where direction enters the role classification.

**Know the limit.** Direction enters *only* through that expected-weight term. The score still sums w(A→B) and w(B→A) under the same "are they in the same community?" test, so the objective **cannot distinguish the orientation of the links themselves** — a chain of one-way citations and a set of mutual alliances with the same weights and degrees score identically (Kim, Son & Jeong 2010 construct explicit counterexamples; the Malliaros & Vazirgiannis 2013 survey lists this as the directed modularity's first limitation). In practice, expect partitions close to undirected Leiden's, with occasional splits where the in/out-degree null bites. The strategy that actually *models* citation orientation — asymmetric block-to-block rates, source vs. amplifier roles — is the [stochastic block model](#stochastic-block-model).

**References:**
- Leicht, E.A. & Newman, M.E.J. (2008) "Community structure in directed networks." *Physical Review Letters* 100, 118703. [doi:10.1103/PhysRevLett.100.118703](https://doi.org/10.1103/PhysRevLett.100.118703) — the directed-modularity formulation.
- Kim, Y., Son, S.-W. & Jeong, H. (2010) "Finding communities in directed networks." *Physical Review E* 81, 016103. [doi:10.1103/PhysRevE.81.016103](https://doi.org/10.1103/PhysRevE.81.016103) — shows the generalised modularity "does not distinguish the direction of links".
- Malliaros, F.D. & Vazirgiannis, M. (2013) "Clustering and community detection in directed networks: A survey." *Physics Reports* 533(4), 95–142. [doi:10.1016/j.physrep.2013.08.002](https://doi.org/10.1016/j.physrep.2013.08.002) — the survey cataloguing that limitation.
- Traag, V.A. et al. (2019) "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports* 9, 5233. [doi:10.1038/s41598-019-41695-z](https://doi.org/10.1038/s41598-019-41695-z) — the Leiden refinement, inherited from [`LEIDEN`](#leiden).

**In practice:** run Leiden (directed) alongside plain Leiden as a degree-null sensitivity check: where the two agree, the grouping doesn't hinge on how direction is handled; where they diverge, the directed null is discounting hub-and-spoke density, which is worth inspecting. Picking it also matches the default basis of Pulpit's within-module-role classification, which resolves to this partition when no explicit basis is given. When the research question is genuinely about direction — who produces, who amplifies, which blocs cite which — pair it with (or prefer) the SBM rather than reading directional structure off this partition alone.

**Example.** Seven regional nationalist channels all forward from a single national aggregator with enormous in-degree. Under undirected Leiden, the aggregator's hub density pulls all eight into one community. Under Leiden (directed), the expected-weight term absorbs much of that density — it is exactly what "high out-degree channels citing a high in-degree target" predicts — so the seven amplifiers separate from the aggregator. The same data under the SBM goes further: it puts the seven in one *role block* (same citation profile) and the aggregator in another, and its block matrix states the direction of the relationship explicitly.

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

K-core decomposition repeatedly removes channels with too few internal connections, exposing progressively denser cores. A channel's "coreness" is the deepest layer it survives in: high coreness means it sits inside a tightly interconnected nucleus where every member is similarly embedded; low coreness means it gets shed in the first peeling rounds and lives on the periphery. The shell index is reported as **structure** — a nested hierarchy of mutual-citation embeddedness — and deliberately *not* as a spreading-influence score: the influential-spreader reading of coreness (Kitsak et al. 2010) presupposes a transmission process that forward-attribution data does not record, and it falters even on genuine transmission networks when core-like groups are present (Liu, Tang & Zhou 2015; see [Measures → what this catalogue covers](network-measures.md#what-this-catalogue-covers)). Pulpit's K-core is computed on the symmetrised view of the citation graph and is **unweighted** — it depends only on whether citations exist, not on how often. The partition is therefore invariant to the choice of `--edge-weight-strategy`. Communities are numbered from the innermost shell outwards, not by size: community 1 is the deepest core, community 2 the next shell out, and so on — the shell index *is* the information being reported.

**References:**
- Seidman, S.B. (1983) "Network structure and minimum degree." *Social Networks* 5(3). [doi:10.1016/0378-8733(83)90028-X](https://doi.org/10.1016/0378-8733(83)90028-X) — the k-core decomposition.
- Kitsak, M. et al. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6(11). [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746) — the influential-spreaders reading of coreness (cited for context; not adopted here — see above).
- Liu, Y., Tang, M. & Zhou, T. (2015) "Core-like groups result in invalidation of identifying super-spreader by k-shell decomposition." *Scientific Reports* 5:9602. [doi:10.1038/srep09602](https://doi.org/10.1038/srep09602) — why the spreader reading fails when core-like groups are present.

**In practice:** K-core is uniquely useful for identifying the ideological engine of a network — the small group of channels that drive the conversation and are all in dialogue with each other — as opposed to the much larger periphery that amplifies without originating. Because the partition is unweighted, a grouping that survives k-core peeling *and* modularity-based detection is structurally cohesive on two independent grounds.

**Example.** In a disinformation network of 300 channels, k-core decomposition reveals an innermost core of just eight channels. These eight regularly forward each other, share a consistent narrative frame, and publish the stories that the outer shells amplify hours later. They are the producers; the rest are distributors.

---

## Stochastic block model

*The SBM asks a different question from every other strategy here: not "where are the dense clusters?" but "which channels play the same role in the citation web?" — grouping channels that cite, and are cited by, the rest of the network in the same way.*

Every other detector in this list looks for **assortative** structure: groups that are dense inside and sparse outside. The stochastic block model drops that assumption. It is a *generative* model — it asks which assignment of channels to blocks best explains the observed pattern of citations, where the probability of a citation depends only on the two channels' blocks. Because the block-to-block citation rates are free to take any values, the SBM recovers structure the modularity family is blind to: not just assortative communities, but **disassortative** groups (channels that avoid each other), **core-periphery** layers, and the **bipartite source / amplifier** pattern that dominates a forward-attribution network — a set of amplifiers that all cite the same sources but never cite each other is a perfectly good block, even though it has zero internal density.

Pulpit fits a **directed, degree-corrected** SBM via [graph-tool](https://graph-tool.skewed.de/) (Peixoto). *Directed*: citation direction is preserved, so the block-affinity matrix is asymmetric — "block A cites block B" is distinct from the reverse, which is exactly the source-vs-amplifier signal. *Degree-corrected* (Karrer & Newman 2011): the model accounts for each channel's degree, so the blocks reflect citation structure **beyond** the raw in-degree heterogeneity of the star topology rather than simply lumping all the high-in-degree hubs together. By default the fit is **unweighted** (binary citation structure), so the partition is invariant to `--edge-weight-strategy` — set `weights=` to change that (below). Inference is by minimum description length, which is **self-regularising**: unlike modularity, the SBM will not invent blocks the data don't support, so it does not hallucinate community structure in a near-random graph.

The strategy takes three per-instance parameters and may be added once per parameter combination:

`mode` selects the inference variant:
- **`NESTED`** (default) — the nested SBM (Peixoto 2017) fits a hierarchy of blocks and Pulpit reports the partition at the finest level. Better model selection on large graphs; avoids the underfitting the flat model suffers on big networks.
- **`FLAT`** — a single-level SBM.

`weights` selects the edge model (Peixoto 2018, nonparametric *weighted* SBM):
- **empty** (default) — binary fit on the bare citation structure; how often channels cite each other doesn't influence the blocks, only *whether* they do.
- **`POISSON`** — edge weights enter the model as discrete counts. Pair with `--edge-weight-strategy TOTAL` (raw forward+mention counts); the fit rejects fractional weights with a clear error.
- **`EXPONENTIAL`** — edge weights enter as positive reals. Pair with the ratio-valued `PARTIAL_MESSAGES` / `PARTIAL_REFERENCES` strategies.

A weighted fit separates blocks the binary fit cannot: forty channels that each forwarded a source once and three channels that forward it daily have identical binary profiles but very different weighted ones. The block structure then reflects citation *intensity*, not just citation *existence* — at the cost of the partition now depending on your `--edge-weight-strategy` choice.

`refine` selects the inference depth:
- **empty** (default) — a single minimum-description-length point estimate: the one best partition found.
- **`MCMC`** — after the fit, the sampler explores the posterior distribution of partitions (multiflip MCMC equilibration, then a fixed sample of partitions) and reports each channel's **most probable block** across the samples (aligned via Peixoto 2021's partition-mode machinery), plus a new per-channel **SBM confidence** column: the share of posterior samples agreeing with the reported block. 1.0 means the data pin the channel's role down; a low value means the channel sits between roles and its assignment should not be leaned on. The column appears in the channel table, CSV/XLSX, and GEXF/GraphML exports, suffixed by the instance's parameters like every parameterised output (e.g. `sbm_confidence_mode_nested_refine_mcmc`). Slower — expect the SBM step to take several times longer.

> **Interpretation guardrail — blocks are roles, not cohesive groups.** An SBM block is a set of channels that are *stochastically equivalent* — they connect to the rest of the network the same way — i.e. a **citation-role / structural-equivalence class** (Lorrain & White 1971). It is **not** necessarily a community of mutually-citing channels: two channels can share a block while having no tie between them, simply because they cite the same sources and are cited by the same amplifiers. Read an SBM block as "these channels occupy the same structural position in the citation ecosystem", never as "these channels talk to each other". Likewise, a block-affinity entry is a one-step, group-to-group **direct citation rate** — not a claim that content flows from one block through to another. This keeps the SBM consistent with Pulpit's one-degree attribution model (see [Measures → interpretation guardrails](network-measures.md#what-this-catalogue-covers)), where multi-hop flow is not recoverable from the data.

**Dependency.** The SBM requires the `graph-tool` package, which is **not installable from pip** (it is a compiled C++ library). Install it via conda-forge (`conda install -c conda-forge graph-tool`) or your system package manager (Debian/Ubuntu: `apt install python3-graph-tool` from the maintainer's repository; a virtualenv must then be created with `--system-site-packages` to see it). If `graph-tool` is missing, requesting `SBM` fails with a clear error and the other strategies are unaffected.

**References:**
- Karrer, B. & Newman, M.E.J. (2011) "Stochastic blockmodels and community structure in networks." *Physical Review E* 83(1), 016107. [doi:10.1103/PhysRevE.83.016107](https://doi.org/10.1103/PhysRevE.83.016107) — the degree-corrected SBM.
- Peixoto, T.P. (2014) "Efficient Monte Carlo and greedy heuristic for the inference of stochastic block models." *Physical Review E* 89(1), 012804. [doi:10.1103/PhysRevE.89.012804](https://doi.org/10.1103/PhysRevE.89.012804) — the MDL inference Pulpit calls.
- Peixoto, T.P. (2017) "Nonparametric Bayesian inference of the microcanonical stochastic block model." *Physical Review E* 95(1), 012317. [doi:10.1103/PhysRevE.95.012317](https://doi.org/10.1103/PhysRevE.95.012317) — the nested SBM.
- Peixoto, T.P. (2018) "Nonparametric weighted stochastic block models." *Physical Review E* 97, 012306. [doi:10.1103/PhysRevE.97.012306](https://doi.org/10.1103/PhysRevE.97.012306) — the edge-covariate model behind `weights=`.
- Peixoto, T.P. (2021) "Revealing consensus and dissensus between network partitions." *Physical Review X* 11, 021003. [doi:10.1103/PhysRevX.11.021003](https://doi.org/10.1103/PhysRevX.11.021003) — the partition-alignment machinery behind `refine=MCMC`'s max-marginal partition and confidence column.
- Lorrain, F. & White, H.C. (1971) "Structural equivalence of individuals in social networks." *Journal of Mathematical Sociology* 1(1). [doi:10.1080/0022250X.1971.9989788](https://doi.org/10.1080/0022250X.1971.9989788) — the structural-equivalence notion that a block operationalises.

**In practice:** reach for the SBM when modularity-based detection feels like it is fighting the data — when you suspect the network is hub-and-spoke or two-mode rather than a set of cohesive cliques. Because it separates *role* from *cohesion*, the SBM is the natural complement to Leiden: where Leiden tells you which channels cluster together, the SBM tells you which channels are interchangeable in the citation structure (e.g. "these forty amplifiers are structurally the same actor, pointed at the same three sources"). Compare it against `LEIDEN_DIRECTED` in the consensus matrix, and against your label-group baseline in the partition-comparison matrices — but remember the partitions answer different questions, so disagreement is expected and informative, not a failure.

**Example.** A network of 500 channels yields six tidy Leiden communities. The SBM, on the same graph, returns a block of 120 channels with almost no internal edges — channels Leiden had scattered across all six communities. Inspection shows they are pure amplifiers: each forwards from the same handful of source channels and is never cited by anyone. Leiden, hunting for density, distributed them by which source-neighbourhood they sat nearest; the SBM, hunting for role, recognised them as a single structural class — the network's audience, distinct from its producers.

---

## Consensus

*The consensus strategy turns "which groupings survive across methods?" from a visual judgement into a partition of its own: channels are grouped together only when at least a threshold share of the other selected algorithms agree they belong together.*

Every detector in this catalogue embodies one notion of community, and each can be led astray by its own blind spot — modularity's resolution limit, a weighting choice, one algorithm's tie-breaking. Consensus clustering (Lancichinetti & Fortunato 2012) hedges across them: take the partitions the run has already computed, count for every pair of channels the fraction of partitions that co-assign them (the **co-assignment matrix**), keep only pairs at or above the **threshold τ** (`threshold`, default 0.5 — a majority), and cluster the resulting agreement graph (Pulpit uses the same seeded Leiden machinery as `LEIDEN`, weighted by the agreement fractions). The output is an ordinary partition: it colours the map, fills a column in every table and export, and — most usefully — joins the [partition-comparison matrices](whole-network-statistics.md#partition-comparison-matrices-ari-ami-nmi-vi), where "how much of the analyst's labelling survives cross-method agreement" becomes a single ARI/AMI number.

**Inputs.** All other selected *algorithmic* strategies feed it — the Leiden family, Louvain, the SBM instances — with two exclusions: `KCORE` (a shell decomposition, not a community detection) and your `LABELGROUP<id>` partitions (the consensus should stay a purely structural result you can then compare *against* the labels). At least **two eligible inputs** must be selected or the run refuses to start. Add the strategy more than once with different thresholds (`CONSENSUS(threshold=0.5),CONSENSUS(threshold=0.9)`) to see agreement cores tighten as τ rises. Channels that no sufficient coalition of algorithms can place end up as singletons — an honest "no consensus" rather than a forced assignment.

**Adaptation note.** Lancichinetti & Fortunato iterate their procedure — recluster the co-assignment matrix repeatedly until it turns block-diagonal — because their inputs are many runs of one *stochastic* algorithm. Pulpit's inputs are deterministic (every strategy is seeded), so after the first clustering pass the procedure is at a fixed point; the single pass Pulpit runs is the faithful specialisation, not a shortcut. This is *method* consensus — one run each of different algorithms, in the lineage of ensemble practice in political-network research (e.g. Evkoski et al. 2021's Ensemble Louvain) — rather than *run* consensus over stochastic restarts.

**References:**
- Lancichinetti, A. & Fortunato, S. (2012) "Consensus clustering in complex networks." *Scientific Reports* 2, 336. [doi:10.1038/srep00336](https://doi.org/10.1038/srep00336) — the co-assignment/threshold/recluster procedure.
- Evkoski, B., Mozetič, I., Ljubešić, N. & Kralj Novak, P. (2021) "Community evolution in retweet networks." *PLOS ONE* 16(9), e0256175. [doi:10.1371/journal.pone.0256175](https://doi.org/10.1371/journal.pone.0256175) — ensemble (consensus) community detection in applied political-network research.

**In practice:** run it alongside `LEIDEN`, `LEIDEN_DIRECTED`, `LOUVAIN`, and `SBM`, and treat its communities as the *defensible core* of the analysis — groupings you can report without the caveat "under algorithm X". It is the partition-valued companion of the [consensus matrix](#consensus-matrix): the balloon plot shows pairwise agreement for inspection, the consensus strategy commits to the partition those agreements imply (and is excluded from the matrix's own inputs, which it would double-count). Report contested channels too: a channel that is a singleton here but confidently placed by individual algorithms is exactly the kind of boundary case worth a qualitative look.

**Example.** Four strategies partition a 300-channel network. Three of them keep a cluster of twelve regional channels together; the fourth splits it. At τ = 0.5 the consensus keeps the twelve intact (3/4 ≥ τ) — but two other channels that only ever co-cluster with them under a single strategy fall out as singletons. The write-up can now say "these twelve channels form a community under every reasonable structural definition", and the two singletons get flagged for manual review instead of being silently absorbed.

---

## Detection on a noise-filtered backbone

*`--community-backbone-alpha` runs every algorithmic strategy on the statistically significant skeleton of the citation graph, so one-off forwards of a viral post don't glue unrelated blocs together.*

A long crawl accumulates many **incidental** edges: a channel forwarded something from another exactly once, two years ago. Each such edge is individually negligible, but collectively they blur community boundaries — modularity-family detectors happily merge two blocs connected by enough one-off noise. The disparity filter (Serrano, Boguñá & Vespignani 2009) removes them on a principled, *per-channel* basis: an edge is kept only when it carries significantly more of one of its endpoints' citation weight than an even spread across that channel's partners would predict (significance < α). Because the test is local, it preserves the strong ties of small channels rather than just keeping the globally heaviest edges — which is what a naive weight threshold would do.

Setting `--community-backbone-alpha 0.05` (0 = off, the default; the Operations panel exposes it as *Community backbone α* under Computation) makes **community detection alone** run on this backbone:

- Every algorithmic strategy — the Leiden family, Louvain, K-core, SBM, and (through its inputs) the consensus partition — sees the filtered graph. Channels whose every edge is filtered away become isolated for detection purposes and are folded into one residual community, exactly like channels that were isolated to begin with.
- Label-group partitions are untouched (they read your labels, not the graph).
- **Everything else stays on the full graph** — measures, layout, node/edge counts, tables, exports. The backbone is a lens for detection, not a modified dataset.
- Reported **modularity** for the detected partitions is computed against the backbone they were optimised on (the community table's preamble says so when the flag was used); all other per-community metrics keep describing the full graph.

The same filter, with the same α convention, already powers the [robustness analysis](robustness-analysis.md)'s attack backbone — this flag brings it to the detection stage. The precedent for backboning *before* community detection on Telegram forwarding networks is Zehring & Domahidi (2023), who filtered at α = 0.05 before running community detection on the German corona-protest network.

**References:**
- Serrano, M.Á., Boguñá, M. & Vespignani, A. (2009) "Extracting the multiscale backbone of complex weighted networks." *PNAS* 106(16), 6483–6488. [doi:10.1073/pnas.0808904106](https://doi.org/10.1073/pnas.0808904106) — the disparity filter.
- Zehring, M. & Domahidi, E. (2023) "German Corona Protest Mobilizers on Telegram and Their Relations to the Far Right: A Network and Topic Analysis." *Social Media + Society* 9(1). [doi:10.1177/20563051231155106](https://doi.org/10.1177/20563051231155106) — disparity-filter backboning before community detection on a Telegram forwarding network.

**In practice:** leave the flag off for a first look, then re-run with α = 0.05 and compare partitions in the [partition-comparison matrices](whole-network-statistics.md#partition-comparison-matrices-ari-ami-nmi-vi): communities that survive backboning rest on repeated, significant citation ties; groupings that dissolve were held together by incidental edges. On a year timeline the filter is re-applied within each year's graph. Note that the weight-dependence of the filter means `--edge-weight-strategy` now matters even for the otherwise weight-blind detectors (label propagation, K-core, unweighted SBM) — the α test runs on the edge weights.

---

## Cross-strategy analysis

<figure>
<img src="../webapp_engine/static/screenshot_03.jpg" alt="Community table">
<figcaption><em>Community table: structural metrics per community for each detection strategy side by side.</em></figcaption>
</figure>
<br>

### Label group × community distribution

For each algorithmic strategy, the community table includes a collapsible **‹label group› × community distribution** panel — one per partition label group, the primary group first (so for a default install the first panel is *Organization × community distribution*). Each panel holds two cross-tabulation tables:

- **% of label nodes per community** (rows sum to 100%): for each label, what fraction of its channels ended up in each detected community? A row concentrated in one column means that label maps cleanly to a single algorithmic cluster; a spread-out row means the label was split across multiple communities.
- **% of community nodes per label** (columns sum to 100%): for each detected community, what fraction comes from each label? A column dominated by one label means the community is label-pure; a mixed column means the algorithm grouped channels from different labels together.

Columns are sorted so that each label's dominant community falls as close to a diagonal as possible (Hungarian algorithm), making alignment easy to read at a glance.

**In practice:** compare the two tables to understand mismatches between your domain-knowledge groupings and the algorithm's output. High purity on both sides confirms the algorithm. A spread-out row for one label signals that the algorithm sees structure *within* what you treated as a single bloc — a prompt to investigate whether that label should be split.

### Consensus matrix

Generated with `--consensus-matrix` (requires at least two algorithmic partition strategies — i.e. excluding your label-group partitions and K-core — active).

<figure>
<img src="../webapp_engine/static/screenshot_14.jpg" alt="Community consensus matrix">
<figcaption><em>Consensus matrix: larger red circles indicate channel pairs co-assigned to the same community by more algorithms.</em></figcaption>
</figure>
<br>

The consensus matrix answers: **across the partition-based strategies (every detection strategy except your label-group partitions and the K-core shell decomposition), how consistently is each pair of channels placed in the same community?** For every pair, the count of strategies that co-assign them is computed and displayed as a lower-triangle balloon plot:

- **Radius** grows with agreement count
- **Colour** shifts from blue (low agreement) to red (full agreement)

Channels are sorted by plurality community assignment so that pairs from the same detected community cluster along the diagonal.

**In practice:** the consensus matrix reveals which groupings are robust and which are algorithm-dependent. A pair of channels with near-full agreement (large red balloon) is co-clustered by every algorithm — that grouping is stable regardless of which method you trust. A pair with low agreement is structurally ambiguous: the network evidence for placing them together or apart is genuinely weak. Pairs in the same manual label group that consistently appear in different algorithmic communities are candidates for review.

### Community intersection (Sankey)

At the foot of the community table is an interactive **Community intersection** Sankey: pick **any two strategies** and a **year** (or *All years*), and it draws the two partitions side by side — strategy A's communities as boxes on the left, strategy B's on the right — with a ribbon for every pair of communities that share channels. Each ribbon's thickness is the **number of channels in both** communities, i.e. the cross-tabulation (contingency table) of the two partitions rendered as flows. Hovering a ribbon gives the exact count, and **clicking a ribbon lists the shared channels** beneath the diagram as channel cards in the `/channels/` layout (avatar, organisation, message/follower counts, activity span). Box colours come from each strategy's own palette and ribbons take their left-hand community's colour. Columns are ordered to minimise crossings, so a clean near-one-to-one mapping shows up as straight, roughly horizontal bands.

This is the per-pair, per-community companion to the whole-graph agreement scores in the **Partition comparison** matrices higher up the same page (ARI / AMI / NMI / VI; see [Partition comparison matrices](whole-network-statistics.md#partition-comparison-matrices-ari-ami-nmi-vi)): where those give a single number for how well two partitions agree, the Sankey shows *where* they agree and where they diverge. The year selector reuses the timeline snapshots (when the export was built with `--timeline-step year`), so you can inspect a single year in isolation.

**In practice:** intersect an algorithmic strategy against a manual label group (e.g. *Leiden × Organisation*) to see, community by community, which detected clusters line up with which organisations and which cut across them — a single fat ribbon means the detected community *is* that organisation; a box fanning into several ribbons means the algorithm split (or merged) what the labels treat as one bloc. Intersecting two algorithms (e.g. *Leiden × Louvain*) localises exactly which communities are stable across methods and which are the source of any disagreement the summary indices report.

---

## Community flow across years

When the export was built with a year timeline (`--timeline-step year`; see [Workflow § Timeline export](workflow.md#timeline-see-how-the-network-changed-over-time)), the community table's full-range (**All**) view shows, beneath each strategy's table, a **Community flow** alluvial diagram — one column per year, that year's communities stacked as boxes, and ribbons carrying the channels that moved from one year's community into the next. Ribbon thickness is proportional to the number of channels; hovering a ribbon or box gives the exact count, and **clicking a ribbon lists the channels travelling along that flow** beneath the diagram as channel cards in the `/channels/` layout.

**Read continuity from the ribbons, not the colours.** Each year is partitioned *independently*, so a community's label, colour, and position carry no meaning across years — "community 3" in 2021 has nothing to do with "community 3" in 2022. What is meaningful is how a year's box flows into the next:

- **One thick ribbon** leaving a box → that cohort stayed together (whatever it was re-labelled). The community persisted.
- **A box fanning into several ribbons** → the community fragmented; its members dispersed into different clusters the following year.
- **Several ribbons converging on one box** → previously separate cohorts merged.
- **A box taller than the ribbons touching it** → churn: the unfilled part is channels that were not in the adjacent year's graph (they entered, left, or fell outside the in-target set that year). Ribbons stack from the top of each box, so this slack sits at the bottom.

Box colours come from each year's own community palette; a ribbon takes its **source** community's colour, so you can follow where one community's members disperse to. Communities within a column are ordered (and ribbons stacked) to minimise crossings, so straighter, more horizontal bands indicate a more stable partition over time. A year in which the strategy produced no communities is omitted, and the diagram is drawn only for strategies present in at least two timeline years.

**In practice:** a strategy whose alluvial is mostly straight, thick bands describes a stable community structure — the same blocs persist year over year. Heavy criss-crossing and fragmentation means the partition is volatile: either the underlying network is genuinely reorganising, or the strategy is resolution-sensitive on this data (compare against a steadier strategy, or against [Leiden CPM](#leiden-cpm) at a coarser resolution). Manual label-group partitions (e.g. an organisation axis) should flow almost perfectly straight — visible turbulence there points to channels whose labels changed over the period.

---

## Choosing a strategy

| Research goal | Recommended strategy |
| :------------ | :------------------- |
| Use your own domain knowledge as the baseline | `LABELGROUP<id>` |
| Find all community structure, no prior knowledge | `LEIDEN` or `LEIDEN_DIRECTED` |
| Direction of citation matters | `SBM` (and `LEIDEN_DIRECTED` as a sensitivity check) |
| Find the ideological core vs. periphery | `KCORE` |
| Group channels by structural *role* (incl. source/amplifier, non-cohesive groups) | `SBM` |
| Probe at multiple granularities | `LEIDEN` + `LEIDEN_CPM(resolution=0.01)` + `LEIDEN_CPM(resolution=0.05)` |
| Reproduce / compare against an older study's classic modularity baseline | `LOUVAIN` (prefer `LEIDEN` for new work) |
| One robust partition where the methods agree | `CONSENSUS` (with ≥2 other algorithmic strategies) |
| Compare algorithms for robustness | `ALL` + `--consensus-matrix` |
| Keep incidental one-off forwards out of the communities | any of the above + `--community-backbone-alpha 0.05` |

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

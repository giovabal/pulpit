# Vacancy analysis

Vacancy Analysis addresses a different class of question from standard network measures. Not *how is this network structured right now?* but *who replaced this channel after it disappeared?*

---

## The problem

Channels go silent for many reasons: voluntary deletion, platform removal, legal action, internal collapse. When a channel disappears it leaves a **structural hole** — a set of channels that previously relied on it as a source are now missing an input. The question is whether someone fills that hole, and if so, who.

In practice, this matters because structural heirs are often more significant than their raw metrics suggest. A new channel with few subscribers but a high neighbour-set equivalence score is already occupying the same position in the information ecosystem as the channel it replaced. Conversely, a channel with many followers that happens to attract some of the same amplifiers may be an opportunist capitalising on an audience vacuum, not a genuine continuation of the same network role.

**Example.** In October 2023, a prominent pro-Kremlin aggregator with 280,000 subscribers stops posting. Over three months, the twelve channels that used to forward it start forwarding two new channels heavily. Vacancy Analysis scores both: one scores high across all metrics — same distributors, same upstream sources, same brokerage role, similar cascade reach, quickly adopted by the orphaned amplifiers. It is a structural heir. The other gets forwarded by the same distributors but draws from entirely different sources and is adopted much more slowly — an opportunist capitalising on the audience vacuum.

---

## Registering a vacancy

A vacancy is not inferred automatically. An analyst manually registers a channel as a vacancy in **Manage → Vacancies**, providing a **closure date** — the point in time when the channel ceased to be active.

The closure date is the analytical boundary:
- The period **before** it is used to characterise the vacancy channel's structural role
- The period **after** it is searched for replacement candidates

All registered vacancies are listed at **Channels → Vacancies** (`/channels/vacancies/`), which shows each channel's last-known in-degree, out-degree, and the count of orphaned amplifiers.

---

## Finding replacement candidates

Any channel with a vacancy record gains a **Vacancy Analysis** card on its detail page. The analyst sets three parameters:

| Parameter | Default | Meaning |
| :-------- | :------ | :------ |
| **Months before** | 12 | How far back before the closure date to characterise the vacancy's structural role |
| **Months after** | 24 | How far forward after the closure date to search for replacement activity |
| **Only after vacancy** | On | When on, restricts candidates to channels whose first message is on or after the closure date — ensuring they are genuinely new rather than pre-existing channels that happened to start being forwarded by the same amplifiers |


<figure>
<img src="../webapp_engine/static/screenshot_21.jpg" alt="Vacancy analysis for a channel">
<figcaption><em>Vacancy analysis for a channel, with proposed replacements.</em></figcaption>
</figure>
<br>

The analysis proceeds in two steps:

**Step 1 — Identify orphaned amplifiers.** Find all monitored channels that forwarded content from the vacancy channel in the *before* window. These are the channels whose source has disappeared — the structural gap they now need to fill from somewhere else.

**Step 2 — Find replacement candidates.** Look at what those same orphaned amplifiers began forwarding from in the *after* window. Channels that appear as new forwarding targets for multiple orphaned amplifiers are replacement candidates. They are then scored by how structurally similar they are to the vacancy.

---

## Scoring

Each replacement candidate is scored on up to six complementary metrics ranging from 0 to 1. Scores A–C appear in both the interactive per-channel card and the batch export; Scores D–F are batch-only, enabled via `--vacancy-measures`.

---

### Score A — Amplifier Coverage

*The fraction of the vacancy's old amplifiers that now also amplify the candidate — a direct read of audience inheritance.*

When a vacancy closes, the in-target channels that used to forward from it — the **orphaned amplifiers** — are left without that input. Amplifier Coverage asks, for each replacement candidate, what share of those same orphaned amplifiers has been observed forwarding the candidate in the after-window. It is an asymmetric set overlap, bounded in `[0, 1]`:

```
score_a = |orphaned_amplifiers ∩ candidate_amplifiers| / |orphaned_amplifiers|
```

The numerator is the count of *distinct* orphaned channels with at least one forward of the candidate in the after-window; tie strength is ignored. The **Amplifiers** column on the same row carries the absolute numerator alongside the normalised score. A score of 1.0 means every orphaned amplifier has re-pointed to the candidate; 0.0 means none have.

The measure is the information-retrieval definition of **recall**, applied to amplifier sets rather than retrieved documents — the same shape that the audience-fragmentation literature uses to map media systems through audience-overlap networks.

**References:**
- Salton, G. & McGill, M.J. (1983) *Introduction to Modern Information Retrieval.* McGraw-Hill. — recall as `|relevant ∩ retrieved| / |relevant|`, the mathematical definition the score instantiates.
- Webster, J.G. & Ksiazek, T.B. (2012) "The Dynamics of Audience Fragmentation: Public Attention in an Age of Digital Media." *Journal of Communication* 62(1):39–56. [doi:10.1111/j.1460-2466.2011.01616.x](https://doi.org/10.1111/j.1460-2466.2011.01616.x) — audience-overlap networks: the social-science framing, where outlets are linked by the share of audience they have in common (here amplifiers stand in for audience members).

**In practice:** Amplifier Coverage is the most direct evidence of audience inheritance and the natural first filter when triaging a vacancy. A high score is *necessary but not sufficient* for a structural heir: it shows the vacancy's distribution network has re-attached to the candidate, but says nothing about whether the candidate also draws from the same upstream sources (Neighbour-set Equivalence), bridges the same organisational divides (Brokerage overlap), reaches the same downstream channels through content cascades (Cascade Overlap), or is well-embedded in the orphaned channels' upstream supply chain (Personalized PageRank). Conversely, a candidate with a low Amplifier Coverage rarely deserves attention on the other five scores — the vacancy's distributors have not picked it up. Read this column first; the other five tell you what kind of successor a high-coverage candidate actually is.

**Example.** A pro-Kremlin aggregator with twelve in-target amplifiers stops posting on the 14th of October. In the 24 months that follow, three candidates surface. Candidate X is forwarded by eleven of the twelve orphaned amplifiers — Amplifier Coverage 0.92; Y by four — 0.33; Z by one — 0.08. Candidate X has clearly inherited the vacancy's distribution network; Y has picked up a partial slice; Z is barely on the same radar. The score does not yet tell you *whether* X is a genuine structural heir or an opportunist who happened to absorb the audience gap — that is what the other five scores are for — but it tells you X is the candidate worth reading them on.

---

### Score B — Neighbour-set Equivalence

*How much of the candidate's amplifier set and source set overlaps the vacancy's — a topological test of whether the candidate sits in the same network position.*

Two channels share the same **structural position** when the rest of the network treats them interchangeably: they are amplified by the same channels and they forward from the same sources. The vacancy left behind a position defined by its in-neighbours (the orphaned amplifiers) and its out-neighbours (the channels it forwarded from in the before-window). Score B asks, for each candidate, how closely its own in- and out-neighbour sets — measured in the after-window — match the vacancy's. It is the unweighted average of two **Ochiai (binary cosine)** similarities, one per side of the citation relation:

```
cos_in  = |vacancy_amplifiers ∩ candidate_amplifiers| / √(|vacancy_amplifiers| · |candidate_amplifiers|)
cos_out = |vacancy_sources    ∩ candidate_sources|    / √(|vacancy_sources|    · |candidate_sources|)
score_b = ½ · cos_in + ½ · cos_out
```

`vacancy_amplifiers` is the orphaned set — the in-target channels that forwarded from the vacancy in the before-window. `candidate_amplifiers` is the candidate's *full* in-target amplifier set in the after-window: every channel that forwarded from the candidate while in-target, not just the orphaned ones. So two candidates with identical Amplifier Coverage can score very differently here — a candidate forwarded only by the ten orphans scores higher than one forwarded by the same ten plus a hundred other channels, because the larger denominator drags the cosine down. `vacancy_sources` and `candidate_sources` are the channels each one forwarded from in its window. All four sets are period-aware: a forward counts only when its channel was inside an in-target attribution period at the message date, matching the rest of the pipeline.

Tie strength is ignored — only set membership counts — so this is the *binary* cousin of the **Structural equivalence matrix** the structural analysis writes (`network/community_stats.py:_compute_structural_equivalence`), which is a **weighted** cosine over the full in + out tie *profile* across every node pair. The two answer related questions with different maths and are kept apart in the UI: this one is labelled *Neighbour-set Equivalence*. Out-similarity collapses to zero for high-originality vacancies that rarely forward (the vacancy source set is empty), in which case the score reflects in-similarity alone.

**References:**
- Lorrain, F. & White, H.C. (1971) "Structural equivalence of individuals in social networks." *Journal of Mathematical Sociology* 1(1):49–80. [doi:10.1080/0022250X.1971.9989788](https://doi.org/10.1080/0022250X.1971.9989788) — the foundational definition: two actors are structurally equivalent iff they hold identical relations to identical others. Score B is the set-overlap relaxation of that equality, which is otherwise degenerate on real data.
- Wasserman, S. & Faust, K. (1994) *Social Network Analysis: Methods and Applications.* Cambridge University Press, chapter 9. — the canonical treatment of similarity-based structural equivalence in SNA, including the cosine-on-relational-vectors formulation Score B instantiates on binary in- and out-neighbour sets.
- Leicht, E.A., Holme, P. & Newman, M.E.J. (2006) "Vertex similarity in networks." *Physical Review E* 73:026120. [doi:10.1103/PhysRevE.73.026120](https://doi.org/10.1103/PhysRevE.73.026120) — the modern vertex-similarity form `|N(u) ∩ N(v)| / √(|N(u)| · |N(v)|)`, separable into in- and out-neighbour components for directed graphs.

**In practice:** Score B is the topological successor test, complementary to Score A. Amplifier Coverage tells you whether the vacancy's distributors picked up the candidate; Score B tells you whether they re-attached to a candidate that *also looks like the vacancy from the rest of the network's point of view*. A candidate with high A but low B has absorbed the audience without taking on the editorial role: typically a broad-reach aggregator that everybody forwards anyway. A candidate with high B has slotted into the same in/out neighbourhood and is the structural heir even when its raw reach is smaller. The out-side of the score, in particular, catches something Amplifier Coverage cannot see at all: whether the candidate draws on the same upstream pool — the same correspondents, agencies, regional outlets — as the vacancy did. For a vacancy that rarely forwarded anything (an originator rather than a curator), the out-similarity collapses to zero and the score reflects in-similarity alone; read it together with Score A in that case, not in isolation.

**Example.** A pro-Kremlin aggregator with twelve orphaned amplifiers stops posting on the 14th of October; in the year before, it forwarded from sixteen upstream channels (state outlets, war-correspondent feeds, three regional aggregators). Candidate X, a smaller new channel, is forwarded by ten of the twelve orphans and by no other in-target channel, and forwards from fourteen of the same sixteen sources plus two new regionals: cos_in = 10 / √(12 · 10) ≈ 0.91, cos_out = 14 / √(16 · 16) ≈ 0.88, Score B ≈ 0.90 — a near-perfect structural heir. Candidate Y is forwarded by the same ten orphans, but also by sixty other in-target channels, and forwards from forty upstream channels of which only three overlap the vacancy's set: cos_in = 10 / √(12 · 70) ≈ 0.35, cos_out = 3 / √(16 · 40) ≈ 0.12, Score B ≈ 0.23 — an opportunist that absorbed part of the audience while serving a different editorial niche. Both have an identical Amplifier Coverage of 10/12 ≈ 0.83; only Score B tells X and Y apart.

---

### Score C — Brokerage overlap

*The overlap between the set of organisation-pairs the vacancy mediated between and the set the candidate mediates between — a positional test of whether the candidate inherits the same inter-organisational bridging role.*

Politically significant channels often act as **brokers** between distinct organisations, carrying content from one organisational ecosystem (a state outlet, say) and delivering it to amplifiers in another (a partisan aggregator). When such a broker disappears, the question is whether some other channel now sits in the same position — mediating flows between the same organisational pairs. Score C answers it as a **Jaccard similarity** between two sets of (source-organisation, amplifier-organisation) pairs, the *brokerage profiles* of the vacancy and each candidate:

```
vacancy_pairs   = { (org(s), org(a)) : s ∈ vacancy_sources_before, a ∈ orphaned_amplifiers }
candidate_pairs = { (org(s), org(a)) : s ∈ candidate_sources_after, a ∈ orphans_that_amplify_candidate }
score_c         = |vacancy_pairs ∩ candidate_pairs| / |vacancy_pairs ∪ candidate_pairs|
```

Organisation membership is **time-bounded** (`ChannelAttribution`): each source's organisation is resolved at the date of the forward, and each orphaned amplifier's at the closure date — matching how the rest of the pipeline handles attribution. The candidate's amplifier side is intentionally restricted to orphans that forward the candidate, rather than to every channel that forwards it: this keeps the amplifier universe comparable to the vacancy's (whose amplifiers are by definition the orphaned set) and aligns the score with the succession question. The Cartesian product of source-orgs and amplifier-orgs gives an upper bound on the broker's role profile — not every observed (source, amplifier) pair corresponds to an actual source→broker→amplifier triad on the same message — but the vacancy and the candidate are measured the same way, so the comparison is fair. The score is `—` (null) when the vacancy's neighbourhood contained no channels with organisation assignments, since there is then no profile to compare against.

This operationalises the **concept** of brokerage roles from inter-group mediation theory as positional overlap of bridged organisation-pairs. It is **not** the Gould-Fernandez brokerage *census*, which classifies each mediating triad into one of five roles (coordinator, gatekeeper, representative, consultant, liaison) — hence the UI label **Brokerage overlap** rather than "Brokerage roles".

**References:**
- Gould, R.V. & Fernandez, R.M. (1989) "Structures of mediation: A formal approach to brokerage in transaction networks." *Sociological Methodology* 19:89–126. [doi:10.2307/270949](https://doi.org/10.2307/270949) — the foundational treatment of brokerage as mediation between actors in distinct groups; Score C measures positional overlap in this sense without classifying the specific triadic role.
- Burt, R.S. (2004) "Structural holes and good ideas." *American Journal of Sociology* 110(2):349–399. [doi:10.1086/421787](https://doi.org/10.1086/421787) — the strategic significance of brokering across organisational divides; structural-hole brokers control which content crosses the gap between groups, which is exactly the position Score C asks about.

**In practice:** Brokerage overlap is the organisation-level position complement to Scores A and B. Amplifier Coverage tells you whether the vacancy's distributors picked up the candidate (channel-level); Neighbour-set Equivalence tells you whether the candidate sits in the same in- and out-neighbourhood (channel-level); Score C lifts the question to organisations and asks whether the candidate inherits the *cross-group brokerage* the vacancy performed. A candidate can score high on A and B but low on C when the orphaned amplifiers re-attached and the topological neighbourhood matches, yet the candidate draws from a narrower or partisan-aligned source set and so does not bridge the same organisational divides. The reverse pattern — low A or B with high C — means the same organisational divides are still being bridged, but by a channel the orphaned set has not (yet) widely adopted: the brokerage role survives without an obvious individual heir. The score returns `—` for vacancies whose neighbourhood lacks organisation assignments, or whose neighbourhood collapses to a single organisation (no divides to bridge); in those cases read Scores A and B alone.

**Example.** The same pro-Kremlin aggregator that goes silent on the 14th of October. In the year before, it forwarded from channels in three source organisations — a state news agency (**State**), war-correspondent feeds (**War**), and regional aggregators (**Regional**) — and was amplified by twelve orphans split evenly across three amplifier organisations: religious-conservative (**Trad**), economic-nationalist (**Econat**), and military-affiliated (**MilAff**). Its brokerage profile is the 3 × 3 = 9 organisation-pairs {(State, Trad), (State, Econat), …, (Regional, MilAff)}. Candidate X is forwarded by ten of the twelve orphans, drawn from all three amplifier orgs, and itself forwards from the same three source orgs — its profile is the same 9 pairs, score_c = 9 / 9 = 1.00, a near-perfect brokerage heir. Candidate Y is also forwarded by ten orphans across all three amplifier orgs, but forwards from State outlets and from a diaspora-media organisation (**Diaspora**) the vacancy never used — its profile is the 2 × 3 = 6 pairs {(State, Trad), (State, Econat), (State, MilAff), (Diaspora, Trad), (Diaspora, Econat), (Diaspora, MilAff)}, of which the three State-pairs overlap the vacancy's. Jaccard = 3 / (9 + 6 − 3) = 3 / 12 = 0.25 — Y inherits a slice of the brokerage role along the State-organisation axis but routes the rest of its sources through a different ecosystem, a partial successor rather than a structural heir. Both X and Y share the same Amplifier Coverage (10/12 ≈ 0.83) and very similar Neighbour-set Equivalence on the in-side; Brokerage overlap is the score that separates them on the cross-organisational dimension neither A nor B can see.

---

### Score D — Cascade overlap

*Whether a Monte Carlo SIR (Susceptible–Infected–Recovered) cascade seeded at the candidate after closure reaches the same downstream channels that the vacancy's cascade used to reach before closure — a dynamical successor test rather than a topological one.*

Scores A–C compare the candidate's *static* neighbourhood to the vacancy's: who forwards them, what they forward from, what organisational pairs they bridge. Score D asks a different question: when content is seeded at the candidate and allowed to propagate through the network via probabilistic forwards, does it eventually reach the same downstream channels that used to receive the vacancy's content? Two channels can share most of their direct amplifiers and still cascade to entirely different audiences — different mid-tier amplifiers reshare them, and a few-hop walk through the forward graph lands in different communities — and conversely, two channels with little immediate overlap can light up the same downstream basin if their amplifiers feed into the same secondary distributors.

The computation builds two SIR substrates:

- **Before subgraph** — every in-target channel plus the vacancy. Edges run `source → amplifier` (information-flow direction) with transmission probability equal to the fraction of the amplifier's window-restricted forwards that came from that source — so an amplifier that drew most of its content from one source transmits that source's cascade with high probability, while an aggregator drawing equally from many sources transmits each with low probability. Built from `Message.objects.alive()` filtered to the before-window and the period-aware `channel_cutoff_q()` chokepoint, so each forward counts only when the amplifier was in-target on the message date.
- **After subgraph** — same construction in the after-window, with the vacancy removed (it can neither transmit nor be transmitted to once closed).

For each focal channel, an SIR process is seeded at that channel and run for `--spreading-runs` independent Monte Carlo replicates (default 200; per-step recovery probability γ = 0.3, mean infectious period ≈ 3 steps; the SIR engine — `network/measures/_spreading.py:sir_ever_infected` — is shared with the per-channel **Spreading Efficiency** measure). A node belongs to the focal channel's **reach set** if it was ever infected in ≥ 25 % of runs — a majority-reach cutoff that filters out the long tail of rare reachability events — and is not the seed itself. The score is the Jaccard similarity of the vacancy's and the candidate's reach sets:

```
reach(seed, subgraph) = { n ≠ seed : n infected in ≥ 25 % of SIR runs seeded at seed }
v_reach               = reach(vacancy_pk,  before_subgraph)
c_reach               = reach(candidate_pk, after_subgraph)
score_d               = |v_reach ∩ c_reach| / |v_reach ∪ c_reach|
```

Like Spreading Efficiency, the weight → transmission-probability mapping is an empirical heuristic rather than a calibrated rate, so read the score **ordinally** — to rank candidates against each other for the *same* vacancy — rather than as a calibrated overlap fraction; absolute values shift with `--spreading-runs`, γ, and the choice of weight normalisation.

**References:**
- Kermack, W.O. & McKendrick, A.G. (1927) "A contribution to the mathematical theory of epidemics." *Proceedings of the Royal Society A* 115(772):700–721. [doi:10.1098/rspa.1927.0118](https://doi.org/10.1098/rspa.1927.0118) — foundational SIR formalism: susceptible neighbours catch the infection independently per time step at rate β, infectious nodes recover at rate γ. Score D instantiates this on a per-vacancy forwarding subgraph.
- Watts, D.J. & Dodds, P.S. (2007) "Influentials, networks, and public opinion formation." *Journal of Consumer Research* 34(4):441–458. [doi:10.1086/518527](https://doi.org/10.1086/518527) — the use of stochastic cascade simulations on directed influence networks to characterise *who reaches whom*. Score D applies the same machinery to two channels (vacancy vs candidate) instead of one population.
- Kitsak, M., Gallos, L.K., Havlin, S., Liljeros, F., Muchnik, L., Stanley, H.E. & Makse, H.A. (2010) "Identification of influential spreaders in complex networks." *Nature Physics* 6:888–893. [doi:10.1038/nphys1746](https://doi.org/10.1038/nphys1746) — the SIR-based "spreader influence" framing reused here: a channel's diffusion role read off the set of nodes its cascade reaches, comparable across channels.

**In practice:** Cascade overlap is the dynamical counterpart to Scores A and B. Those ask "is the candidate's first-hop neighbourhood the vacancy's?"; Score D asks "does content actually flow to the same downstream audience, two or more hops out?" A candidate can score high on A and B (the orphaned amplifiers re-attached, the in/out neighbourhoods overlap) yet low on D when those amplifiers' onward forwards land in a different mid-tier community — the candidate has inherited the audience but not the cascade footprint. Conversely a candidate with low A and B but high D is reaching the vacancy's broader downstream basin through a different first-hop path: a **lateral successor** whose content ends up in the right places even though it travelled by a different route. Score D is **computationally heavy** — run time scales linearly with the number of candidates, the SIR replicate count, and the number of in-target channels — so enable it on the batch export when the topological screens (A–C) have narrowed the candidate list, or when the analytical question is specifically about downstream reach rather than immediate audience.

**Example.** The pro-Kremlin aggregator that goes silent on the 14th of October once cascaded — in the before window — into a downstream basin of roughly 90 channels: the 12 orphaned amplifiers, the ~50 mid-tier channels those amplifiers themselves seed via secondary forwards, and a long tail of ~30 further-hop channels reached only sporadically across the 200 SIR runs. After closure, Candidate X (the structural heir from Scores A–C) cascades to 75 channels in the after window, of which 70 sit in the vacancy's old reach set: score_d = 70 / (90 + 75 − 70) ≈ 0.74 — content is propagating to nearly the same destinations as before. Candidate Y, the partial broker from Score C, cascades to 60 channels of which 30 overlap the vacancy's: score_d = 30 / (90 + 60 − 30) = 0.25 — Y has inherited a slice of the immediate audience but its cascade lands largely in a different downstream basin. Candidate Z, a high-A high-B aggregator that the topological tests favoured, cascades to 80 channels of which only 25 overlap the vacancy's: score_d ≈ 0.18 — Z's first-hop neighbourhood matches the vacancy's, but two hops out the orphaned amplifiers' onward forwards now feed into a different community. Cascade overlap separates X (the cascade heir) from Z (the topological look-alike) on a dimension Scores A–C cannot see.

---

### Score E — Personalized PageRank

*A random walk on the citation graph that teleports back to the orphaned amplifiers — high score = the candidate sits in the upstream supply chain those orphans repeatedly reach when walking toward their sources.*

A random surfer who starts at one of the orphaned amplifiers and, at each step, either follows one of its outgoing citation edges (with probability α) or teleports back to a uniformly chosen orphan (with probability 1 − α) will, over time, accumulate mass on the channels that the orphans cite directly, the channels their sources cite, the channels *those* sources cite, and so on. Score E reads off this stationary distribution at each candidate. It is Page et al.'s (1999) PageRank with one twist: the teleportation vector is concentrated on the orphaned amplifier set instead of uniform across the network (Haveliwala 2002, "Topic-Sensitive PageRank"), so the rank reflects relevance *from the perspective of the vacancy's distribution network* rather than the network as a whole.

The walk runs on the citation graph `build_graph` writes — with no reversal. Edges already point amplifier → source, so following an out-edge from an orphan steps upstream toward its content source — exactly the direction the question asks about. (The SIR-based `Spreading Efficiency` and `Cascade overlap` measures *do* reverse the graph because *they* model the opposite flow — information moving downstream from source to amplifier.) The personalisation vector and stationary equation are:

```
personalization[node] = 1 / |orphaned_amplifiers|  if node ∈ orphaned_amplifiers
                      = 0                          otherwise

ppr = stationary distribution of a random surfer that, at each step,
      follows a uniformly chosen out-edge with probability α
      or teleports to a node sampled from `personalization` with probability 1 − α

score_e[candidate] = ppr[candidate] / max_c ppr[c]
```

Damping factor α defaults to 0.85 (tunable via `--vacancy-ppr-alpha`). Raw PPR values sum to 1 across the full graph (typically O(1/N) at each node), so Pulpit divides each candidate's value by the maximum candidate value for the *same* vacancy — the top candidate rescales to 1.0 and the rest sit in (0, 1]. This makes scores comparable *within* a vacancy's candidate list but not *across* vacancies; if the iterative solver fails to converge in 200 power-iteration steps every candidate gets 0.0. The walk also uses the citation graph the structural analysis built across the **full analysis window** — not just the before/after windows that Scores A/B/C/D/F restrict themselves to — so PPR is the only one of the six scores that does not respect the per-vacancy temporal split.

**References:**
- Page, L., Brin, S., Motwani, R. & Winograd, T. (1999) *The PageRank Citation Ranking: Bringing Order to the Web.* [Stanford InfoLab Technical Report](http://ilpubs.stanford.edu:8090/422/). — the original algorithm: a stationary distribution of a random surfer who follows out-edges with probability α and teleports uniformly at random with probability 1 − α.
- Haveliwala, T.H. (2002) "Topic-Sensitive PageRank." *Proceedings of WWW 2002*, 517–526. [doi:10.1145/511446.511513](https://doi.org/10.1145/511446.511513) — replaces the uniform teleportation vector with a topic-biased one, so the rank reflects relevance from the perspective of a chosen seed set. Score E uses the orphaned amplifiers as that seed set.
- Jeh, G. & Widom, J. (2003) "Scaling Personalized Web Search." *Proceedings of WWW 2003*, 271–279. [doi:10.1145/775152.775191](https://doi.org/10.1145/775152.775191) — formalises personalised PageRank as a linear operator on the personalisation vector and proves the decomposition results that justify reading PPR mass at a target as the share of the seed-rooted walk that lands there — the interpretation Score E asks the analyst to take.

**In practice:** PPR is the only one of the six scores that probes the orphans' **upstream supply chain** rather than their immediate audience. Scores A and B (and D) ask whether the orphans re-attached to the candidate and whether downstream cascades land in the same places; Score C asks about cross-organisation bridging; Score E asks whether the candidate is structurally embedded in the same set of sources the orphans repeatedly hit on their way upstream. A candidate can score low on A (the orphans have not started forwarding it directly yet) and still rank highly on E — the random walk reaches it through *the orphans' own existing sources*, signalling a likely future heir whose role the network is already wired for. Conversely, a high-A but low-E candidate has audience inheritance without supply-chain embedding: the orphans forward it, but the deeper upstream graph routes mass elsewhere. Because the normalisation is per-vacancy and the walk ignores edge timestamps, Score E answers "which candidate is most central to *these* orphans' supply chain across the full window we have data for?" — not "is candidate X more central than candidate Y under a different vacancy?" nor "is X more central this year than last."

**Example.** The pro-Kremlin aggregator that goes silent on the 14th of October: its 12 orphaned amplifiers collectively forward, across the analysis window, from a pool of state outlets, war-correspondent feeds, and three regional aggregators. Starting a random walk that teleports back to one of those 12 orphans 15 % of the time (1 − α = 0.15) and otherwise follows their citation edges upstream, the walk accumulates the most mass on the channels the orphans cite most consistently and which themselves cite each other in tight loops — typically a state news agency reading at PPR-raw ≈ 4.3 × 10⁻³, a war-correspondent hub at 3.9 × 10⁻³, and several mid-tier aggregators clustered around 2.0 – 2.5 × 10⁻³. Candidate X (the structural heir from Scores A–C) reads PPR-raw ≈ 4.1 × 10⁻³ — extremely well embedded in this supply chain, near the top of the candidate list; normalised against the top candidate (≈ 4.3 × 10⁻³), score_e ≈ 0.95. Candidate Y (the partial broker from Score C) reads PPR-raw ≈ 1.8 × 10⁻³, normalised to ≈ 0.42 — Y appears in the supply chain but is downstream of the main loops the orphans walk through. Candidate Z (the topological look-alike from Score D's example) reads PPR-raw ≈ 6.0 × 10⁻⁴, normalised to ≈ 0.14 — although Z's first-hop neighbourhood matches the vacancy's, the random walk almost never reaches it through the orphans' upstream paths, because Z draws from a different ecosystem of sources. Score E flags X as the supply-chain heir, separating it from Z (whose topological resemblance is superficial when the deeper graph is queried) on a dimension Scores A and B alone cannot see.

---

### Score F — Temporal adoption

*Coverage of the orphaned amplifier set discounted by the mean delay before each adopter's first forward — a candidate adopted quickly by many orphans scores high; one adopted late, or only by a few, scores low.*

When a content source disappears, its old amplifiers do not all pivot at once. Some attach to a replacement within days; others drift for months. Score F treats the orphaned set as a local diffusion population anchored at the closure date and asks two diffusion-of-innovations questions at once — *what fraction of the orphans ever adopted the candidate?* and *how quickly did the adopters get there?* — then collapses both into a single discounted-coverage figure. For each orphan that ever forwarded the candidate in the after-window the **days-to-adoption** is the gap between the closure date and that orphan's first such forward:

```
coverage  = adopting_orphans / total_orphaned
mean_days = mean of (first_forward_date − closure_date) over the adopting orphans
score_f   = coverage / (1 + mean_days / 30)
```

The denominator instantiates the **hyperbolic discount function** `V = A / (1 + k · d)` of Mazur (1987) with `k = 1 / 30 days⁻¹`, so a mean delay of 30 days halves the score, 60 days drops it to a third, 90 days to a quarter. This is *not* an exponential half-life: hyperbolic and exponential decay coincide only at `d = 30`, and past that the hyperbolic falls much more slowly (at 90 days hyperbolic ≈ 0.25 vs exponential ≈ 0.125, at 180 days ≈ 0.14 vs ≈ 0.016), which preserves a usable signal from broad-but-late adoptions instead of crushing them to zero. A score of 1.0 would require every orphan to have adopted the candidate on the day of the vacancy.

The mean-then-discount order matters: `1 / (1 + mean(d) / 30)` is **more conservative** than `mean(1 / (1 + d_i / 30))` because the discount function is convex, so by Jensen's inequality a candidate with one very fast and one very slow adopter scores lower under Pulpit's formula than under the alternative — uniformly moderate delay is preferred to bimodal adoption. Days are clamped to ≥ 0, so any forward dated before the registered closure (timezone drift, late registration) is treated as same-day adoption. Messages are restricted to the after-window and to the period-aware `channel_cutoff_q()`, matching the rest of the pipeline.

The combination of cumulative coverage and a hyperbolic time discount is a **heuristic operationalisation** of the diffusion-of-innovations frame — both constituent quantities are canonical, but their multiplicative composition is Pulpit-specific. Read the score ordinally to rank candidates against each other for the *same* vacancy; absolute values shift with the closure-date precision and the choice of time constant.

**References:**
- Mazur, J.E. (1987) "An adjusting procedure for studying delayed reinforcement." In Commons, M.L., Mazur, J.E., Nevin, J.A. & Rachlin, H. (eds.) *Quantitative Analyses of Behavior, Vol. 5: The Effect of Delay and of Intervening Events on Reinforcement Value*, pp. 55–73. Erlbaum. — the canonical hyperbolic discount function `V = A / (1 + kd)`. Score F instantiates it with `A` = coverage and `k = 1/30 days⁻¹` on the mean adoption delay.
- Rogers, E.M. (2003) *Diffusion of Innovations* (5th ed.). Free Press. — the diffusion framework where an innovation's spread is characterised by both the *cumulative* fraction of adopters and the *time profile* by which they got there: the same two-parameter (breadth × speed) description Score F collapses into a single number.
- Valente, T.W. (1995) *Network Models of the Diffusion of Innovations.* Hampton Press. — extends Rogers to networked settings: each actor has a *time of adoption* relative to a diffusion start, and population-level curves aggregate those times. Score F reads the orphaned amplifier set as exactly such a localised diffusion population, anchored at the closure date.

**In practice:** Temporal adoption is the only one of the six scores that integrates *when* the adoption happened, not just *whether* it happened — and the only one anchored to the closure date as a temporal origin. Two candidates with identical Amplifier Coverage can score very differently here: a candidate adopted by ten orphans within the first month outscores a candidate adopted by the same ten orphans only after a year of drift, because the first absorbed the vacancy's distribution network at the moment the gap opened (evidence of a pre-positioned heir) while the second only inherited it after the orphans had tried and discarded other options. The four high/low combinations with Score A read as: *high A + high F* — broad and fast, a strong heir; *high A + low F* — broad but late, a lateral successor the network eventually settled on; *low A + high F* — narrow but fast, a specialised pickup serving a sub-niche of the orphaned set; *low A + low F* — neither broad nor fast, not a heir. The score is sensitive to the closure date being correct: registering a closure date later than the channel's actual fade makes every "first forward after closure" artificially close to zero and inflates the score uniformly across all candidates; registering it earlier counts pre-closure forwards as adoptions and produces the same direction of bias.

**Example.** The pro-Kremlin aggregator that goes silent on the 14th of October leaves twelve orphaned amplifiers. Over the 24 months that follow:
- Candidate X — the structural heir from Scores A–C — is adopted by ten orphans (coverage 10/12 ≈ 0.83) with a mean delay of 18 days: `score_f = 0.83 / (1 + 18/30) ≈ 0.83 / 1.6 ≈ 0.52`. Broad, fast adoption — the orphans pivoted to X almost as soon as the vacancy opened.
- Candidate Y — the partial broker from Score C — is adopted by four orphans (coverage 4/12 ≈ 0.33) with a mean delay of 65 days: `score_f = 0.33 / (1 + 65/30) ≈ 0.33 / 3.17 ≈ 0.11`. A slower pickup by a smaller fraction — Y took time to register with the orphaned set and never fully absorbed it.
- Candidate Z — the topological look-alike from Score D's example, with a high Amplifier Coverage but a divergent cascade footprint — is eventually adopted by all twelve orphans (coverage 12/12 = 1.0) but only after a mean delay of 320 days: `score_f = 1.0 / (1 + 320/30) ≈ 1.0 / 11.67 ≈ 0.09`. Universal adoption, but only after nearly a year of drift — Score F flags this as *late* absorption rather than *immediate* succession. Z probably absorbed the audience by attrition once the orphans had given up on a direct heir, not because it was structurally positioned to inherit the role at the moment of closure.

---

## Batch export via Structural Analysis

The per-channel vacancy card (live, interactive) and the batch export (offline, reproducible) serve different purposes. The card is useful for investigating a single vacancy quickly; the batch export is designed for systematic analysis of all vacancies at once, with reproducible parameters embedded in `summary.json`.

**Enable the batch export** by passing `--vacancy-measures` to `structural_analysis`:

```sh
python manage.py structural_analysis --vacancy-measures ALL
python manage.py structural_analysis --vacancy-measures AMPLIFIER_JACCARD,STRUCTURAL_EQUIV,BROKERAGE
python manage.py structural_analysis --vacancy-measures CASCADE_OVERLAP,PPR,TEMPORAL
```

When at least one measure is selected, two additional files are written to the export:

| File | Description |
| :--- | :---------- |
| `data/vacancy_analysis.json` | Machine-readable payload: all vacancies, all candidates, all scores |
| `vacancy_analysis.html` | Interactive HTML page with an accordion per vacancy and a sortable candidate table per section |

The HTML page is linked from `index.html` under a **Vacancy Analysis** section that appears only when the export was produced with vacancy measures enabled.

### Available measures

| Token | Algorithm | Cost |
| :---- | :-------- | :--- |
| `AMPLIFIER_JACCARD` | Fraction of orphaned amplifiers that adopted the candidate | Cheap (DB query) |
| `STRUCTURAL_EQUIV` | Cosine of shared amplifiers + shared sources | Cheap (DB query) |
| `BROKERAGE` | Jaccard of (source-org × amplifier-org) pairs | Cheap (DB query) |
| `CASCADE_OVERLAP` | SIR diffusion reach Jaccard (vacancy before vs candidate after) | **Heavy** — reuses `--spreading-runs` |
| `PPR` | Personalized PageRank seeded on orphaned amplifiers (walk runs on the citation graph as-built; no reversal) | Moderate (one power iteration per vacancy) |
| `TEMPORAL` | Coverage hyperbolically discounted by mean days-to-adoption (halved at 30 days) | Cheap (DB query) |
| `ALL` | All of the above | — |

### Parameters

| Flag | Default | Description |
| :--- | :------ | :---------- |
| `--vacancy-months-before N` | 12 | Look-back window (months) before each vacancy's closure date |
| `--vacancy-months-after N` | 24 | Forward window (months) after each vacancy's closure date |
| `--vacancy-max-candidates N` | 30 | Maximum candidates scored per vacancy (ranked by orphaned-amplifier count) |
| `--vacancy-ppr-alpha α` | 0.85 | Damping factor for PPR; higher values weight long-range connections more |
| `--spreading-runs N` | 200 | Monte Carlo SIR runs for `CASCADE_OVERLAP`; shared with the `SPREADING` node measure |

In the **Operations panel**, all six measures are pre-checked when any vacancy exists in the database. Use the **All** / **None** buttons in the Vacancy Analysis legend to toggle the group in one click.

---

## Interpreting results

The six scores are complementary, not redundant, and fall into two analytical perspectives. Scores A–C characterise the candidate's structural position from a topological standpoint — who forwards it, what it forwards from, and what organizational boundaries it crosses. Scores D–F characterise it from a dynamical standpoint — whether information actually propagates to the same destinations, how well-embedded the candidate is in the orphaned channels' content supply chain, and how quickly it was adopted.

| Pattern | Interpretation |
| :------ | :------------- |
| High on all six | Strong structural replacement across all dimensions — topological, diffusion, and temporal |
| High A/B/C, low D/E/F | The candidate occupies the same structural slot but does not yet reach the same downstream audience through information cascades — possibly too new or poorly connected to established amplifiers |
| Low A/B/C, high D/E/F | The candidate is well-connected in the broader diffusion network and was adopted quickly, but does not mirror the vacancy's immediate neighbourhood — a lateral successor rather than a direct replacement |
| High A, high B, low C | The orphaned amplifiers have converged on a new source that serves a different ideological function — perhaps drawing from a narrower set of sources or operating within a single community |
| Low A, low B, high C | The network has not found a single replacement; brokerage between the same organizations is handled by a channel not yet widely forwarded by the orphaned set |
| Low on all six | No structural replacement has emerged; the orphaned amplifiers have diversified without collectively filling the vacancy |

The table is sorted by **First activity** by default — the candidate's earliest recorded message — so that genuinely new channels appear at the top when *Only after vacancy* is enabled. Click any column header to re-sort.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

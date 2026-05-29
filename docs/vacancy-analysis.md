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

Each replacement candidate receives three complementary scores, each ranging from 0 to 1.

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

*Watts & Dodds (2007), "Influentials, networks, and public opinion formation", [Journal of Consumer Research 34(4)](https://doi.org/10.1086/518527). Kermack & McKendrick (1927), "A contribution to the mathematical theory of epidemics", [Proceedings of the Royal Society A 115(772)](https://doi.org/10.1098/rspa.1927.0118).*

*"Does information flow through this candidate to the same nodes it used to flow through the vacancy?"*

Two subgraphs are constructed from message forwards: one covering the *before* window (vacancy alive) and one the *after* window (candidate alive, vacancy excluded). For each subgraph, a Monte Carlo SIR (Susceptible–Infected–Recovered) epidemic process is seeded at the focal channel and run for `--spreading-runs` replicates. A node is counted as part of the *reach set* if it is infected in at least 25% of runs. The score is:

```
score_d = |reach(vacancy, before) ∩ reach(candidate, after)| / |reach(vacancy, before) ∪ reach(candidate, after)|
```

A high Cascade Overlap score means the candidate's content reaches the same downstream channels that used to receive the vacancy's content. Unlike Neighbour-set Equivalence, which is topological, this measure is dynamical: it captures whether information actually propagates to the same destinations, not just whether the candidates look similar in the static graph. **Computationally intensive** — run time scales with the number of candidates × SIR runs × graph size.

---

### Score E — Personalized PageRank

*Haveliwala (2002), "Topic-sensitive PageRank", [WWW 2002](https://doi.org/10.1145/511446.511513). Page et al. (1999), "The PageRank citation ranking: bringing order to the Web", [Stanford Technical Report](http://ilpubs.stanford.edu:8090/422/).*

*"How deeply is this candidate embedded in the upstream content supply chain of the orphaned channels?"*

Personalized PageRank is computed directly on the citation graph `build_graph` writes — edges already run amplifier→source, so the random walk's out-edges naturally lead from an orphaned amplifier upstream toward its content sources — with the teleportation probability concentrated on the set of orphaned amplifiers:

```
personalization[node] = 1 / |orphaned_amplifiers|  if node is an orphaned amplifier
personalization[node] = 0                           otherwise
```

Damping factor α = 0.85 by default (tunable via `--vacancy-ppr-alpha`). The resulting PPR value for each candidate reflects how much of the random walk mass starting from orphaned channels flows upstream toward that candidate. Scores are normalised to [0, 1] relative to the maximum across all candidates for the same vacancy.

A high PPR score means the candidate sits in the heart of the content ecosystem that orphaned channels draw from — well-connected to their sources of information, not just incidentally forwarded.

---

### Score F — Temporal adoption

*"How quickly and how broadly did the orphaned channels adopt this candidate?"*

For each orphaned amplifier, the first message that forwards from the candidate after the closure date is recorded. The **days-to-adoption** is the gap between the closure date and that first forward. The score combines coverage (fraction of orphaned channels that adopted the candidate) with adoption speed using a 30-day half-life:

```
score_f = coverage / (1 + mean_days_to_adoption / 30)
```

Where `coverage = adopting_orphans / total_orphaned`. A score of 1.0 would require every orphaned channel to have adopted the candidate on the day of the vacancy. Fast adoption by many orphaned channels indicates a channel that was already positioned to absorb the audience gap, rather than one that grew into the role gradually.

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
| `PPR` | Personalized PageRank from orphaned amplifiers on the reversed graph | Moderate (one power iteration per vacancy) |
| `TEMPORAL` | Recency-weighted coverage fraction (30-day half-life) | Cheap (DB query) |
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

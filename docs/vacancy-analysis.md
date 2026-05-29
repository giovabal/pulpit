# Vacancy analysis

Vacancy Analysis addresses a different class of question from standard network measures. Not *how is this network structured right now?* but *who replaced this channel after it disappeared?*

---

## The problem

Channels go silent for many reasons: voluntary deletion, platform removal, legal action, internal collapse. When a channel disappears it leaves a **structural hole** — a set of channels that previously relied on it as a source are now missing an input. The question is whether someone fills that hole, and if so, who.

In practice, this matters because structural heirs are often more significant than their raw metrics suggest. A new channel with few subscribers but a high neighbour-set equivalence score is already occupying the same position in the information ecosystem as the channel it replaced. Conversely, a channel with many followers that happens to attract some of the same amplifiers may be an opportunist capitalising on an audience vacuum, not a genuine continuation of the same network role.

**Example.** In October 2023, a prominent pro-Kremlin aggregator with 280,000 subscribers stops posting. Over three months, the twelve channels that used to forward it start forwarding two new channels heavily. Vacancy Analysis scores both: one scores high across all metrics — same distributors, same upstream sources, same brokerage role, quickly adopted by the orphaned amplifiers. It is a structural heir. The other gets forwarded by the same distributors but draws from entirely different sources and is adopted much more slowly — an opportunist capitalising on the audience vacuum.

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

Each replacement candidate is scored on up to four complementary metrics ranging from 0 to 1. Scores A–C appear in both the interactive per-channel card and the batch export; Score D is batch-only, enabled via `--vacancy-measures`.

---

### Score A — Amplifier Coverage

*The share of the vacancy's old amplifiers that now also forward the candidate.*

When a vacancy closes, the in-target channels that used to forward from it — the **orphaned amplifiers** — are left without that input. Amplifier Coverage asks, for each candidate, what share of those orphans has been observed forwarding the candidate in the after-window. It is an asymmetric set overlap, bounded in `[0, 1]`:

```
score_a = |orphaned_amplifiers ∩ candidate_amplifiers| / |orphaned_amplifiers|
```

The numerator counts *distinct* orphaned channels with at least one forward of the candidate; tie strength is ignored. The **Amplifiers** column carries the absolute numerator alongside the normalised score. A value of 1.0 means every orphan has re-pointed to the candidate; 0.0 means none have. The measure is the information-retrieval definition of **recall**, applied to amplifier sets rather than retrieved documents.

**References:**
- Salton, G. & McGill, M.J. (1983) *Introduction to Modern Information Retrieval.* McGraw-Hill — recall as `|relevant ∩ retrieved| / |relevant|`, the mathematical definition Score A instantiates.
- Webster, J.G. & Ksiazek, T.B. (2012) "The Dynamics of Audience Fragmentation: Public Attention in an Age of Digital Media." *Journal of Communication* 62(1):39–56. [doi:10.1111/j.1460-2466.2011.01616.x](https://doi.org/10.1111/j.1460-2466.2011.01616.x) — audience-overlap networks: outlets are linked by the share of audience they have in common (here amplifiers stand in for audience members).

**In practice:** This is the most direct read of audience inheritance and the natural first column to look at when triaging a vacancy. A high score shows that the vacancy's distribution network has re-attached to the candidate; a low score is a sign the candidate has not been picked up — and rarely deserves attention from the other scores. It is *necessary but not sufficient* for a structural heir: a candidate can absorb the orphaned amplifiers without taking on the same editorial role (Neighbour-set Equivalence) or the same brokerage role (Brokerage overlap). Read this column first; the other three tell you what *kind* of successor a high-coverage candidate actually is.

**Example.** A pro-Kremlin aggregator with twelve in-target amplifiers stops posting in October. In the two years that follow, three candidates surface. Eleven of the twelve old amplifiers begin forwarding Candidate X — a coverage of about 92%. Candidate Y is picked up by four of them, around 33%. Candidate Z by only one, below 10%. X has clearly inherited the vacancy's distribution network; Y has taken a partial slice; Z is barely on the same radar. The score does not yet tell you *whether* X is a genuine heir or an opportunist who happened to absorb the gap — that is what the other scores are for — but it tells you X is the candidate worth reading them on.

---

### Score B — Neighbour-set Equivalence

*Whether the candidate is amplified by the same channels — and forwards from the same sources — as the vacancy.*

Two channels share the same **structural position** when the rest of the network treats them interchangeably: they are amplified by the same channels and they forward from the same sources. The vacancy left behind a position defined by its in-neighbours (the orphaned amplifiers) and its out-neighbours (the channels it forwarded from in the before-window). Score B asks, for each candidate, how closely its own in- and out-neighbour sets — measured in the after-window — match the vacancy's. It is the unweighted average of two **Ochiai (binary cosine)** similarities, one per side of the citation relation:

```
cos_in  = |vacancy_amplifiers ∩ candidate_amplifiers| / √(|vacancy_amplifiers| · |candidate_amplifiers|)
cos_out = |vacancy_sources    ∩ candidate_sources|    / √(|vacancy_sources|    · |candidate_sources|)
score_b = ½ · cos_in + ½ · cos_out
```

Tie strength is ignored — only set membership counts. The candidate's amplifier set is its *full* in-target amplifier set in the after-window, not just the orphaned ones: two candidates with identical Amplifier Coverage can score very differently here, because a candidate forwarded by the ten orphans and nothing else scores higher than one forwarded by the same ten plus a hundred other channels. Out-similarity collapses to zero for high-originality vacancies that rarely forward, in which case the score reflects in-similarity alone.

**References:**
- Lorrain, F. & White, H.C. (1971) "Structural equivalence of individuals in social networks." *Journal of Mathematical Sociology* 1(1):49–80. [doi:10.1080/0022250X.1971.9989788](https://doi.org/10.1080/0022250X.1971.9989788) — the foundational definition: two actors are structurally equivalent iff they hold identical relations to identical others. Score B is the set-overlap relaxation of that equality.
- Leicht, E.A., Holme, P. & Newman, M.E.J. (2006) "Vertex similarity in networks." *Physical Review E* 73:026120. [doi:10.1103/PhysRevE.73.026120](https://doi.org/10.1103/PhysRevE.73.026120) — the cosine vertex-similarity form `|N(u) ∩ N(v)| / √(|N(u)| · |N(v)|)`, separable into in- and out-neighbour components for directed graphs.

**In practice:** This is the topological successor test, the natural complement to Amplifier Coverage. Coverage tells you whether the vacancy's distributors picked up the candidate; Neighbour-set Equivalence tells you whether they re-attached to a candidate that *also looks like the vacancy from the rest of the network's point of view*. A candidate with high Coverage but low Equivalence has absorbed the audience without taking on the editorial role — typically a broad-reach aggregator that everybody forwards anyway. A candidate with high Equivalence has slotted into the same in/out neighbourhood and is the structural heir even when its raw reach is smaller. The out-side of the score catches something Coverage cannot see at all: whether the candidate draws on the same upstream pool — the same correspondents, agencies, regional outlets — as the vacancy did.

**Example.** The pro-Kremlin aggregator with twelve orphaned amplifiers stops posting in October; in the year before, it forwarded from sixteen upstream channels — state outlets, war-correspondent feeds, regional aggregators. Candidate X, a smaller new channel, is forwarded by ten of the twelve orphans and by no other in-target channel, and itself forwards from fourteen of those same sixteen sources plus two new regionals — a near-perfect structural match on both sides. Candidate Y is also forwarded by the same ten orphans, but additionally by sixty other in-target channels, and forwards from forty sources of which only three overlap the vacancy's set — an opportunist that has absorbed part of the audience while serving a different editorial niche. Both X and Y have an identical Amplifier Coverage; only Neighbour-set Equivalence tells them apart.

---

### Score C — Brokerage overlap

*Whether the candidate bridges the same organisations as the vacancy — connecting the same political and media ecosystems.*

Politically significant channels often act as **brokers** between distinct organisations, carrying content from one ecosystem (a state outlet, say) and delivering it to amplifiers in another (a partisan aggregator). When such a broker disappears, the question is whether some other channel now sits in the same position — mediating flows between the same organisational pairs. Score C answers it as a **Jaccard similarity** between two sets of (source-organisation, amplifier-organisation) pairs:

```
vacancy_pairs   = { (org(s), org(a)) : s ∈ vacancy_sources_before, a ∈ orphaned_amplifiers }
candidate_pairs = { (org(s), org(a)) : s ∈ candidate_sources_after, a ∈ orphans_that_amplify_candidate }
score_c         = |vacancy_pairs ∩ candidate_pairs| / |vacancy_pairs ∪ candidate_pairs|
```

Organisation membership is **time-bounded**: each source's organisation is resolved at the date of the forward, and each orphan's at the closure date. The candidate's amplifier side is intentionally restricted to orphans that forward the candidate, so the amplifier universe is comparable to the vacancy's. The score is `—` when the vacancy's neighbourhood contains no channels with organisation assignments. This operationalises the *concept* of brokerage from inter-group mediation theory as positional overlap of bridged organisation-pairs. It is **not** the Gould-Fernandez brokerage *census*, which classifies each mediating triad into one of five roles — hence the UI label **Brokerage overlap** rather than "Brokerage roles".

**References:**
- Gould, R.V. & Fernandez, R.M. (1989) "Structures of mediation: A formal approach to brokerage in transaction networks." *Sociological Methodology* 19:89–126. [doi:10.2307/270949](https://doi.org/10.2307/270949) — the foundational treatment of brokerage as mediation between actors in distinct groups; Score C measures positional overlap in this sense without classifying the specific triadic role.
- Burt, R.S. (2004) "Structural holes and good ideas." *American Journal of Sociology* 110(2):349–399. [doi:10.1086/421787](https://doi.org/10.1086/421787) — the strategic significance of brokering across organisational divides; structural-hole brokers control which content crosses the gap between groups.

**In practice:** This is the organisation-level complement to Coverage and Neighbour-set Equivalence — both of which work at the channel level. Score C lifts the question to organisations and asks whether the candidate inherits the *cross-group brokerage* the vacancy performed. A candidate can score high on A and B but low on C when the orphaned amplifiers have re-attached and the topological neighbourhood matches, yet the candidate draws from a narrower or partisan-aligned source set and so does not bridge the same divides. The reverse pattern — low A or B with high C — means the same divides are still being bridged, but by a channel the orphaned set has not yet widely adopted: the role survives without an obvious individual heir. The score returns `—` for vacancies whose neighbourhood lacks organisation assignments, or collapses to a single organisation (no divides to bridge); in those cases read A and B alone.

**Example.** The pro-Kremlin aggregator goes silent in October. In the year before, it forwarded from channels in three source organisations — a state news agency, war-correspondent feeds, and regional aggregators — and was amplified by twelve orphans split evenly across three amplifier organisations: religious-conservative, economic-nationalist, and military-affiliated. Its brokerage profile is the full grid of source-by-amplifier organisation pairs across that three-by-three layout. Candidate X is forwarded by ten of the orphans drawn from all three amplifier orgs, and itself forwards from the same three source orgs — its profile matches the vacancy's almost perfectly, a near-perfect brokerage heir. Candidate Y is also forwarded by ten orphans across all three amplifier orgs, but forwards from state outlets and from a diaspora-media organisation the vacancy never used — it inherits the state-organisation axis but routes the rest of its sources through a different ecosystem, a partial successor rather than a structural heir. X and Y have an identical Amplifier Coverage and very similar Neighbour-set Equivalence on the in-side; Brokerage overlap is the score that separates them on the cross-organisational dimension neither A nor B can see.

---

### Score D — Temporal adoption

*How many of the orphaned amplifiers picked up the candidate, and how quickly after closure.*

When a content source disappears, its old amplifiers do not all pivot at once. Some attach to a replacement within days; others drift for months. Score D treats the orphaned set as a local diffusion population anchored at the closure date and asks two questions at once — *what fraction of the orphans ever adopted the candidate?* and *how quickly did the adopters get there?* — then collapses both into a single discounted-coverage figure:

```
coverage  = adopting_orphans / total_orphaned
mean_days = mean of (first_forward_date − closure_date) over the adopting orphans
score_d   = coverage / (1 + mean_days / 30)
```

The denominator instantiates the **hyperbolic discount function** `V = A / (1 + k · d)` of Mazur (1987) with `k = 1 / 30 days⁻¹`, so a mean delay of 30 days halves the score, 60 days drops it to a third, 90 days to a quarter. This is *not* an exponential half-life: past 30 days the hyperbolic curve falls much more slowly, preserving a usable signal from broad-but-late adoptions instead of crushing them to zero. A score of 1.0 would require every orphan to have adopted the candidate on the day of the closure. Read it ordinally — to rank candidates against each other for the *same* vacancy.

**References:**
- Mazur, J.E. (1987) "An adjusting procedure for studying delayed reinforcement." In Commons, M.L. et al. (eds.) *Quantitative Analyses of Behavior, Vol. 5*, Erlbaum, pp. 55–73 — the canonical hyperbolic discount function `V = A / (1 + kd)`. Score D instantiates it with `A` = coverage and `k = 1/30 days⁻¹` on the mean adoption delay.
- Rogers, E.M. (2003) *Diffusion of Innovations* (5th ed.). Free Press — the diffusion framework where an innovation's spread is characterised by both the *cumulative* fraction of adopters and the *time profile* by which they got there: the same two-parameter (breadth × speed) description Score D collapses into a single number.

**In practice:** This is the only one of the four scores that integrates *when* the adoption happened, not just *whether* it happened — and the only one anchored to the closure date as a temporal origin. Two candidates with identical Amplifier Coverage can score very differently here: a candidate adopted by ten orphans within the first month outscores a candidate adopted by the same ten orphans only after a year of drift, because the first absorbed the vacancy's distribution network at the moment the gap opened (a pre-positioned heir) while the second only inherited it after the orphans had tried and discarded other options. Read together with Coverage: *high A + high D* is a broad and fast heir; *high A + low D* a lateral successor the network eventually settled on; *low A + high D* a specialised pickup for a sub-niche of the orphans; *low A + low D* neither broad nor fast — not a heir. The score is sensitive to the closure date being correct: registering it later than the channel's actual fade inflates the score uniformly across all candidates.

**Example.** The pro-Kremlin aggregator goes silent in October, leaving twelve orphaned amplifiers. Over the two years that follow, Candidate X — the structural heir from Scores A–C — is adopted by ten of the orphans within about three weeks of the closure: broad, fast adoption, the orphans pivoted to X almost as soon as the vacancy opened. Candidate Y — the partial broker from Score C — is adopted by four orphans only after a couple of months: a slower pickup by a smaller fraction, Y took time to register and never fully absorbed the set. Candidate Z — the topological look-alike — is eventually adopted by all twelve orphans, but only after the better part of a year of drift, so even with full coverage the score collapses under the time discount. Score D flags Z as *late* absorption rather than *immediate* succession: Z probably absorbed the audience by attrition once the orphans had given up on a direct heir, not because it was structurally positioned to inherit the role at the moment of closure.

---

## Batch export via Structural Analysis

The per-channel vacancy card (live, interactive) and the batch export (offline, reproducible) serve different purposes. The card is useful for investigating a single vacancy quickly; the batch export is designed for systematic analysis of all vacancies at once, with reproducible parameters embedded in `summary.json`.

**Enable the batch export** by passing `--vacancy-measures` to `structural_analysis`:

```sh
python manage.py structural_analysis --vacancy-measures ALL
python manage.py structural_analysis --vacancy-measures AMPLIFIER_JACCARD,STRUCTURAL_EQUIV,BROKERAGE
python manage.py structural_analysis --vacancy-measures TEMPORAL
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
| `TEMPORAL` | Coverage hyperbolically discounted by mean days-to-adoption (halved at 30 days) | Cheap (DB query) |
| `ALL` | All of the above | — |

### Parameters

| Flag | Default | Description |
| :--- | :------ | :---------- |
| `--vacancy-months-before N` | 12 | Look-back window (months) before each vacancy's closure date |
| `--vacancy-months-after N` | 24 | Forward window (months) after each vacancy's closure date |
| `--vacancy-max-candidates N` | 30 | Maximum candidates scored per vacancy (ranked by orphaned-amplifier count) |

In the **Operations panel**, all four measures are pre-checked when any vacancy exists in the database. Use the **All** / **None** buttons in the Vacancy Analysis legend to toggle the group in one click.

---

## Interpreting results

The four scores are complementary, not redundant. Scores A–C characterise the candidate's structural position from a topological standpoint — who forwards it, what it forwards from, and what organisational boundaries it crosses. Score D adds the temporal dimension — how quickly the orphaned amplifiers picked the candidate up.

| Pattern | Interpretation |
| :------ | :------------- |
| High on all four | Strong structural replacement across all dimensions — topological *and* adopted quickly |
| High A/B/C, low D | The candidate occupies the same structural slot but was adopted slowly or partially — the network eventually settled on it rather than turning to it immediately |
| Low A/B/C, high D | A fast-but-narrow pickup: a sub-niche of orphans adopted the candidate quickly without making it the dominant heir |
| High A, high B, low C | The orphaned amplifiers have converged on a new source that serves a different ideological function — perhaps drawing from a narrower set of sources or operating within a single community |
| Low A, low B, high C | The network has not found a single replacement; brokerage between the same organisations is handled by a channel not yet widely forwarded by the orphaned set |
| Low on all four | No structural replacement has emerged; the orphaned amplifiers have diversified without collectively filling the vacancy |

The table is sorted by **First activity** by default — the candidate's earliest recorded message — so that genuinely new channels appear at the top when *Only after vacancy* is enabled. Click any column header to re-sort.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

# Vacancy analysis

Vacancy Analysis addresses a different class of question from standard network measures. Not *how is this network structured right now?* but *who replaced this channel after it disappeared?*

---

## The problem

Channels go silent for many reasons: voluntary deletion, platform removal, legal action, internal collapse. When a channel disappears it leaves a **structural hole** — a set of channels that previously relied on it as a source are now missing an input. The question is whether someone fills that hole, and if so, who.

In practice, this matters because structural heirs are often more significant than their raw metrics suggest. A new channel with few subscribers but a high structural equivalence score is already occupying the same position in the information ecosystem as the channel it replaced. Conversely, a channel with many followers that happens to attract some of the same amplifiers may be an opportunist capitalising on an audience vacuum, not a genuine continuation of the same network role.

**Example.** In October 2023, a prominent pro-Kremlin aggregator with 280,000 subscribers stops posting. Over three months, the twelve channels that used to forward it start forwarding two new channels heavily. Vacancy Analysis scores both: one scores high on all three metrics — same distributors, same upstream sources, same brokerage role. It is a structural heir. The other gets forwarded by the same distributors but draws from entirely different sources — an opportunist capitalising on the audience vacuum.

---

## Registering a vacancy

A vacancy is not inferred automatically. An analyst manually registers a channel as a vacancy in **Manage → Vacancies**, providing a **death date** — the point in time when the channel ceased to be active.

The death date is the analytical boundary:
- The period **before** it is used to characterise the vacancy channel's structural role
- The period **after** it is searched for replacement candidates

All registered vacancies are listed at **Channels → Vacancies** (`/channels/vacancies/`), which shows each channel's last-known in-degree, out-degree, and the count of orphaned amplifiers.

> **[PLACEHOLDER: `images/vacancy-list.png`]** Vacancies list: all registered vacant channels with in-degree, orphaned amplifier counts, and death date.

---

## Finding replacement candidates

Any channel with a vacancy record gains a **Vacancy Analysis** card on its detail page. The analyst sets three parameters:

| Parameter | Default | Meaning |
| :-------- | :------ | :------ |
| **Months before** | 12 | How far back before the death date to characterise the vacancy's structural role |
| **Months after** | 24 | How far forward after the death date to search for replacement activity |
| **Only after vacancy** | On | When on, restricts candidates to channels whose first message is on or after the death date — ensuring they are genuinely new rather than pre-existing channels that happened to start being forwarded by the same amplifiers |

> **[PLACEHOLDER: `images/vacancy-analysis-card.png`]** Vacancy Analysis card on a channel detail page: parameter form and ranked replacement candidate table.

The analysis proceeds in two steps:

**Step 1 — Identify orphaned amplifiers.** Find all monitored channels that forwarded content from the vacancy channel in the *before* window. These are the channels whose source has disappeared — the structural gap they now need to fill from somewhere else.

**Step 2 — Find replacement candidates.** Look at what those same orphaned amplifiers began forwarding from in the *after* window. Channels that appear as new forwarding targets for multiple orphaned amplifiers are replacement candidates. They are then scored by how structurally similar they are to the vacancy.

---

## Scoring

Each replacement candidate receives three complementary scores, each ranging from 0 to 1.

---

### Score A — Amplifier similarity

Inspired by co-citation analysis ([Small 1973](https://doi.org/10.1002/asi.4630240103), "Co-citation in the scientific literature").

*"How many of the orphaned amplifiers have started forwarding this candidate?"*

```
score_a = amplifier_count / total_orphaned_amplifiers
```

A score of 1.0 means every orphaned amplifier is now forwarding the candidate. This is the most direct signal of audience inheritance: the same distributors that pushed the vacancy's content are now pushing this channel's content. It does not, however, tell you whether the candidate serves the same structural function — only that it has attracted the same distribution network.

---

### Score B — Structural equivalence

*Lorrain & White (1971), "Structural equivalence of individuals in social networks", [Journal of Mathematical Sociology 1(1)](https://doi.org/10.1080/0022250X.1971.9989788).*

*"Does this candidate occupy the same position in the network as the vacancy did?"*

Two channels are structurally equivalent if they are forwarded by the same channels (same amplifiers) and forward from the same sources (same inputs). A perfect replacement would be structurally identical to the channel it replaces.

The score averages two cosine similarities:

- **In-similarity** — overlap between the vacancy's amplifier set and the candidate's amplifier set. Because the candidate's amplifiers are drawn from the orphaned set, this simplifies to √(shared orphaned amplifiers / total orphaned amplifiers).
- **Out-similarity** — cosine similarity between the vacancy's forwarding sources (before) and the candidate's forwarding sources (after): |vacancy\_sources ∩ candidate\_sources| / (√|vacancy\_sources| × √|candidate\_sources|).

The two components are averaged equally (weight 0.5 each). Out-similarity will be low for vacancy channels that rarely forwarded anything (high-originality producers), in which case the score primarily reflects in-similarity.

A high structural equivalence score means the candidate has stepped into the same editorial position: forwarded by the same amplifiers, drawing from the same upstream sources.

---

### Score C — Brokerage role

*Gould & Fernandez (1989), "Structures of mediation", [Sociological Methodology 19](https://doi.org/10.2307/270949). Burt (2004), "Structural holes and good ideas", [American Journal of Sociology 110(2)](https://doi.org/10.1086/421787).*

*"Does this candidate bridge the same organisational communities as the vacancy did?"*

Politically significant channels often function as **brokers** — they mediate between channels from distinct organisations. A nationalist aggregator that forwards from both a religious conservative outlet and an economic nationalist outlet bridges two otherwise separate communities. When that aggregator disappears, the question is not only who else gets forwarded by the same channels, but who else bridges the same organisational divide.

The brokerage role score is a **Jaccard similarity** between the set of organisation-pairs the vacancy bridged and the set the candidate bridges:

- For the vacancy (before window): for each forwarded message, record the organisation of the source; for each channel that forwarded the vacancy, record its organisation. The vacancy's *brokerage profile* is the set of (source-organisation, amplifier-organisation) pairs it mediated.
- For the candidate (after window): compute the same pairs.
- Jaccard = |intersection| / |union|.

A score of 1.0 means the candidate bridges exactly the same organisational pairs. The score is shown as `—` when the vacancy's neighbourhood contained no channels with organisation assignments.

---

### Score D — Cascade overlap

*Watts & Dodds (2007), "Influentials, networks, and public opinion formation", [Journal of Consumer Research 34(4)](https://doi.org/10.1086/518527). Kermack & McKendrick (1927), "A contribution to the mathematical theory of epidemics", [Proceedings of the Royal Society A 115(772)](https://doi.org/10.1098/rspa.1927.0118).*

*"Does information flow through this candidate to the same nodes it used to flow through the vacancy?"*

Two subgraphs are constructed from message forwards: one covering the *before* window (vacancy alive) and one the *after* window (candidate alive, vacancy excluded). For each subgraph, a Monte Carlo SIR (Susceptible–Infected–Recovered) epidemic process is seeded at the focal channel and run for `--spreading-runs` replicates. A node is counted as part of the *reach set* if it is infected in at least 25% of runs. The score is:

```
score_d = |reach(vacancy, before) ∩ reach(candidate, after)| / |reach(vacancy, before) ∪ reach(candidate, after)|
```

A high Cascade Overlap score means the candidate's content reaches the same downstream channels that used to receive the vacancy's content. Unlike Structural Equivalence, which is topological, this measure is dynamical: it captures whether information actually propagates to the same destinations, not just whether the candidates look similar in the static graph. **Computationally intensive** — run time scales with the number of candidates × SIR runs × graph size.

---

### Score E — Personalized PageRank

*Haveliwala (2002), "Topic-sensitive PageRank", [WWW 2002](https://doi.org/10.1145/511446.511513). Page et al. (1999), "The PageRank citation ranking: bringing order to the Web", [Stanford Technical Report](http://ilpubs.stanford.edu:8090/422/).*

*"How deeply is this candidate embedded in the upstream content supply chain of the orphaned channels?"*

PageRank is computed on the **reversed graph** (edges reversed so the random walk travels upstream from amplifiers toward sources) with the teleportation probability concentrated on the set of orphaned amplifiers:

```
personalization[node] = 1 / |orphaned_amplifiers|  if node is an orphaned amplifier
personalization[node] = 0                           otherwise
```

Damping factor α = 0.85 by default (tunable via `--vacancy-ppr-alpha`). The resulting PPR value for each candidate reflects how much of the random walk mass starting from orphaned channels flows upstream toward that candidate. Scores are normalised to [0, 1] relative to the maximum across all candidates for the same vacancy.

A high PPR score means the candidate sits in the heart of the content ecosystem that orphaned channels draw from — well-connected to their sources of information, not just incidentally forwarded.

---

### Score F — Temporal adoption

*"How quickly and how broadly did the orphaned channels adopt this candidate?"*

For each orphaned amplifier, the first message that forwards from the candidate after the death date is recorded. The **days-to-adoption** is the gap between the death date and that first forward. The score combines coverage (fraction of orphaned channels that adopted the candidate) with adoption speed using a 30-day half-life:

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
| `--vacancy-months-before N` | 12 | Look-back window (months) before each vacancy's death date |
| `--vacancy-months-after N` | 24 | Forward window (months) after each vacancy's death date |
| `--vacancy-max-candidates N` | 30 | Maximum candidates scored per vacancy (ranked by orphaned-amplifier count) |
| `--vacancy-ppr-alpha α` | 0.85 | Damping factor for PPR; higher values weight long-range connections more |
| `--spreading-runs N` | 200 | Monte Carlo SIR runs for `CASCADE_OVERLAP`; shared with the `SPREADING` node measure |

In the **Operations panel**, all six measures are pre-checked when any vacancy exists in the database. Use the **All** / **None** buttons in the Vacancy Analysis legend to toggle the group in one click.

---

## Interpreting results

The six scores are complementary, not redundant. The three legacy scores (A, B, C) characterise the candidate's structural position from a static, topological perspective. The three new scores (D, E, F) characterise it from dynamic, diffusion, and temporal perspectives.

| Pattern | Interpretation |
| :------ | :------------- |
| High on all six | Strong structural replacement across all dimensions — topological, diffusion, and temporal |
| High A/B/C, low D/E/F | The candidate occupies the same structural slot but does not yet reach the same downstream audience through information cascades — possibly too new or poorly connected to established amplifiers |
| Low A/B/C, high D/E/F | The candidate is well-connected in the broader diffusion network and was adopted quickly, but does not mirror the vacancy's immediate neighbourhood — a lateral successor rather than a direct replacement |
| High A, high B, low C | The orphaned amplifiers have converged on a new source that serves a different ideological function — perhaps drawing from a narrower set of sources or operating within a single community |
| Low A, low B, high C | The network has not found a single replacement; brokerage between the same organisations is handled by a channel not yet widely forwarded by the orphaned set |
| Low on all six | No structural replacement has emerged; the orphaned amplifiers have diversified without collectively filling the vacancy |

The table is sorted by **First activity** by default — the candidate's earliest recorded message — so that genuinely new channels appear at the top when *Only after vacancy* is enabled. Click any column header to re-sort.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

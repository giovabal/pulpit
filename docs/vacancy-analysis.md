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

## Interpreting results

The three scores are complementary, not redundant:

| Pattern | Interpretation |
| :------ | :------------- |
| High A, high B, high C | Strong structural replacement — the candidate occupies the same position, is forwarded by the same distributors, and mediates the same organisational boundaries |
| High A, high B, low C | The orphaned amplifiers have converged on a new source that serves a different ideological function — perhaps drawing from a narrower set of sources or operating within a single community |
| Low A, low B, high C | The network has not found a single replacement; brokerage between the same organisations is handled by a channel not yet widely forwarded by the orphaned set |
| Low A, low B, low C | No structural replacement has emerged; the orphaned amplifiers have diversified without collectively filling the vacancy |

The table is sorted by **First activity** by default — the candidate's earliest recorded message — so that genuinely new channels appear at the top when *Only after vacancy* is enabled. Click any column header to re-sort:

- **Structural equivalence** or **Brokerage role** — focus on quality of structural fit
- **Amplifiers** — focus on how much of the orphaned audience each candidate has already captured

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

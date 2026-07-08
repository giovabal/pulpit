# Vacancy analysis

Vacancy Analysis addresses a different class of question from standard network measures. Not *how is this network structured right now?* but *who replaced this channel after it disappeared?*

---

## The problem

Channels go silent for many reasons: voluntary deletion, platform removal, legal action, internal collapse. When a channel disappears it leaves a **structural hole** — a set of channels that previously relied on it as a source are now missing an input. The question is whether someone fills that hole, and if so, who.

In practice, this matters because structural heirs are often more significant than their raw metrics suggest. A new channel with few subscribers but a high neighbour-set equivalence score is already occupying the same position in the information ecosystem as the channel it replaced. Conversely, a channel with many followers that happens to attract some of the same amplifiers may be an opportunist capitalising on an audience vacuum, not a genuine continuation of the same network role.

**Example.** In October 2023, a prominent pro-Kremlin aggregator with 280,000 subscribers stops posting. Over three months, the twelve channels that used to forward it start forwarding two new channels heavily. Vacancy Analysis scores both: one scores high across all metrics — same distributors, same upstream sources, same organisational position, quickly adopted by the orphaned amplifiers. It is a structural heir. The other gets forwarded by the same distributors but draws from entirely different sources and is adopted much more slowly — an opportunist capitalising on the audience vacuum.

---

## Registering a vacancy

A vacancy is not inferred automatically. An analyst manually registers a channel as a vacancy in **Manage → Vacancies**, providing a **closure date** — the point in time when the channel ceased to be active — and, optionally, a **known successor** once qualitative evidence identifies one (see [Known successors and validation](#known-successors-and-validation)).

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
| **Only after vacancy** | On | When on, restricts the *displayed* candidates to channels whose first message is on or after the closure date — genuinely new channels rather than pre-existing ones. All candidates are always scored; the toggle filters the table only, so every score and q-value is identical whichever way it is set (and identical to the batch export's) |


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

Each replacement candidate is scored on up to six complementary metrics ranging from 0 to 1. Scores A, N, B, C and O appear in both the interactive per-channel card and the batch export; Score D is batch-only, enabled via `--vacancy-measures`. The set-overlap scores are additionally calibrated against a null model — see [Statistical calibration](#statistical-calibration) below.

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

**In practice:** This is the most direct read of audience inheritance and the natural first column to look at when triaging a vacancy. A high score shows that the vacancy's distribution network has re-attached to the candidate; a low score is a sign the candidate has not been picked up — and rarely deserves attention from the other scores. It is *necessary but not sufficient* for a structural heir: a candidate can absorb the orphaned amplifiers without taking on the same editorial role (Neighbour-set Equivalence) or the same organisational position (Brokerage overlap) — and its coverage may be pre-existing habit rather than adoption (New-adopter Coverage). Read this column first; the others tell you what *kind* of successor a high-coverage candidate actually is.

**Example.** A pro-Kremlin aggregator with twelve in-target amplifiers stops posting in October. In the two years that follow, three candidates surface. Eleven of the twelve old amplifiers begin forwarding Candidate X — a coverage of about 92%. Candidate Y is picked up by four of them, around 33%. Candidate Z by only one, below 10%. X has clearly inherited the vacancy's distribution network; Y has taken a partial slice; Z is barely on the same radar. The score does not yet tell you *whether* X is a genuine heir or an opportunist who happened to absorb the gap — that is what the other scores are for — but it tells you X is the candidate worth reading them on.

---

### Score N — New-adopter Coverage

*The share of the orphaned amplifiers that adopted the candidate for the first time.*

Amplifier Coverage counts every orphan that forwards the candidate in the after-window — including orphans that had been forwarding it all along. An orphan that forwarded both the vacancy *and* the candidate before the closure, and simply kept doing so, is evidence of a long-standing habit, not of succession. Score N is Coverage restricted to genuinely new relationships:

```
new_adopters = orphans that forwarded the candidate in the after-window
               AND did not forward it in the before-window
score_n      = |new_adopters| / |orphaned_amplifiers|
```

The habit test uses the same before-window that defines the orphans, so the before/after comparison is windowed symmetrically. By construction `score_n ≤ score_a`, and the difference `score_a − score_n` is the pre-existing-habit share of the coverage. Each score cell carries the absolute new-adopter count in its tooltip.

**References:**
- The before/after cohort design — characterise an audience before a removal, then measure where that *same cohort* re-attaches afterwards — is how the deplatforming-migration literature operationalises audience movement between platforms and channels; Score N is the within-Telegram version, with orphaned amplifiers standing in for the audience cohort.
- Rogers, E.M. (2003) *Diffusion of Innovations* (5th ed.). Free Press — adoption as a *new* behaviour by a member of the population at risk; an actor already exhibiting the behaviour before the event is not an adopter of it.

**In practice:** Read N right after A. *High A + high N* is real succession: the orphans moved somewhere they had not been going before. *High A + low N* means the candidate's coverage is mostly inherited habit — a channel the orphans always forwarded anyway (typically a big aggregator), which absorbed nothing when the vacancy opened. N is the most succession-specific of the structural scores; when triaging many candidates, sorting by N first is usually the fastest route to the genuine heirs.

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
- Burt, R.S. (1987) "Social Contagion and Innovation: Cohesion versus Structural Equivalence." *American Journal of Sociology* 92(6):1287–1335. [doi:10.1086/228667](https://doi.org/10.1086/228667) — the empirical payoff claim Score B relies on: structurally equivalent actors are behaviourally substitutable, because the surrounding network treats them as interchangeable.
- Leicht, E.A., Holme, P. & Newman, M.E.J. (2006) "Vertex similarity in networks." *Physical Review E* 73:026120. [doi:10.1103/PhysRevE.73.026120](https://doi.org/10.1103/PhysRevE.73.026120) — the cosine vertex-similarity form `|N(u) ∩ N(v)| / √(|N(u)| · |N(v)|)`, separable into in- and out-neighbour components for directed graphs.

**A deliberate modelling choice — structural, not regular, equivalence.** Score B demands overlap with the *same* amplifiers and the *same* sources. The alternative notion, **regular equivalence** (White, D.R. & Reitz, K.P. 1983, "Graph and semigroup homomorphisms on networks of relations", *Social Networks* 5(2):193–234; Borgatti, S.P. & Everett, M.G. 1992, "Notions of Position in Social Network Analysis", *Sociological Methodology* 22:1–35), would ask only that the candidate hold the same *kind* of position — amplified by similar-role channels, not necessarily the identical ones. For succession inside one ecosystem the strict form is the right test: the heir to a specific channel inherits its specific distribution network, not an analogous one elsewhere. But it means Score B cannot detect a channel occupying the same *role* in a different corner of the network — that question belongs to the SBM block structure, not to this score.

**In practice:** This is the topological successor test, the natural complement to Amplifier Coverage. Coverage tells you whether the vacancy's distributors picked up the candidate; Neighbour-set Equivalence tells you whether they re-attached to a candidate that *also looks like the vacancy from the rest of the network's point of view*. A candidate with high Coverage but low Equivalence has absorbed the audience without taking on the editorial role — typically a broad-reach aggregator that everybody forwards anyway. A candidate with high Equivalence has slotted into the same in/out neighbourhood and is the structural heir even when its raw reach is smaller. The out-side of the score catches something Coverage cannot see at all: whether the candidate draws on the same upstream pool — the same correspondents, agencies, regional outlets — as the vacancy did.

**Example.** The pro-Kremlin aggregator with twelve orphaned amplifiers stops posting in October; in the year before, it forwarded from sixteen upstream channels — state outlets, war-correspondent feeds, regional aggregators. Candidate X, a smaller new channel, is forwarded by ten of the twelve orphans and by no other in-target channel, and itself forwards from fourteen of those same sixteen sources plus two new regionals — a near-perfect structural match on both sides. Candidate Y is also forwarded by the same ten orphans, but additionally by sixty other in-target channels, and forwards from forty sources of which only three overlap the vacancy's set — an opportunist that has absorbed part of the audience while serving a different editorial niche. Both X and Y have an identical Amplifier Coverage; only Neighbour-set Equivalence tells them apart.

---

### Score C — Brokerage overlap

*Whether the candidate occupies the same organisational position as the vacancy — drawing on the same source organisations and amplified by the same audience organisations.*

Politically significant channels often sit in a distinctive **organisational position**: they republish content from one ecosystem (a state outlet, say) and are in turn republished by amplifiers in another (a partisan aggregator). Pulpit records this as two independent one-degree facts — the channel directly forwards *from* the source organisations, and the audience organisations directly forward *from* the channel. It is **not** content transiting from one organisation to the other *through* the channel: under one-degree attribution a forward is a direct citation of the original author, not a relay, so the two sides are unrelated content streams rather than a flow the channel mediates. When such a channel disappears, the question is whether some other channel now occupies the same position — drawing on the same source organisations and feeding the same audience organisations. Score C answers it as a **Jaccard similarity** between two sets of (source-organisation, amplifier-organisation) pairs — the cross-product of each channel's source-org set and amplifier-org set:

```
vacancy_pairs   = { (org(s), org(a)) : s ∈ vacancy_sources_before, a ∈ orphaned_amplifiers }
candidate_pairs = { (org(s), org(a)) : s ∈ candidate_sources_after, a ∈ orphans_that_amplify_candidate }
score_c         = |vacancy_pairs ∩ candidate_pairs| / |vacancy_pairs ∪ candidate_pairs|
```

Organisation membership is **time-bounded**: each source's organisation is resolved at the date of the forward, and each orphan's at the closure date. The candidate's amplifier side is intentionally restricted to orphans that forward the candidate, so the amplifier universe is comparable to the vacancy's. The score is `—` when the vacancy's neighbourhood contains no channels with organisation assignments. This operationalises the *concept* of brokerage from inter-group mediation theory as **positional overlap** of the organisation-pairs each channel spans — read it as "same structural slot between the same ecosystems", not as flow the channel routes between them. It is **not** the Gould-Fernandez brokerage *census*, which classifies each mediating triad into one of five roles and reads each 2-path as a relayed transaction (a flow claim one-degree attribution does not support) — hence the UI label **Brokerage overlap** rather than "Brokerage roles".

**References:**
- Gould, R.V. & Fernandez, R.M. (1989) "Structures of mediation: A formal approach to brokerage in transaction networks." *Sociological Methodology* 19:89–126. [doi:10.2307/270949](https://doi.org/10.2307/270949) — the foundational treatment of brokerage as mediation between actors in distinct groups; Score C measures positional overlap in this sense without classifying the specific triadic role.
- Burt, R.S. (2004) "Structural holes and good ideas." *American Journal of Sociology* 110(2):349–399. [doi:10.1086/421787](https://doi.org/10.1086/421787) — the strategic significance of brokering across organisational divides; structural-hole brokers control which content crosses the gap between groups.

**In practice:** This is the organisation-level complement to Coverage and Neighbour-set Equivalence — both of which work at the channel level. Score C lifts the question to organisations and asks whether the candidate occupies the same *cross-organisational position* the vacancy did — same source ecosystems on one side, same audience ecosystems on the other. A candidate can score high on A and B but low on C when the orphaned amplifiers have re-attached and the topological neighbourhood matches, yet the candidate draws from a narrower or partisan-aligned source set and so does not span the same organisational divides. The reverse pattern — low A or B with high C — means the same divides are still spanned, but by a channel the orphaned set has not yet widely adopted: the position survives without an obvious individual heir. The score returns `—` for vacancies whose neighbourhood lacks organisation assignments, or collapses to a single organisation (no divides to span); in those cases read A and B alone.

**Example.** The pro-Kremlin aggregator goes silent in October. In the year before, it forwarded from channels in three source organisations — a state news agency, war-correspondent feeds, and regional aggregators — and was amplified by twelve orphans split evenly across three amplifier organisations: religious-conservative, economic-nationalist, and military-affiliated. Its organisational-position profile is the full grid of source-by-amplifier organisation pairs across that three-by-three layout. Candidate X is forwarded by ten of the orphans drawn from all three amplifier orgs, and itself forwards from the same three source orgs — its profile matches the vacancy's almost perfectly, a near-perfect positional heir. Candidate Y is also forwarded by ten orphans across all three amplifier orgs, but forwards from state outlets and from a diaspora-media organisation the vacancy never used — it inherits the state-organisation axis but draws the rest of its sources from a different ecosystem, a partial successor rather than a structural heir. X and Y have an identical Amplifier Coverage and very similar Neighbour-set Equivalence on the in-side; Brokerage overlap is the score that separates them on the cross-organisational dimension neither A nor B can see.

---

### Score O — Content Continuity

*Whether the candidate circulates the same content the vacancy did — re-forwarding the origin messages it curated, or its own authored posts.*

All the preceding scores characterise the candidate's **position** — who forwards it, what it forwards from, which organisational divides it spans. A position can be inherited by an unrelated opportunist. Score O asks the identity-flavoured question directly: does the candidate's stream contain the *vacancy's* content? Every forward on Telegram carries the identity of its origin message (the same `(origin channel, origin post)` identity the [coordination layer](coordination-analysis.md) is built on), so two channels circulating the same origin messages are observably drawing on the same stream — and a candidate re-forwarding the vacancy's *own* posts is re-seeding its back-catalogue.

One design problem has to be solved first: origins are **temporally censored** across the closure. Content posted after the closure did not exist before it, so a naive intersection of before-window and after-window origin sets is empty by construction. Both sides are therefore conditioned on origins that *predate the closure*:

```
universe  = origins the vacancy forwarded in the before-window        (curated)
          ∪ posts the vacancy authored                                (its back-catalogue)
recirc(C) = origins the candidate forwarded in the after-window
            whose origin date precedes the closure
score_o   = |universe ∩ recirc(C)| / √(|universe| · |recirc(C)|)
```

Authored posts enter the universe both from the crawl and from observed forwards: Telegram attributes every forward to the original author, so any in-target forward of the vacancy whose origin predates the closure testifies that the origin is the vacancy's pre-closure content — including forwards made *after* the closure, because authorship, not co-occurrence, is the claim (archive re-seeding testifies to it just as well). The score is the same Ochiai form as Score B; `—` when the universe is empty (a vacancy with no origin-tagged content), 0.0 when the candidate circulates no old content at all. The score cell's tooltip carries the **archive-forward count** — shared origins authored by the vacancy itself. Even a handful of these is close to a smoking gun for a rebrand: the candidate is re-publishing the closed channel's own posts.

**References:**
- Niverthi, M., Verma, G. & Kumar, S. (2022) "Characterizing, Detecting, and Predicting Online Ban Evasion." *Proceedings of the ACM Web Conference 2022 (WWW '22)*:2614–2623. [doi:10.1145/3485447.3512133](https://doi.org/10.1145/3485447.3512133) — linking accounts across a ban by behavioural and content similarity: the identity question Score O operationalises with Telegram's native origin attribution.
- Giglietto, F., Righetti, N., Rossi, L. & Marino, G. (2020) "It takes a village to manipulate the media: coordinated link sharing behavior during 2018 and 2019 Italian elections." *Information, Communication & Society* 23(6):867–891. [doi:10.1080/1369118X.2020.1739732](https://doi.org/10.1080/1369118X.2020.1739732) — shared-content identity as the tie that reveals actors operating in concert; Score O applies the same origin-identity logic across a closure instead of within a time window.

**A known blind spot.** Origin identity only survives a true *forward*. A successor that **re-uploads** the old channel's material — fresh posts containing the same media — gets fresh authorship from Telegram and is invisible to this score. Score O's positive signal is strong (shared origins are hard to accumulate accidentally); its zero is weak (a rebrand that re-uploads rather than re-forwards scores 0). Media-fingerprint matching would close that gap; it is out of scope for the forward-based scorer.

**In practice:** Read O as the identity column. Scores A–D say the candidate *fills the hole*; O says the stream flowing through it is *the vacancy's stream*. A high O with any structural pattern deserves immediate qualitative review — check the archive-forward count in the tooltip first, since forwards of the vacancy's own posts are the strongest single tell. A low O with high A/B/C reads as role succession without content identity: a different operation absorbing the audience. Because the score only sees origin-datable forwards, judge it together with the Origin q column — a significant q on even a modest overlap means the candidate's old-content circulation targets the vacancy's stream, not what a random channel would produce.

**Example.** The pro-Kremlin aggregator goes silent in October. Candidate X — the structural heir on Scores A–C — forwards, in its first two months, fourteen origin messages that predate the closure: nine are posts the vacancy itself had forwarded from its war-correspondent sources, and three are the vacancy's *own* posts, re-seeded from its archive. Twelve of fourteen land in the vacancy's universe, three of them archive forwards — a Content Continuity near 0.8 with a highly significant q. X is not merely occupying the position; it is continuing the stream. Candidate Y, with identical Amplifier Coverage, also posts heavily after the closure — but almost none of its old-origin forwards belong to the vacancy's universe, and none are the vacancy's own posts. Y absorbed the audience; X continued the channel.

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

**In practice:** This is the only score that integrates *when* the adoption happened, not just *whether* it happened — and the only one anchored to the closure date as a temporal origin. Two candidates with identical Amplifier Coverage can score very differently here: a candidate adopted by ten orphans within the first month outscores a candidate adopted by the same ten orphans only after a year of drift, because the first absorbed the vacancy's distribution network at the moment the gap opened (a pre-positioned heir) while the second only inherited it after the orphans had tried and discarded other options. Read together with Coverage: *high A + high D* is a broad and fast heir; *high A + low D* a lateral successor the network eventually settled on; *low A + high D* a specialised pickup for a sub-niche of the orphans; *low A + low D* neither broad nor fast — not a heir. The score is sensitive to the closure date being correct: registering it later than the channel's actual fade inflates the score uniformly across all candidates.

**Example.** The pro-Kremlin aggregator goes silent in October, leaving twelve orphaned amplifiers. Over the two years that follow, Candidate X — the structural heir from Scores A–C — is adopted by ten of the orphans within about three weeks of the closure: broad, fast adoption, the orphans pivoted to X almost as soon as the vacancy opened. Candidate Y — the partial positional match from Score C — is adopted by four orphans only after a couple of months: a slower pickup by a smaller fraction, Y took time to register and never fully absorbed the set. Candidate Z — the topological look-alike — is eventually adopted by all twelve orphans, but only after the better part of a year of drift, so even with full coverage the score collapses under the time discount. Score D flags Z as *late* absorption rather than *immediate* succession: Z probably absorbed the audience by attrition once the orphans had given up on a direct heir, not because it was structurally positioned to inherit the role at the moment of closure.

---

## Statistical calibration

The overlap scores are descriptive: a large, indiscriminately amplified candidate overlaps *any* orphan set to some degree by chance alone, and raw coefficients cannot say when an overlap is bigger than chance. Pulpit therefore tests the two set overlaps the scores are built on against an explicit null model and reports the result next to the scores:

- **Amplifier overlap** (the numerator of Coverage and of `cos_in`): the probability that a candidate whose amplifier set was drawn *uniformly at random* from the active amplifier universe — the in-target channels that made at least one forward in the after-window — would overlap the orphan set at least as much as observed. Exact one-tailed **hypergeometric** tail probability.
- **Source overlap** (the numerator of `cos_out`): same test for the candidate's source set against the vacancy's, over the universe of channels forwarded from by any in-target channel across the combined before + after span. Candidates with no sources are not tested — absence of data is not evidence of independence.
- **Origin overlap** (the numerator of Content Continuity): same test for the candidate's set of re-circulated pre-closure origins against the vacancy's content universe, over the pool of pre-closure-dated origins any in-target channel still circulated in the after-window. Candidates circulating no old content are not tested.

Because up to `--vacancy-max-candidates` candidates are tested per vacancy, the p-values are **Benjamini-Hochberg adjusted** across the candidate list; the tables show the adjusted values (q) with the usual star convention (\* q < 0.05, \*\* q < 0.01, \*\*\* q < 0.001), and each q cell's tooltip carries the raw p. Read them as a filter, not a verdict: a high Coverage with a non-significant q means the overlap is what a random popular channel would produce; a modest Coverage with q < 0.01 is a targeted re-attachment worth reading the other scores on. With very few orphans nothing will reach significance — that is the test working, not failing: small orphan sets genuinely cannot distinguish succession from chance.

**References:**
- Tumminello, M., Miccichè, S., Lillo, F., Piilo, J. & Mantegna, R.N. (2011) "Statistically validated networks in bipartite complex systems." *PLoS ONE* 6(3):e17994. [doi:10.1371/journal.pone.0017994](https://doi.org/10.1371/journal.pone.0017994) — the statistically-validated-networks method: validate each observed overlap against a hypergeometric null with multiple-comparison correction, exactly the scheme applied here.
- Benjamini, Y. & Hochberg, Y. (1995) "Controlling the false discovery rate: a practical and powerful approach to multiple testing." *Journal of the Royal Statistical Society B* 57(1):289–300 — the FDR step-up procedure used for the per-vacancy adjustment.

---

## Known successors and validation

The scores are heuristics until they are checked against reality. When qualitative evidence identifies the actual successor of a vacancy — an announced rebrand, a known operator migration, reporting — record it in **Manage → Vacancies** as the vacancy's **Known successor**. The batch export then closes the loop:

- The successor's row is starred (★) in the candidate tables (card and export), and each vacancy's section reports the successor's **rank** on every selected measure.
- The export page opens with a **validation block**: over all vacancies with a labelled successor, how often each measure ranked the true successor first, in the top 3, in the top 5 (*hits@k*), and the mean reciprocal rank (MRR). A successor missing from the candidate list counts as a miss — the denominator is every labelled vacancy.

This is the same held-out evaluation regime used for link prediction and for the successor-prediction literature (see below). It tells you, on *your* corpus, which measures actually find successors — and therefore which columns deserve weight when reading unlabelled vacancies. Even a handful of labelled cases is informative; label them as they become known.

---

## Prior art

The question — *who replaces a removed actor in a covert or political network?* — has a research lineage worth knowing when reporting results:

- **Vacancy chains:** White, H.C. (1970) *Chains of Opportunity: System Models of Mobility in Organizations* (Harvard UP); Chase, I.D. (1991) "Vacancy Chains." *Annual Review of Sociology* 17:133–154 — the founding theory of positions outliving their occupants, from which this feature takes its name. It has not previously been operationalised for online influence networks.
- **Successor prediction:** the STONE system — Spezzano, F., Subrahmanian, V.S. & Mannes, A. (2013) "STONE: Shaping terrorist organizational network efficiency." *ASONAM 2013*:348–355 (also "Reshaping Terrorist Networks." *Communications of the ACM* 57(8):60–69, 2014) — predicts who will replace removed members of terrorist networks and is the closest published counterpart to this feature, with a different method (optimising predicted organisational effectiveness) for the same question. Pulpit's approach is closer to the structural-equivalence tradition: the successor is whoever the network *treats* as the vacancy's replacement.
- **Covert-network replacement:** Bright, D., Koskinen, J. & Malm, A. (2019) "Illicit Network Dynamics: The Formation and Evolution of a Drug Trafficking Network." *Journal of Quantitative Criminology* 35(2):237–258 — replacements emerge at short social distance from the removed actor, which is why the candidate pool is built from the vacancy's own orphaned ecosystem; Carley, K.M., Lee, J.-S. & Krackhardt, D. (2002) "Destabilizing Networks." *Connections* 24(3):79–92 — the effective successor is often a structurally well-positioned but low-profile node, which is why candidates are scored positionally rather than by raw reach.

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
| `AMPLIFIER_JACCARD` | Fraction of orphaned amplifiers that forwarded the candidate after closure | Cheap (DB query) |
| `NEW_ADOPTERS` | Fraction of orphaned amplifiers that *newly* adopted the candidate (no before-window forwards) | Cheap (DB query) |
| `STRUCTURAL_EQUIV` | Cosine of shared amplifiers + shared sources | Cheap (DB query) |
| `BROKERAGE` | Jaccard of (source-org × amplifier-org) pairs | Cheap (DB query) |
| `ORIGIN_OVERLAP` | Ochiai of shared pre-closure origin messages, with the archive-forward count | Cheap (DB query) |
| `TEMPORAL` | Coverage hyperbolically discounted by mean days-to-adoption (halved at 30 days) | Cheap (DB query) |
| `ALL` | All of the above | — |

Selecting any of `AMPLIFIER_JACCARD`, `NEW_ADOPTERS` or `STRUCTURAL_EQUIV` also computes the [hypergeometric calibration](#statistical-calibration) columns for the overlaps those measures share; `ORIGIN_OVERLAP` brings its own origin-overlap q column.

### Parameters

| Flag | Default | Description |
| :--- | :------ | :---------- |
| `--vacancy-months-before N` | 12 | Look-back window (months) before each vacancy's closure date |
| `--vacancy-months-after N` | 24 | Forward window (months) after each vacancy's closure date |
| `--vacancy-max-candidates N` | 30 | Maximum candidates scored per vacancy (ranked by orphaned-amplifier count) |

In the **Operations panel**, the **Neighbour-set Equivalence** and **Brokerage overlap** measures are pre-checked by default (per the committed `.operations-structural` baseline, which sets `measures = ["STRUCTURAL_EQUIV", "BROKERAGE"]`); the fieldset is enabled only when at least one vacancy exists in the database. Use the **All** / **None** buttons in the Vacancy Analysis legend to toggle the whole group in one click.

---

## Interpreting results

The six scores are complementary, not redundant. Scores A, N, B and C characterise the candidate's structural position — who forwards it, whether that audience is newly acquired, what it forwards from, and what organisational boundaries it crosses. Score O is the identity check — whether the candidate circulates the vacancy's own content stream rather than merely occupying its position. Score D adds the temporal dimension — how quickly the orphaned amplifiers picked the candidate up. The q columns say which overlaps beat chance at all.

| Pattern | Interpretation |
| :------ | :------------- |
| High on all | Strong structural replacement across all dimensions — topological *and* adopted quickly |
| High A, low N | The coverage is inherited habit: the orphans always forwarded this candidate. An absorber of attention, not a successor |
| High O, any structural pattern | The candidate circulates the vacancy's specific content; archive forwards of the vacancy's own posts are the strongest single rebrand tell — escalate to qualitative review |
| High A/B/C, low O | Role succession without content identity: a different operation absorbing the audience (or a rebrand that re-uploads instead of forwarding — Score O cannot see those) |
| High A/B/C, low D | The candidate occupies the same structural slot but was adopted slowly or partially — the network eventually settled on it rather than turning to it immediately |
| Low A/B/C, high D | A fast-but-narrow pickup: a sub-niche of orphans adopted the candidate quickly without making it the dominant heir |
| High A, high B, low C | The orphaned amplifiers have converged on a new source that serves a different ideological function — perhaps drawing from a narrower set of sources or operating within a single community |
| Low A, low B, high C | The network has not found a single replacement; the same cross-organisational position is held by a channel not yet widely forwarded by the orphaned set |
| Low on all | No structural replacement has emerged; the orphaned amplifiers have diversified without collectively filling the vacancy |

The table is sorted by **First activity** by default — the candidate's earliest recorded message — so that genuinely new channels appear at the top when *Only after vacancy* is enabled. Click any column header to re-sort.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

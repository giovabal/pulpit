# Measure proposals: political relevance in leaderless far-right networks

Node-level measure candidates for Pulpit, developed against the one-degree constraint: a
measure must be a function of observed citation dyads incident to the node, its neighbours'
attributes, and dyad timestamps — no path or walk aggregation beyond one step, with
Burt-constraint-style ego locality (ties among a node's own neighbours) as the outer limit.

**TL;DR recommendation.** Build three things — **Effective amplifier blocs** (original
composite, the flagship: strength-weighted effective number of structurally independent
amplifier clusters), **in-h-degree** (an obscure existing measure that fits the construct
almost perfectly), and **Uptake lag** (the origin-side mirror of `DIFFUSIONLAG`) — plus two
cheap imports and one pilot-grade idea. Rejections and reasons at the end.

## 1. What "relevance" means when nobody leads

In the leaderless-resistance / groupuscular model (Beam 1992; Griffin 2003's "rhizomatic"
groupuscules; Urman & Katz 2022 for Telegram specifically), relevance is not command
authority — it is being *load-bearing infrastructure for a milieu of nominally independent
cells*. That decomposes into distinct axes:

1. breadth of uptake across **structurally independent** actors,
2. **sustained** rather than spike-driven uptake,
3. temporal position — agenda-setter vs archive,
4. uptake **across organizational boundaries**,
5. the **dependence** a node creates in others.

The current battery covers recursive status (`PAGERANK`/`HITSHUB`/`HITSAUTH`), volume
(strength, `AMPLIFICATION`), cross-community evenness (`MODULEROLE` participation), and
adopter-side timing (`DIFFUSIONLAG`) — but none of (1), (3) origin-side, or (5), and
(2)/(4) only partially.

## 2. Existing measures worth importing

### 2.1 Effective number of amplifiers

Inverse disparity (Barthélemy et al. 2005 — the same Y(v) already in `disparity_filter`;
Hill numbers, Jost 2006): `1 / Σ_u (w_uv / s_in)²` over in-edges — how many amplifiers
*effectively* sustain this channel. In-strength 10 from one superfan → 1; spread over ten
channels → 10. Distinguishes milieu relevance from patronage dependence. Cheap, weighted,
one-degree trivially. Presented mainly as the baseline the flagship (§3.1) generalises.

### 2.2 Weighted average amplifier strength (knn^w)

Pastor-Satorras et al. 2001; Barrat et al. 2004 — restricted to in-neighbours: are you
amplified by hubs (elite consecration) or by the small periphery (grassroots uptake)? This
is exactly one recursion step — strictly less inference than PageRank, which the battery
already accepts. The *low* end is the interesting pole for leaderless milieus: relevance
from below. Adversarial note: correlates with PageRank at the high end, so its marginal
value is asymmetric — worth having, not worth headlining.

### 2.3 Directional E-I / external-uptake share

Krackhardt & Stern 1988, rescaled to [0, 1]: the fraction of in-strength arriving from
channels whose representative label in a chosen basis group differs from yours — with the
in/out split as the twist, since `MODULEROLE`'s participation is deliberately
direction-invariant. In-side external share = *post-organizational audience*; out-side =
post-organizational curation. On a `LABELGROUP` basis this directly quantifies
"post-organizational" behaviour per channel. Convention needed for unlabelled channels
(own bucket). Same evidence class as `MODULEROLE`.

### 2.4 Non-imports, checked

- Kitsak et al. 2010's coreness-as-spreading-power is already served by the `KCORE`
  strategy — no new measure needed.
- The lobby index (Korn et al. 2009) is superseded by the h-degree proposal (§3.2).

## 3. New proposals (adversarially vetted)

### 3.1 Effective amplifier blocs — "cell-reach" (flagship, original composite)

**Definition.** Take v's amplifiers (in-neighbours; necessarily in-target, since dead
leaves have no out-edges), form the induced subgraph on them with symmetrised edges, find
connected components, let p_c = the share of v's in-strength contributed by component c,
and report `1 / Σ_c p_c²` — the effective number of *mutually unconnected amplifier
blocs*, in [1, |A|], null when no amplifiers.

**Lineage.** Composes Ugander et al. 2012's structural diversity (PNAS — contagion tracks
the number of independent components in the audience, not its size) with effective-number
weighting (Laakso & Taagepera 1979's effective number of parties — a fitting lineage for a
political measure).

**Substantive punch.** It separates organizational amplification from milieu amplification
without needing labels: an org's ten interlinked regional channels collapse to ~1 bloc,
while ten genuinely independent cells count as 10. That is the leaderless-relevance
construct stated as arithmetic — and unlike the participation coefficient it is
partition-free, so immune to community-detection instability.

**One-degree compliance.** Uses only observed dyads — edges into v and edges among v's
neighbours, the exact evidence class of `BURTCONSTRAINT` and `LOCALCLUSTERING`.

**Weaknesses probed.**
- Correlated with in-degree, but saturates under concentration — report beside `in_deg`;
  the effective-number form is what tames it.
- "Independence" means *citation-observable* independence — two amplifiers may coordinate
  invisibly. An optional `links=` parameter could add coordination-layer co-forwarding
  ties as linking evidence among amplifiers.
- Sockpuppet inflation is possible but no worse than for any in-side measure, and costs
  the attacker many channels.
- Cost: O(Σ deg²)-ish, negligible at Pulpit scale.

### 3.2 Amplification h-degree

**Definition.** Largest h such that ≥ h distinct in-target amplifiers each cited the
channel ≥ h times — the in-side h-degree (Zhao, Rousseau & Ye 2011, *Journal of
Informetrics*; lineage Hirsch 2005), computed on raw citation counts regardless of
`--edge-weight-strategy` (same invariance convention as `INDEGCENTRALITY`).

**Substantive fit.** Measures **sustained breadth × depth jointly**: robust to one
superfan (unlike in-strength) and to drive-by mentions (unlike in-degree), and expensive
to game — an attacker needs many channels *each* citing many times. For leaderless milieus
this is the "repeated uptake by many independents" signal.

**Weaknesses.** Integer-coarse at the low end (many ties among small channels — fine, it
is a top-of-distribution measure); grows with observation-window length (uniform within an
export; per-year exports handle time). Trivial to compute.

### 3.3 Uptake lag — `UPTAKELAG(window=…)`

**Definition.** The origin-side mirror of `DIFFUSIONLAG`: median hours from a channel's
original post to in-target forwards of it, attributing each forward event to the *origin*
channel instead of the forwarder.

**Substantive fit.** Low = agenda-setter — the milieu metabolises your content fast. With
`window=0` (disabled) the high tail identifies **archive/library nodes** — channels whose
old content keeps circulating (the "Terrorgram librarian" phenomenon; conceptual kin of
sleeping-beauty papers, Ke et al. 2015) — a real and analytically important far-right role
that every burst-style metric misses.

**Implementation.** Reuses `DIFFUSIONLAG`'s machinery, window semantics, and null
convention wholesale. Forwards only (references carry no origin-message date), like
`DIFFUSIONLAG`.

**Weakness `DIFFUSIONLAG` does not share as acutely.** Right-censoring — posts near the
export cutoff can only exhibit short lags, so the median should count only forwards of
origins posted at least `window` before the analysis end.

### 3.4 Satellite count (secondary)

**Definition.** The number of amplifiers who devote a *majority* of their citation
activity to v (share of their out-weight > 0.5, threshold as a parameter,
e.g. `SATELLITES(share=0.5)`).

**Substantive fit.** Dependence-based relevance — how many channels orbit you — with
lineage in ecological dependence asymmetry (Bascompte, Jordano & Olesen 2006) and
patron-client structure. One-degree: neighbours' row-normalised direct weights — the same
information `PARTIAL_MESSAGES` already uses. Majority (not top-1) makes it tie-free.

**Weakness.** Noisy for amplifiers with few citing messages; add a minimum-citations
floor.

### 3.5 Amplification burstiness (pilot only)

Goh & Barabási 2008's B = (σ − μ)/(σ + μ) over inter-arrival times of *received*
citations: steady infrastructural relevance vs event-driven/stochastic spikes — a
genuinely interesting distinction for stochastic-mobilisation dynamics. But: unstable
below ~10 events (use Kim & Jo 2016's finite-size estimator, null below a floor), and
confounded by network-wide event waves that spike everyone at once. Pilot before
committing it to the battery.

## 4. Rejected after adversarial review

| Candidate | Reason for rejection |
| :-- | :-- |
| Bonacich β<0 power centrality | The "hub of small cells" intuition is better served by knn^w's low pole; negative-β is numerically unstable near the spectral bound on sparse citation graphs |
| Simmelian-tie share (Krackhardt 1999) | Empirically ≈ f(clustering × reciprocity); redundant with two existing columns |
| Local/multiscale assortativity (Peel et al. 2018) | Random-walk multiscale — violates one-degree; knn is its legitimate one-degree rung |
| ECI / fitness-complexity on the channel×origin bipartite matrix | Measures curation *distinctiveness*, not relevance; leans on the opt-in coordination data |
| Irreplaceability (1 − max neighbour-set similarity) | O(n²), noise-dominated by near-duplicate small channels; the vacancy module already answers the substantive question with temporal evidence |
| A composite "far-right relevance index" | Hides weighting judgments inside a scalar; against the battery's philosophy of separable, referenced columns |

## 5. Fit with the battery

All proposals slot into the existing token grammar: `UPTAKELAG(window=…)` repeatable like
`DIFFUSIONLAG`; `AMPLIFIERBLOCS(links=…)` and `SATELLITES(share=…)` parameterised;
h-degree parameter-free. Null conventions follow the Burt/reciprocity precedent (null when
no amplifiers); h-degree is weight-strategy-invariant by design, blocs and satellites
respect the strategy. Dead leaves score legitimately on all in-side measures (they are
cited; their own citations stay out of scope, consistent with the `RECIPROCITY`
convention). Each measure has an out-side dual, but relevance is audience-side — skip the
duals for now.

**Suggested build order.** Effective amplifier blocs + h-degree first (one PR — both are
pure graph-side, no new queries); `UPTAKELAG` second (touches the message-query layer).

## References

- Barrat, A., Barthélemy, M., Pastor-Satorras, R., & Vespignani, A. (2004). The architecture of complex weighted networks. *PNAS*.
- Barthélemy, M., Barrat, A., Pastor-Satorras, R., & Vespignani, A. (2005). Characterization and modeling of weighted networks. *Physica A*.
- Bascompte, J., Jordano, P., & Olesen, J. M. (2006). Asymmetric coevolutionary networks facilitate biodiversity maintenance. *Science*.
- Beam, L. (1992). Leaderless resistance. *The Seditionist*.
- Goh, K.-I., & Barabási, A.-L. (2008). Burstiness and memory in complex systems. *EPL*.
- Griffin, R. (2003). From slime mould to rhizome: an introduction to the groupuscular right. *Patterns of Prejudice*.
- Hirsch, J. E. (2005). An index to quantify an individual's scientific research output. *PNAS*.
- Jost, L. (2006). Entropy and diversity. *Oikos*.
- Ke, Q., Ferrara, E., Radicchi, F., & Flammini, A. (2015). Defining and identifying Sleeping Beauties in science. *PNAS*.
- Kim, E.-K., & Jo, H.-H. (2016). Measuring burstiness for finite event sequences. *Physical Review E*.
- Kitsak, M., et al. (2010). Identification of influential spreaders in complex networks. *Nature Physics*.
- Korn, A., Schubert, A., & Telcs, A. (2009). Lobby index in networks. *Physica A*.
- Krackhardt, D. (1999). The ties that torture: Simmelian tie analysis in organizations. *Research in the Sociology of Organizations*.
- Krackhardt, D., & Stern, R. N. (1988). Informal networks and organizational crises: an experimental simulation. *Social Psychology Quarterly*.
- Laakso, M., & Taagepera, R. (1979). "Effective" number of parties: a measure with application to West Europe. *Comparative Political Studies*.
- Pastor-Satorras, R., Vázquez, A., & Vespignani, A. (2001). Dynamical and correlation properties of the Internet. *Physical Review Letters*.
- Peel, L., Delvenne, J.-C., & Lambiotte, R. (2018). Multiscale mixing patterns in networks. *PNAS*.
- Ugander, J., Backstrom, L., Marlow, C., & Kleinberg, J. (2012). Structural diversity in social contagion. *PNAS*.
- Urman, A., & Katz, S. (2022). What they do in the shadows: examining the far-right networks on Telegram. *Information, Communication & Society*.
- Zhao, S. X., Rousseau, R., & Ye, F. Y. (2011). h-Degree as a basic measure in weighted networks. *Journal of Informetrics*.

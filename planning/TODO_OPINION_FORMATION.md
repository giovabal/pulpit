# TODO — Opinion-formation layer (INOF) on the citation graph

Roadmap of 2026-11-20. The six design questions were settled with the user the same day (§3).
Nothing is implemented yet. Goal: an opt-in `structural_analysis` layer that runs the **Ising Network
Opinion Formation** model (INOF; Ermann, Frahm & Shepelyansky), generalised to *q* camps, on the
Pulpit graph. Camps are analyst-chosen channel sets with fixed opinions; the layer reports which
camp each remaining channel settles into and how robust that is. Results come for the full range
and for every timeline period, on a separate page of their own.

**TL;DR.**
- Build one q-colour INOF kernel. Binary Ising is the q = 2 case.
- Ship two baselines with it: the **one-step vote** (the one-degree baseline) and the **linear
  harmonic solution** (the voter model with the seeds as zealots).
- Default direction is **exposure**: a channel takes the weighted majority of the channels it
  forwards.
- Report the per-run outcome distribution, a dissent rate and seed-matched nulls. The published
  papers report none of these, and the probe (§2) shows they are needed on this graph.

---

## 1. The model as published (checked against the papers)

- **Vote.** Z_i = Σ_{j→i} σ_j · S̃_ij, with S̃_ij = 1/k_out(j). Dangling columns are zero, and the
  damping/teleport term is not used. Variant *OPA* uses the adjacency matrix instead; the papers
  mostly use *OPS* (the Markov matrix).
- **Update.** σ_i = +1 if Z_i > 0, −1 if Z_i < 0, unchanged if Z_i = 0. A channel is visited
  asynchronously, in a random order shuffled every pass.
- **Undecided ("white") channels.** All non-fixed channels start with σ = 0. A white channel casts no
  vote, and once coloured it never becomes white again. A channel the seeds never reach stays white
  and is left out of the colour shares.
- **Run length.** τ = 20 full passes, the steady state the papers judge from their f_r(τ) plots.
  N_r = 10³–10⁶ realisations, which differ only in the update order.
- **Readout.** μ_i = ⟨σ_i⟩ over realisations, μ_0 = network mean, reported as Δμ_i = μ_i − μ_0. The
  authors read a high Δμ as *influence*, not as a positive or negative attitude.
- **q colours (2025).** Z_i(C) = Σ_j [σ_j = C] · S̃_ij. A channel takes the colour with a strict
  maximum; a tie changes nothing. Preferences are η_C(i) and Δη_C(i) = η_C(i) − η_{0,C}, drawn on
  RGB-triangle maps.
- **Temperature (2025).** W_± = Z_±^β / (Z_+^β + Z_−^β), T = 1/β. The polarised phase is stable
  below T_c ≈ 1.
- **GINOF (Bukina & Shepelyansky 2026).** An undirected network. Non-fixed channels start with
  random ±1 opinions and vote with a reduced amplitude W < 1. A flip needs |Z_i| > Z_c (the
  "conviction threshold"), after which the channel votes at W = 1. There is a phase transition from
  elite-dominated to crowd-dominated opinion. The paper also shows the *Erdős barrage*: one
  well-placed opposite colour next to a seed can flip the balance.
- **What the papers lack.** None of them reports a null model: no rewiring, no matched seeds.
  Uncertainty is Monte Carlo error only, √((1−μ²)/(N_r−1)) or block subsampling. Seeds are picked
  by hand, and sensitivity to that choice is asserted rather than swept.

## 2. Feasibility probe on a real graph (2026-11-20)

Throwaway scratchpad script, not kept. It used `build_graph` defaults (PARTIAL_REFERENCES, mentions
on, no dead leaves, self-loops removed): **342 channels, 6,181 ties**. 291 channels (85%) sit in
the largest strongly connected component, 12 are never cited and 45 cite nobody in scope. Each
contest used 2,000 realisations × 20 passes.

Two readings of Pulpit's X→Y edge (X cites Y):
- **Endorsement** is literal INOF: a channel takes the majority of the channels citing it, each
  citer's vote split across what it cites.
- **Exposure** is the transpose: a channel takes the weighted majority of the channels it forwards
  or cites.

| Check | Exposure | Endorsement |
|:--|:--|:--|
| 1 vs 1 seed: Channel A (+, top PageRank in North America) vs Channel B (−, top in Europe) | Per-run share of + is **bimodal**: 43% of runs end below 0.1, most others at 0.5–1.0. The core flips as a block, so μ_i ≈ P(core goes +) | Broad spread; no channel ends on the same side in > 95% of runs |
| Same, 5 seeds per side (top-5 PageRank) | Unimodal at 0.4–0.7: a stable split | Still bimodal |
| Seeds swapped for each side's #2 / #3 PageRank channel (Spearman of μ_i) | 0.86 / 0.73 | 0.40 / 0.46 |
| INOF vs linear harmonic, 2 camps | Spearman 0.85, same side 92% | Spearman 0.89, same side **41%** |
| INOF vs linear harmonic, 3 camps (top PageRank of each Type) | Spearman 0.77, same side 91%; 40% of decided channels end on one side in > 95% of runs | Spearman 0.91, same side 45%; 24% end on one side in > 95% |
| Channels the seeds never reach | 13% | 4% |
| Label recovery, channels tied directly to a seed | One-step vote **94%**, INOF 86%, harmonic 85% | One-step **92%**, INOF 90%, harmonic 90% |
| Label recovery, channels with no direct tie to any seed (59–82 of ~241) | INOF **74%**, harmonic 66%, at 68% coverage | INOF **82%**, harmonic 79%, at 83% coverage |
| Temperature (mean + share / run-to-run sd) | T = 0.25: 0.38 / 0.42; T = 1: 0.47 / 0.20; T = 2: 0.49 / 0.08 | T = 0.25: 0.25 / 0.31; T = 1: 0.28 / 0.25; T = 2: 0.50 / 0.05 |
| Runtime (numba) | ≈ 0.6 s per 2,000 realisations | ≈ 1.1 s |

Label recovery seeded a random 20% of North America and of Europe (Continent label), predicted the
rest, and averaged over 10 draws. Guessing the larger label scores 56%.

What follows from this:
- A single-seed contest is mostly a lottery over update order on a dense core.
- The one-step vote beats propagation wherever it can vote at all, so INOF only adds information
  for channels with no direct tie to a seed. These numbers still carry signal: 66–82% against a
  56% baseline.
- Exposure is much less sensitive to which seeds are chosen.
- The ordered phase holds up to T ≈ 1, as in the paper.
- `numba` is installed only as a dependency of `umap-learn`.

## 3. Decisions (agreed 2026-11-20)

| # | Question | Decision |
|:--|:--|:--|
| 1 | Default direction | **EXPOSURE**. ENDORSEMENT (literal INOF) is available per contest |
| 2 | Seeds | **Analyst-chosen channel sets** ("camps") |
| 3 | Where contests are defined | **Command-line tokens referencing channel and label IDs**, recorded in `PARAMETERS.md` |
| 4 | Weights | The export's `--edge-weight-strategy`, normalised so each channel's outgoing citations sum to 1. This is PageRank's matrix without teleport; see §6.2 for how each direction reads it |
| 5 | Where node results appear | **Only on the separate page** (`opinion.html` + its XLSX/CSV). Not in the channel table, `measures_labels`, map colouring or GEXF/GraphML |
| 6 | Periods | **Per-period results from Phase 1 on**, alongside the full range |

Design rules that follow from the probe:
- **R1.** Every contest reports its per-run outcome distribution plus a bimodality flag, never μ_i
  alone.
- **R2.** Every channel gets a **dissent rate** besides η / Δη: the share of runs in which it ends
  against that run's plurality colour.
- **R3.** The one-step vote and the linear harmonic solution are always computed and shown next to
  INOF. The page states that INOF adds information only on channels with no direct seed tie.
- **R4.** Significance runs against nulls the papers lack (Phase 2): seed sets matched on size and
  prominence, and leave-one-seed-out.
- **R5.** Censoring follows the rest of Pulpit. A channel with no observed outgoing citations (dead
  leaf, or a channel citing nobody in scope) has a zero row. Under exposure it can only be
  coloured as a seed; under endorsement it gets a colour but casts no vote. A channel the seeds
  never reach is reported as *unreached*, never as 0.

## 4. Reading under the one-degree model

docs/network-measures.md: the graph is a *citation* network and its multi-hop paths carry no
recorded flow. INOF is a recursion over recorded dyads. Like PageRank, it asserts no path along
which content travelled. The result is **structural alignment**: the camp whose citation
neighbourhood a channel sits in, *if every forward were an act of influence*. It is not an observed
opinion and not a diffusion forecast.
- **Exposure** reads a forward as attention. X forwarding Y is a recorded exposure of X to Y, and
  Y's state comes from what Y forwards in turn.
- **Endorsement** is PageRank's recursion split by camp.

Homophily and influence cannot be told apart in cross-section (Shalizi & Thomas 2011). The page
and the docs must say so.

## 5. Non-binary approaches (evaluated)

| Approach | What it adds | Verdict |
|:--|:--|:--|
| **q-colour INOF** (2025, strict-max vote) | k camps at once; q = 2 is the binary model | **Build (Phase 1)**: one kernel for all q |
| **Potts heat bath**, P(c) ∝ Z_c^{1/T} | Robustness of spheres to noise; a T_c diagnostic | **Build** as a contest parameter (Phase 1) and a sweep (Phase 2) |
| **Linear harmonic / voter model with zealots / DeGroot with stubborn agents** | Exact, deterministic, continuous on the q-simplex, one sparse solve in milliseconds; equals the expected final state of the voter model | **Build** as a companion baseline (Phase 1) |
| Friedkin–Johnsen (susceptibility λ, anchoring to a prior) | Partial stubbornness | Phase 4, only with empirical priors |
| GINOF crowd prior (W, Z_c) | Robustness to random starting opinions; the elite-vs-crowd transition | Phase 4 experiment |
| Empirical external fields (random-field Potts) from content layers (link-category shares, tags, image copies) | Data-anchored starting opinions | Phase 4, research-grade. Its inferential counterpart is the network autocorrelation model (Leenders 2002), confounded by homophily (Shalizi & Thomas 2011) |
| Bounded confidence (Deffuant 2000; Hegselmann–Krause 2002) | Continuous opinions with homophily | **Rejected**: needs an observed starting opinion for every channel, and results are set by the confidence ε |
| Signed / antagonistic ties (Altafini 2013) | Negative influence | **Rejected**: contradicts the positive-citation assumption (docs/dominance.md) |

## 6. Specification

### 6.1 Camps and contests (command line)

```bash
python manage.py structural_analysis --opinion \
  --opinion-camp CORE=1234,5678,L12 \
  --opinion-camp EUROPE=L4 \
  --opinion-camp NORDIC=2201,2207,2310 \
  --opinion-contests "INOF(camps=CORE+EUROPE), INOF(camps=CORE+EUROPE, direction=ENDORSEMENT), INOF(camps=CORE+EUROPE+NORDIC, temperature=0.5)" \
  --opinion-realisations 10000 --opinion-seed 42
```

- `--opinion-camp NAME=MEMBER[,MEMBER…]` is repeatable.
  - `NAME` matches `[A-Z][A-Z0-9_]*` (upper-cased) and is unique.
  - A `MEMBER` is a channel pk (`1234`, as in `/channel/<pk>/`) or `L<label id>`.
  - `L<id>` means every graph channel whose representative label in that label's group is the label,
    over the window being computed (`graph_builder.resolve_window_label`, the same resolution as the
    `group_partitions` node data; a container label resolves through its children). It is therefore
    re-resolved per period.
- `--opinion-contests` takes a token list parsed by `network/tokens.py` (`parse_tokens`). The one
  spec is `INOF`, repeatable:
  - `camps` (str, required): 2–8 camp names joined by `+`, validated against the defined camps at the
    call site, like MODULEROLE `basis`.
  - `direction`: enum `EXPOSURE` (default) | `ENDORSEMENT`.
  - `temperature`: float ≥ 0, default `0` = majority rule.
  - The contest key follows the tokens.py suffix rules, e.g. `inof_camps_core_europe`.
    `slug_value` must map `+` to `_`.
- **Validation**, run in `_resolve_options` and again per period before anything is computed:
  - unknown camp name, or the same camp twice in a contest;
  - a channel belonging to two camps of one contest (error naming the channels);
  - fewer than 2 camps, or more than 8;
  - a pk that is not a channel.
- **Resolution per window.** Seeds absent from that window's graph are dropped and listed as
  `dropped`. A camp left with no member present skips the contest for that window, with a reason.
- **Config and panel.** Config gets `[outputs].opinion` plus an `[opinion]` table (`camps`, `contests`,
  `realisations`, `seed`, Phase 2 keys). The panel uses the shared `token_builder.js` for contests and
  a camps text area (Phase 3).

### 6.2 Voting matrix and dynamics

- **Matrix.** W = tie weights under `--edge-weight-strategy` (`weight_raw`), self-loops removed.
  P = D_out⁻¹ W, row-stochastic and without teleport.
  - **EXPOSURE**: V = P. Row i is the focal citer, and its voters are the channels it cites, weighted
    by their share of its citations (its attention). The normalisation is per focal channel. It
    rescales all of i's votes by one constant, so it does not change which camp wins.
    - The literal per-*voter* normalisation in this direction would be INOF's G* convention: a
      source's vote split across its audience. That penalises widely forwarded sources, so it is
      **not** used.
  - **ENDORSEMENT**: V = Pᵀ. Row i is the cited channel, and its voters are its citers, each citer's
    single unit of endorsement split over what it cites. This is literal INOF (S̃), normalised per
    voter.
  - **Consequence.** In both directions the per-amplifier constants of TOTAL, PARTIAL_MESSAGES and
    PARTIAL_REFERENCES cancel. As for PageRank, the three give identical results and only `NONE`
    differs. The docs must say so.
- **State.** Colours 1..q plus 0 = undecided. Seeds are fixed. Every other channel starts at 0.
- **Update.** Asynchronous; each pass visits the non-seed channels in a fresh random order;
  `SWEEPS` = 20 passes.
  - **T = 0**: take the strict-max colour of Z_i(c) = Σ_j V_ij [σ_j = c]. A tie or an all-zero vote
    leaves the state unchanged.
  - **T > 0**: heat bath P(c) ∝ Z_i(c)^{1/T} over colours with Z_i(c) > 0. An all-zero vote leaves
    the state unchanged. This generalises the 2025 equation 3 to q colours.
  - An undecided channel never comes back to 0 once coloured.
- **Realisations.** Default 10,000, about 5 s per contest per window at N ≈ 340. The RNG is seeded
  from `--opinion-seed` + contest index + window index, so results are reproducible and windows are
  independent.
- **Convergence check.** Mean flips in the last pass. Warn if above `CONVERGENCE_WARN_SHARE` of free
  channels at T = 0.
- **Kernel.** numba `@njit`, one function for all q and T. `numba` becomes a direct entry in
  `requirements.txt` (it is already installed with `umap-learn`).

### 6.3 Outputs per contest and window

**Per channel** (page, XLSX and CSV only):

| Field | Definition |
|:--|:--|
| `eta[c]` | Share of runs ending in camp c, among the runs where the channel is decided |
| `undecided` | Share of runs ending undecided; 1 = unreached |
| `mu`, `delta_mu` | q = 2 only: η₊ − η₋ and μ − μ_0 |
| `delta_eta[c]` | η_c − η_{0,c} |
| `dissent` | Share of decided runs ending in a colour other than the run's plurality colour among free decided channels |
| `one_step` | Weighted plurality of the channel's *direct* ties to seeds, using the same V; `null` without a direct seed tie |
| `direct` | Has at least one direct tie to a seed |
| `linear[c]` | Absorption probability of the walk on V into camp c (harmonic solution, sparse solve restricted to channels that reach a seed); `null` when unreached |
| `se` | Monte Carlo standard error by block subsampling (`MC_BLOCKS` = 100) |
| context | Name, primary label, seed camp if any |

**Per contest:**
- camps with members and dropped seeds;
- η_0 per camp (μ_0 for q = 2), the undecided share, the convergence figure;
- outcome histogram: per-run share of the winning colour, in `OUTCOME_BINS`;
- the **Sarle bimodality coefficient**, flagged above 5/9 as a "lottery";
- agreement with the baselines: INOF vs one-step on direct channels; INOF vs linear as side
  agreement and Spearman;
- the share of free channels with no direct seed tie, which is where INOF is the only estimate.

**Files:**
- `data/opinion.json` and `data_<key>/opinion.json` = `{contests: [{key, label, direction,
  temperature, realisations, camps, summary, channels, inference?}], skipped: [...]}`.
- `timeline.json` gains `has_opinion`.

### 6.4 Periods

- `_run_period_export` runs every contest on the period graph (`_build_period_graph`). `L<id>`
  members are re-resolved on the period's labels, and channel members are kept when present.
- Sliding windows are fine: the contests need no disjoint periods.
- The page's period navigator uses `readTimeline` / `periodDataDir`. A per-contest trend chart plots
  η_0 by period.

## 7. Phases

### Phase 1: engine, contests, JSON, full range and periods
- [ ] `network/opinion.py`: `voting_matrix(graph, direction)`, `run_contest(V, seeds, q, temperature,
      realisations, rng_seed)` (numba kernel returning per-channel colour counts + per-run outcome
      vectors), `harmonic(V, seeds)`, `one_step_vote(V, seeds)`, `summarise(...)` (η, Δη, dissent, SE,
      histogram, bimodality, agreement), `resolve_camps(graph, camps, window)`.
- [ ] `FIXED_PARAMETERS`, added to `PARAMETER_MODULES`; scope `opinion` in `SCOPES` /
      `active_scopes`. Declare: `SWEEPS`, the tie rule, the undecided rule, `OUTCOME_BINS`,
      `BIMODALITY_THRESHOLD`, `MC_BLOCKS`, `CONVERGENCE_WARN_SHARE`, the RNG seed derivation, the
      default realisations, self-loops excluded.
- [ ] `network/tokens.py`: the `INOF` spec; `+` handled in `slug_value`.
- [ ] `structural_analysis`: `--opinion`, `--opinion-camp`, `--opinion-contests`,
      `--opinion-realisations`, `--opinion-seed`; `ResolvedOptions` fields; validation; run in `_handle`
      and `_run_period_export`; `exporter.write_opinion_json`; `has_opinion` in timeline.json.
- [ ] `requirements.txt`: `numba`.
- [ ] Tests, `network/tests_opinion.py` (§9).
- [ ] Smoke run on a real DB with the probe's contests, to check that §2's numbers are reproduced.

### Phase 2: inference
- [ ] **Seed-matched null** (`--opinion-null-samples K`, default 0 = off). Replace one camp's seeds
      with K random free channel sets of the same size, stratified by PageRank decile
      (`NULL_STRATA`), the other camps fixed; `NULL_REALISATIONS` = 1,000 per draw. Statistic: the
      camp's sphere η_{0,c}. Report z and the add-one empirical p
      (`robustness.null_model.empirical_p`), with BH q over camps × contests × windows
      (`robustness.bh_adjust`). Cost ≈ K × 0.5 s per camp per window, so it is opt-in.
- [ ] **Leave-one-seed-out.** Free each seed in turn and rerun. Record whether it returns to its own
      camp (*camp cohesion* = share recovered, against the camp's base rate among free channels), and
      the Spearman of the other channels' η against the full run (*seed influence*: which seed
      carries the camp).
- [ ] **Temperature sweep** (`--opinion-temperature-grid 0,0.25,0.5,1,2`, full range only): η_0 and
      the run-to-run sd per T, plus the T_c estimate.
- [ ] Results under `contests[].inference` in opinion.json.

### Phase 3: page, exports, panel, docs
- [ ] `network/templates/network/opinion.html` + `webapp_engine/map/js/opinion.js`, following
      `dominance.html` / `dominance.js`:
  - contest selector;
  - contest card: camps, η_0, undecided share, outcome histogram + lottery flag, baseline agreement,
    Phase 2 results;
  - sortable channel table;
  - period navigator and η_0 trend (Chart.js).
- [ ] `tables.write_opinion_html` and `tables.write_opinion_xlsx` (sheets Contests, Channels,
      Periods); `exporter.write_opinion_csv` (`opinion_contests.csv`, `opinion_channels.csv`). All
      three share one column layout, like dominance's `NODE_COLUMNS`.
- [ ] Index card `include_opinion_html/xlsx`; probe in `compare_analysis`.
- [ ] Operations panel: `runner/templates/runner/operations.html` fieldset (camps text area +
      token_builder contests), `runner/views.py` `_apply_spec`, `webapp_engine/config/defaults.py`,
      `configuration/.operations-structural` keys.
- [ ] `docs/opinion-formation.md`: method, §4 reading, caveats (lottery, seed sensitivity, structural
      alignment ≠ opinion, homophily, weight-strategy invariance), references. Plus
      `docs/workflow.md` flags, `docs/configuration.md`, CHANGELOG, a CLAUDE.md key-modules entry.
- [ ] `npm run lint`, `python beautify.py` on the new JS, `ruff`.

### Phase 4: extensions (each optional, decide later)
- [ ] **Pivotal channels.** For each free channel, the shift in η_0 when it is fixed to the opposite
      camp or removed (the GINOF Erdős barrage). About 4 min at N ≈ 340 with 2,000 realisations.
      Pairs with the robustness ban waves.
- [ ] **GINOF crowd prior**: random starting opinions, amplitude W, conviction threshold Z_c; an
      elite-vs-crowd phase diagram.
- [ ] Friedkin–Johnsen and random-field Potts with empirical priors from the content layers.
- [ ] Camps removed by recorded closures (`ChannelVacancy`) or before/after events: does a sphere
      shrink when its seeds vanish?

## 8. Files touched

New:
- `network/opinion.py`, `network/tests_opinion.py`;
- `network/templates/network/opinion.html`, `webapp_engine/map/js/opinion.js`;
- `docs/opinion-formation.md`.

Edited:
- `network/tokens.py`, `network/parameters.py`, `network/exporter.py`, `network/tables.py`;
- `network/management/commands/structural_analysis.py`,
  `network/management/commands/compare_analysis.py`, `network/templates/network/index.html`;
- `runner/templates/runner/operations.html`, `runner/views.py`;
- `webapp_engine/config/defaults.py`, `configuration/.operations-structural`;
- `requirements.txt`, `docs/workflow.md`, `docs/configuration.md`, `CHANGELOG.md`, `CLAUDE.md`.

## 9. Tests

- **Two cliques joined by one bridge**, one seed per clique: each clique takes its seed's colour
  (η ≈ 1); the bridge channels split.
- **Directed path and star.** EXPOSURE and ENDORSEMENT mirror each other on the reversed graph, and
  the star hub follows the weighted majority of its seeds.
- **Unreachable component**: undecided = 1, linear `null`, one-step `null`.
- **q = 2** through the q-colour kernel gives Ising results (same RNG seed → identical output).
- **T > 0 kernel**: at very high T, η tends to uniform over the colours voting; at T = 0 it equals
  the majority kernel.
- **Harmonic sparse solve** equals a dense solve on a small random graph; rows sum to 1 over reached
  channels.
- **Weight strategies**: TOTAL = PARTIAL_MESSAGES = PARTIAL_REFERENCES; NONE differs on a crafted
  graph.
- **Dead leaf / zero row**: stays undecided under EXPOSURE, casts no vote under ENDORSEMENT.
- **Tokens and camps**: unknown or duplicate camp, overlapping membership, `L<id>` resolution
  (container label included), dropped seeds, skipped contest in a period without members.
- **Reproducibility**: same `--opinion-seed` → byte-identical opinion.json.
- **Phase 2**: null p-value ∈ (0, 1]; leave-one-seed-out on the two cliques recovers every seed.

## 10. Open details (settle while building)

- The `+` separator in `camps=`, versus `/`, for readability in shell and keys.
- Whether the seed-matched null also runs per period (cost × number of periods) or on the full
  range only.
- The maximum q (8 is proposed) and the camp colours: a fixed categorical palette, or each camp's
  dominant label colour.
- Whether a camp member's period-level absence should be shown on the page as a per-period seed
  table.

## 11. References

- Ermann, L. & Shepelyansky, D. L. (2024) "Confrontation of capitalism and socialism in Wikipedia
  networks." *Information* 15(9):571. [doi:10.3390/info15090571](https://doi.org/10.3390/info15090571)
  — introduces INOF.
- Ermann, L., Frahm, K. M. & Shepelyansky, D. L. (2025) "Opinion formation in Wikipedia Ising
  networks." *Information* 16(9):782. [doi:10.3390/info16090782](https://doi.org/10.3390/info16090782)
  — q colours, temperature, OPA/OPS.
- Bukina, K. & Shepelyansky, D. L. (2026) "Opinion formation at Ising social networks."
  *Information* 17(1):41. [doi:10.3390/info17010041](https://doi.org/10.3390/info17010041) — GINOF,
  conviction threshold, Erdős barrage.
- Kandiah, V. & Shepelyansky, D. L. (2012) "PageRank model of opinion formation on social networks."
  *Physica A* 391(22):5779–5793 — the PROF ancestor.
- Mobilia, M. (2003) "Does a single zealot affect an infinite group of voters?" *Phys. Rev. Lett.*
  91:028701; Yildiz, E., Ozdaglar, A., Acemoglu, D., Saberi, A. & Scaglione, A. (2013) "Binary
  opinion dynamics with stubborn agents." *ACM Trans. Econ. Comput.* 1(4):19 — voter model with
  zealots, the linear baseline.
- Zhu, X., Ghahramani, Z. & Lafferty, J. (2003) "Semi-supervised learning using Gaussian fields and
  harmonic functions." *ICML* — the harmonic solution.
- DeGroot, M. H. (1974) "Reaching a consensus." *JASA* 69(345):118–121; Friedkin, N. E. & Johnsen,
  E. C. (1990) "Social influence and opinions." *J. Math. Sociol.* 15(3–4):193–206.
- Wu, F. Y. (1982) "The Potts model." *Rev. Mod. Phys.* 54:235–268.
- Deffuant, G. et al. (2000) "Mixing beliefs among interacting agents." *Adv. Complex Syst.* 3:87–98;
  Hegselmann, R. & Krause, U. (2002) "Opinion dynamics and bounded confidence." *JASSS* 5(3) —
  rejected.
- Altafini, C. (2013) "Consensus problems on networks with antagonistic interactions." *IEEE Trans.
  Autom. Control* 58(4):935–946 — rejected.
- Leenders, R. Th. A. J. (2002) "Modeling social influence through network autocorrelation."
  *Social Networks* 24(1):21–47; Shalizi, C. R. & Thomas, A. C. (2011) "Homophily and contagion are
  generically confounded in observational social network studies." *Sociol. Methods Res.*
  40(2):211–239.
- Pfister, R. et al. (2013) "Good things peak in pairs: a note on the bimodality coefficient."
  *Front. Psychol.* 4:700.
- Phipson, B. & Smyth, G. K. (2010) "Permutation p-values should never be zero." *Stat. Appl. Genet.
  Mol. Biol.* 9(1):39.

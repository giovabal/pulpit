# Dyadic models

*Why does one channel cite another?*

The [network statistics](whole-network-statistics.md) describe the citation graph and test single features of it against chance. They cannot say which of several overlapping reasons explains a tie: a chapter may cite another because both belong to the same nation, because the other cites it back, because it posts a lot, or because the other is widely followed — and in a transnational network those reasons are correlated. Pulpit offers two tools for that question:

- **`--mrqap`** — a dyadic regression computed inside the export, with permutation p-values built for network data;
- **`--dyadic-export`** — the network written as data for the dedicated modelling packages (ERGM, relational event models, stochastic actor-oriented models).

Both read the very graph and messages the export was computed on, inside the [one-degree attribution model](network-measures.md#what-this-catalogue-covers): every tie is a citation — a forward or mention of j by i — never a path along which content travelled.

---

## Dyadic regression (MRQAP)

Every ordered pair of channels (i, j) is one observation, and two outcomes are modelled by ordinary least squares, each on all the predictors at once:

| Dependent variable | Meaning |
| :-- | :-- |
| **Tie (0/1)** | Does i cite j at all? A linear probability model: a coefficient is a change in the probability of a tie. |
| **log(1 + citations)** | How intensely: the raw forwards + mentions (+ near-copies) from i to j, whatever `--edge-weight-strategy`. |

| Predictor | Meaning |
| :-- | :-- |
| **Same ‹group›** | i and j hold the same label in a partition label group (one predictor per group: Nation, Continent, …). The homophily effect *net of* the others. With nested groups — nation inside continent — the finer one reads as "same nation beyond same continent". |
| **Reverse tie** | j cites i: the reciprocity control. |
| **Sender / receiver activity** | log(1 + messages in the analysis window) of i and of j. |
| **Sender / receiver audience** | log(1 + subscribers) of i and of j; the receiver's audience is the popularity control. |

**Actors.** The observed channels — dead leaves are left out, since their own citations were never read and their row of the dyad matrix is unknown — that hold a label in every partition group used. A group is used when it has at least two labels among the observed channels and labels at least half of them; a sparser group is left out (and named in the output) rather than dropping every channel it does not label. A predictor constant across all pairs is dropped. Above 3,000 actors the regression is skipped: the dyad table grows with the square.

**Inference.** Dyads are not independent — every row and every column of the matrix shares a channel — so the ordinary standard errors (and the t-statistics' textbook p-values) are wrong. Pulpit uses the multiple-regression quadratic assignment procedure with **double semi-partialling** (Dekker, Krackhardt & Snijders 2007): for each predictor, its residual on all the other predictors is permuted — rows and columns together, by one random relabelling of the channels — and the model refitted; the observed |t| is compared with the permuted ones. Of the permutation schemes for MRQAP, it is the one that keeps its size under the collinearity and the row / column autocorrelation network data has (Dekker et al. 2007), where Krackhardt's (1988) original Y-permutation does not. `--mrqap-permutations` (default 1000, panel *MRQAP permutations*) sets the relabellings per predictor; the p-value is two-sided add-one, so its floor is 1/(N+1). Each permutation is evaluated through the Frisch–Waugh–Lovell identity, at the cost of a regression on one column.

**Reported** — in the network table's *Dyadic regression (MRQAP)* section, the `MRQAP` sheet of `network_table.xlsx` and `data/mrqap.json` (and per timeline year): for each model R², the intercept, and per predictor the coefficient, the **standardised β** (in standard deviations of predictor and outcome, so predictors compare), t and the permutation p.

### Reading it

- **Same nation** positive with a small p, net of reciprocity, activity and audience: national homophily is not an artefact of national scenes being more active, better followed, or more reciprocal. Its standardised β set against the receiver audience's says whether *who you are* or *how visible they are* weighs more in whom a channel cites.
- **Same continent** next to **same nation**: whether proximity matters beyond the nation (a European bloc) or only inside it.
- **Receiver audience** strongly positive: citation follows visibility — the popularity logic of a broadcast network rather than of peer exchange.
- **Reverse tie** large: citation is largely mutual, the signature of peer amplification.

### Guardrails

- **Reverse tie is endogenous.** It is a control, not a cause: i and j citing each other may share a third reason. Read the other coefficients *given* reciprocity.
- **The tie model is linear.** Predicted probabilities can leave [0, 1]; the signs and relative sizes of the coefficients are what to read, and the log-citation model is the check on intensity.
- **One window, one boundary.** The model describes ties inside the export's in-target scope and date window; channels outside it, or ties lost to deleted messages, are not in the data (coverage is a floor — see [the measures catalogue](network-measures.md#coverage-is-a-floor-not-a-census)).
- **No dependence terms.** MRQAP corrects the inference for network dependence but does not model it: triadic closure, popularity snowballing or the timing of citations belong to ERGMs, SAOMs and relational event models — hence the export below.

---

## Dyadic export (`dyads/`)

`--dyadic-export` (panel *Dyadic export*) writes a `dyads/` folder at the export root, with its own `README.md` file dictionary:

| File | Content | Typical use |
| :-- | :-- | :-- |
| `actors.csv` | Every node: title, URL, its label in each partition label group, `observed` (0 = a dead leaf, cited only), environment depth, messages in the window, subscribers, activity period, lost flag, channel type | Vertex attributes for every tool |
| `edgelist.csv` | Every tie, citing → cited: `citations` = `forwards` + `mentions` + `copies` (raw counts) and the `--edge-weight-strategy` `weight` | ERGM / valued ERGM (R `statnet`, `ergm`, `ergm.count`), QAP |
| `events.csv` | One row per citation counted on a tie, in time order: `sender`, `receiver`, UTC `timestamp`, `type` (forward / mention / copy), `message_id` | Relational event models (R `goldfish`, `relevent`, `rem`; `eventnet`) |
| `dyads.csv` | With `--mrqap`: one row per ordered pair of MRQAP actors — both dependent variables and every predictor | QAP / logistic QAP in R (`sna::netlm`, `sna::netlogit`) |
| `waves/wave_YYYY.csv`, `waves/presence.csv` | With `--timeline-step year`: one binary adjacency matrix per year over the union of the years' observed channels, and which channels exist in each year | Stochastic actor-oriented models (R `RSiena`, with `sienaCompositionChange` for channels that join or leave) |

`events.csv` is drawn from the same querysets `build_graph` aggregates (`forward_messages_qs`, `reference_rows_qs`) plus the near-copies the graph was built with, keeping only those on an edge of the graph — so its per-pair counts equal the edge's `weight_forwards`, `weight_mentions` and `weight_copies`. In every model, restrict the senders to `observed == 1`: a dead leaf's own citations were never read, so its missing out-ties are unknown, not absent.

---

## Options

| Flag | Panel | Config | Default |
| :-- | :-- | :-- | :-- |
| `--mrqap` | Outputs → *Dyadic regression* | `[outputs].mrqap` | off |
| `--mrqap-permutations N` | *MRQAP permutations* | `[computation].mrqap_permutations` | 1000 |
| `--dyadic-export` | Outputs → *Dyadic export* | `[outputs].dyadic_export` | off |

Both run on the full range and, with `--timeline-step year`, on every year (the regression per year in `data_YYYY/mrqap.json`; the bundle's waves from the year graphs). The fixed parameters behind them — actor and predictor rules, seed, the actor limit — are listed in each export's `PARAMETERS.md`.

---

## References

- Butts, C.T. (2008) "A relational event framework for social action." *Sociological Methodology* 38(1):155–200. [doi:10.1111/j.1467-9531.2008.00203.x](https://doi.org/10.1111/j.1467-9531.2008.00203.x) — relational event models.
- Dekker, D., Krackhardt, D. & Snijders, T.A.B. (2007) "Sensitivity of MRQAP tests to collinearity and autocorrelation conditions." *Psychometrika* 72(4):563–581. [doi:10.1007/s11336-007-9016-1](https://doi.org/10.1007/s11336-007-9016-1) — double semi-partialling.
- Krackhardt, D. (1988) "Predicting with networks: nonparametric multiple regression analysis of dyadic data." *Social Networks* 10(4):359–381. [doi:10.1016/0378-8733(88)90004-4](https://doi.org/10.1016/0378-8733(88)90004-4) — MRQAP.
- Krivitsky, P.N. (2012) "Exponential-family random graph models for valued networks." *Electronic Journal of Statistics* 6:1100–1128. [doi:10.1214/12-EJS696](https://doi.org/10.1214/12-EJS696) — valued ERGM.
- Snijders, T.A.B., van de Bunt, G.G. & Steglich, C.E.G. (2010) "Introduction to stochastic actor-based models for network dynamics." *Social Networks* 32(1):44–60. [doi:10.1016/j.socnet.2009.02.004](https://doi.org/10.1016/j.socnet.2009.02.004) — SAOM / RSiena.
- Stadtfeld, C. & Block, P. (2017) "Interactions, actors, and time: dynamic network actor models for relational events." *Sociological Science* 4:318–352. [doi:10.15195/v4.a14](https://doi.org/10.15195/v4.a14) — DyNAM (`goldfish`).

---

← [Whole-network statistics](whole-network-statistics.md) · [Dominance analysis](dominance.md) →

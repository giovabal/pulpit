# Event impact

*Did the network change when the event happened?*

Analysts record events in **Manage → Events**: a date, a subject, a type and, optionally, the labels the event concerns (its *scope* — e.g. *Nation: Germany* for a national ban). The web app draws them as lines on its charts. `--event-impact` (Outputs → *Event impact*) tests them: for each event inside the data it fits an **interrupted time series** (ITS) to the network's weekly activity around the event's date, and asks whether the level or the trend of each series changed at the event beyond what the weeks before predict.

---

## The weekly series

Weeks run Monday to Sunday in local calendar days (`TIME_ZONE`), the convention of every date filter in Pulpit; the event's own week counts as *after*. The series cover the export's scope — the observed channels of the full-range graph, inside their in-target periods and the date window:

| Metric | What it counts | Modelled as |
| :-- | :-- | :-- |
| Messages posted | every message | log(1 + count) |
| Forwards posted | messages with a forward header | log(1 + count) |
| Active channels | channels posting that week | log(1 + count) |
| New channels | channels posting their first in-scope message | log(1 + count) |
| In-scope citations | forwards (and, with `--mentions`, `t.me/` mentions) between observed channels — the events the citation graph is built from | log(1 + count) |
| Imported share | forwards whose source is outside the scope | share |
| Citation concentration | Herfindahl index of the week's citations over the cited channels (1 = every citation to one channel) | share |
| Cross-label share (one per partition label group) | citations whose citing and cited channels hold different labels in the group at that date — e.g. the cross-border share for a Nation group | share |

Counts are modelled on log(1 + count): a **level change** is then roughly a proportional change (0.1 ≈ +10%, reported as a % in the table), and the model is not dominated by the network's growth. A share resting on fewer than 5 events in a week is left missing rather than read as noise.

## The model

**Unscoped event — segmented regression** (Wagner et al. 2002; Bernal, Cummins & Gasparrini 2017), over ±W weeks around the event (`--event-window-weeks`, default 26):

> y = β₀ + β₁·t + β₂·post + β₃·t·post

with t in weeks from the event's week. **β₂** is the level change at the event, **β₃** the change in slope after it.

**Scoped event — comparative ITS** (Linden 2015). The *affected* series covers the channels holding one of the event's labels at each message's date (a container label — e.g. a continent — counts through its child labels); the *comparison* series covers every other observed channel. Both are stacked, with the group and its interactions added; the effects are the group × post terms. A movement-wide shift that moves both groups alike cancels out, so what is left is the change specific to the affected channels.

The window is cut at the edges of the data; each side needs at least 8 non-missing weeks, else the metric is reported as *not enough weeks*.

## Inference

Weekly series are autocorrelated — a busy week tends to follow a busy week — so ordinary standard errors are too small. Pulpit reports two p-values per effect:

- **p (HAC)** — from Newey–West heteroskedasticity- and autocorrelation-consistent standard errors (Bartlett kernel, lag ⌊4(T/100)^{2/9}⌋; Newey & West 1987, 1994), computed within each stacked series.
- **p (placebo)** — an *in-time placebo* (Abadie, Diamond & Hainmueller 2015; Bernal et al. 2018): the same model refitted with the break at every other admissible week — its whole window inside the data, more than half a window away from every recorded event — and the share of placebo effects at least as large as the observed one, (#|β̂_placebo| ≥ |β̂| + 1)/(K + 1). It needs no assumption about the shape of the errors and asks the right question for bursty data: *is this week's break unusual for this series?* With fewer than 19 admissible dates it is flagged as too coarse to read.

**q** — Benjamini–Hochberg false-discovery control of the placebo p-values across all events × metrics, separately for the level and the slope effects.

## Reading it

- **Read the placebo p and q first.** HAC p-values can look impressive on a bursty series where placebo dates regularly show breaks as large. A small HAC p with a large placebo p means *the series often jumps like this*.
- **Level vs slope.** A level change is a step at the event (e.g. channels going silent at once); a slope change a bend in the trend (e.g. growth slowing afterwards). Look at the chart: the dashed line continues the pre-event trend — what the model expects without the event.
- **Scoped events.** A positive level change for a Nation-scoped event means the affected channels moved up *relative to the others*; check the comparison series in the chart to see whether the affected group rose or the rest fell.
- **Events close together** are flagged *other events fall inside this window*: their effects are mixed, and one event's window contains the other's break.

## Guardrails

- **The date is the analyst's.** The test is only as good as the event date: a ban announced on Monday and enforced on Friday may straddle two weeks. Record the date the network could react to.
- **Association, not cause.** An ITS rules out a continuation of the pre-event trend; it does not rule out another cause at the same time. The comparative design rules out movement-wide causes for scoped events; unrelated simultaneous events remain.
- **One-degree data.** Citation counts are forwards and mentions as Telegram records them; deleted channels and messages take their citations with them, so a takedown wave lowers the series both by changing behaviour and by removing the record. Compare with the vacancy list.
- **Linear trends.** The model assumes a straight trend on each side over ±W weeks; with strong seasonality or non-linear growth, shorten the window.
- **Coverage.** The weekly series start with the first in-scope message; early weeks of a young network are small and noisy, which also widens the placebo distribution (conservative).

## Outputs

- `data/event_impact.json` — the weekly series of the network and, per event, every metric's coefficients, standard errors, p-values, q, and the fitted lines and counterfactual for the charts.
- `events.html` (with `--html`) — a weekly overview with the events marked and one card per event with a chart and the effects table.
- `event_impact.xlsx` (with `--xlsx`: `Effects`, `Weekly series`) and `event_impact.csv` (with `--csv`, the effects).
- With a timeline export, the period navigators mark the periods containing events.

The fixed parameters — the week rule, the share floor, the minimum weeks per side, the placebo rule and the affected-channel rule — are listed in each export's `PARAMETERS.md`.

## References

- Abadie, A., Diamond, A. & Hainmueller, J. (2015) "Comparative politics and the synthetic control method." *American Journal of Political Science* 59(2):495–510. [doi:10.1111/ajps.12116](https://doi.org/10.1111/ajps.12116) — in-time placebo tests.
- Bernal, J.L., Cummins, S. & Gasparrini, A. (2017) "Interrupted time series regression for the evaluation of public health interventions: a tutorial." *International Journal of Epidemiology* 46(1):348–355. [doi:10.1093/ije/dyw098](https://doi.org/10.1093/ije/dyw098)
- Bernal, J.L., Cummins, S. & Gasparrini, A. (2018) "The use of controls in interrupted time series studies of public health interventions." *International Journal of Epidemiology* 47(6):2082–2093. [doi:10.1093/ije/dyy135](https://doi.org/10.1093/ije/dyy135)
- Linden, A. (2015) "Conducting interrupted time-series analysis for single- and multiple-group comparisons." *The Stata Journal* 15(2):480–500. [doi:10.1177/1536867X1501500208](https://doi.org/10.1177/1536867X1501500208)
- Newey, W.K. & West, K.D. (1987) "A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix." *Econometrica* 55(3):703–708. [doi:10.2307/1913610](https://doi.org/10.2307/1913610)
- Newey, W.K. & West, K.D. (1994) "Automatic lag selection in covariance matrix estimation." *Review of Economic Studies* 61(4):631–653. [doi:10.2307/2297912](https://doi.org/10.2307/2297912)
- Wagner, A.K., Soumerai, S.B., Zhang, F. & Ross-Degnan, D. (2002) "Segmented regression analysis of interrupted time series studies in medication use research." *Journal of Clinical Pharmacy and Therapeutics* 27(4):299–309. [doi:10.1046/j.1365-2710.2002.00430.x](https://doi.org/10.1046/j.1365-2710.2002.00430.x)

---

← [Dyadic models](dyadic-models.md) · [Workflow](workflow.md) →

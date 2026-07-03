# Coordination analysis

The *coordination analysis* asks: **which channels move in step?** Two channels form a coordination tie when they repeatedly forward the **same origin message** within a short time window of each other. This is a second network layer, deliberately distinct from the citation graph: the citation graph records *who amplifies whom* (volume and direction of attention), the coordination graph records *who acts in synchrony with whom* (timing). A channel pair can be prominent in one layer and absent from the other — and the difference is the finding.

Enable with `--coordination-2d` and/or `--coordination-3d` on `structural_analysis` — the coordination counterparts of `--graph-2d` / `--graph-3d` — or with the two **Coordination map** toggles on the second row of the Operations panel's **Outputs** fieldset. The output is a dedicated data directory (`data_coordination/`) and, per selected toggle, an **interactive map with its own force-directed layout**: `coordination.html` (2D) and `coordination3d.html` (3D), rendered by the same viewers as the main network maps.

---

## Why a separate layer

None of the citation-graph measures can see synchrony. [Local clustering](network-measures.md#local-clustering) finds closed triangles, and reciprocity finds mutual citation — but both shapes arise organically among ideologically aligned channels, and a static graph records no timing, so neither can distinguish spontaneous affinity from arranged amplification. The distinction lives at the message level: *when* did each channel forward *what*. The coordination layer operationalises exactly that, following the coordinated-behaviour detection literature: build ties from repeated near-simultaneous identical actions, and let repetition separate arrangement from coincidence.

The layer is fully consistent with Pulpit's [one-degree attribution model](network-measures.md#what-this-catalogue-covers): every event is a dyadic fact carrying its own timestamp — channel X forwarded origin message M at time t — and no path, relay, or flow claim is ever made. Telegram's forward attribution, which *prevents* multi-hop cascade reconstruction, is precisely what makes co-forwarding detection reliable: every forward names its origin, so "the same content" is an exact identity, not a fuzzy text match.

---

## How ties are built

1. **Collect forwards.** All alive, in-window forwards by the export's in-target channels, period-aware via the same chokepoint as the citation graph (`channel_cutoff_q()` — a message counts only while its channel is in an in-target period). Self-forwards are excluded. The *origin* channel does not need to be in-target: two in-target channels co-forwarding an out-of-target origin is still coordination *between them*.
2. **Identify the origin message.** Primarily `(forwarded_from, fwd_from_channel_post)` — the origin channel plus the original post id that Telegram carries in the forward header. Forwards missing the post id fall back to `(forwarded_from, fwd_from_date)` (origin channel + original timestamp); forwards carrying neither are skipped.
3. **Deduplicate.** Per channel and origin message, only the **earliest** forward counts — a channel re-sharing the same origin twice is not two events.
4. **Pair events.** For each origin message, every pair of channels whose (first) forwards lie within `--coordination-window` seconds of each other scores one co-forwarding event for that pair.
5. **Keep repeated pairs.** A pair's tie survives only with at least `--coordination-min-events` events on **distinct origin messages**. One shared burst is breaking news; many shared bursts across different content are behaviour.

Edge weight is the number of distinct co-forwarded origins. Each tie is symmetric and is rendered in both directions, so the map viewer lists partners under *Two ways connections* — the truthful rendering of a mutual relation.

### Node measures

The coordination map carries its own columns (also offered by the *Nodes dimension* selector):

| Key | Meaning |
| :-- | :------ |
| `coordination_strength` | Total co-forwarding events across the channel's retained ties (sum of its edge weights) — the default node size |
| `coordination_partners` | Distinct channels it keeps a retained tie with |
| `coordination_ratio` | Share of the channel's forwarded origins that were co-forwarded with at least one retained partner, in [0, 1] — how much of its forwarding behaviour is synchronised |

Node colours, community assignments, and channel metadata are copied verbatim from the main citation graph, so the two maps are directly comparable: a cluster that is one colour on the citation map stays that colour on the coordination map.

---

## Parameters

| Flag | Default | Meaning |
| :--- | :------ | :------ |
| `--coordination-2d` | off | Build the layer and its 2D map (`coordination.html` + `data_coordination/`) |
| `--coordination-3d` | off | Also (or only) build the 3D map (`coordination3d.html`, with its own 3D layout) |
| `--coordination-window` | `300` s | Two forwards of the same origin count as coordinated when they land within this many seconds of each other |
| `--coordination-min-events` | `3` | Minimum distinct shared origins before a pair's tie is kept |

**Choosing the window.** Lower values are stricter: at 60 seconds you are essentially selecting automation-scale synchrony (bots, cross-posting tools, simultaneous operators); at 300 seconds (the default) you also catch human-paced pushes ("everyone forward this now"); above ~15 minutes you increasingly admit ordinary fast reaction to the same feeds. There is no universally correct value — the coordinated-behaviour literature typically derives thresholds from the data (e.g. the fast tail of the co-share delay distribution), so treat the default as a starting point and check the sensitivity of your ties to the window before reading them.

**Choosing the repetition threshold.** `--coordination-min-events` is the precision knob. Two channels subscribed to the same popular source *will* occasionally forward the same post within minutes by coincidence; the probability of doing so repeatedly across many distinct origins without arrangement falls fast. Raise it on dense, high-volume ecosystems; lower it to 2 for small or slow corpora — and say which you did when reporting.

---

## Interpretation guardrails

- **Synchrony is evidence, not proof.** A retained tie means *repeated, tightly-timed identical behaviour* — the standard trace of arranged amplification, and also the possible trace of two channels automated onto the same source or run by the same person. The map identifies the pairs worth investigating; intent is established by looking at the channels, not at the score.
- **Breaking news compresses timing organically.** During major events, many channels forward the same origin post quickly. The repetition threshold across *distinct* origins is the guard, but event-heavy windows still raise the coincidence floor — compare a quiet period before concluding.
- **Absence of a tie is weak evidence.** Coordination via copy-paste, screenshots, or link sharing bypasses the forward header entirely and is invisible to this layer (as it is to the citation graph). Forwards whose origin cannot be resolved are skipped. The layer's ties are a *floor* on coordinated behaviour, never a census.
- **The two maps answer different questions.** High citation-graph prestige with no coordination ties is the profile of an organically amplified source; modest prestige with strong coordination ties is the profile of an amplification arrangement. Read them side by side.

---

## Output files

| File | Content |
| :--- | :------ |
| `coordination.html` | 2D interactive map of the coordination network (with `--coordination-2d`; requires an HTTP server, like `graph.html`) |
| `coordination3d.html` | 3D interactive map (with `--coordination-3d`; requires an HTTP server) |
| `data_coordination/channel_position.json` | 2D layout + ties |
| `data_coordination/channel_position_3d.json` | 3D layout + ties (only with `--coordination-3d`) |
| `data_coordination/channels.json` | Node metadata, coordination measures, community assignments |
| `data_coordination/communities.json` | Community-strategy payload of the matching citation-graph scope (drives colour-by and the legend) |
| `data_coordination/timeline.json` | Year switcher entries (only with `--timeline-step year`; lists only years with surviving ties) |
| `data_coordination_<year>/` | Per-year coordination network, one directory per timeline year with ties (only with `--timeline-step year`) |

Channels with no retained tie do not appear on the coordination map — it shows the coordinated core, not the whole network. When no pair survives the thresholds, the maps are skipped with a console note (widen the window or lower the repetition threshold to loosen them).

### Timeline years

With `--timeline-step year`, the coordination layer is recomputed **per year** with the same thresholds, and the coordination maps gain the same in-page year switcher as the main maps. Each year's layout is seeded from the full-range coordination layout and orientation-aligned to it, so channels stay put as you step through the years and what moves is the *tie structure* — pairs appearing, thickening, and dissolving. Two guarantees keep the switcher honest: a year's ties are always a subset of the full range's (event counts only grow with a wider window, so nothing can appear in a year that the full-range map lacks), and only years whose network survived the thresholds are listed — a year with forwards but no surviving synchrony simply does not appear.

---

## References

- Giglietto, F., Righetti, N., Rossi, L. & Marino, G. (2020) "It takes a village to manipulate the media: coordinated link sharing behavior during 2018 and 2019 Italian elections." *Information, Communication & Society* 23(6):867–891. [doi:10.1080/1369118X.2020.1739732](https://doi.org/10.1080/1369118X.2020.1739732) — coordinated *link sharing*: the same content shared by the same accounts within an unusually short interval, repeatedly.
- Pacheco, D., Hui, P.-M., Torres-Lugo, C., Truong, B.T., Flammini, A. & Menczer, F. (2021) "Uncovering coordinated networks on social media: methods and case studies." *ICWSM 2021*. [doi:10.1609/icwsm.v15i1.18075](https://doi.org/10.1609/icwsm.v15i1.18075) — the general framework: build a coordination network from traces of unexpectedly similar behaviour.
- Nizzoli, L., Tardelli, S., Avvenuti, M., Cresci, S. & Tesconi, M. (2021) "Coordinated behavior on social media in 2019 UK general election." *ICWSM 2021*. [doi:10.1609/icwsm.v15i1.18074](https://doi.org/10.1609/icwsm.v15i1.18074) — coordination as a *spectrum* measured by tie weight, rather than a binary label.
- Magelinski, T., Ng, L.H.X. & Carley, K.M. (2022) "A synchronized action framework for detection of coordination on social media." *Journal of Online Trust and Safety* 1(2). [doi:10.54501/jots.v1i2.30](https://doi.org/10.54501/jots.v1i2.30) — synchronised identical actions in short windows as the coordination primitive.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

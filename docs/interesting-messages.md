# Interesting messages

The standard message browser sorts by *absolute* counts — most views, most reactions, newest first. That is useful but it always favours the same large channels: a routine post on a 200,000-subscriber channel will out-rank a viral post on a 1,000-subscriber one even when the small channel's post massively outperformed its own baseline. Pulpit's *interest scoring* asks a different, more analytically useful question: **for each channel, which posts punched above the channel's own weight — and which posts escaped their own community?**

The answer is split into two layers with deliberately different cadences. A fast **hot layer** scores every message inside its channel using z-scored engagement (views, forwards, reactions), refreshes at the end of each crawl, and powers the global "Top messages" feed and the per-channel panel. A slower **structural layer** runs as part of `structural_analysis` and adds two graph-aware metrics — *how many distinct communities did this message's forwards reach?* and *how prestigious were the channels that forwarded it?* — written to a sidecar JSON alongside the rest of the export.

Both layers are read-only from the analyst's perspective: the hot layer is always on (it costs nothing to keep current), the structural layer is opt-in via `--interest-structural` on `structural_analysis`.

---

## Quick reference

| Output / surface | What it surfaces |
| :--------------- | :--------------- |
| `Message.interest_score` (DB column, indexed) | Weighted composite of per-channel z-scored reactions, forwards, views. Indexed so the message browser can sort on it. |
| `Message.z_views` / `z_forwards` / `z_reactions` | The three facet z-scores feeding the composite, exposed separately so you can see *why* a post scored well. |
| `interest_desc` / `interest_asc` sort modes | New radio options in the Options dropdown on home (`/`), search (`/search/`), and channel detail (`/channel/<pk>/`). |
| `/messages/highlights/` | New global feed across all in-target channels, default-sorted by `interest_score`. Cold-start channels are excluded. |
| **Top messages** panel on the channel detail page | Per-channel sortable table: date, message preview, interest, facet z-scores; optional cross-community reach and authority-weighted reach when a structural export is loaded. |
| `data/interest_structural.json` (export sidecar) | Per-message *cross-community reach* (C) and *authority-weighted reach* (D), produced opt-in by `structural_analysis --interest-structural`. |

---

## The hot layer (z-scored engagement)

*Scored inside each channel, refreshed automatically, always on.*

The hot layer answers: **did this post outperform other posts on the same channel?**

### Why z-score inside the channel

Raw views, forwards, and reactions favour large channels by construction: a channel with 10× the subscribers will tend to have 10× the engagement on every post. Ranking globally by raw counts therefore reproduces the channel-size ranking, which is rarely the question the analyst is asking.

The cleanest fix in the social-media-analytics literature is to z-score each facet *inside its own channel*: subtract the channel's mean for that facet and divide by the channel's standard deviation. The resulting number is comparable across channels of any size — *"this post was 3.2 standard deviations above what this channel usually gets"*.

**Reference:** Salganik, M. J., Dodds, P. S. & Watts, D. J. (2006) "Experimental study of inequality and unpredictability in an artificial cultural market." *Science* 311(5762). [doi:10.1126/science.1121066](https://doi.org/10.1126/science.1121066)

**In practice:** on a real dev-DB channel of 105,825 alive messages, the z-scored facets land on a textbook distribution (mean ≈ 0, stddev ≈ 1 by construction). The top message scored z_views ≈ 121 — twelve dozen standard deviations above the channel's own baseline. That kind of post is what the analyst wants to find; raw-view sorting would have buried it under a hundred routine posts from the largest in-target channel.

### How the composite works

A single number is more useful than three. The composite blends the three facet z-scores with literature-default weights:

```
interest_score = 0.5 · z(reactions) + 0.3 · z(forwards) + 0.2 · z(views)
```

The weighting puts deliberate engagement (reactions, which require a tap) above rebroadcast intent (forwards, which require some judgement) above passive exposure (views, which are nearly automatic).

**References:**
- Suh, B., Hong, L., Pirolli, P. & Chi, E. H. (2010) "Want to be retweeted? Large scale analytics on factors impacting retweet in Twitter network." *SocialCom* 2010. [doi:10.1109/SocialCom.2010.33](https://doi.org/10.1109/SocialCom.2010.33)
- Cha, M., Haddadi, H., Benevenuto, F. & Gummadi, K. P. (2010) "Measuring user influence in Twitter: the million follower fallacy." *ICWSM* 2010. [aaai.org/ojs/index.php/ICWSM/article/view/14033](https://ojs.aaai.org/index.php/ICWSM/article/view/14033)

**Partial renormalisation for missing facets.** Not every Telegram message carries all three counters. Sticker posts often lack `views`. Old crawls sometimes recorded `forwards = NULL`. When a facet is missing for a *specific* message, that facet is dropped from the formula and the remaining weights are rescaled to sum to 1 — so a media-only post is not penalised against a text post just because Telegram never reported its view count. `interest_score` is `NULL` only when *all three* facets are NULL.

**Cold-start floor.** Channels with fewer than 30 alive messages receive `NULL` z-scores: the per-channel standard deviation is too noisy below that threshold to baseline anything meaningfully. These channels still appear in the standard message browser; they are simply absent from the "Top messages" rankings. The threshold is a defensible literature default — small enough to keep most active channels in scope, large enough that one anomalously popular post can't dominate a thin baseline.

### When the scores get refreshed

Two paths keep the hot layer current. **Crawl-time** — at the end of every per-channel crawl, `crawl_channels` automatically calls the channel-level recompute whenever messages were touched (`--get-new-messages`, `--refresh-messages-stats`, or `--fixholes` ran). The recompute is O(*N* messages) and trivially cheap — a 10,000-message channel takes well under a second.

**Manual / batch.** A new management command lets you recompute on demand:

```bash
python manage.py compute_message_scores                           # every channel
python manage.py compute_message_scores --channel-id 42           # one channel
python manage.py compute_message_scores --recency-days 90         # rolling baseline
python manage.py compute_message_scores --weights "reactions=0.6,forwards=0.3,views=0.1"
```

`--recency-days` switches the per-channel baseline from all-time to a rolling window — useful when a channel changed editorial focus and you want recent posts scored against recent peers rather than against a years-old archive. `--weights` overrides the composite blend for ad-hoc experimentation; partial overrides are accepted (missing facets fall back to their defaults) and weights are renormalised to sum to 1.

### Surfaces

Two new entry points expose the hot layer; the existing message browser also gains new sort options for free.

- **`/messages/highlights/`** — new global feed listing the highest-`interest_score` messages across every in-target channel. Default sort is `interest_desc`; the standard Options dropdown (date range, content type, lost-message filter, sort selector) all apply. Cold-start channels are excluded (their `interest_score` is `NULL`).
- **Top messages** panel on the channel detail page — appears below the standard charts on `/channel/<pk>/`. Returns the channel's top 30 by `interest_score`, presented as a sortable table with click-to-sort columns for Date, Message preview, Interest, z(react), z(fwd), z(views), plus two more columns when a structural export sidecar is loaded (see next section).
- **Sort dropdown** — home, search, and channel detail browsers all gain `Most interesting` / `Least interesting` radio options alongside the existing date / views / reactions sorts. `?sort=interest_desc` propagates through `MessageJumpView` and every paginated link.

---

## The structural layer (cross-community reach + authority-weighted reach)

*Graph-aware, opt-in, computed by `structural_analysis`.*

The hot layer answers *"did this post outperform its channel's baseline?"*. The structural layer answers a different and complementary question: *"did this post escape its origin community, and were the channels that re-amplified it themselves significant?"*. Both axes are needed — a post can score huge on engagement without spreading beyond its original audience (echo-chamber hit), and a post can spread across the whole ecosystem without dominating any single channel's engagement.

Enable with `--interest-structural` on `structural_analysis`. Both options below have sensible defaults; tune them when the question warrants it.

### Cross-community reach (C)

*"How many distinct communities did this post's forwards reach?"*

For each origin message, Pulpit walks the set of in-target channels that forwarded it (the `forwarded_from = origin.channel, fwd_from_channel_post = origin.telegram_id` join), looks up each forwarder's community label from the chosen partition (default `LEIDEN_DIRECTED`, matching the [community bridging measure](network-measures.md#community-bridging) default), and counts the distinct labels. A post that ricochets inside its origin community scores `C = 1`; a post picked up across the religious-conservative, economic-nationalist, *and* libertarian clusters scores `C = 3`.

**Reference (adapted):** Goel, S., Anderson, A., Hofman, J. & Watts, D. J. (2016) "The structural virality of online diffusion." *Management Science* 62(1). [doi:10.1287/mnsc.2015.2158](https://doi.org/10.1287/mnsc.2015.2158)

Goel et al.'s structural-virality measure is the Wiener index of the diffusion tree, distinguishing *broadcast* (one source, flat star) from *viral* (long branching cascade). Telegram exposes only depth-1 forwarding — every forward points back to the original, never to an intermediate retweeter — so the Wiener-index axis collapses by construction. What remains is *breadth across communities*, which is the cleanest faithful adaptation: a flat star *within* one community is broadcast; a flat star *across* communities is the closest thing to "this post broke out of its bubble" that the Telegram data model can express.

**In practice:** the C value is small (single digits) for most posts and large (tens) for the rare ones that crossed boundaries. The most interesting C profiles are usually not the absolute top values but the ones where a small channel's post reached a high C — a structural amplifier that the channel's own engagement metrics would not have flagged.

### Authority-weighted reach (D)

*"How prestigious were the channels that forwarded this post?"*

Same downstream-forwarder set as C, but instead of counting distinct communities Pulpit sums each forwarder's authority centrality. The default authority is PageRank (computed via the existing [PAGERANK measure](network-measures.md#pagerank)), with a fallback chain to HITS authority and then to in-degree centrality based on what `--measures` selected.

**Reference:** Cha, M., Haddadi, H., Benevenuto, F. & Gummadi, K. P. (2010) "Measuring user influence in Twitter: the million follower fallacy." *ICWSM* 2010. [aaai.org/ojs/index.php/ICWSM/article/view/14033](https://ojs.aaai.org/index.php/ICWSM/article/view/14033)

D is essentially Cha et al.'s *weighted indegree* applied at message-level instead of channel-level: a forward from a 30-PageRank channel counts an order of magnitude more than a forward from a 0.001-PageRank channel, so a post that got picked up by three hub channels can outrank a post forwarded by twenty marginal ones.

**In practice:** D is most informative when read *alongside* the in-target forwarder count. A high D with a low forwarder count means *one or two hub channels* picked the post up — a structurally significant signal even though the absolute reach is small. A high D with a high forwarder count means broad pickup *including* hubs — the strongest possible diffusion outcome.

### Edge cases and what gets dropped

The structural layer encodes a few deliberate exclusions, each documented inline in `network/interest_structural.py`:

- **Self-forwards** are excluded. A channel rebroadcasting its own post inflates both C and D without saying anything about reach.
- **Out-of-target forwarders** are dropped from the C / D calculation (community labels are only defined for in-target nodes per `graph_builder.build_graph`), but their count is emitted as a parallel `forwarder_count_out_of_target` field for transparency. The split lets you tell whether a post broke out of the in-target subset entirely or stayed within it.
- **Window filter.** Forwards more than `--interest-window-days` days after the origin post are dropped (default 30, matching `--diffusion-window`). The window excludes anniversary or archival re-shares from the structural-reach figure. Pass `--interest-window-days 0` to disable.
- **Mentions** (the `Message.references` M2M) are *not* counted toward C or D, even though Pulpit elsewhere treats forwards and mentions symmetrically as edges in the graph. Telegram's `references` is a *message → channel* relation: when a post contains a t.me link to channel B, that creates a Message.references entry for B, not for any specific post of B. The relation doesn't carry message-level identity, so a faithful translation to *who mentioned this specific post* would require separate design. The `--interest-include-mentions` flag is accepted for forward compatibility and emits a warning when set; it is currently a no-op.
- **Lost messages** (`is_lost=True`) are excluded on both sides of the join.

### When the results are interpretable

The structural layer is most informative on networks that satisfy two conditions:

1. **Some posts actually crossed community boundaries.** On a network where every channel mostly forwards from the same handful of sources, every C will be 1 and the metric carries no signal. A diagnostic: if the `by_message` payload's distribution of C values is concentrated at 1, the structural layer is not the right lens for this corpus — fall back to the hot layer.
2. **At least one centrality measure is informative.** D inherits the strengths and weaknesses of the authority key it uses. On a network where PageRank is concentrated in a few hubs, D will be dominated by whether those hubs forwarded the post; on a flatter network, D distinguishes more posts. See [Network measures § PageRank](network-measures.md#pagerank) for when PageRank is interpretable.

---

## Surfaces revisited: how C and D appear in the UI

When `data/interest_structural.json` exists in the latest published export, the per-channel **Top messages** panel automatically gains two extra columns — *Cross-comm.* (the integer C) and *Auth. reach* (the float D). A small caption above the table records the chosen community strategy, authority key, and window so the analyst sees exactly what the numbers mean. When no structural export is present (the typical case during day-to-day crawling), the panel renders just the hot layer; nothing breaks.

The sidecar is read on demand by `webapp/utils/exports.py::latest_export_payload`, which finds the most-recently-modified `exports/<name>/` whose `summary.json` exists, skipping `.tmp` and `.old` directories, and caches the JSON decode keyed on the file's modification time so a re-published export invalidates the cache automatically.

The global `/messages/highlights/` feed is *not* enriched with C and D inline — the post-card rendering is shared with home and search, where adding two columns would feel out of place. The intended pattern for cross-channel investigation of structural reach is: open `interest_structural.json` directly in a JSON viewer or through a notebook, or visit the per-channel "Top messages" panel for any candidate channel.

---

## What gets written

The hot layer lives entirely in the database. The structural layer is a sidecar JSON file alongside the rest of the structural-analysis output.

### Database (migration `0046_message_interest_score`)

Five new nullable columns on `Message`:

| Column | Type | Meaning |
| :----- | :--- | :------ |
| `z_views` | `FloatField(null=True)` | Per-channel z-score of `views`. NULL when the channel is cold-start or the value itself was NULL. |
| `z_forwards` | `FloatField(null=True)` | Same for `forwards`. |
| `z_reactions` | `FloatField(null=True)` | Same for `total_reactions`. |
| `interest_score` | `FloatField(null=True, db_index=True)` | Weighted composite. Indexed standalone and via the composite `(channel, interest_score)` for the per-channel sort. |
| `interest_scored_at` | `DateTimeField(null=True)` | When this row was last (re)scored. |

The migration's `RunPython` backfill computes scores via `apps.get_model`, so it stays self-contained and replayable. On a 1.7M-message dev DB the backfill takes a few minutes (dominated by `bulk_update`).

### Export sidecar (`data/interest_structural.json`)

When `--interest-structural` runs, the export receives a single self-contained JSON file:

```json
{
  "computed_at": "2026-05-22T12:34:56",
  "community_strategy": "leiden_directed",
  "authority_key": "pagerank",
  "window_days": 30,
  "include_mentions": false,
  "by_message": [
    {
      "channel_pk": 123,
      "telegram_id": 4567,
      "date": "2026-04-13T12:34:56+00:00",
      "grouped_id": null,
      "c_cross_community": 7,
      "d_authority_reach": 0.0421,
      "interest_score": 3.18,
      "forwarder_count_in_target": 18,
      "forwarder_count_out_of_target": 4
    }
  ],
  "by_channel_top": {
    "123": {
      "by_interest": [/* same record shape, up to 50 entries, sorted by interest_score */],
      "by_cross_community": [/* same record shape, up to 50 entries, sorted by C */]
    }
  }
}
```

`by_message` is the source of truth: every origin with at least one in-target forwarder appears there. `by_channel_top` is a convenience map — each channel gets twin sorted lists so the per-channel panel can switch between "interest-led" and "structurally-led" ranking without re-sorting client-side.

The file honours the same `_sanitize_nan_inf` + `allow_nan=False` discipline as `vacancy_analysis.json` and `robustness.json`, so `JSON.parse` in the browser will not choke. Written via the atomic-publish convention (`exports/<name>.tmp/` → `exports/<name>/`), so an aborted run never corrupts a previous one.

### Timeline export

When `--timeline-step year` is active alongside `--interest-structural`, the structural layer runs once on the global graph *and* once per calendar year — per-year payloads land in `data_YYYY/interest_structural.json`. The hot layer is global only: per-channel z-scores are computed against the channel's all-time (or `--recency-days`) baseline regardless of timeline slicing, so an unusually engaging post stays an unusually engaging post no matter which year-slice you read it from.

---

## When the results are interpretable (and when they aren't)

The hot layer is interpretable on every channel above the cold-start floor — that's the whole point of per-channel normalisation. The pitfalls are mostly editorial:

- **A channel that changed editorial focus.** Posts from before the change get baselined against posts from after — the z-scores can become misleading. Mitigation: use `--recency-days N` to restrict the baseline to a rolling window matching the channel's current era.
- **A channel where most posts get a fixed audience size** (e.g., scheduled news digests). The per-channel stddev becomes very small, and any anomaly gets a huge z-score. This is *correct*: an anomaly genuinely is anomalous against that tight baseline. Read the absolute counts alongside the z-scores to calibrate.
- **A channel where Telegram never reports `views`** (some private-pivoted channels). The composite falls back to forwards + reactions only via partial renormalisation, which is correct — but you lose one of the three signals. The `z_views` column is NULL in those cases and the table makes it visible.

The structural layer adds a third pitfall:

- **A network with few community boundaries.** If `LEIDEN_DIRECTED` produces a small number of large communities, most posts will reach all of them at once and C saturates near the partition count. Try a finer partition (`LEIDEN_CPM_FINE`) if the community-strategies list permits.

The system as a whole is *not* meant to detect what humans would call *interesting* in the semantic / editorial sense — that requires NLP and content models. It is a *structural* lens: which posts stand out from their channel's engagement baseline, and which posts spread structurally beyond their origin community. The two questions are surprisingly often the right ones, but they are not the only ones, and the doc would lie to claim otherwise.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

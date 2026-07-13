# Workflow

This guide walks you through the four steps of a Pulpit research project, from finding channels to opening the finished network map in a browser.

**The pipeline:**

```
1. Find channels  →  2. Organize  →  3. Collect messages  →  4. Generate the map
```

Everything is done through the browser interface at [http://localhost:8000](http://localhost:8000). You do not need to use the terminal for normal research work.

---

## Before you start

Make sure Pulpit is running:

```sh
python manage.py runserver
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Step 1 — Add keywords to find channels

Go to **Manage** in the navigation bar, then choose **Search terms**.

Click **Add search term** and type a keyword — for example, a political party name, a topic, or a country name. Add as many terms as you need to cover the scope of your research. You can add more at any time.

> **Tip:** use terms in the same language as the channels you are looking for. Telegram's search is language-sensitive.

Once your terms are saved, go back to the home page and click **Operations** in the navigation bar. This is the control panel where you launch all data collection steps.

---

## Step 2 — Search for channels

In the Operations panel, find the **Search Channels** card (Step 1) and click **Run**.

Pulpit searches Telegram for channels matching your keywords and saves the results. You will see a live log of what is happening. When it finishes, the status badge changes from *running* to *done*.

The first time Pulpit connects to Telegram, it will send a verification code to your Telegram app. Enter it in the terminal when prompted.

> **Nothing found?** Try broader or different keywords. Telegram's search only matches channel names and descriptions, not message content.

### Adding specific channels directly

If you already know which channels you want, you don't have to rely on keyword search. Open **Options** on the Search Channels card and fill the **Add channels** box — one channel per line, in any of these forms:

- a `t.me` link (`https://t.me/channelname`, message links and `t.me/c/…` links work too)
- an `@username`
- a bare username
- a numeric Telegram ID

Each line is resolved on Telegram and the channel is added to the database. Channels that cannot be resolved (deleted, private, mistyped, or — for numeric IDs — never seen by your Telegram account before) are reported as **warnings** in the log; the rest of the run continues. To *only* add channels, set **Max search terms** to `0` and leave the search-term boxes empty.

---

## Step 3 — Organize your channels

Your job here is to decide which channels matter for your research and label them. A channel enters the analysis only while it carries an **in-target** label.

### Labels and label groups

A **label** is a category you define — *Far right*, *Pro-government*, *State media*, *France*, or any grouping that fits your project. Labels live in **groups**; think of each group as one labelling *axis*:

- A **partition** group holds at most one label per channel at any moment — use it for mutually-exclusive axes like *Organization* or *Region*. A channel's periods within the group can't overlap.
- A **non-partition** group lets a channel carry several of its labels at once — use it for free-form tags like *Topic*.

Exactly one group is the **primary** group. It supplies the node colour on the map, the "Label" column in the exports, the actor identity in vacancy analysis, and the default community / role basis — the job the old single "Organization" used to do. On a fresh install the primary group is called *Organization*, but you can rename it or make a different axis primary.

Each label is marked **in target** or not. **Only channels that hold at least one in-target label are crawled and included in the map.** Everything else stays out of scope — though it can still show up as a *dead leaf* when an in-target channel forwards from it or mentions it.

### Create your labels

1. Go to **Manage → Labels**.
2. Click **Add group**, give it a name and colour, and tick **Partition** (and **Primary** for your main axis).
3. Add labels to the group; give each a colour and tick **In target** for the ones whose channels you want to analyse.

### Apply labels to channels

1. Go to **Manage → Channels** and open a channel (click its name or ID).
2. Add one or more labels. Each label membership can carry an optional **start** and **end** date, so a channel's grouping can change over the study period — e.g. a channel that switched hands mid-year. Leave both dates blank for an "always" membership.
3. Click **Save**.

Channels with no in-target label are left out of the analysis.

> **Tip — bulk assign.** In the Channels list, tick the checkboxes next to several channels, then use the **Bulk assign** bar at the bottom of the page to give them all the same label at once.

> **Why dated memberships?** Because label memberships are time-bounded, every forward is counted against whichever label the channel held *on the date of that message*. A channel that changed allegiance is split correctly across the timeline instead of being forced into a single present-day box.

**Inspect flag (optional, for discovery):** each channel has an **Inspect** checkbox that asks the crawler to fetch the channel's messages even when the channel has no in-target label. Inspected channels are *not* added to the analysis set — they remain out-of-target for measures, communities, and graph building — but their crawled messages are kept so you can discover new in-target candidates from the channels they forward and mention.

Set it from the **Inspect** column in the Channels list (inline checkbox) or from the channel edit page. Use this to try out a channel for a while before deciding whether to give it an in-target label.

**Channel sources (optional):** channel sources are a separate tagging axis — for example *activists*, *media*, *state-affiliated* — independent of your label groups. A channel can belong to any number of sources.

To create sources go to **Manage → Sources** and click **Add**. To assign a channel to a source, open its edit page and pick from the **Sources** field.

Sources act as a scope filter: when you select one or more sources in the Operations panel (Crawl Channels or Structural Analysis), only channels belonging to at least one of the selected sources are processed. Leaving all boxes unchecked means all in-target channels are included, as usual.

Use sources when you want to run separate analyses on a subset of your corpus without changing any labels — for example, crawl only state-affiliated channels, or generate a graph limited to media outlets.

---

## Step 4 — Collect messages

In the Operations panel, find the **Crawl Channels** card (Step 2) and click **Run**.

Pulpit downloads messages from every in-target channel, and traces every cross-channel link — when one channel forwards a message from another, or mentions another channel by name.

This step can take a while, especially on a first run. The log shows progress channel by channel. When it finishes, the status changes to *done*.

### What the options do (expand Options to see them)

The options panel is organized into three independent groups — each is its own pass over the channels in scope.

**1. Channels** — update channel metadata without touching messages.

| Option | When to use it |
| :----- | :------------- |
| **Get channels info** | On by default. Updates profile pictures, subscriber counts, about text, and other channel details. A linked chat seen for the first time — a channel's discussion group, or a group's broadcast channel — is added to the database and inherits the parent's current labels (same labels and periods), so it enters analysis scope right away; its timeline can then be edited like any other channel's. |
| **Mine about texts** | Scan channel descriptions for links to other Telegram channels and add any new ones to your database. |
| **Fetch recommended channels** | Ask Telegram for its own channel suggestions and add them to the database. New channels are saved but not automatically crawled. |
| **Retry lost & private** | Re-attempt channels previously marked as inaccessible. If a channel is now reachable its flag is cleared. |

**2. Messages** — download and update message content.

| Option | When to use it |
| :----- | :------------- |
| **Get new messages** | On by default. Downloads messages published since the last crawl. |
| **Fetch replies** | Fetch reply threads from linked discussion groups for posts that have replies. |
| **Refresh message stats** | Periodically re-fetch view counts, forward counts, and reactions for already-downloaded messages. Messages that Telegram no longer returns are flipped to `is_lost=True` and stop counting toward charts, edge weights, and citation measures (they still appear in the message list when the *Lost messages* filter is set to *Include* or *Only*). A previously-lost message that Telegram returns again is automatically un-marked. Use the *Limit*, *From date*, and *To date* fields to restrict which messages are refreshed. |
| **Fix message holes** | Scan message ID sequences for gaps and fill them in. Can run without *Get new messages*. |
| **Fix missing media** | Re-download photos, videos, audio (voice notes and audio files), stickers, and other media that were never saved or are missing from disk. Honors the toggles in the **Media types** sidebar — uncheck a type to skip it. |
| **Retry lost messages** | Re-fetch every message currently marked as lost. Messages that Telegram returns are unmarked and their stats refreshed; the rest stay lost. Useful after a transient outage or to clean up stale lost-flags accumulated by older refreshes that ran with a small date window. |
| **Retry unresolved references** | Re-attempt t.me/ links that could not be resolved in a previous run. |

**3. Refresh degrees** — recalculate citation counts (no Telegram connection needed).

| Option | When to use it |
| :----- | :------------- |
| **In target channels** | On by default. Recomputes in-degree and out-degree for all in-target channels. |
| **Out of target channels** | On by default. Recomputes citation degree for out-of-target channels referenced by in-target ones. |

**Limiting the scope:** you can restrict the crawl to a subset of channels in two ways:

- **DB id filter** — enter specific channel IDs (e.g. `5, 10-20, 50`). Find a channel's ID in the Manage → Channels list.
- **Channel sources** — tick one or more sources in the **Channel sources** fieldset. Only channels belonging to at least one selected source are crawled. Leave all unchecked to crawl all in-target channels.

**Media types:** the right-hand **Media types** fieldset controls which message attachments are downloaded. The five checkboxes apply to every operation that fetches messages from Telegram — *Get new messages*, *Fix message holes*, and *Fix missing media* — and are disabled when none of those is selected. Operations that touch media show a small sliders icon next to their label as a reminder.

- **Image download** — photo files attached to messages.
- **Video download** — video files, including GIFs/animations and round videos (which carry attribute flags on the saved row).
- **Audio download** — both voice notes and uploaded audio documents; the saved row records `is_voice` to distinguish them.
- **Sticker download** — static webp stickers, animated TGS, and video webm stickers.
- **Other media download** — everything else (PDFs, archives, arbitrary documents).

> **The first connection to Telegram:** if this is your first run, Telegram will send a verification code to your phone. Enter it in the terminal when prompted.

---

## Step 5 — Generate the map

In the Operations panel, find the **Structural Analysis** card (Step 3) and click **Run**.

This step builds the network graph, runs community-detection algorithms to identify clusters of channels, and produces the output files. By default it writes the data files needed to power the interactive map.

### What you get

Before clicking Run, expand **Options** and choose which outputs you want:

| Output | What it is |
| :----- | :--------- |
| **Structural 2D map** | An interactive map of the citation network (`graph.html`) you can open in a browser — search, zoom, filter by cluster, click channels for details. This is the main output most people want. |
| **Structural 3D map** | The same map in a rotatable 3D view (`graph3d.html`). |
| **HTML tables** | Sortable tables listing every channel with its network scores, and tables summarising each cluster. |
| **Excel spreadsheets** | The same tables as `.xlsx` files you can open in Excel or Google Sheets. |
| **GEXF / GraphML** | Files for network analysis software like Gephi or Cytoscape. |

> **Tip:** tick at least **Structural 2D map** and **HTML tables** for a first run. That gives you the interactive map and a spreadsheet-style overview.

### Choosing how channels are grouped

The map can group and colour channels two complementary ways. Pick from either or both — every selection becomes a colour-by option you can switch between in the map without re-exporting:

- **Label groups** — your own *partition* label groups from Manage › Labels (an axis where each channel holds at most one label at a time, e.g. an "Organization" or "Region" grouping). Drag the groups you want into the Selected area to carry them into the analysis. A good starting point to see whether your manual categories line up with the actual citation patterns. Only partition groups appear here.
- **Community strategies** — algorithmic community detection from the citation patterns themselves, independent of your labels. **Leiden** or **Leiden Directed** are good defaults and often reveal groupings you did not expect.

### Other useful analysis options

| Option | What it does |
| :----- | :----------- |
| **Measures** | Which influence scores to compute for each channel. See [Network measures](network-measures.md) for what each one means. |
| **Start date / End date** | Limit the analysis to a specific time period — for example, the six months before an election. |
| **Channel sources** | Restrict the graph to channels belonging to at least one selected source. Leave all unchecked to include all in-target channels. |
| **Export name** | Give this export a name (e.g. `march-2024`). If you leave it blank, the date and time are used. You can keep multiple exports and compare them. |
| **Draw dead leaves** | Include *dead leaves* — out-of-target channels that one of your monitored channels has forwarded from or mentioned via a `t.me/` link. Useful for seeing what outside content your corpus amplifies. |

When the export finishes, click **Data** in the navigation bar to browse your exports and open the map.

---

## What else you can do

### Timeline: see how the network changed over time

Enable **Timeline by year** in the Structural Analysis options. Pulpit repeats the full analysis once per calendar year found in your data and adds a year navigator to the graph — click the arrows to step through time and watch the network evolve.

### Compare two networks

Run a second export — perhaps with a later date range or a different set of channels. Then go to the **Compare Analysis** card (Step 4) in the Operations panel, set the target export, and click Run. Pulpit generates a side-by-side comparison showing which channels gained or lost influence between the two snapshots.

### Mark events on charts

Go to **Manage → Event types** to define categories like *Election* or *Policy change*, then **Manage → Events** to add specific dates and descriptions. Pulpit draws vertical lines at those dates on all channel activity charts, making it easy to see whether the event affected a channel's behaviour.

### Robustness: resistance to node removal

Enable in the Structural Analysis options (or with `--robustness` on the CLI). The attack strategies are picked via `--robustness-strategies` (or the checkbox grid in the Operations panel) — defaults to `random,in_strength,out_strength,pagerank,betweenness`; `subscribers` (audience-targeted moderation, from Telegram member counts), the near-optimal **dismantling** strategies `collective_influence` / `fragmentation_dyn` (worst-case fragmentation bounds), and the dynamic (re-rank-after-removal) variants are also available. For each selected strategy Pulpit:

- optionally extracts the Serrano-Boguñá-Vespignani disparity-filter backbone (`--robustness-alpha`, default 0.05),
- records the residual-size curves `S(q)` for WCC, SCC, directed reachability, and surviving strength (the weight share of the heaviest residual component),
- compresses each curve into the Schneider et al. R-index plus a 5%-collapse threshold `f_c`,
- samples the weighted global efficiency along the removal order on a coarse grid,
- compares the residual-size curves against a null model (`--robustness-null` simulations, default 20; `--robustness-null-model configuration` or `reciprocal`) and reports per-(strategy, metric) z-scores plus add-one empirical p-values, BH-corrected across the whole strategy×metric grid into a `q` column (smallest reportable p is `2/(K+1)`, so raise K to 79+ for α = 0.05 claims),
- optionally sweeps the R-index across a grid of backbone thresholds (`--robustness-alpha-grid 0,0.01,0.05,0.1`) to show whether the rankings are stable or a backbone artefact,
- with `--timeline-step year`, optionally runs the **ban-replay validation** (`--robustness-replay`): for each year with recorded channel closures, removes them from the prior-year graph and compares the predicted residual against the observed next-year structure,
- if at least one community partition is active, also produces intra/inter community edge-survival curves per partition, plus the **ban-wave scenarios**: residual sizes after removing each whole community in one step, next to the equal-count random baseline.

Results are written to `data/robustness.json` (always) and rendered as `robustness_table.html` (when `--html`) / `robustness_table.xlsx` (when `--xlsx`). See [Robustness analysis](robustness-analysis.md) for what each metric measures, when it is interpretable, and the limits of the null model.

### Coordination: temporal co-forwarding maps

Enable with the two **Coordination map** toggles on the second row of the Outputs fieldset (or `--coordination-2d` / `--coordination-3d` on the CLI — the coordination counterparts of `--graph-2d` / `--graph-3d`). Pulpit ties together channels that repeatedly forward the **same origin message** within `--coordination-window` seconds of each other (default 300), keeping only pairs with at least `--coordination-min-events` distinct shared origins (default 3) — repetition across different content is what separates coordination from coincidence on viral posts. The result is a second network layer with its own force-directed layouts, rendered per selected toggle as a dedicated interactive map: `coordination.html` (2D) and `coordination3d.html` (3D), backed by `data_coordination/`. Node colours and community assignments are carried over from the main citation graph so the two maps read side by side; node size defaults to the number of coordinated co-forwards. Combined with `--timeline-step year`, the layer is recomputed per year (`data_coordination_YYYY/`, layouts seeded from the full-range coordination layout) and the coordination maps gain the same in-page year switcher as the main maps, listing only the years with surviving ties. See [Coordination analysis](coordination-analysis.md) for the method, the parameter guidance, and the interpretation guardrails.

### Interesting messages

Per-channel z-scored engagement is always on once the relevant migration has been applied — Pulpit refreshes the scores automatically at the end of each crawl, and you can recompute on demand with `python manage.py compute_message_scores` (accepts `--channel-id`, `--min-sample`, `--recency-days`, `--weights`). The structural reach metrics (cross-community reach + authority-weighted reach) are opt-in via `--interest-structural` on `structural_analysis`, with companion flags `--interest-window-days N` (default 30, matches `--diffusion-window`; 0 disables) and `--interest-include-mentions` (accepted for forward compatibility, currently a no-op). The structural layer writes `data/interest_structural.json` and is consumed on demand by the per-channel **Top messages** panel. See [Interesting messages](interesting-messages.md) for the scoring formula, the academic references, and when the metrics are interpretable.

---

## Viewing your results

Go to **Operations → Exports** (`/operations/exports/`) to see all your exports. Click an export name to open its index page, which links to the interactive map, tables, and any other files you generated.

You can also share an export by copying the whole `exports/<name>/` folder to a web server or to a colleague's machine. The files are self-contained and work without an internet connection.

---

## Advanced: running from the command line

If you prefer to work in a terminal — for example to automate or schedule runs — every operation has a CLI equivalent.

> **Bare invocations do nothing.** `python manage.py crawl_channels` and `python manage.py structural_analysis` with no flags exit immediately without doing any work. Saved Operations-panel defaults pre-populate the *form*; they do **not** apply to the CLI. Always pass explicit flags. The easiest way to discover the right flag combination is the **Write CLI command** button next to Save / Load defaults in the panel — it generates the exact `python manage.py …` line for the current form. See [Operations defaults & configuration](operations-defaults.md).

> **Windows users:** use **PowerShell** for these examples — it supports `#` comments just like bash. In Command Prompt, replace `#` comment lines with `rem`. All `python manage.py ...` commands work identically on both platforms.

```sh
# Start the server
python manage.py runserver

# Search for channels
python manage.py search_channels
python manage.py search_channels --amount 15
python manage.py search_channels --extra-term "keyword"

# Add specific channels by identifier (repeatable; unresolvable ones are logged as warnings)
python manage.py search_channels --amount 0 --add-channel "https://t.me/channelname" --add-channel "@channelname" --add-channel 1234567890

# Collect messages — the three independent groups
python manage.py crawl_channels --get-channels-info --channel-types CHANNEL          # 1. update channel metadata only
python manage.py crawl_channels --get-new-messages --channel-types CHANNEL           # 2. fetch new messages only
python manage.py crawl_channels --in-degrees --out-degrees                            # 3. refresh degrees only (no Telegram connection)

# Combine as needed (--channel-types omitted below for brevity — it falls back to the
# DEFAULT_CHANNEL_TYPES setting, i.e. [scope].channel_types in configuration/.operations-crawl)
python manage.py crawl_channels --get-channels-info --get-new-messages
python manage.py crawl_channels --get-new-messages --fix-holes
python manage.py crawl_channels --get-new-messages --retry-references
python manage.py crawl_channels --get-new-messages --fetch-replies
python manage.py crawl_channels --mine-about-texts
python manage.py crawl_channels --fetch-recommended
python manage.py crawl_channels --refresh-messages-stats
python manage.py crawl_channels --refresh-messages-stats --refresh-from 2024-01-01 --refresh-to 2024-06-30
python manage.py crawl_channels --refresh-messages-stats --refresh-limit 200
python manage.py crawl_channels --ids "5, 10-20, 50"
python manage.py crawl_channels --get-new-messages --channel-sources media,activists

# Media downloads (tri-state: --download-X enables, --no-download-X disables for the run only)
python manage.py crawl_channels --get-new-messages --no-download-video --no-download-audio --no-download-stickers --no-download-other-media  # text-only
python manage.py crawl_channels --get-new-messages --download-audio --download-stickers           # add audio + stickers to a default crawl
python manage.py crawl_channels --fix-missing-media --download-images --no-download-video         # repair photos only

# Generate the map
python manage.py structural_analysis --graph-2d --html
python manage.py structural_analysis --graph-2d --html --xlsx
python manage.py structural_analysis --graph-2d --graph-3d --html --xlsx
python manage.py structural_analysis --gexf --graphml
python manage.py structural_analysis --csv
python manage.py structural_analysis --measures PAGERANK,AMPLIFICATION
python manage.py structural_analysis --measures ALL
# Parameterised measures take keyword args in parens and may repeat with different params
# (each combination produces its own parameter-suffixed output column):
python manage.py structural_analysis --measures "DIFFUSIONLAG(window=7),DIFFUSIONLAG(window=30)"   # same measure twice
python manage.py structural_analysis --measures "MODULEROLE(basis=LEIDEN_DIRECTED)" --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --measures DIFFUSIONLAG --diffusion-window 7   # bare token inherits the global default; 0 disables
python manage.py structural_analysis --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --community-strategies "SBM(mode=NESTED),SBM(mode=FLAT)"   # role-based blocks; needs graph-tool (conda/apt, not pip)
python manage.py structural_analysis --community-strategies "SBM(weights=POISSON)" --edge-weight-strategy TOTAL   # weighted SBM: blocks reflect citation intensity (POISSON=counts, EXPONENTIAL=PARTIAL_* ratios)
python manage.py structural_analysis --community-strategies "SBM(refine=MCMC)"   # posterior sampling: max-marginal blocks + per-channel SBM-confidence column (slower)
python manage.py structural_analysis --community-strategies "LEIDEN,LOUVAIN"   # classic Louvain baseline alongside Leiden, for comparison with older studies
python manage.py structural_analysis --community-strategies "LEIDEN,LEIDEN_DIRECTED,LOUVAIN,CONSENSUS(threshold=0.5)"   # consensus partition of the other strategies (needs ≥2 of them; KCORE doesn't count)
python manage.py structural_analysis --community-strategies SBM_ASSORTATIVE   # statistically supported cohesive communities (planted partition; needs graph-tool)
python manage.py structural_analysis --community-strategies "LEIDEN,LEIDEN_TEMPORAL(resolution=0.05,interslice=1.0)" --timeline-step year --graph-2d   # temporal communities with stable ids across years (not in ALL)
python manage.py structural_analysis --community-strategies ALL
python manage.py structural_analysis --community-strategies LEIDEN --community-backbone-alpha 0.05   # detect on the disparity-filter backbone; everything else stays on the full graph
python manage.py structural_analysis --startdate 2023-01-01 --enddate 2023-12-31
python manage.py structural_analysis --name my-export
python manage.py structural_analysis --graph-2d --timeline-step year
python manage.py structural_analysis --graph-2d --html --channel-sources media,activists

# Robustness analysis (resistance to node removal)
python manage.py structural_analysis --robustness --html --xlsx               # default: α=0.05, N_runs=100, K_null=20, static strategies only
python manage.py structural_analysis --robustness --robustness-alpha 0        # skip disparity filter, attack the full graph
python manage.py structural_analysis --robustness --robustness-null 0         # observed R only, no null model (no z-scores)
python manage.py structural_analysis --robustness --robustness-strategies ALL          # every available strategy (including dynamic)
python manage.py structural_analysis --robustness --robustness-strategies random,pagerank,collective_influence   # custom subset with a dismantling bound
python manage.py structural_analysis --robustness --robustness-runs 200 --robustness-null 50 --robustness-seed 7
python manage.py structural_analysis --robustness --robustness-null-model reciprocal   # preserve reciprocity in the null
python manage.py structural_analysis --robustness --robustness-alpha-grid 0,0.01,0.05,0.1   # backbone-sensitivity sweep
python manage.py structural_analysis --robustness --robustness-replay --timeline-step year  # validate against recorded closures

# Coordination analysis (temporal co-forwarding maps: coordination.html / coordination3d.html)
python manage.py structural_analysis --coordination-2d --coordination-3d                # both maps; defaults: 300 s window, ≥3 shared origins per pair
python manage.py structural_analysis --coordination-2d --coordination-window 60         # 2D map only, strict: automation-scale synchrony
python manage.py structural_analysis --coordination-2d --coordination-min-events 2      # looser repetition threshold for small corpora

# Interesting messages — structural reach layer (hot per-channel z-scores are always on)
python manage.py compute_message_scores                                                 # recompute hot scores for every channel
python manage.py compute_message_scores --channel-id 42 --recency-days 90               # one channel, rolling baseline
python manage.py structural_analysis --interest-structural --measures PAGERANK --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --interest-structural --interest-window-days 0     # disable the 30-day forwarder window

# Compare two exports (--target names the export the comparison is written into)
python manage.py compare_analysis /path/to/exports/<other-name> --target my-export
# Windows: use backslashes or quote the path
# python manage.py compare_analysis exports\<other-name> --target my-export
```

See `python manage.py <command> --help` for the full list of flags for any command.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Coordination](coordination-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

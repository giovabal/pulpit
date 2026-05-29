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

---

## Step 3 — Organize your channels

Go to **Manage → Channels**. You will see a list of all channels Pulpit found. Your job here is to decide which ones matter for your research and assign each a label.

### What is an organization?

An "organization" in Pulpit is a category label you define — for example *Far right*, *Mainstream conservative*, *Pro-government*, *Independent media*, or any grouping that makes sense for your project. Every channel you want to analyse must belong to an organization.

### How to assign channels

1. In the Channels list, find a channel you want to include.
2. Click on the channel's name or ID to open its edit page.
3. Choose an organization from the **Organization** dropdown.
4. Click **Save**.

Repeat for all the channels you want in your analysis. Channels without an organization are not collected or included in the map.

**To create organizations:** go to **Manage → Organizations**, click **Add**, give the organization a name and a colour, and make sure **In target** is ticked. Only organizations marked as in target are included in data collection.

> **Tip:** you can also assign organizations in bulk. In the Channels list, tick the checkboxes next to several channels, then use the **Bulk assign** bar at the bottom of the page to set the organization for all of them at once.

**Inspect flag (optional, for discovery):** each channel has an **Inspect** checkbox that asks the crawler to fetch the channel's messages even when its organization is not in target. Inspected channels are *not* added to the analysis set — they remain out-of-target for measures, communities, and graph building — but their crawled messages are kept so you can discover new in-target candidates from the channels they forward and mention.

Set it from the **Inspect** column in the Channels list (inline checkbox) or from the channel edit page. Use this to try out a channel for a while before deciding whether to attach it to an in-target organization.

**Channel groups (optional):** channel groups let you tag channels with one or more labels — for example *activists*, *media*, *state-affiliated* — independent of their organization. A channel can belong to any number of groups.

To create groups go to **Manage → Channel groups** and click **Add**. To assign a channel to a group, open its edit page and pick from the **Groups** field.

Groups act as a scope filter: when you select one or more groups in the Operations panel (Crawl Channels or Structural Analysis), only channels belonging to at least one of the selected groups are processed. Leaving all boxes unchecked means all in-target channels are included, as usual.

Use groups when you want to run separate analyses on a subset of your corpus without changing organizations — for example, crawl only state-affiliated channels, or generate a graph limited to media outlets.

---

## Step 4 — Collect messages

In the Operations panel, find the **Crawl Channels** card (Step 2) and click **Run**.

Pulpit downloads messages from all the channels you organized, and traces every cross-channel link — when one channel forwards a message from another, or mentions another channel by name.

This step can take a while, especially on a first run. The log shows progress channel by channel. When it finishes, the status changes to *done*.

### What the options do (expand Options to see them)

The options panel is organized into three independent groups — each is its own pass over the channels in scope.

**1. Channels** — update channel metadata without touching messages.

| Option | When to use it |
| :----- | :------------- |
| **Get channels info** | On by default. Updates profile pictures, subscriber counts, about text, and other channel details. |
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
- **Channel groups** — tick one or more groups in the **Channel groups** fieldset. Only channels belonging to at least one selected group are crawled. Leave all unchecked to crawl all in-target channels.

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
| **2D graph** | An interactive map (`graph.html`) you can open in a browser — search, zoom, filter by cluster, click channels for details. This is the main output most people want. |
| **3D graph** | The same map in a rotatable 3D view (`graph3d.html`). |
| **HTML tables** | Sortable tables listing every channel with its network scores, and tables summarising each cluster. |
| **Excel spreadsheets** | The same tables as `.xlsx` files you can open in Excel or Google Sheets. |
| **GEXF / GraphML** | Files for network analysis software like Gephi or Cytoscape. |

> **Tip:** tick at least **2D graph** and **HTML tables** for a first run. That gives you the interactive map and a spreadsheet-style overview.

### Choosing how clusters are detected

Under **Community strategies**, select the algorithm Pulpit uses to group channels into clusters:

- **Organization** (default) — clusters follow the organizations you defined in Step 3. A good starting point to see whether your categories map onto the actual citation patterns.
- **Leiden** or **Leiden Directed** — mathematical community detection based on citation patterns, independent of your labels. Often reveals groupings you did not expect.

You can select multiple strategies at once; the map lets you switch between them without re-exporting.

### Other useful analysis options

| Option | What it does |
| :----- | :----------- |
| **Measures** | Which influence scores to compute for each channel (PageRank, betweenness, etc.). Start with the default (PageRank). See [Network measures](network-measures.md) for what each one means. |
| **Start date / End date** | Limit the analysis to a specific time period — for example, the six months before an election. |
| **Channel groups** | Restrict the graph to channels belonging to at least one selected group. Leave all unchecked to include all in-target channels. |
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

Enable in the Structural Analysis options (or with `--robustness` on the CLI). The attack strategies are picked via `--robustness-strategies` (or the checkbox grid in the Operations panel) — defaults to `random,in_strength,out_strength,pagerank,betweenness`; another seven strategies are available including harmonic, bridging, spreading efficiency, and dynamic (re-rank-after-removal) variants. For each selected strategy Pulpit:

- optionally extracts the Serrano-Boguñá-Vespignani disparity-filter backbone (`--robustness-alpha`, default 0.05),
- records the residual-size curves `S(q)` for WCC, SCC, and directed reachability,
- compresses each curve into the Schneider et al. R-index plus a 5%-collapse threshold `f_c`,
- compares both against a weight-rewiring null model (`--robustness-null` simulations, default 20) and reports per-(strategy, metric) z-scores,
- if at least one community partition is active, also produces intra/inter community edge-survival curves per partition.

Results are written to `data/robustness.json` (always) and rendered as `robustness_table.html` (when `--html`) / `robustness_table.xlsx` (when `--xlsx`). See [Robustness analysis](robustness-analysis.md) for what each metric measures, when it is interpretable, and the limits of the null model.

### Interesting messages

Per-channel z-scored engagement is always on once the relevant migration has been applied — Pulpit refreshes the scores automatically at the end of each crawl, and you can recompute on demand with `python manage.py compute_message_scores` (accepts `--channel-id`, `--min-sample`, `--recency-days`, `--weights`). The structural reach metrics (cross-community reach + authority-weighted reach) are opt-in via `--interest-structural` on `structural_analysis`, with companion flags `--interest-window-days N` (default 30, matches `--diffusion-window`; 0 disables) and `--interest-include-mentions` (accepted for forward compatibility, currently a no-op). The structural layer writes `data/interest_structural.json` and is consumed on demand by the per-channel **Top messages** panel. See [Interesting messages](interesting-messages.md) for the scoring formula, the academic references, and when the metrics are interpretable.

---

## Viewing your results

Go to **Data** (`/data/`) to see all your exports. Click an export name to open its index page, which links to the interactive map, tables, and any other files you generated.

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

# Collect messages — the three independent groups
python manage.py crawl_channels --get-channels-info --channel-types CHANNEL          # 1. update channel metadata only
python manage.py crawl_channels --get-new-messages --channel-types CHANNEL           # 2. fetch new messages only
python manage.py crawl_channels --in-degrees --out-degrees                            # 3. refresh degrees only (no Telegram connection)

# Combine as needed (--channel-types omitted below for brevity — pass it on every crawl that
# touches Telegram, or the in-target queryset filters down to nothing)
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
python manage.py crawl_channels --get-new-messages --channel-groups media,activists

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
python manage.py structural_analysis --measures PAGERANK,BETWEENNESS
python manage.py structural_analysis --measures ALL
python manage.py structural_analysis --measures DIFFUSIONLAG --diffusion-window 7   # reaction window in days; 0 disables
python manage.py structural_analysis --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --community-strategies ALL
python manage.py structural_analysis --startdate 2023-01-01 --enddate 2023-12-31
python manage.py structural_analysis --name my-export
python manage.py structural_analysis --graph-2d --timeline-step year
python manage.py structural_analysis --graph-2d --html --channel-groups media,activists

# Robustness analysis (resistance to node removal)
python manage.py structural_analysis --robustness --html --xlsx               # default: α=0.05, N_runs=100, K_null=20, static strategies only
python manage.py structural_analysis --robustness --robustness-alpha 0        # skip disparity filter, attack the full graph
python manage.py structural_analysis --robustness --robustness-null 0         # observed R only, no null model (no z-scores)
python manage.py structural_analysis --robustness --robustness-strategies ALL          # every available strategy (including dynamic)
python manage.py structural_analysis --robustness --robustness-strategies pagerank,bridging,harmonic,spreading   # custom subset
python manage.py structural_analysis --robustness --robustness-strategies pagerank,bridging\(louvain\)  # explicit bridging basis (escape parens in bash)
python manage.py structural_analysis --robustness --robustness-runs 200 --robustness-null 50 --robustness-seed 7

# Interesting messages — structural reach layer (hot per-channel z-scores are always on)
python manage.py compute_message_scores                                                 # recompute hot scores for every channel
python manage.py compute_message_scores --channel-id 42 --recency-days 90               # one channel, rolling baseline
python manage.py structural_analysis --interest-structural --measures PAGERANK --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --interest-structural --interest-window-days 0     # disable the 30-day forwarder window

# Compare two exports
python manage.py compare_analysis /path/to/exports/<other-name>
# Windows: use backslashes or quote the path
# python manage.py compare_analysis exports\<other-name>
```

See `python manage.py <command> --help` for the full list of flags for any command.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

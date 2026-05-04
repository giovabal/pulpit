# Workflow

A complete guide to collecting, processing, and exporting a Pulpit network. The primary interface is the **Operations panel** in the browser (`/operations/`). Every operation is also available as a CLI management command for scripted or automated runs.

> On some systems replace `python` with `python3` or `py`.

---

## Overview

The pipeline has four stages:

```
1. Find channels     →  search_channels
2. Organise          →  admin interface: assign to organisations
3. Crawl messages    →  crawl_channels
4. Export network    →  structural_analysis
```

A researcher mapping German-language far-right channels might add 12 search terms in German, discover 340 channels, group them into five organisations by political leaning, crawl messages from January to September, and then export with Leiden Directed communities and PageRank node sizes. The result: an interactive map showing that three channels are the structural bridges between the conspiracy cluster and the mainstream conservative cluster — invisible in any media registry, but clearly visible in the graph.

---

## 1. Start the server

```sh
python manage.py migrate   # first run only
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000).

---

## 2. Add search terms

Go to **Manage** (`/manage/search-terms/`) and add keywords. These are used to discover channels by name via the Telegram search API.

There is no minimum or maximum number of search terms. Add as many as you need to cover the thematic or geographic scope of your project. You can add more at any time and re-run the search step.

---

## 3. Discover channels

**Operations panel** (`/operations/`) → **Search Channels** → click **Run**.

Processes pending search terms (in order of oldest check first) and saves matching channels to the database. New channels are not automatically marked as interesting; you review them in the next step.

**Options** (expand the panel):
- **Max search terms** — limit how many search terms are processed in this run (useful for large term lists)

**CLI alternative:**

```sh
python manage.py search_channels              # process all pending search terms
python manage.py search_channels --amount 15  # process at most 15 terms
python manage.py search_channels --extra-term "keyword"  # add a one-off term without saving it
```

---

## 4. Organise channels

In **Manage** (`/manage/channels/`), review the discovered channels and assign those you want to analyse to **Organisations**. An organisation is a thematic grouping of your choosing — by political orientation, country, funding source, language, or any other criterion.

- Go to `/manage/organizations/` and mark each organisation as `is_interesting = True`
- Channels whose organisation is not interesting are excluded from crawling and graph export

**Why organisation matters:** every network measure, community detection algorithm, and the vacancy analysis scoring system use organisation membership as a key variable. The quality of your categorisation shapes what the analysis can reveal.

You can also assign channels to **Groups** (`/manage/channel-groups/`) for finer-grained filtering — for example, to run analyses on a subset of your corpus without changing organisation assignments.

---

## 5. Crawl channels

**Operations panel** (`/operations/`) → **Get Channels** → click **Run**.

Downloads messages for all channels whose organisation is marked `is_interesting = True`, and resolves cross-channel references. Re-run at any time to fetch new messages.

<figure>
<img src="../webapp_engine/static/screenshot_13.jpg" alt="Operations panel">
<figcaption><em>Operations panel: four numbered pipeline steps as task cards with real-time log output.</em></figcaption>
</figure>

All steps are opt-in — expand **Options** to configure:

| Option | Description |
| :----- | :---------- |
| **Get new messages** | Fetch new messages from Telegram for each interesting channel; uncheck to run only post-processing steps |
| **Fix message holes** | Fill gaps in message history (messages missed or deleted on a previous run) |
| **Retry unresolved references** | Re-attempt `t.me/` usernames in message text that could not be resolved in earlier runs |
| **Force-retry dead references** | Also re-attempt references already marked permanently unresolvable; only applies when Retry is enabled |
| **Refresh message stats** | Update view counts, forward counts, and pinned status; combine with **Refresh limit** to restrict to the N most recent messages per channel, or to messages from a given date |
| **Mine about texts** | Scan the `about` field of all channels for `t.me/` links and fetch any referenced channels not yet in the database |
| **Refresh degrees** | Recompute and store in-degree and out-degree for all channels |
| **Fetch recommended channels** | Call Telegram's "recommended channels" API and add new suggestions to the database; new channels are not crawled automatically |
| **Fix missing media** | Re-download photo and video files absent from disk |
| **Channel types** | Which Telegram entity types to crawl: `CHANNEL` (default), `GROUP`, `USER` (comma-separated) |
| **DB id filter** | Restrict the crawl to specific channel database IDs and ranges, e.g. `5, 10-20, 50-`, `-30` |

**CLI alternative:**

```sh
python manage.py crawl_channels --get-new-messages
python manage.py crawl_channels --get-new-messages --fixholes
python manage.py crawl_channels --get-new-messages --retry-references
python manage.py crawl_channels --get-new-messages --retry-references --force-retry-unresolved-references
python manage.py crawl_channels --get-new-messages --refresh-messages-stats        # all messages
python manage.py crawl_channels --get-new-messages --refresh-messages-stats 200    # N most recent per channel
python manage.py crawl_channels --get-new-messages --refresh-messages-stats 2024-01-01
python manage.py crawl_channels --mine-about-texts
python manage.py crawl_channels --refresh-degrees
python manage.py crawl_channels --fetch-recommended-channels
python manage.py crawl_channels --ids "-30, 50-80, 99"
python manage.py crawl_channels --channel-types CHANNEL,GROUP
```

---

## 6. Export the network

**Operations panel** (`/operations/`) → **Export Network** → click **Run**.

Builds the directed citation graph, applies community detection algorithms and the ForceAtlas2 layout, computes all requested measures, and writes the result to `exports/<name>/`. By default only the data files (`data/*.json`) are written. Enable additional outputs via the options below.

**Interruption safety.** Exports are written atomically: all output goes to a `<name>.tmp` staging directory; only once every file including `summary.json` has been written is the directory renamed to `<name>`. Aborting an in-progress export leaves any previous export with the same name untouched.

### Output options

| Option | Description |
| :----- | :---------- |
| **2D graph** | Generate `graph.html` and run the ForceAtlas2 layout computation |
| **HTML tables** | Generate `channel_table.html`, `network_table.html`, `community_table.html` |
| **3D graph** | Also produce `graph3d.html` (requires **2D graph**) |
| **Excel spreadsheets** | Also produce `channel_table.xlsx`, `network_table.xlsx`, `community_table.xlsx` |
| **GEXF file** | Write `network.gexf` for import into Gephi or Cytoscape |
| **GraphML file** | Write `network.graphml` |
| **SEO-optimised** | Set `index, follow` robots tags; without this flag the output actively discourages indexing |
| **Vertical layout** | Orient the graph vertically (default is horizontal) |
| **Draw dead leaves** | Include non-interesting channels referenced by interesting ones as leaf nodes |

### Analysis options

| Option | Description |
| :----- | :---------- |
| **Measures** | Comma-separated list of [network measures](network-measures.md) to compute; default `PAGERANK`; use `ALL` for everything |
| **Community strategies** | Comma-separated list of [community detection algorithms](community-detection.md); default `ORGANIZATION`; use `ALL` for everything |
| **Network stat groups** | Which [whole-network metric groups](whole-network-statistics.md) to compute: `SIZE`, `PATHS`, `COHESION`, `COMPONENTS`, `DEGCORRELATION`, `CENTRALIZATION`, `CONTENT`, `ALL`; deselect `PATHS` and `COHESION` to skip expensive calculations on large networks |
| **Start date / End date** | Restrict the graph to a date range; channels with no messages in the period are excluded |
| **FA2 iterations** | ForceAtlas2 layout iterations; default 5000; higher values improve node separation but take longer |
| **Recency weights** | Integer N; messages up to N days old carry full weight; older messages decay as `exp(−(age−N)/N)` |
| **Spreading runs** | Monte Carlo SIR simulations per node for the `SPREADING` measure; default 200 |
| **Edge weight strategy** | How edge weights are computed: `PARTIAL_REFERENCES` (default), `PARTIAL_MESSAGES`, `TOTAL`, `NONE` |
| **Channel types** | Telegram entity types to include: `CHANNEL` (default), `GROUP`, `USER` |
| **Export name** | Custom name for the output directory; default is a timestamp |

### Vacancy analysis options

When at least one vacancy is registered in the database, `structural_analysis` can score replacement candidates for all vacancies at once and embed the results in the export as `vacancy_analysis.html` and `data/vacancy_analysis.json`.

| Option | Description |
| :----- | :---------- |
| **Vacancy measures** | One or more scoring algorithms to run; see the [Vacancy Analysis](vacancy-analysis.md#batch-export-via-structural-analysis) documentation for the full list; pre-checked automatically when any vacancy exists |
| **Months before** | Look-back window before each vacancy's closure date; default 12 |
| **Months after** | Forward window after each vacancy's closure date; default 24 |
| **Max candidates** | Maximum candidates scored per vacancy; default 30 |
| **PPR α** | Damping factor for the Personalized PageRank measure; default 0.85 |

The **Spreading runs** parameter in *Linked parameters* also controls the number of Monte Carlo SIR simulations used by the Cascade Overlap measure.

In the Operations panel the Vacancy Analysis legend (like Measures, Community strategies, and Network stat groups) has **All** / **None** buttons to toggle all checkboxes in one click.

**CLI alternative:**

```sh
python manage.py structural_analysis
python manage.py structural_analysis --2dgraph --html
python manage.py structural_analysis --2dgraph --3dgraph
python manage.py structural_analysis --2dgraph --html --xlsx
python manage.py structural_analysis --gexf --graphml
python manage.py structural_analysis --seo
python manage.py structural_analysis --2dgraph --vertical-layout
python manage.py structural_analysis --2dgraph --fa2-iterations 10000
python manage.py structural_analysis --draw-dead-leaves
python manage.py structural_analysis --measures PAGERANK,BETWEENNESS,BRIDGING
python manage.py structural_analysis --measures ALL
python manage.py structural_analysis --community-strategies LEIDEN,LOUVAIN
python manage.py structural_analysis --community-strategies ALL
python manage.py structural_analysis --html --network-stat-groups SIZE,COMPONENTS,CENTRALIZATION
python manage.py structural_analysis --html --network-stat-groups ALL
python manage.py structural_analysis --edge-weight-strategy TOTAL
python manage.py structural_analysis --recency-weights 30
python manage.py structural_analysis --spreading-runs 500
python manage.py structural_analysis --channel-types CHANNEL,GROUP
python manage.py structural_analysis --startdate 2023-01-01
python manage.py structural_analysis --enddate 2023-12-31
python manage.py structural_analysis --startdate 2023-01-01 --enddate 2023-12-31
python manage.py structural_analysis --name my-export-name
python manage.py structural_analysis --vacancy-measures ALL
python manage.py structural_analysis --vacancy-measures AMPLIFIER_JACCARD,STRUCTURAL_EQUIV,BROKERAGE
python manage.py structural_analysis --vacancy-measures CASCADE_OVERLAP,PPR,TEMPORAL
python manage.py structural_analysis --vacancy-measures ALL --vacancy-months-before 6 --vacancy-months-after 18
python manage.py structural_analysis --vacancy-measures ALL --vacancy-max-candidates 50 --vacancy-ppr-alpha 0.9
```

For a full description of all output files, see [Export formats](export-formats.md).

---

## Timeline export

Enable **Timeline by year** in the Operations panel (or pass `--timeline-step year` on the CLI) together with **2D graph** to generate a per-year breakdown of the network alongside the normal full-range export.

> **[PLACEHOLDER: `images/workflow-timeline-nav.gif`]** Year navigator: step through annual snapshots of the network with animated transitions.

### What is produced

In addition to the regular export, the pipeline repeats — graph construction, community detection, layout, measure computation — once per calendar year found in the message data:

| Path | Description |
| :--- | :---------- |
| `data_YYYY/` | Per-year data files (`channel_position.json`, `channels.json`, `communities.json`, `meta.json`) |
| `data/timeline.json` | Index of all generated years with node/edge counts |
| `channel_table_YYYY.html` | Per-year channel table *(requires `--html`)* |
| `network_table_YYYY.html` | Per-year network metrics table *(requires `--html`)* |
| `community_table_YYYY.html` | Per-year community statistics table *(requires `--html`)* |

Years with no messages in the database are silently skipped.

### Year navigator

When `data/timeline.json` is present, `graph.html` and `graph3d.html` show a compact year navigator in the bottom bar. All year datasets are preloaded during the initial spinner so every switch is instant.

| Control | Action |
|---------|--------|
| **[←]** | Step to the previous year (or *All* if on the first year) |
| **[All]** | Return to the full-range view |
| **[YYYY ▲]** | Show current year; click to open a scrollable dropdown of all available years |
| **[→]** | Step to the next year |

Selecting a year triggers an animated transition: nodes glide between positions, entering nodes grow from the centroid, the camera pans to fit. The community colouring and node-size measure are preserved across year switches.

The HTML table pages also show pill buttons at the top; clicking a year re-fetches and re-renders content for that year without a page reload.

**CLI:**

```sh
python manage.py structural_analysis --2dgraph --timeline-step year
python manage.py structural_analysis --2dgraph --html --xlsx --timeline-step year
```

> Each year runs the full ForceAtlas2 pipeline. Reduce `--fa2-iterations` if total run time is a concern.

---

## Network comparison

**Operations panel** (`/operations/`) → **Compare Analysis** → set **Project directory** → click **Run**.

Compare the current export with any previous `structural_analysis` export to see what changed between two time periods, two different corpora, or before and after a significant event.

> **[PLACEHOLDER: `images/workflow-compare-analysis.png`]** Compare Analysis: two network snapshots side by side with a normalised scatter plot.

The command:

1. Copies the compare network's data, graph files, and table files into the current export directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, etc.)
2. Generates `network_compare_table.html` with a three-column whole-network metrics table, a modularity-by-strategy comparison, and interactive scatter plots (current network in blue, compare network in red)
3. A "Normalise axes [0–1] per network" toggle min-max-scales each network independently, making size-dependent measures comparable across networks of different sizes
4. Updates `index.html` with a "Compare network" section

**Example:** a team exports two network snapshots — one before a platform content-moderation wave, one after. The scatter plot shows that 40 channels gained betweenness centrality after the event; they became bridges as previously connected channels were removed. The Algebraic Connectivity (Fiedler value) fell from 0.14 to 0.03 — the network is now on the verge of fragmentation.

**CLI alternative:**

```sh
python manage.py compare_analysis /path/to/other/exports/<name>
python manage.py compare_analysis /path/to/other/exports/<name> --seo
```

The argument must be the export directory containing `index.html`.

---

## Events (optional)

Events mark significant external occurrences — elections, incidents, publication dates — as vertical lines on all time-series charts on channel detail pages.

### Create event types

Go to **Manage** (`/manage/event-types/`) and create one or more types (e.g. *Election*, *Incident*). Each type has:

| Field | Description |
| :---- | :---------- |
| Name | Short label shown in chart tooltips |
| Description | Optional free-text note |
| Color | Hex color for the vertical marker line (default: red) |

### Create events

Go to **Manage** (`/manage/events/`) and add entries:

| Field | Description |
| :---- | :---------- |
| Date | Full calendar date |
| Subject | One-line description shown in the tooltip |
| Action | The EventType this event belongs to |

Events are fetched once per page load from `GET /events/data/`. Multiple events in the same month share a single vertical line; hovering shows a popup listing all events in that month.

---

## View the results

After exporting, go to **Data** (`/data/`) to browse exports and open graphs and tables. Or open the export directory directly in a browser:

```sh
cd exports/<name>
python -m http.server 8001
# open http://localhost:8001
```

For a full description of all generated files, see [Export formats](export-formats.md).

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

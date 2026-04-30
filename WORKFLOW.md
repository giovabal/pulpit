# Workflow

A complete guide to collecting, processing, and exporting a Pulpit network.

The primary way to run operations is through the **Operations panel** in the browser (`/operations/`). Each operation can also be run as a CLI management command — useful for scripting, automation, or running on a remote server without a browser.

> On some systems replace `python` with `python3` or `py`.

## 1. Start the server

```sh
python manage.py migrate  # first run only
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000). The browser interface handles the entire workflow from here.

## 2. Add search terms

Go to **Manage** (`/manage/search-terms/`) and add keywords. These are used to discover channels by name.

## 3. Discover channels

**Operations panel** (`/operations/`) → **Search Channels** → click **Run**.

Optional: expand **Options** to set a maximum number of search terms to process in this run.

Processes pending search terms (ordered by oldest check first) and saves the matching channels to the database.

**CLI alternative:**

```sh
python manage.py search_channels              # process all pending search terms
python manage.py search_channels --amount 15  # process at most 15 terms
```

## 4. Organise channels

In **Manage** (`/manage/channels/`), assign each channel you want to analyse to an **Organization**. Mark the organization as `is_interesting = True` in `/manage/organizations/`. Channels without an interesting organization are ignored during crawling and graph export.

## 5. Crawl channels

**Operations panel** (`/operations/`) → **Get Channels** → click **Run**.

Downloads messages for all interesting channels and resolves cross-channel references. Re-run at any time to fetch new messages.

All steps are opt-in (expand **Options** to set):

- **Get new messages** — fetch new messages from Telegram for each interesting channel; uncheck to run only post-processing steps
- **Fix message holes** — fill gaps in message history (messages missed or deleted on a previous run)
- **Retry unresolved references** — re-attempt `t.me/` usernames from message text that could not be resolved in earlier runs; references that fail permanently are marked dead and skipped on future runs
- **Force-retry dead references** — also re-attempt references already marked permanently unresolvable (e.g. deleted channels); only applies when **Retry unresolved references** is enabled
- **Refresh message stats** — update view counts, forward counts, and pinned status; combine with **Refresh limit** to restrict to the N most recent messages per channel, or messages from a given date
- **Mine about texts** — scan the `about` field of all channels in the database for `t.me/` links and fetch any referenced channels not yet in the database; zero extra API calls for already-known channels
- **Refresh degrees** — recompute and store the in-degree and out-degree for all interesting channels, and the citation degree for non-interesting channels that are forwarded or mentioned by interesting ones
- **Fetch recommended channels** — call the Telegram "recommended channels" API for each interesting channel and add new suggestions to the database; new channels are not crawled automatically
- **Fix missing media** — re-download photo and video files that are absent from disk or were never fetched
- **Channel types** — which Telegram entity types to crawl: `CHANNEL` (default), `GROUP`, `USER` (comma-separated)
- **DB id filter** — comma-separated IDs and ranges, e.g. `5, 10-20, 50-` (from 50 upward), `-30` (up to 30); restricts the crawl to matching channels

**CLI alternative:**

```sh
python manage.py get_channels --get-new-messages
python manage.py get_channels --get-new-messages --fixholes
python manage.py get_channels --get-new-messages --retry-references
python manage.py get_channels --get-new-messages --retry-references --force-retry-unresolved-references
python manage.py get_channels --get-new-messages --refresh-messages-stats        # refresh all messages
python manage.py get_channels --get-new-messages --refresh-messages-stats 200    # N most recent per channel
python manage.py get_channels --get-new-messages --refresh-messages-stats 2024-01-01
python manage.py get_channels --mine-about-texts
python manage.py get_channels --refresh-degrees
python manage.py get_channels --fetch-recommended-channels
python manage.py get_channels --ids "-30, 50-80, 99"
python manage.py get_channels --channel-types CHANNEL,GROUP
```

## 6. Export the graph

**Operations panel** (`/operations/`) → **Export Network** → click **Run**.

Builds the graph, applies community detection and layout, and writes the result to `exports/<name>/`.
By default only the data files (`data/*.json`) are written. Enable additional outputs with the options below.

When **2D graph** is enabled, the output also includes:

- `channel_table.html` — one row per channel with all computed measures
- `network_table.html` — whole-network structural metrics (density, reciprocity, clustering, path length, WCC/SCC fractions, directed assortativity, Freeman centralization, modularity per strategy) plus an interactive scatter plot for comparing any two measures
- `community_table.html` — one table per community detection strategy with structural metrics per community (node count, internal/external edges, density, reciprocity, clustering coefficient, path length, diameter)

All HTML outputs load their data at page load time from `data/*.json`; they work from any HTTP server.

**Interruption safety** — exports are written atomically. All output goes to a `<name>.tmp` staging directory; only once every file including `summary.json` has been written is the staging directory renamed to `<name>`. Aborting an in-progress export (via the **Abort** button or Ctrl-C) leaves any previous export with the same name untouched. A stale `<name>.tmp` directory from a crashed run is cleaned up automatically at the start of the next export.

Optional (expand **Options** to set):

- **2D graph** — generate the interactive `graph.html` and run the layout computation
- **HTML tables** — generate `channel_table.html`, `network_table.html`, and `community_table.html`
- **3D graph** — also produce `graph3d.html` (requires **2D graph**)
- **Excel spreadsheets** — also produce `channel_table.xlsx`, `network_table.xlsx`, `community_table.xlsx`
- **GEXF file** — also write `network.gexf`
- **GraphML file** — also write `network.graphml`
- **SEO-optimised** — sets `index, follow` robots tags and writes a permissive `robots.txt`; without this flag the output actively discourages indexing
- **Vertical layout** — orient the graph vertically; default is horizontal; the graph is rotated 90° when the computed aspect ratio does not match
- **Draw dead leaves** — include non-interesting channels referenced by interesting ones as leaf nodes; adds context but can significantly increase graph size
- **FA2 iterations** — number of ForceAtlas2 layout iterations; higher values improve node separation but take longer; default 5000
- **Recency weights** — integer N; messages up to N days old carry full weight; older messages decay as `exp(−(age−N)/N)`; leave blank to weight all messages equally
- **Spreading runs** — Monte Carlo SIR simulations per node for the `SPREADING` measure; default 200
- **Edge weight strategy** — how edge weights are computed: `PARTIAL_REFERENCES` (default), `PARTIAL_MESSAGES`, `TOTAL`, or `NONE` (unweighted)
- **Channel types** — which Telegram entity types to include: `CHANNEL` (default), `GROUP`, `USER` (comma-separated)
- **Measures** — comma-separated list of centrality measures: `PAGERANK`, `HITSHUB`, `HITSAUTH`, `BETWEENNESS`, `FLOWBETWEENNESS`, `INDEGCENTRALITY`, `OUTDEGCENTRALITY`, `HARMONICCENTRALITY`, `KATZ`, `SPREADING`, `BRIDGING` or `BRIDGING(STRATEGY)`, `BURTCONSTRAINT`, `EGODENSITY`, `AMPLIFICATION`, `CONTENTORIGINALITY`, `ALL`; default `PAGERANK`
- **Community strategies** — comma-separated list of community detection algorithms: `ORGANIZATION`, `LEIDEN`, `LEIDEN_DIRECTED`, `LOUVAIN`, `KCORE`, `INFOMAP`, `ALL`; default `ORGANIZATION`
- **Network stat groups** — comma-separated list of whole-network metric groups to compute (only when HTML tables, Excel, or consensus matrix is enabled): `SIZE`, `PATHS`, `COHESION`, `COMPONENTS`, `DEGCORRELATION`, `CENTRALIZATION`, `CONTENT`, `ALL`; default `ALL`. Deselect `PATHS` and `COHESION` to skip the expensive O(n·m) path-length and eigendecomposition calculations on large networks.
- **Start date / End date** — restrict the graph to a date range; channels with no messages in the period are excluded

**CLI alternative:**

```sh
python manage.py structural_analysis
python manage.py structural_analysis --2dgraph
python manage.py structural_analysis --html
python manage.py structural_analysis --2dgraph --html
python manage.py structural_analysis --2dgraph --3dgraph
python manage.py structural_analysis --2dgraph --xlsx
python manage.py structural_analysis --html --xlsx
python manage.py structural_analysis --gexf
python manage.py structural_analysis --graphml
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
```

## 6b. Timeline export (year-by-year animation)

Enable **Timeline by year** in the Operations panel (or pass `--timeline-step year` on the CLI) together with **2D graph** (and optionally **3D graph**) to generate a full per-year breakdown of the network alongside the normal full-range export.

### What is produced

In addition to the regular `graph/` output, the exporter repeats the full pipeline — graph construction, community detection, layout, measure computation — once per calendar year found in the message data, and writes:

| Path | Description |
| :--- | :---------- |
| `graph/data_YYYY/` | Per-year data files (`channel_position.json`, `channels.json`, `communities.json`, `meta.json`; also `channel_position_3d.json` when `--3dgraph` is used) |
| `graph/data/timeline.json` | Index listing all generated years and their node/edge counts |
| `graph/channel_table_YYYY.html` | Per-year channel table *(requires `--html`)* |
| `graph/network_table_YYYY.html` | Per-year network metrics table *(requires `--html`)* |
| `graph/community_table_YYYY.html` | Per-year community statistics table *(requires `--html`)* |

Years with no messages in the database are silently skipped.

### Year navigator in HTML tables

When `data/timeline.json` is present, all three HTML table pages (`channel_table.html`, `network_table.html`, `community_table.html`) automatically show a row of pill buttons at the top. Clicking a button re-fetches and re-renders the page content for that year without a page reload — the same single-page approach used by the graph views. **All** returns to the full-range view; the active year is highlighted in blue. Fetched data is cached in memory, so revisiting a year is instant.

### Year switcher in the 2D and 3D graphs

When `data/timeline.json` is present, both `graph.html` and `graph3d.html` automatically show a compact year navigator in the bottom navigation bar. No separate per-year graph HTML files are generated — the switcher is the sole entry point for all year views.

The navigator has four controls:

| Control | Action |
|---|---|
| **[←]** | Step to the previous year (or *All* if on the first year); disabled on *All* |
| **[All]** | Return to the full-range view |
| **[YYYY ▲]** | Show current year; click to open a scrollable dropup list of all available years |
| **[→]** | Step to the next year; disabled on the last year |

All year datasets (`data_YYYY/`) are preloaded during the initial spinner so every switch is instant. Selecting a year triggers an animated transition:

- Nodes present in **both** years glide from their old position to the new one.
- Nodes **entering** the graph grow from the old centroid into their final position.
- The camera smoothly pans and zooms to fit the new layout.
- Edges are removed before the animation and rebuilt with the new year's edges once it settles.

The currently selected community coloring and node-size measure are preserved across year switches. Clicking a year while a transition is in progress cancels the current animation and starts the new one immediately.

Per-year 2D layouts are seeded from the full-range positions and corrected via best-matching 90° rotation alignment, keeping node positions stable across years. Per-year 3D layouts are similarly seeded from the full-range 3D positions (Kamada-Kawai is run only for nodes absent from the reference).

### CLI

```sh
python manage.py structural_analysis --2dgraph --timeline-step year
python manage.py structural_analysis --2dgraph --3dgraph --timeline-step year
python manage.py structural_analysis --2dgraph --html --timeline-step year
python manage.py structural_analysis --2dgraph --html --xlsx --timeline-step year
```

`--timeline-step year` is the only supported value (the default `none` disables the feature). The option is silently ignored if no messages are found in the database.

> **Performance note.** Each year runs the full layout pipeline including ForceAtlas2. For large graphs or many years, total run time increases proportionally. Reduce `--fa2-iterations` if speed is a concern.

## 6c. Compare two networks

**Operations panel** (`/operations/`) → **Compare Analysis** → set **Project directory** → click **Run**.

Copies a previously exported `graph/` directory into the current one with `_2` suffixes and generates a side-by-side comparison page. Run this after `structural_analysis` whenever you want to compare the current network with an earlier snapshot or a different dataset.

The command:

1. Copies the compare network's `data/`, graph files, `*_table.html`, and `*.xlsx` into the current `graph/` directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, `network_table_2.xlsx`, etc.). Internal links inside the copied HTML files are rewritten to their `_2` equivalents so they work as a self-contained set.
2. Generates `graph/network_compare_table.html` with a 3-column whole-network metrics table, a modularity-by-strategy comparison table, and interactive scatter plots with this network's nodes in blue and the compare network's nodes in red. A "Normalize axes [0–1] per network" toggle min-max scales each network's values independently, making size-dependent measures comparable across networks of different sizes.
3. Updates `graph/index.html` with a "Compare network" section listing all copied files and linking to the comparison page.

Optional (expand **Options** to set):

- **SEO-optimised** — sets `index, follow` robots tags on the generated HTML

**CLI alternative:**

```sh
python manage.py compare_analysis /path/to/other/graph
python manage.py compare_analysis /path/to/other/graph --seo
```

The argument must be the `graph/` output directory of a previous `structural_analysis` run — the directory that contains `index.html`.

## 7. Add events (optional)

Events mark significant external occurrences — elections, incidents, publication dates — on all time-series charts in the **Network** home page and on individual **Channel** detail pages.

### Event types

Go to **Admin** → **Event types** and create one or more types (e.g. *Election*, *Incident*, *Publication*). Each type has:

| Field | Description |
| :---- | :---------- |
| Name | Short label shown in chart tooltips |
| Description | Optional free-text note |
| Color | Hex color used for the vertical marker line (default: red) |

### Events

Go to **Admin** → **Events** and create entries:

| Field | Description |
| :---- | :---------- |
| Date | The date of the event (full calendar date) |
| Subject | One-line description shown in the tooltip |
| Action | The `EventType` this event belongs to |

### How they appear in charts

Events are fetched once per page load from `GET /events/data/`. For each chart, events whose month falls within the chart's time span are drawn as dashed vertical lines in the EventType color. Hovering a line shows a popup listing all events in that month: date, type name, and subject. Multiple events in the same month share a single line (first event's color is used).

## 8. View the graph

After exporting, go to **Data** (`/data/`) or open [http://localhost:8000/graph/](http://localhost:8000/graph/) directly.

To serve the output as a standalone site (e.g. for deployment or sharing without the Django server):

```sh
cd graph
python -m http.server 8001
```

Open [http://localhost:8001/](http://localhost:8001/). The landing page (`index.html`) links to the graph, tables, and downloads.

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

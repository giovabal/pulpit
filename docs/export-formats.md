# Export formats

Every export is written by the **Export Network** operation (or `structural_analysis` on the CLI) into a named subdirectory of `exports/`. This document describes each output file and how to use it.

---

## Directory structure

```
exports/
  <name>/
    index.html              ← landing page
    graph.html              ← 2D interactive graph
    graph3d.html            ← 3D interactive graph (optional)
    channel_table.html      ← per-channel metrics table
    network_table.html      ← whole-network metrics
    community_table.html    ← per-community metrics
    consensus_matrix.html   ← cross-strategy co-clustering (optional)
    structural_similarity.html  ← structural equivalence matrix (optional)
    behavioural_equivalence.html  ← behavioural equivalence matrix (optional)
    network_compare_table.html   ← network comparison (optional)
    robustness_table.html   ← node-removal R-index page (optional)
    channel_table.xlsx      ← Excel version (optional)
    network_table.xlsx
    community_table.xlsx
    robustness_table.xlsx   ← raw S(f) curves and summary (optional)
    network.gexf            ← GEXF network file (optional)
    network.graphml         ← GraphML network file (optional)
    nodes.csv               ← CSV node list (optional)
    edges.csv               ← CSV edge list (optional)
    data/
      channels.json
      channel_position.json
      channel_position_3d.json  (optional)
      communities.json
      meta.json
      summary.json
      structural_similarity.json  (when --structural-similarity)
      behavioural_equivalence.json  (when --behavioural-equivalence)
      robustness.json       (when --robustness)
      timeline.json         (when --timeline-step year)
    data_YYYY/              (one per year when --timeline-step year)
      ...
    media/
      <channel_id>.jpg      ← channel avatars
```

### Atomic writes

All output first goes to a `<name>.tmp` staging directory. Only after every file — including `summary.json` — has been successfully written is the staging directory renamed to `<name>`. Aborting an in-progress export (via the Abort button or Ctrl-C) leaves any previous export with the same name untouched. A stale `<name>.tmp` directory from a crashed run is removed automatically at the start of the next export with the same name.

---

### Opening the output files: HTTP server vs. direct file access

Some files can be opened directly from the filesystem (`file://`); others require an HTTP server because they load their data via JavaScript `fetch()` calls, which browsers block under the `file://` protocol.

| File | Requires HTTP server |
| :--- | :------------------: |
| `graph.html`, `graph3d.html` | ✓ |
| `vacancy_analysis.html` | ✓ |
| `channel_table.html` / `.xlsx` | — |
| `network_table.html` / `.xlsx` | — |
| `community_table.html` / `.xlsx` | — |
| `consensus_matrix.html` | — |
| `structural_similarity.html` | — |
| `behavioural_equivalence.html` | — |
| `network_compare_table.html` | — |
| `robustness_table.html` | ✓ |
| `index.html` | — |
| `network.gexf`, `network.graphml` | — |
| `nodes.csv`, `edges.csv` | — |

The graph and vacancy-analysis pages fetch JSON files from the `data/` subdirectory at runtime. The table pages have their data embedded at generation time and open fine as local files.

**Quickest way to serve locally:**

```sh
cd exports/<name>
python -m http.server 8001
```

Open [http://localhost:8001](http://localhost:8001) in your browser. This works on macOS, Linux, and Windows — run it from any terminal with Python on the PATH.

If the Pulpit web interface is already running (`python manage.py runserver`), the export is also accessible at `http://localhost:8000/exports/<name>/graph.html` without starting a separate server.

---

## index.html — landing page

The entry point for sharing or publishing results. Lists every generated file with a short description and direct link. When Compare Analysis has been run, a "Compare network" section is added automatically. Can be opened directly from the filesystem or served via HTTP.

---

## graph.html — 2D interactive graph

<figure>
<img src="../webapp_engine/static/screenshot_08.jpg" alt="Options panel in the interactive graph">
<figcaption><em>Options panel: switch community strategy, resize nodes by any computed measure.</em></figcaption>
</figure>
<br>

Powered by [Sigma.js](http://sigmajs.org/). Generated with `--graph-2d`. **Requires an HTTP server** — see [Opening the output files](#opening-the-output-files-http-server-vs-direct-file-access).

**Controls:**

- **Search** — type a channel name to highlight and zoom to it
- **Community filter** — colour nodes by any active community strategy; switch strategies via the options panel
- **Node size** — resize nodes by any computed measure (PageRank, betweenness, amplification, etc.)
- **Click a node** — opens a detail panel with subscriber count, all computed measures, and direct links to the channel and to its detail page in the web interface
- **Year navigator** — appears when a timeline export was generated; step through annual snapshots with animated transitions (see [Workflow § Timeline export](workflow.md#timeline-export))

<figure>
<img src="../webapp_engine/static/screenshot_06.jpg" alt="3D interactive graph">
<figcaption><em>3D interactive graph (~800 nodes, ~5,000 edges): rotate, zoom, click nodes to inspect measures.</em></figcaption>
</figure>
<br>

> **[PLACEHOLDER: `images/workflow-timeline-nav.gif`]** Year navigator: step through annual snapshots of the network with animated transitions.

---

## graph3d.html — 3D interactive graph

Powered by [Three.js](https://threejs.org/). Generated with `--graph-3d` (requires `--graph-2d`). **Requires an HTTP server** — see [Opening the output files](#opening-the-output-files-http-server-vs-direct-file-access).

- Rotate, zoom, and pan the graph in three dimensions
- Click a node to open the same detail panel as in the 2D view
- The year navigator is also present when a timeline export was generated

<figure>
<img src="../webapp_engine/static/screenshot_07.jpg" alt="Node detail panel in the 3D graph">
<figcaption><em>Node detail panel: subscriber count, all computed measures, direct channel link.</em></figcaption>
</figure>
<br>

---

## channel_table.html / .xlsx — per-channel metrics

One row per channel. All computed measures appear as sortable columns. Generated with `--html`; the Excel version with `--xlsx`.

Columns include: channel name and link, organization, all computed network measures (PageRank, betweenness, amplification, etc.), subscriber count, message count, activity period, in-degree, out-degree.

Click any column header to sort. Download the `.xlsx` for further analysis in a spreadsheet application.

---

## network_table.html / .xlsx — whole-network statistics

Whole-network metrics organized by group (SIZE, PATHS, COHESION, etc.), one row per metric. Includes an interactive scatter plot: drop any two measures on the axes to compare their distributions across channels. A modularity-by-strategy table shows partition quality for every active community detection algorithm.

For a full explanation of each metric, see [Whole-network statistics](whole-network-statistics.md).

---

## community_table.html / .xlsx — per-community metrics

One section per active community detection strategy. For each strategy: a table of per-community structural metrics (node count, internal/external edges, density, reciprocity, clustering, E-I index, path lengths), a modularity-contribution column, and a collapsible organization × community distribution panel (when multiple organizations are present).

For a full explanation of the metrics, see [Whole-network statistics](whole-network-statistics.md) and [Community detection](community-detection.md).

---

## structural_similarity.html — structural equivalence matrix

Generated with `--structural-similarity`. (The filename is retained for saved-config and URL compatibility; the page shows true structural equivalence.)

A lower-triangle SVG heatmap where each cell (i, j) shows the **structural equivalence** (Lorrain & White 1971) of channels i and j: the cosine similarity of their weighted *tie profiles* — each channel's weighted out-citations to, and in-citations from, every other channel (`P = [A | Aᵀ]`, self-ties dropped). Two channels score high when they cite, and are cited by, the same channels.

Color scale: white (similarity = 0, no shared neighbours) → steel-blue (similarity = 1, identical neighbourhood). Diagonal is always 1 and is marked in grey. Hover a cell for a tooltip: "Channel A × Channel B: 0.8742."

A sort dropdown above the matrix controls channel ordering:
- **Community** (default): groups channels by their plurality community assignment, making block-diagonal structure visible when communities are structurally cohesive.
- **Any measure** (e.g. PageRank): sorts channels descending by that value.

Pre-computed data is stored in `data/structural_similarity.json` (lower-triangle float matrix + node labels and measure list). The page loads `channels.json` and `communities.json` at runtime for sorting.

See [Whole-network statistics § Structural equivalence matrix](whole-network-statistics.md#structural-equivalence-matrix) for interpretation guidance.

---

## behavioural_equivalence.html — behavioural equivalence matrix

Generated with `--behavioural-equivalence`.

A lower-triangle SVG heatmap where each cell (i, j) shows the cosine similarity of channels i and j's **behavioural-measure profiles**: amplification factor, content originality, diffusion lag, spreading efficiency, and audience/activity volume (followers, message count) — whichever were computed. Measures are min-max normalised per column; missing values (e.g. diffusion lag for a channel with no dated forwards) are imputed to the column median rather than 0. Two channels score high when they behave alike, independent of their network position.

Color scale, sort controls, and rendering match the structural equivalence matrix. Pre-computed data is stored in `data/behavioural_equivalence.json`.

See [Whole-network statistics § Behavioural equivalence matrix](whole-network-statistics.md#behavioural-equivalence-matrix) for interpretation guidance.

---

## consensus_matrix.html — cross-strategy agreement

Generated with `--consensus-matrix` (requires at least two non-ORGANIZATION community strategies).

A lower-triangle balloon plot where each cell shows how many active strategies co-assign a pair of channels to the same community. Larger, redder circles indicate higher agreement. Channels are sorted by plurality community assignment so that consistently co-clustered pairs appear near the diagonal.

Hover a cell for a tooltip: "Channel A × Channel B: N/K partitions agree."

See [Community detection § Consensus matrix](community-detection.md#consensus-matrix) for interpretation guidance.

---

## vacancy_analysis.html — vacancy succession analysis

Generated when at least one `--vacancy-measures` algorithm is selected and at least one vacancy is defined in the database. **Requires an HTTP server** — see [Opening the output files](#opening-the-output-files-http-server-vs-direct-file-access).

Loads `data/vacancy_analysis.json` at runtime and renders an accordion: one panel per vacancy channel, each listing scored replacement candidates with sortable columns for every selected measure.

See [Vacancy analysis](vacancy-analysis.md) for a full description of the algorithms and how to interpret the scores.

---

## robustness_table.html / .xlsx — node-removal robustness

Generated when `--robustness` is enabled, with the HTML produced when `--html` is also set and the XLSX when `--xlsx` is set. **The HTML requires an HTTP server** — it loads `data/robustness.json` at runtime.

The HTML page contains a summary table (one row per `(strategy, metric)` with R, R_null mean/std, z-score, and `f_c`), three Chart.js line charts (one per metric: WCC / SCC / REACH) overlaying the observed `S(f)` curves of every attack strategy, and an accordion of intra/inter community edge-survival curves per partition. The Excel workbook has the same data in three sheet families: `Summary`, one `Curve <strategy>` per attack strategy with the raw `S(f)` values and the null-model columns, and one `Modular <partition>` per partition.

`data/robustness.json` carries the full payload (config, graph metadata, per-strategy curves and R/f_c values, optional null-model statistics, optional modular curves). `None` is used for undefined ratios so the file is plain JSON (no `Infinity` / `NaN`).

See [Robustness analysis](robustness-analysis.md) for what each metric measures, how to interpret the z-score, and the limits of the null model.

---

## network_compare_table.html — network comparison

Generated by Compare Analysis. Requires a previous `structural_analysis` export as the reference.

Contains:
- A three-column whole-network metrics table (current network, compare network, difference)
- A modularity-by-strategy comparison table
- Interactive scatter plots with the current network's channels in blue and the compare network's channels in red
- A "Normalise axes [0–1] per network" toggle that min-max-scales each network independently, making size-dependent measures comparable across networks of different sizes

See [Workflow § Network comparison](workflow.md#network-comparison) for how to generate it.

---

## nodes.csv / edges.csv — CSV node and edge lists

Generated with `--csv`. Two plain-text CSV files, the most portable format for downstream analysis in R, Python, pandas, or shell scripts.

### nodes.csv

One row per channel, mirroring `channel_table.xlsx` — plus the five Gould-Fernandez brokerage role counts when `BROKERAGEROLES` was computed (these ride in the CSV and the graph-exchange exports rather than the on-screen channel table):

| Column | Content |
| :----- | :------ |
| Channel | Channel label (name or username) |
| URL | Telegram URL |
| Users | Subscriber count |
| Messages | Total message count |
| Inbound | In-degree (number of channels that forward or cite this channel) |
| Outbound | Out-degree (number of channels this channel forwards or cites) |
| *Measure columns* | One column per computed measure (PageRank, Betweenness, etc.) — only present when the measure was selected at export time |
| *Brokerage census* | When `BROKERAGEROLES` was computed: a `Brokerage role` label plus five role-count columns (Coordinator, Gatekeeper, Representative, Consultant, Liaison) — in `nodes.csv` and GEXF/GraphML only, not the HTML/Excel channel table |
| *Community columns* | One column per active community strategy, containing the community label assigned to this channel |
| Activity start | Earliest message date (`YYYY-MM`), empty if no messages |
| Activity end | Most recent message date (`YYYY-MM`), empty if no messages |

Rows are sorted by in-degree descending (most-cited channels first), matching the default order of the HTML and Excel channel tables.

### edges.csv

One row per directed edge in the network:

| Column | Content |
| :----- | :------ |
| `source_label` | Label of the source node (as in `nodes.csv`) |
| `target_label` | Label of the target node |
| `weight` | Combined edge weight computed by the active `--edge-weight-strategy` |
| `weight_forwards` | Raw count of message forwards contributing to this edge (before normalisation) |
| `weight_mentions` | Raw count of `t.me/` reference mentions contributing to this edge (before normalisation) |

`weight_forwards + weight_mentions` equals the raw total from which `weight` is computed (with the exception of the `NONE` strategy, where `weight` is always 1.0 regardless of counts). This lets you re-apply any normalisation or filter to only forwards vs. only mentions.

**Quick start in Python:**

```python
import pandas as pd

nodes = pd.read_csv("exports/my-export/nodes.csv")
edges = pd.read_csv("exports/my-export/edges.csv")

# Top 10 channels by PageRank
print(nodes.nlargest(10, "PageRank")[["Channel", "PageRank", "Users"]])

# Edges where forwards dominate over mentions
forward_heavy = edges[edges["weight_forwards"] > edges["weight_mentions"]]
```

**Quick start in R:**

```r
nodes <- read.csv("exports/my-export/nodes.csv")
edges <- read.csv("exports/my-export/edges.csv")

library(igraph)
g <- graph_from_data_frame(edges[, c("source_label", "target_label")],
                           directed = TRUE, vertices = nodes)
E(g)$weight <- edges$weight
```

---

## network.gexf / network.graphml — network exchange formats

Generated with `--gexf` and `--graphml`. Import directly into [Gephi](https://gephi.org/), [Cytoscape](https://cytoscape.org/), or any other network analysis application that reads GEXF or GraphML.

Both files include all node attributes (channel name, organization, subscriber count, all computed measures, community assignments for each active strategy) and edge weights.

---

## summary.json / meta.json — machine-readable metadata

`summary.json` records the name, creation timestamp, node and edge counts, and every CLI option used to generate this export. Useful for reproducing an export or documenting methodology.

`meta.json` records export date, project title, edge direction description, edge weight strategy, date range, total node/edge counts, and configuration flags.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

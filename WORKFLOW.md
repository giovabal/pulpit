# Workflow

A complete guide to collecting, processing, and exporting a Pulpit network.

The primary way to run operations is through the **Operations panel** in the browser (`/ops/`). Each operation can also be run as a CLI management command — useful for scripting, automation, or running on a remote server without a browser.

> On some systems replace `python` with `python3` or `py`.

## 1. Start the server

```sh
python manage.py migrate  # first run only
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000). The browser interface handles the entire workflow from here.

## 2. Add search terms

Go to **Admin** (`/admin/`) → **Search Terms** and add keywords. These are used to discover channels by name.

## 3. Discover channels

**Operations panel** (`/ops/`) → **Search Channels** → click **Run**.

Optional: expand **Options** to set a maximum number of search terms to process in this run.

Processes pending search terms (ordered by oldest check first) and saves the matching channels to the database.

**CLI alternative:**

```sh
python manage.py search_channels              # process all pending search terms
python manage.py search_channels --amount 15  # process at most 15 terms
```

## 4. Organise channels

In the **Admin** (`/admin/`), open **Channels** and assign each channel you want to analyse to an **Organization**. Mark the organization as `is_interesting = True`. Channels without an interesting organization are ignored during crawling and graph export.

## 5. Crawl channels

**Operations panel** (`/ops/`) → **Get Channels** → click **Run**.

Downloads messages for all interesting channels and resolves cross-channel references. Re-run at any time to fetch new messages.

After crawling, `get_channels` automatically refreshes the in-degree and out-degree counters for all interesting channels. It also refreshes the citation degree (direction depends on `REVERSED_EDGES`) for non-interesting channels that are forwarded or mentioned — so the graph correctly shows how much each referenced channel is cited even if it was never crawled.

Optional (expand **Options** to set):

- **Fix message holes** — fill gaps in message history (messages deleted or missed on a previous run)
- **Refresh message stats** — update view counts, forward counts, and pinned status; combine with **Refresh limit** to restrict to the N most recent messages per channel, or messages from a given date
- **From DB id ≤** — crawl only channels whose database id is at most this value; useful to resume or target a specific subset

**CLI alternative:**

```sh
python manage.py get_channels
python manage.py get_channels --fixholes
python manage.py get_channels --fromid 42
python manage.py get_channels --refresh-messages-stats               # refresh all messages
python manage.py get_channels --refresh-messages-stats 200           # refresh only the 200 most recent per channel
python manage.py get_channels --refresh-messages-stats 2024-01-01    # refresh all messages from that date to present
```

## 6. Export the graph

**Operations panel** (`/ops/`) → **Export Network** → click **Run**.

Builds the graph, applies community detection and layout, and writes the result to `graph/`.
By default produces the 2D interactive graph and three sortable HTML tables:

- `graph/channel_table.html` — one row per channel with all computed measures
- `graph/network_table.html` — whole-network structural metrics (density, reciprocity, clustering, path length, WCC/SCC fractions, directed assortativity, Freeman centralization, modularity per strategy) plus an interactive scatter plot for comparing any two measures
- `graph/community_table.html` — one table per community detection strategy with structural metrics per community (node count, internal/external edges, density, reciprocity, clustering coefficient, path length, diameter)

All HTML outputs load their data at page load time from `graph/data/*.json`; they work from any HTTP server.

Optional (expand **Options** to set):

- **3D graph** — also produce `graph3d.html`
- **Excel spreadsheets** — also produce `channel_table.xlsx`, `network_table.xlsx`, `community_table.xlsx`
- **GEXF file** — also write `network.gexf`
- **SEO-optimised** — sets `index, follow` robots tags and writes a permissive `robots.txt`; without this flag the output actively discourages indexing
- **Skip 2D graph** — skip the interactive graph (tables only)
- **Skip HTML tables** — skip HTML tables (graph only)
- **Start date / End date** — restrict the graph to a date range; channels with no messages in the period are excluded
- **Compare with project dir** — path to a previous `export_network` output (`graph/` directory); produces a side-by-side comparison page

**CLI alternative:**

```sh
python manage.py export_network
python manage.py export_network --3d
python manage.py export_network --xlsx
python manage.py export_network --no-html
python manage.py export_network --no-graph
python manage.py export_network --no-graph --xlsx
python manage.py export_network --gexf
python manage.py export_network --seo
python manage.py export_network --startdate 2023-01-01
python manage.py export_network --enddate 2023-12-31
python manage.py export_network --startdate 2023-01-01 --enddate 2023-12-31
python manage.py export_network --compare /path/to/other/graph
```

The `--compare` argument must be the `graph/` output directory of a previous run — the directory that contains `index.html`. The command:

1. Copies the compare network's `data/`, graph files, `*_table.html`, and `*.xlsx` into the current `graph/` directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, `network_table_2.xlsx`, etc.). Internal links inside the copied HTML files are rewritten to their `_2` equivalents so they work as a self-contained set.
2. Generates `graph/network_compare_table.html` with a 3-column whole-network metrics table, a modularity-by-strategy comparison table, and interactive scatter plots with this network's nodes in blue and the compare network's nodes in red. A "Normalize axes [0–1] per network" toggle min-max scales each network's values independently, making size-dependent measures comparable across networks of different sizes.
3. Adds a "Compare network" section to `graph/index.html` listing all copied files and linking to the comparison page.

## 7. View the graph

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

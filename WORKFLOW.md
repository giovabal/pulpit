# Workflow

A complete guide to collecting, processing, and exporting a Pulpit network. Each step corresponds to a Django management command or an action in the admin interface.

> On some systems replace `python` with `python3` or `py`.

## 1. Start the admin interface

```sh
python manage.py runserver
```

Open [http://localhost:8000/admin/](http://localhost:8000/admin/).

## 2. Add search terms

In the admin, go to **Search Terms** and add keywords. These are used to discover channels by name.

## 3. Discover channels

```sh
python manage.py search_channels              # process all pending search terms
python manage.py search_channels --amount 15  # process at most 15 terms
```

Processes pending search terms (ordered by oldest check first) and saves the matching channels to the database. Use `--amount` to cap the number of terms processed in one run.

## 4. Organise channels

Back in the admin, open **Channels** and assign each channel you want to analyse to an **Organization**. Mark the organization as `is_interesting = True`. Channels without an interesting organization are ignored during crawling and graph export.

## 5. Crawl channels

```sh
python manage.py get_channels
```

Downloads messages for all interesting channels. Re-run at any time to fetch new messages.

After crawling, `get_channels` automatically refreshes the in-degree and out-degree counters for all interesting channels. It also refreshes the citation degree (the direction depends on `REVERSED_EDGES`) for non-interesting channels that are forwarded or mentioned (via `t.me/` links) by interesting ones — so the graph correctly shows how much each referenced channel is cited even if it was never crawled.

To also fill gaps in message history (messages that were deleted or missed on a previous run):

```sh
python manage.py get_channels --fixholes
```

To crawl only channels whose database id is less than or equal to a given value (useful to resume or target a specific subset):

```sh
python manage.py get_channels --fromid 42
```

To refresh view counts, forward counts, and pinned status (these counters change over time but are only recorded when a message is first crawled):

```sh
python manage.py get_channels --refresh-messages-stats               # refresh all messages
python manage.py get_channels --refresh-messages-stats 200           # refresh only the 200 most recent per channel
python manage.py get_channels --refresh-messages-stats 2024-01-01    # refresh all messages from that date to present
```

## 6. Export the graph

```sh
python manage.py export_network
```

Builds the graph, applies community detection and layout, and writes the result to `graph/`.
By default also writes three sortable HTML tables:

- `graph/channel_table.html` — one row per channel with all computed measures
- `graph/network_table.html` — whole-network structural metrics (density, reciprocity, clustering, path length, WCC/SCC fractions, directed assortativity, Freeman centralization, modularity per strategy) plus an interactive scatter plot for comparing any two measures on log-log axes
- `graph/community_table.html` — one table per community detection strategy with structural metrics per community (node count, internal/external edges, density, reciprocity, average clustering coefficient, average shortest path length, diameter)

All HTML outputs load their data at page load time from `graph/data/*.json`; they are static files that work from any HTTP server.

To control what outputs are produced, use `--format` with a comma-separated list of `graph`, `3dgraph`, `html`, and `xlsx` (default: `graph,html`):

```sh
python manage.py export_network --format graph,html        # default: 2D graph + HTML tables
python manage.py export_network --format graph,3dgraph,html  # also generate the 3D graph
python manage.py export_network --format graph,html,xlsx   # graph + both HTML and Excel tables
python manage.py export_network --format html,xlsx         # tables only, no graph
python manage.py export_network --format graph             # graph only, no tables
```

The Excel output produces `graph/channel_table.xlsx` (one row per channel), `graph/network_table.xlsx` (whole-network metrics on a single sheet), and `graph/community_table.xlsx` (one sheet per community detection strategy).

To restrict the graph to a date range (channels with no messages in the period are excluded):

```sh
python manage.py export_network --startdate 2023-01-01                       # messages from this date
python manage.py export_network --enddate 2023-12-31                         # messages up to this date
python manage.py export_network --startdate 2023-01-01 --enddate 2023-12-31  # date range
```

To make the output discoverable by search engines (sets `index, follow` robots tags and writes a permissive `robots.txt`; without this flag the output actively discourages indexing):

```sh
python manage.py export_network --seo
```

To compare this network against another export side-by-side:

```sh
python manage.py export_network --compare /path/to/other/graph
```

The argument must be the `graph/` output directory of a previous `export_network` run — the directory that contains `index.html`. The command:

1. Copies the compare network's `data/`, graph files, `*_table.html`, and `*.xlsx` into the current `graph/` directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, `network_table_2.xlsx`, etc.). Internal links inside the copied HTML files are rewritten to their `_2` equivalents so they work as a self-contained set.
2. Generates `graph/network_compare_table.html` with:
   - a 3-column whole-network metrics table (Metric / This network / Compare network)
   - a modularity-by-strategy comparison table
   - interactive scatter plots with this network's nodes in blue and the compare network's nodes in red; axes are user-selectable, log scale, zoom/pan enabled
   - a "Normalize axes [0–1] per network" toggle that min-max scales each network's values independently, making size-dependent measures directly comparable across networks of different sizes
3. Adds a "Compare network" section to `graph/index.html` listing all copied files and linking to the comparison page.

## 7. View the graph

When `runserver` is running, the output is available directly at:

[http://localhost:8000/graph/](http://localhost:8000/graph/)

To serve it as a standalone site (e.g. for deployment or sharing without the Django server):

```sh
cd graph
python -m http.server 8001
```

Open [http://localhost:8001/](http://localhost:8001/). The landing page (`index.html`) links to the graph, tables, and downloads.

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md)

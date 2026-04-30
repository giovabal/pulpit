# Pulpit
### Political undercurrents: linkage, propagation, influence on Telegram

Telegram is home to thousands of political channels — news outlets, activist groups, propaganda outlets, and everything in between. They constantly reference each other: forwarding messages, linking to one another, amplifying certain voices and ignoring others. These cross-references are not random; they reveal alliances, ideological clusters, and influence networks that are otherwise invisible.

**Pulpit** makes those networks visible. It collects messages from a set of Telegram channels you define, traces every forward and every `t.me/` link between them, and turns the result into an interactive map you can explore in a browser — zooming in on individual channels, filtering by community, comparing the reach of different nodes.

It is designed for journalists, researchers, and analysts working on political communication, disinformation, and online influence. Pulpit is actively developed and evolving — see the [changelog](CHANGELOG.md) for what is new.

---

<figure>

![Example graph — ~400 nodes, ~8 000 edges, Louvain community detection, vapoRwave palette](webapp_engine/static/example.jpg)

<figcaption>Example output — ~400 nodes, ~8 000 edges, Louvain community detection, vapoRwave palette. More screenshots <a href="SCREENSHOTS.md">are available</a>.</figcaption>
</figure>

## How it works

1. You provide search terms; Pulpit finds matching Telegram channels via the API.
2. You review the results in the admin interface and group channels into **Organizations** — thematic clusters (e.g. by political leaning, country, topic).
3. Pulpit crawls the selected channels, collecting messages and resolving cross-channel references (forwards and `t.me/` links).
4. A graph is built from those references, communities are detected and colored, a ForceAtlas2 layout is applied, and the result is exported as an interactive HTML map.


## What you get

After the export completes, the `graph/` directory contains:

- **`index.html`** — a landing page listing every output with descriptions and links; the starting point for sharing or publishing results
- **`graph.html`** — the interactive 2D graph: search channels, filter by community, size nodes by any computed measure, inspect individual channels and their connections
- **`channel_table.html`** — sortable table with one row per channel and all computed measures; download as `channel_table.xlsx`
- **`network_table.html`** — whole-network structural metrics with an interactive scatter plot for comparing any two measures; download as `network_table.xlsx`
- **`community_table.html`** — per-community structural metrics for each detection strategy; download as `community_table.xlsx`

During development the entire output is served at `http://localhost:8000/graph/` by the Django server — no separate HTTP server needed.


## Quick start

> See [INSTALLATION.md](INSTALLATION.md) for setup and [WORKFLOW.md](WORKFLOW.md) for the complete guide including all options.

```sh
python manage.py migrate
python manage.py runserver   # open http://localhost:8000
```

Once the server is running, the whole workflow is driven from the browser:

1. **Admin** (`/admin/`) → add **Search Terms** to seed channel discovery.
2. **Operations** (`/operations/`) → run **Search Channels** to find matching Telegram channels.
3. **Admin** → assign channels to **Organizations**, mark `is_interesting = True`.
4. **Operations** → run **Get Channels** to crawl messages and resolve cross-channel references.
5. **Operations** → run **Structural Analysis** to build the graph and write output files.
6. **Data** (`/data/`) → browse the exported graph and tables, or open `http://localhost:8000/graph/` directly.

The **Channels** tab (`/channels/`) and per-channel pages show crawled data, message history, and network statistics as you go.

All three operations are also available as CLI commands for scripted or automated runs — see [WORKFLOW.md](WORKFLOW.md).


## How it's built

Pulpit is built around three stages:

**1. Crawling.** Pulpit uses the official Telegram API (via [Telethon](https://github.com/LonamiWebs/Telethon)) to download messages from the channels you select. For each message it records forwards (which channel's content was reposted) and inline `t.me/` references (links to other channels appearing in the message text or as URL entities). This produces a directed, weighted graph: an edge from channel A to channel B means A regularly amplifies B's content, and its weight reflects how often, relative to A's total output.

**2. Analysis.** The graph is analysed with [NetworkX](https://networkx.org/). Several centrality measures can be computed — PageRank, HITS Hub and Authority scores, betweenness centrality, in-degree centrality, out-degree centrality, harmonic centrality, Katz centrality, bridging centrality, Burt's constraint, content originality, and amplification — to rank channels by influence, reach, or structural importance. Community detection algorithms (Louvain, Leiden, k-shell decomposition, Infomap, or your own manually defined groups) identify clusters of channels that behave as coherent ecosystems.

**3. Visualisation.** The graph is laid out using [ForceAtlas2](https://github.com/bhargavchippada/forceatlas2), a force-directed algorithm that naturally pulls tightly connected clusters together. The result is exported as a self-contained HTML file powered by [Sigma.js](http://sigmajs.org/), with controls for searching, filtering by community, changing node size by any computed measure, and inspecting individual channels. An optional 3D version (`--3dgraph`) is also available, rendered with [Three.js](https://threejs.org/).


## Documentation

| | |
| :--- | :--- |
| [INSTALLATION.md](INSTALLATION.md) | Requirements, setup, and database initialisation |
| [WORKFLOW.md](WORKFLOW.md) | Complete step-by-step guide: finding channels, crawling, exporting — via the Operations panel and the CLI |
| [CONFIGURATION.md](CONFIGURATION.md) | Full reference for all `.env` settings |
| [ANALYSIS.md](ANALYSIS.md) | All network measures and community detection strategies — what they measure and how to read them |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [SCREENSHOTS.md](SCREENSHOTS.md) | Example output across different graph sizes, strategies, and display modes |


## Disclaimer

Pulpit is intended for academic research, investigative journalism, and analytical work on publicly accessible Telegram channels. It was written with the aim of complying with applicable laws and with [Telegram's Terms of Service](https://telegram.org/tos) as they stood at the time of development.

Laws governing data collection, storage, and analysis of public communications vary across jurisdictions and change over time. Telegram's Terms of Service are likewise subject to revision. It is your responsibility to verify that your use of this software complies with the laws of your country and with Telegram's current Terms of Service before running it. The authors accept no liability for uses that fall outside lawful research and analysis.

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

# Pulpit

### Political undercurrents: linkage, propagation, influence on Telegram

**Map influence, information flow, and community structure in Telegram networks.**

Telegram channels constantly reference each other — forwarding messages, linking to one another, amplifying certain voices and ignoring others. These cross-references are not random: they reveal alliances, ideological clusters, and influence structures that are otherwise invisible. Which channels set the agenda? Who redistributes their content? Where do otherwise separate ecosystems overlap? Who is the only bridge connecting two communities that never directly interact?


<figure>

![Example graph — ~700 channels, ~10,000 edges, Leiden directed community detection, PageRank nodes size, vapoRwave palette](webapp_engine/static/2d_graph_example.jpg)

<figcaption><em>~700 channels, ~10,000 edges. Leiden directed community detection, PageRank node size, vapoRwave palette.</em></figcaption>
</figure>
<br>

Pulpit collects messages from a set of Telegram channels you define, traces every forward and every `t.me/` link between them, and turns the result into an interactive network map you can explore in a browser — zooming in on individual channels, filtering by detected community, comparing the reach of different actors, stepping through how the network evolved year by year.

The analytical layer is built on established methods from network science: [PageRank](docs/network-measures.md#pagerank), [Burt's structural holes](docs/network-measures.md#burts-constraint), [Leiden community detection](docs/community-detection.md#leiden), [k-core decomposition](docs/community-detection.md#k-core), and more — applied to the specific dynamics of Telegram forwarding networks. See the [changelog](CHANGELOG.md) for recent additions.

---

## Who uses it and for what

- **Investigative journalists** mapping political influence networks, tracing disinformation ecosystems, or documenting coordinated information campaigns across Telegram
- **Academic researchers** in political communication, network science, computational social science, and disinformation studies
- **Activists and NGOs** monitoring specific Telegram ecosystems — far-right networks, health misinformation communities, foreign-influence operations
- **Students** in digital methods, computational journalism, or media studies courses

---

## Questions you can answer

Pulpit answers both structural and dynamical questions about a Telegram information ecosystem.

**About individual channels:**

- Which channels are the hidden agenda-setters — forwarded by all the key players, regardless of subscriber count? *([PageRank](docs/network-measures.md#pagerank))*
- Which channels are pure distributors — aggregating and reposting from many sources without producing original content? *([HITS Hub](docs/network-measures.md#hits-hub-score), [Content Originality](docs/network-measures.md#content-originality))*
- Which channels bridge ideologically separate communities — the only link between two groups that otherwise share no direct contact? *([Burt's Constraint](docs/network-measures.md#burts-constraint))*
- Whose content spreads farthest per post published, despite a modest following? *([Amplification Factor](docs/network-measures.md#amplification-factor))*

**About communities:**

- How does the network cluster when the citation data decides the boundaries — not your own labels? *([Leiden](docs/community-detection.md#leiden), [Leiden (directed)](docs/community-detection.md#leiden-directed), [Leiden CPM](docs/community-detection.md#leiden-cpm), and more)*
- Which channels form the tight, mutually-reinforcing nucleus of the network? *([K-core](docs/community-detection.md#k-core))*
- Which community detection algorithms agree on a grouping, and which disagree? *([Consensus matrix](docs/community-detection.md#consensus-matrix))*
- How cohesive or competitive are the communities? How much do they interact? *([E-I Index, Modularity](docs/whole-network-statistics.md))*

**About change over time:**

- How did the network evolve year by year? Which channels rose, fell, or switched communities? *([Timeline export](docs/workflow.md#timeline-see-how-the-network-changed-over-time))*
- How does the network today compare to a snapshot from six months ago? *([Network comparison](docs/workflow.md#compare-two-networks))*
- After a key channel went silent — removed, banned, or simply abandoned — who filled its structural role? *([Vacancy Analysis](docs/vacancy-analysis.md))*
- How resilient is this ecosystem if a moderation wave starts pulling channels offline — and which kinds of removals would damage it most? *([Robustness Analysis](docs/robustness-analysis.md))*
- Which messages punched above their channel's own baseline, and which ones escaped their origin community to spread across the network? *([Interesting messages](docs/interesting-messages.md))*

---

## Quick start

> **Prerequisites:** Python 3.12, 3.13, or 3.14 (all fully supported). No Git required for the download below.

1. **Download the latest stable release:** open the **[releases page](https://github.com/giovabal/pulpit/releases/latest)**, download **Source code (zip)** under *Assets*, and unzip it. You'll get a folder such as `pulpit-0.25`.
2. **Open a terminal in that folder** and run the setup for your platform:

**macOS / Linux**
```sh
sh setup.sh
# Edit configuration/.env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE_NUMBER
python manage.py runserver
```

**Windows**
```cmd
setup.bat
rem Edit configuration/.env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE_NUMBER
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000). The entire workflow runs from the browser from here. See [Getting started](docs/getting-started.md) for setup details, Telegram credential registration, and database configuration.

> **Prefer Git?** Run `git clone https://github.com/giovabal/pulpit`, then `cd pulpit`, then setup as above — this gives you the latest *development* code instead of the stable release. The [Getting started](docs/getting-started.md#alternative-install-with-git) guide covers this path.

---

## How it works

A Pulpit research project runs in five steps, all accessible from the browser interface:

<figure>

![The four-step pipeline: search channels → crawl channels → structural analysis → compare analysis](webapp_engine/static/pipeline.jpg)

<figcaption><em>The four operations: search channels → crawl channels → structural analysis → compare analysis.</em></figcaption>
</figure>
<br>

1. **Find channels** — *Operations: Search channels* — add keywords; Pulpit searches Telegram and populates a list of matching channels
2. **Organize** — *Manage: Channels* — assign channels to categories you define (by political orientation, country, funding source, or any grouping that fits your research); channels without a category are excluded from analysis
3. **Collect channels info and messages** — *Operations: Crawl channels* — download messages from all organized channels; Pulpit records every forward and every `t.me/` link, building a directed citation network
4. **Generate the map** — *Operations: Structural analysis* — run community detection and layout algorithms; export an interactive map, sortable tables, and network exchange files
5. **Compare maps** — *Operations: Compare analysis* — compare two set of data; It could be the same network at two different times, compare the same network context but for two different countries, or just compare two different networks

The core data model is a **directed, weighted citation graph**: a directed edge from channel A to channel B means A regularly amplifies B's content. Edge weight reflects how much of A's output references B relative to A's overall citing activity.

---

## What you get

After export, the output directory contains self-contained files that can be shared without an internet connection. Multiple named exports can coexist — each is written atomically, so an interrupted run never corrupts a previous result.

| Output | What it is |
| :----- | :--------- |
| **Interactive 2D graph** (`graph.html`) | Search, filter by community, resize nodes by any measure, click for channel detail. Switch between ForceAtlas2, Spectral, Spring, and Circular layouts with animated transitions — no re-export required. [more](docs/export-formats.md#graphhtml--2d-interactive-graph) |
| **Interactive 3D graph** (`graph3d.html`) | Three.js, rotate/zoom/inspect; multiple themes and coloured-edge toggle [more](docs/export-formats.md#graph3dhtml--3d-interactive-graph) |
| **Channel table** (`channel_table.html/.xlsx`) | One row per channel with all computed measures, sortable; per-year sparklines when a timeline was exported [more](docs/export-formats.md#channel_tablehtml--xlsx--per-channel-metrics) |
| **Network statistics table** (`network_table.html/.xlsx`) | Whole-ecosystem metrics, measure comparison scatter plot, NMI partition agreement matrix [more](docs/export-formats.md#network_tablehtml--xlsx--whole-network-statistics) |
| **Community table** (`community_table.html/.xlsx`) | Per-community metrics for each detection strategy; Organization × community cross-tabulation [more](docs/export-formats.md#community_tablehtml--xlsx--per-community-metrics) |
| **Structural equivalence matrix** (`structural_similarity.html`) | Lorrain & White (1971) structural equivalence: cosine similarity of each channel's weighted citation tie profile — high when two channels cite, and are cited by, the same others. Sortable by community or by measure [more](docs/export-formats.md) |
| **Consensus matrix** (`consensus_matrix.html`) | Agreement heatmap: how consistently each pair of channels is co-assigned across the partition-based strategies (Organization and K-core excluded) [more](docs/community-detection.md#consensus-matrix) |
| **Vacancy Analysis** (`vacancy_analysis.html`) | Replacement candidates ranked by four algorithms after a channel goes silent [more](docs/vacancy-analysis.md) |
| **Robustness analysis** (`robustness_table.html` / `.xlsx`) | Resistance to node removal: residual-size R-index per attack strategy on the (optionally disparity-filtered) backbone, z-score against a weight-rewiring null model, plus intra/inter community edge survival curves [more](docs/robustness-analysis.md) |
| **Timeline animation** | Step through annual snapshots with animated node transitions in both the 2D and 3D graphs [more](docs/workflow.md#timeline-see-how-the-network-changed-over-time) |
| **Network comparison** (`network_compare_table.html`) | Side-by-side comparison of two exports: which channels gained or lost influence [more](docs/workflow.md#compare-two-networks) |
| **CSV node and edge lists** (`nodes.csv`, `edges.csv`) | Most portable format for scripting in R, Python, or shell. `nodes.csv` has the same columns as the channel table. `edges.csv` has `source_label`, `target_label`, `weight`, `weight_forwards`, `weight_mentions`. [more](docs/export-formats.md) |
| **GEXF and GraphML** | For Gephi, Cytoscape, R/igraph, and any graph-analysis tool [more](docs/export-formats.md#networkgexf--networkgraphml--network-exchange-formats) |

---

## Network measures — 11 per channel

Each channel receives a score for up to 11 measures. All can be used to size nodes in the graph viewer, making the most significant channels visually prominent. Measures are grouped below by the type of question they answer.

**Influence and reach**

| Measure | What it surfaces |
| :------ | :--------------- |
| [PageRank](docs/network-measures.md#pagerank) | Channels the network's key players treat as authoritative — prestige propagates through forwarding chains |
| [HITS Hub](docs/network-measures.md#hits-hub-score) | The distributors: channels that amplify many authoritative sources at scale |
| [HITS Authority](docs/network-measures.md#hits-authority-score) | The primary sources that distributors choose to spread |
| [In-degree centrality](docs/network-measures.md#in-degree-centrality) | The most-cited channels, by raw fraction of the network citing them |
| [Out-degree centrality](docs/network-measures.md#out-degree-centrality) | The most active amplifiers, by raw fraction of the network they cite |
| [Amplification factor](docs/network-measures.md#amplification-factor) | Forwards received per message published — who punches above its weight |

**Position and brokerage**

| Measure | What it surfaces |
| :------ | :--------------- |
| [Burt's constraint](docs/network-measures.md#burts-constraint) | Structural hole brokers — the only bridges between otherwise disconnected groups |
| [Local clustering](docs/network-measures.md#local-clustering) | Whether the channel's immediate contacts also cite each other — a tight mutual-amplification neighbourhood vs. an open star of independent sources (Fagiolo 2007) |
| [Within-module role](docs/network-measures.md#within-module-role) | Within-community hub vs. cross-community connector — the Guimerà-Amaral role taxonomy |

**Content and dynamics**

| Measure | What it surfaces |
| :------ | :--------------- |
| [Content originality](docs/network-measures.md#content-originality) | Producers vs. redistributors — 1 minus the fraction of forwarded messages |
| [Diffusion lag](docs/network-measures.md#diffusion-lag) | Median hours between a forwarded message's original publication and this channel forwarding it — early adopter vs. late amplifier |

See [Network measures](docs/network-measures.md) for academic references and worked examples for each measure.

---

## Community detection — 7 algorithms and one custom selection

Pulpit runs up to seven community detection algorithms at once, alongside your own Organization grouping as a baseline. Each reveals a different structural layer of the same data; comparing them shows which groupings are robust and which are algorithm-dependent.

| Algorithm | What it finds | Direction-aware? |
| :-------- | :------------ | :--------------- |
| [Organization](docs/community-detection.md#organization) | Your own domain-knowledge categories as a baseline | — |
| [Leiden](docs/community-detection.md#leiden) | General community structure from citation density | No |
| [Leiden Directed](docs/community-detection.md#leiden-directed) | Same, but the directed null model respects who cites whom | Yes |
| [Leiden CPM](docs/community-detection.md#leiden-cpm) | Resolution γ tunes granularity — low γ gives few large communities, high γ many small ones | No |
| [Louvain](docs/community-detection.md#louvain) | Classic modularity baseline — kept for comparison with older studies; Leiden supersedes it | No |
| [Label propagation](docs/community-detection.md#label-propagation) | Parameter-free label consensus — near-linear time, best for large graphs | No |
| [K-core](docs/community-detection.md#k-core) | Onion-layer peeling from the tight nucleus to the peripheral amplifiers | No |
| [Stochastic block model](docs/community-detection.md#stochastic-block-model) | Citation-role blocks — channels grouped by structural position (source/amplifier, core/periphery), not just dense clusters | Yes |

The **Organization × community cross-tabulation** in every strategy section shows how your manual categories map onto the algorithm's output — confirming agreement or surfacing unexpected internal splits. The **consensus matrix** aggregates the partition-based detection strategies — every algorithm except your manual Organization labels and the K-core shell decomposition — into a single heatmap: pairs with large red circles are co-assigned by every algorithm, making their grouping robust independent of method choice.

See [Community detection](docs/community-detection.md) for descriptions, references, and a strategy selection guide.

---

## Vacancy analysis — 4 algorithms

When a channel goes silent — removed from Telegram, legally forced offline, or simply abandoned — it leaves a structural hole in the network. Channels that used to rely on it as a source now need to find an alternative. Pulpit's Vacancy Analysis answers: *who fills that structural role?*

An analyst registers a channel as a vacancy with a closure date. Pulpit then identifies the **orphaned amplifiers** — channels that forwarded from the vacancy before it closed — and ranks replacement candidates by four complementary scores:

| Score | Question | Method |
| :---- | :------- | :----- |
| Amplifier Coverage | What fraction of orphaned amplifiers have started forwarding the candidate? | Coverage / recall (|A ∩ B| / |A|) |
| Neighbour-set Equivalence | Does the candidate occupy the same position — same inputs, same amplifiers? | Cosine similarity (Lorrain & White 1971) |
| Brokerage overlap | Does the candidate sit in the same organizational position — drawing on the same source orgs and amplified by the same audience orgs? | Jaccard of the (source-org, amplifier-org) pairs it spans; a one-degree structural-position overlap, not content flow. Brokerage *concept* per Gould & Fernandez 1989 (not their census) |
| Temporal adoption | How quickly and broadly did the orphaned channels adopt the candidate? | Coverage hyperbolically discounted by mean days-to-adoption (Mazur 1987) |

A–C characterise structural position topologically; Temporal adoption adds the timing dimension. A channel scoring high on all four is a strong structural heir — the same distributors, the same upstream sources, the same brokerage role, all settled on quickly.

See [Vacancy analysis](docs/vacancy-analysis.md) for academic grounding, score interpretation patterns, and the batch export API.

---

## Robustness analysis — 7 attack strategies

How well does this ecosystem hold up when channels start disappearing? Different removals damage the network in different ways: peripheral amplifiers can leave without a trace, but stripping a hub or a community bridge can fragment information flow across half the network. Pulpit's Robustness Analysis answers: *which kinds of node loss matter most, and does this network have identifiable critical channels at all?*

The analysis optionally extracts the [disparity-filter backbone](docs/robustness-analysis.md#what-gets-attacked) (Serrano-Boguñá-Vespignani 2009) — pruning edges statistically indistinguishable from uniform weight noise — then progressively removes nodes under several attack strategies and tracks how the residual network shrinks:

| Strategy | Mode | What it models |
| :------- | :--- | :------------- |
| Random | Static (averaged over N runs) | Indiscriminate node loss — the baseline against which targeted attacks should look much worse |
| In-strength | Static | Take down everything that's heavily cited — moderation aimed at popular destinations |
| Out-strength | Static | Take down everything that cites heavily — moderation aimed at aggregators |
| PageRank | Static | Take down the highest-prestige nodes — moderation aware of inherited prestige |
| In-strength (dyn) | Dynamic — re-rank after every removal | Strength-based attack with cascade awareness |
| Out-strength (dyn) | Dynamic — re-rank after every removal | Aggregator-targeting attack with cascade awareness |
| PageRank (dyn) | Dynamic — re-rank after every removal | PageRank attack with cascade awareness |

For each (strategy, "size" metric) Pulpit reports the **Schneider et al. (2011) R-index** — the average residual size across the entire attack — plus a 5%-collapse threshold and a **z-score** against a weight-rewiring null model that preserves topology and the weight multiset but reshuffles weights among edges. R values lower than random failure mean the network has critical channels; |z| ≥ 2 means the deviation didn't happen by chance under the null. When community partitions are active, the analysis additionally tracks intra-community vs inter-community edge survival — a network where bridges go first behaves very differently from one that loses cohesive cliques first.

Three size metrics are tracked simultaneously: largest weakly-connected component, largest strongly-connected component (the mutually-reinforcing core), and the fraction of directed source→target pairs still reachable. When `--timeline-step year` is also active, the whole battery runs once per calendar year alongside the global one, with the HTML page surfacing a year navigator over the per-year results.

See [Robustness analysis](docs/robustness-analysis.md) for the formal definitions, the null-model limits (what it does *not* preserve), interpretation guidance, and the academic references.

---

## Technical foundation

**Crawling.** The official Telegram API (via [Telethon](https://github.com/LonamiWebs/Telethon)) downloads messages from the channels you select. For each message, Pulpit records forwards (which channel's content was reposted) and inline `t.me/` references (links to other channels). The result is a directed, weighted graph. Edge weight is computed as the number of forwards and references from A to B divided by the number of A's messages that contain any outward reference — not A's total message count — so channels that mostly publish original content and channels that are mostly aggregators are treated symmetrically.

**Analysis.** The graph is analysed with [NetworkX](https://networkx.org/). Node-level measures rank channels by influence, reach, or structural importance. Community detection algorithms identify clusters. Whole-network statistics — density, reciprocity, algebraic connectivity (Fiedler 1973), E-I index (Krackhardt & Stern 1988), global efficiency (Latora & Marchiori 2001), and more — characterise the ecosystem as a system. The NMI matrix (Kvalseth 1987) quantifies how much two community partitions agree, independently of community labels.

**Layout and visualisation.** Nodes are placed using [ForceAtlas2](https://github.com/bhargavchippada/forceatlas2) seeded from a Kamada-Kawai initial layout, improving reproducibility across re-exports. Alternative spatial layouts (Spectral, Spring, Circular) are pre-computed at export time and selectable at viewing time with smooth animated transitions. The 2D graph is a self-contained HTML file powered by [Sigma.js](http://sigmajs.org/). The optional 3D graph uses [Three.js](https://threejs.org/) with Lambert-shaded spheres and full mouse rotation, zoom, and pan.

**Storage and access control.** Data is stored in SQLite by default — a single file, no database server required. PostgreSQL, MySQL/MariaDB, and Oracle are supported for multi-user deployments. The browser interface supports three access modes: fully open (personal use on your own machine), semi-protected (public channel browser, restricted operations panel), and fully protected (login required for all pages).

**CLI access.** Every operation is also available as a management command for scripting, scheduling, and automation. See the [Workflow](docs/workflow.md#advanced-running-from-the-command-line) documentation for the full command reference.

**Accessibility.** Even though Pulpit is a data-intensive interface, we care about accessibility, and most of the interface tries to be friendly in this regard: keyboard-reachable controls, visible focus indicators, screen-reader announcements for asynchronous updates, hidden data-table companions for charts, labelled landmarks, and a skip-to-content link on every page.

---

## Documentation

| File | Contents |
| :--- | :------- |
| [Getting started](docs/getting-started.md) | Requirements, installation, Telegram credentials, database setup, access control — written for readers with no prior programming experience |
| [Workflow](docs/workflow.md) | Step-by-step guide: search → organize → crawl → export; all CLI options |
| [Network measures](docs/network-measures.md) | All 11 per-channel measures with academic references and worked examples |
| [Community detection](docs/community-detection.md) | 8 strategies, consensus matrix, cross-strategy comparison, choosing a strategy |
| [Whole-network statistics](docs/whole-network-statistics.md) | Ecosystem-level metrics: density, reciprocity, clustering, Fiedler value, E-I index, NMI, and more |
| [Vacancy analysis](docs/vacancy-analysis.md) | 4 algorithms for identifying structural replacement channels after a node disappears |
| [Robustness analysis](docs/robustness-analysis.md) | Resistance to node removal: R-index per attack strategy, z-score against a weight-rewiring null model, intra/inter community edge survival |
| [Interesting messages](docs/interesting-messages.md) | Per-channel z-scored engagement composite plus structural-reach metrics (cross-community reach, authority-weighted reach) |
| [Web interface](docs/web-interface.md) | Browser UI: channel browser, channel detail pages, Operations panel, backoffice |
| [Export formats](docs/export-formats.md) | All output files: graphs, tables, GEXF, GraphML, atomic write safety |
| [Operations defaults & configuration](docs/operations-defaults.md) | How the form, the CLI, and the snapshot files relate; the three buttons (Save / Load / Write CLI); the every-flag-must-be-explicit CLI rule |
| [Configuration reference](docs/configuration.md) | Every setting in `configuration/.env` and the two `.operations-*` TOML files, with built-in defaults |
| [Changelog](CHANGELOG.md) | Version history |

---

## Disclaimer

Pulpit is intended for academic research, investigative journalism, and analytical work on publicly accessible Telegram channels. It was written with the aim of complying with applicable laws and with [Telegram's Terms of Service](https://telegram.org/tos) as they stood at the time of development.

Laws governing data collection, storage, and analysis of public communications vary across jurisdictions and change over time. Telegram's Terms of Service are likewise subject to revision. It is your responsibility to verify that your use of this software complies with the laws of your country and with Telegram's current Terms of Service before running it. The authors accept no liability for uses that fall outside lawful research and analysis.

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

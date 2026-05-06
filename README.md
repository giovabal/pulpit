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

The analytical layer is built on established methods from network science: [PageRank](docs/network-measures.md#pagerank), [Burt's structural holes](docs/network-measures.md#burts-constraint), [Leiden community detection](docs/community-detection.md#leiden), [Infomap echo-chamber detection](docs/community-detection.md#infomap), [SIR spreading simulation](docs/network-measures.md#spreading-efficiency), and more — applied to the specific dynamics of Telegram forwarding networks. See the [changelog](CHANGELOG.md) for recent additions.

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
- Which channels bridge ideologically separate communities — the only link between two groups that otherwise share no direct contact? *([Betweenness](docs/network-measures.md#betweenness-centrality), [Burt's Constraint](docs/network-measures.md#burts-constraint), [Bridging Centrality](docs/network-measures.md#bridging-centrality))*
- Whose content spreads farthest per post published, despite a modest following? *([Amplification Factor](docs/network-measures.md#amplification-factor))*
- If a channel started spreading a piece of false information, what fraction of the network would eventually receive it? *([Spreading Efficiency](docs/network-measures.md#spreading-efficiency))*

**About communities:**

- How does the network cluster when the citation data decides the boundaries — not your own labels? *([Leiden](docs/community-detection.md#leiden), [Louvain](docs/community-detection.md#louvain), [Infomap](docs/community-detection.md#infomap), [MCL](docs/community-detection.md#mcl-markov-clustering), and more)*
- Which channels form a genuine echo chamber — where content circulates in a closed loop and almost never escapes? *([Infomap](docs/community-detection.md#infomap), [Strongly Connected Components](docs/community-detection.md#strongly-connected-components-strongcc))*
- Which community detection algorithms agree on a grouping, and which disagree? *([Consensus matrix](docs/community-detection.md#consensus-matrix))*
- How cohesive or competitive are the communities? How much do they interact? *([E-I Index, Modularity](docs/whole-network-statistics.md))*

**About change over time:**

- How did the network evolve year by year? Which channels rose, fell, or switched communities? *([Timeline export](docs/workflow.md#timeline-see-how-the-network-changed-over-time))*
- How does the network today compare to a snapshot from six months ago? *([Network comparison](docs/workflow.md#compare-two-networks))*
- After a key channel went silent — removed, banned, or simply abandoned — who filled its structural role? *([Vacancy Analysis](docs/vacancy-analysis.md))*

---

## Quick start

```sh
git clone https://github.com/giovabal/pulpit
cd pulpit
sh setup.sh
# Edit .env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE_NUMBER
python manage.py migrate && python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000). The entire workflow runs from the browser from here. See [Getting started](docs/getting-started.md) for setup details, Telegram credential registration, and database configuration.

---

## How it works

A Pulpit research project runs in four steps, all accessible from the browser interface:

<figure>

![The four-step pipeline: search channels → crawl channels → structural analysis → compare analysis](webapp_engine/static/pipeline.jpg)

<figcaption><em>The four-step pipeline: search channels → crawl channels → structural analysis → compare analysis.</em></figcaption>
</figure>
<br>

1. **Find channels** — add keywords; Pulpit searches Telegram and populates a list of matching channels
2. **Organise** — assign channels to categories you define (by political orientation, country, funding source, or any grouping that fits your research); channels without a category are excluded from analysis
3. **Collect messages** — download messages from all organised channels; Pulpit records every forward and every `t.me/` link, building a directed citation network
4. **Generate the map** — run community detection and layout algorithms; export an interactive map, sortable tables, and network exchange files

The core data model is a **directed, weighted citation graph**: a directed edge from channel A to channel B means A regularly amplifies B's content. Edge weight reflects how much of A's output references B relative to A's total publishing volume.

---

## What you get

After export, the output directory contains self-contained files that can be shared without an internet connection. Multiple named exports can coexist — each is written atomically, so an interrupted run never corrupts a previous result.

| Output | What it is |
| :----- | :--------- |
| **Interactive 2D graph** (`graph.html`) | Search, filter by community, resize nodes by any measure, click for channel detail. Switch between ForceAtlas2, Spectral, Spring, and Circular layouts with animated transitions — no re-export required. [more](docs/export-formats.md#graphhtml--2d-interactive-graph) |
| **Interactive 3D graph** (`graph3d.html`) | Three.js, rotate/zoom/inspect; multiple themes and coloured-edge toggle [more](docs/export-formats.md#graph3dhtml--3d-interactive-graph) |
| **Channel table** (`channel_table.html/.xlsx`) | One row per channel with all 15 computed measures, sortable; per-year sparklines when a timeline was exported [more](docs/export-formats.md#channel_tablehtml--xlsx--per-channel-metrics) |
| **Network statistics table** (`network_table.html/.xlsx`) | Whole-ecosystem metrics, measure comparison scatter plot, NMI partition agreement matrix [more](docs/export-formats.md#network_tablehtml--xlsx--whole-network-statistics) |
| **Community table** (`community_table.html/.xlsx`) | Per-community metrics for each detection strategy; Organisation × community cross-tabulation [more](docs/export-formats.md#community_tablehtml--xlsx--per-community-metrics) |
| **Structural similarity matrix** (`structural_similarity.html`) | Pairwise cosine similarity between all channels across all computed measures, sortable by community or by measure [more](docs/export-formats.md) |
| **Consensus matrix** (`consensus_matrix.html`) | Agreement heatmap: how consistently each pair of channels is co-assigned across all detection strategies [more](docs/community-detection.md#consensus-matrix) |
| **Vacancy Analysis** (`vacancy_analysis.html`) | Replacement candidates ranked by six algorithms after a channel goes silent [more](docs/vacancy-analysis.md) |
| **Timeline animation** | Step through annual snapshots with animated node transitions in both the 2D and 3D graphs [more](docs/workflow.md#timeline-see-how-the-network-changed-over-time) |
| **Network comparison** (`network_compare_table.html`) | Side-by-side comparison of two exports: which channels gained or lost influence [more](docs/workflow.md#compare-two-networks) |
| **GEXF and GraphML** | For Gephi, Cytoscape, R/igraph, and any graph-analysis tool [more](docs/export-formats.md#networkgexf--networkgraphml--network-exchange-formats) |

---

## Network measures — 16 per channel

Each channel receives a score for up to 16 measures. All can be used to size nodes in the graph viewer, making the most significant channels visually prominent. Measures are grouped below by the type of question they answer.

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
| [Betweenness centrality](docs/network-measures.md#betweenness-centrality) | Channels sitting on the shortest paths between sub-networks — the brokers |
| [Flow betweenness](docs/network-measures.md#flow-betweenness) | Random-walk brokers that geodesic betweenness misses (Newman 2005) |
| [Harmonic centrality](docs/network-measures.md#harmonic-centrality) | Channels best-positioned to reach the entire network in the fewest hops |
| [Closeness centrality](docs/network-measures.md#closeness-centrality) | Channels most easily reached from the rest of the network — high incoming accessibility |
| [Katz centrality](docs/network-measures.md#katz-centrality) | Deeply embedded nodes reachable through many indirect paths |
| [Burt's constraint](docs/network-measures.md#burts-constraint) | Structural hole brokers — the only bridges between otherwise disconnected groups |
| [Ego network density](docs/network-measures.md#ego-network-density) | How deeply a channel is embedded in an echo-chamber clique vs. how much it bridges isolated sources |
| [Bridging centrality](docs/network-measures.md#bridging-centrality) | Channels that are both structurally central AND bridge genuinely distinct communities |

**Content and dynamics**

| Measure | What it surfaces |
| :------ | :--------------- |
| [Content originality](docs/network-measures.md#content-originality) | Producers vs. redistributors — 1 minus the fraction of forwarded messages |
| [Spreading efficiency](docs/network-measures.md#spreading-efficiency) | Fraction of the network reached if this channel seeds a rumour (Monte Carlo SIR simulation) |

See [Network measures](docs/network-measures.md) for academic references and worked examples for each measure.

---

## Community detection — 13 algorithms

Pulpit runs up to 13 community detection algorithms simultaneously. Each reveals a different structural layer of the same data; comparing them shows which groupings are robust and which are algorithm-dependent.

| Algorithm | What it finds | Direction-aware? |
| :-------- | :------------ | :--------------- |
| [Organisation](docs/community-detection.md#organisation) | Your own domain-knowledge categories as a baseline | — |
| [Leiden](docs/community-detection.md#leiden) | General community structure from citation density | No |
| [Leiden Directed](docs/community-detection.md#leiden-directed) | Same, but the directed null model respects who cites whom | Yes |
| [Leiden CPM coarse](docs/community-detection.md#leiden-cpm-coarse-and-fine) | Few, large communities — even weak citation ties bind | No |
| [Leiden CPM fine](docs/community-detection.md#leiden-cpm-coarse-and-fine) | More, smaller communities — only dense mutual citation | No |
| [Louvain](docs/community-detection.md#louvain) | Modularity maximisation — fast, widely used baseline | No |
| [Infomap](docs/community-detection.md#infomap) | Echo chambers: communities where information circulates in closed loops | Yes |
| [Memory Infomap](docs/community-detection.md#memory-infomap-second-order) | Second-order Infomap: path-dependent flow traps invisible to first-order methods | Yes |
| [MCL](docs/community-detection.md#mcl-markov-clustering) | Flow-based communities: channels bound by shared circulation patterns | Yes |
| [Walktrap](docs/community-detection.md#walktrap) | Proximity by shared neighbourhood — also produces a full dendrogram | No |
| [K-core](docs/community-detection.md#k-core) | Onion-layer peeling from the tight nucleus to the peripheral amplifiers | No |
| [Weakly connected](docs/community-detection.md#weakly-connected-components-weakcc) | Structurally isolated sub-ecosystems with no cross-referencing links | No |
| [Strongly connected](docs/community-detection.md#strongly-connected-components-strongcc) | Mutually reinforcing circular cores — coordinated circular amplification | Yes |

The **Organisation × community cross-tabulation** in every strategy section shows how your manual categories map onto the algorithm's output — confirming agreement or surfacing unexpected internal splits. The **consensus matrix** aggregates all non-Organisation strategies into a single heatmap: pairs with large red circles are co-assigned by every algorithm, making their grouping robust independent of method choice.

See [Community detection](docs/community-detection.md) for descriptions, references, and a strategy selection guide.

---

## Vacancy analysis

When a channel goes silent — removed from Telegram, legally forced offline, or simply abandoned — it leaves a structural hole in the network. Channels that used to rely on it as a source now need to find an alternative. Pulpit's Vacancy Analysis answers: *who fills that structural role?*

An analyst registers a channel as a vacancy with a closure date. Pulpit then identifies the **orphaned amplifiers** — channels that forwarded from the vacancy before it closed — and ranks replacement candidates by six complementary scores:

| Score | Question | Method |
| :---- | :------- | :----- |
| Amplifier Jaccard | What fraction of orphaned amplifiers have started forwarding the candidate? | Direct count |
| Structural equivalence | Does the candidate occupy the same position — same inputs, same amplifiers? | Cosine similarity (Lorrain & White 1971) |
| Brokerage role | Does the candidate bridge the same organisational communities? | Jaccard (Gould & Fernandez 1989) |
| Cascade overlap | Does information seeded at the candidate reach the same downstream channels? | SIR simulation (Watts & Dodds 2007) |
| Personalized PageRank | How deeply embedded is the candidate in the orphaned channels' content supply chain? | PPR on reversed graph (Haveliwala 2002) |
| Temporal adoption | How quickly and broadly did the orphaned channels adopt the candidate? | Coverage × recency decay |

The six scores span two analytical perspectives: A–C characterise structural position topologically; D–F characterise dynamics and timing. A channel scoring high on all six is a strong structural heir. A channel scoring high only on D–F was already well-positioned in the broader diffusion network but does not mirror the vacancy's immediate neighbourhood — a lateral successor rather than a direct replacement.

See [Vacancy analysis](docs/vacancy-analysis.md) for academic grounding, score interpretation patterns, and the batch export API.

---

## Technical foundation

**Crawling.** The official Telegram API (via [Telethon](https://github.com/LonamiWebs/Telethon)) downloads messages from the channels you select. For each message, Pulpit records forwards (which channel's content was reposted) and inline `t.me/` references (links to other channels). The result is a directed, weighted graph. Edge weight is computed as the number of forwards and references from A to B divided by the number of A's messages that contain any outward reference — not A's total message count — so channels that mostly publish original content and channels that are mostly aggregators are treated symmetrically.

**Analysis.** The graph is analysed with [NetworkX](https://networkx.org/). Node-level measures rank channels by influence, reach, or structural importance. Community detection algorithms identify clusters. Whole-network statistics — density, reciprocity, algebraic connectivity (Fiedler 1973), E-I index (Krackhardt & Stern 1988), global efficiency (Latora & Marchiori 2001), and more — characterise the ecosystem as a system. The NMI matrix (Kvalseth 1987) quantifies how much two community partitions agree, independently of community labels.

**Layout and visualisation.** Nodes are placed using [ForceAtlas2](https://github.com/bhargavchippada/forceatlas2) seeded from a Kamada-Kawai initial layout, improving reproducibility across re-exports. Alternative spatial layouts (Spectral, Spring, Circular) are pre-computed at export time and selectable at viewing time with smooth animated transitions. The 2D graph is a self-contained HTML file powered by [Sigma.js](http://sigmajs.org/). The optional 3D graph uses [Three.js](https://threejs.org/) with Lambert-shaded spheres and full mouse rotation, zoom, and pan.

**Storage and access control.** Data is stored in SQLite by default — a single file, no database server required. PostgreSQL, MySQL/MariaDB, and Oracle are supported for multi-user deployments. The browser interface supports three access modes: fully open (personal use on your own machine), semi-protected (public channel browser, restricted operations panel), and fully protected (login required for all pages).

**CLI access.** Every operation is also available as a management command for scripting, scheduling, and automation. See the [Workflow](docs/workflow.md#advanced-running-from-the-command-line) documentation for the full command reference.

---

## Documentation

| File | Contents |
| :--- | :------- |
| [Getting started](docs/getting-started.md) | Requirements, installation, Telegram credentials, database setup, access control — written for readers with no prior programming experience |
| [Workflow](docs/workflow.md) | Step-by-step guide: search → organise → crawl → export; all CLI options |
| [Network measures](docs/network-measures.md) | All 15 per-channel measures with academic references and worked examples |
| [Community detection](docs/community-detection.md) | 13 algorithms, consensus matrix, cross-strategy comparison, choosing a strategy |
| [Whole-network statistics](docs/whole-network-statistics.md) | Ecosystem-level metrics: density, reciprocity, clustering, Fiedler value, E-I index, NMI, and more |
| [Vacancy analysis](docs/vacancy-analysis.md) | Six algorithms for identifying structural replacement channels after a node disappears |
| [Web interface](docs/web-interface.md) | Browser UI: channel browser, channel detail pages, Operations panel, backoffice |
| [Export formats](docs/export-formats.md) | All output files: graphs, tables, GEXF, GraphML, atomic write safety |
| [Configuration](CONFIGURATION.md) | All `.env` settings |
| [Changelog](CHANGELOG.md) | Version history |

---

## Disclaimer

Pulpit is intended for academic research, investigative journalism, and analytical work on publicly accessible Telegram channels. It was written with the aim of complying with applicable laws and with [Telegram's Terms of Service](https://telegram.org/tos) as they stood at the time of development.

Laws governing data collection, storage, and analysis of public communications vary across jurisdictions and change over time. Telegram's Terms of Service are likewise subject to revision. It is your responsibility to verify that your use of this software complies with the laws of your country and with Telegram's current Terms of Service before running it. The authors accept no liability for uses that fall outside lawful research and analysis.

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

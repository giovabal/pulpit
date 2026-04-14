# Changelog

## [0.12] - To be announced

### New features
- Channel list: date range filter to show only channels active in a given period.

### Fixes
- `get_channels`: unresolvable PeerUser entities no longer print a full traceback; a clean warning is emitted instead.

## [0.11] - 2026-04-11
*Reworking commands options. Reworking tables presentation.*

### New features
- Channel detail page now includes a lazy-loaded **Domains & emails** panel listing all non-Telegram domains and email addresses found in the channel's messages, sorted by frequency.
- Channel detail page now includes a lazy-loaded **Channel connections** panel with two tables: channels mentioned by this channel (forwards sent + t.me references) and channels that mention it (forwards received + t.me references from interesting channels), each row linking to the internal page and to Telegram.
- Network Statistics table now includes a lazy-loaded **degree distribution** bar chart (bins of 10 links), switchable between forwards received and forwards sent.
- Network Comparison table now includes the same degree distribution chart showing both networks side by side, and power-law trend lines for each network in the measure comparison scatter plot.
- New `DEFAULT_CHANNEL_TYPES` `.env` option (comma-separated; default `CHANNEL`): sets which Telegram entity types are considered monitored throughout the app — used as the default for `get_channels --channel-types` and `export_network --channel-types`, and applied by `Channel.objects.interesting()` everywhere channels are filtered by monitoring status. Operations panel channel-type checkboxes reflect the setting on page load.
- `get_channels` now accepts `--channel-types` (same values and default as `export_network`).
- `get_channels --fix-missing-media`: after crawling, identifies photo and video messages whose media file is absent from disk or was never downloaded, and re-fetches them from Telegram. Available as a checkbox in the Operations panel.

### Improvements
- Generated HTML tables overhauled for scientific rigor: metric grouping with labeled sub-headers, normalization range annotations (e.g. "Density (0–1)"), interpretive tooltips on all column headers, em-dash for undefined values, `†` footnote symbol for WCC-only metrics, column reordering with group separators (Network position / Influence / Structural / Content / Communities), merged Activity column, rank column (#), 3 significant figures for continuous measures, diverging heatmap for Burt's Constraint, mean ± SD footer row, default sort by size in community table, External Fraction and Modularity Contribution columns in community table, table preambles populated from a new `data/meta.json` export artifact, and locale-aware thousands separators.
- Network Statistics and Network Comparison tables: added **Edges / Nodes** row after Edges in the whole-network metrics summary.
- Generated table pages footer now shows the Pulpit logo instead of plain text.
- `get_channels` now permanently marks unresolvable message references (deleted or invalid channels) with a dead flag so they are skipped on subsequent runs, avoiding redundant Telegram API calls. A new `--force-retry-unresolved-references` flag (and matching Operations panel checkbox) overrides this and retries all references including dead ones.

### Fixes
- `refresh_degrees` and `refresh_cited_degree` now filter citing channels through `Channel.objects.interesting()` so `DEFAULT_CHANNEL_TYPES` is respected when computing stored degree values.
- `MessageSearchView` and home-page message search now scope results via `Channel.objects.interesting()` (respects `DEFAULT_CHANNEL_TYPES`); `scripts/delete_unused_messages.py` uses the same manager for consistency.
- Channel detail message list now uses `select_related("forwarded_from")` instead of `prefetch_related`, eliminating a redundant query per page load.
- Reference resolver: M2M writes (`message.references.add`) are now deferred until after `missing_references` is persisted via `bulk_update`, closing the inconsistency window if the process is interrupted mid-batch.
- `export_network` table preambles now show a human-readable edge-weight description instead of the raw strategy key.

### Backward incompatibility
- Network comparison extracted into a dedicated `compare_networks` command; `export_network --compare` is removed. Run `python manage.py compare_networks /path/to/graph` (or use the new **Compare Networks** card in the Operations panel) after exporting to generate the side-by-side comparison page.
- `export_network --graph` renamed to `--2dgraph`; `--3d` renamed to `--3dgraph`. Update any scripts or aliases accordingly.
- `export_network` output is now fully opt-in: `--no-graph` and `--no-html` are replaced by `--2dgraph` and `--html`. Running `export_network` with no flags only writes the data JSON files; add `--2dgraph` and/or `--html` to generate the interactive graph and HTML tables.
- `FETCH_RECOMMENDED_CHANNELS` `.env` option removed; use `get_channels --fetch-recommended-channels` instead.
- `FA2_ITERATIONS` and `LAYOUT` `.env` options removed; use `export_network --fa2-iterations N` and `export_network --vertical-layout` instead.
- `NETWORK_MEASURES`, `COMMUNITY_STRATEGIES`, `EDGE_WEIGHT_STRATEGY`, `RECENCY_WEIGHTS`, `SPREADING_RUNS`, `DRAW_DEAD_LEAVES`, and `CHANNEL_TYPES` `.env` options removed; pass them as `export_network` flags instead. Defaults are unchanged: `--measures PAGERANK`, `--community-strategies ORGANIZATION`, `--edge-weight-strategy PARTIAL_REFERENCES`, `--channel-types CHANNEL`; `--recency-weights`, `--spreading-runs`, and `--draw-dead-leaves` are opt-in.

## [0.10] - 2026-04-07
*Commands management. Access control. Multiple database support.*

### New features
- New **Operations panel** (`/operations/`) in the webapp for launching and monitoring management commands (`get_channels`, `search_channels`, `export_network`) directly from the browser. Each task runs as a background subprocess; live output streams into a terminal-style log panel with 1-second polling. Commands can be aborted via SIGTERM.
- New `WEB_ACCESS` setting with three modes: `ALL` (default, no auth required), `OPEN` (admin and operations require a staff account), `PROTECTED` (all pages require login; admin and operations require staff). Includes a login form styled consistently with the rest of the webapp. Staff accounts are managed through Django's user system (`python manage.py createsuperuser`).
- PostgreSQL, MySQL, MariaDB, and Oracle support via `DB_ENGINE` in `.env`. SQLite remains the default. Each backend requires its own driver installed separately (`psycopg2-binary`, `mysqlclient`, or `oracledb`). MySQL/MariaDB connections use `utf8mb4` charset.
- `export_network --graphml` writes `graph/network.graphml` with all computed measures and community assignments embedded as node attributes, compatible with R/igraph, NetworkX, yEd, and any GraphML-aware tool.

### Improvements
- Message options (sort / content-type filter) for the search bar.
- Channels page: organization filter select and 4-column grid layout.
- `get_channels` now mines the `about` field of all channels in the DB for `t.me/` links after the main crawl loop, fetching any referenced channels not yet in the database (zero extra API calls for already-known channels).
- `get_channels` optionally fetches Telegram-recommended channels for each interesting channel (`FETCH_RECOMMENDED_CHANNELS=True` in `.env`).
- Hardened SQLite concurrency.

### Fixes
- Graph: clicking a node no longer crashes when a neighbour channel has a null label (channels discovered but not yet crawled).
- Graph: profile pictures now served at the correct path (`media/channels/…`) matching the URL embedded in the data JSON.
- Graph: favicon added to 2D and 3D graph pages.


## [0.9] - 2026-04-05
*A logo. Refining measures and communities detection. New webapp navigation.*

### New features
- Project logo.
- Webapp navigation replaced with a top horizontal menu (Network / Channels / Data). The former sidebar is removed from all pages.
- A few screenshots added to documentation.
- New `NETWORK_MEASURES` option: `FLOWBETWEENNESS` (random-walk / current-flow betweenness centrality, Newman 2005).
- New `NETWORK_MEASURES` option: `SPREADING` (spreading efficiency). Runs a Monte Carlo SIR epidemic simulation with each node as the seed and reports the mean fraction of the network eventually infected. Number of runs controlled by `SPREADING_RUNS` (default 200).
- New `RECENCY_WEIGHTS` option (integer N or `None`, default `None`). When set, messages up to N days old carry full weight; older messages decay as `exp(−(age−N)/N)`. This surfaces channels that are currently active rather than historically prominent, and is compatible with all `EDGE_WEIGHT_STRATEGY` values.
- `export_network --gexf` writes `graph/network.gexf` with all computed measures (PageRank, betweenness, etc.), community assignments, and channel metadata embedded as node attributes, ready to open in Gephi or any GEXF-compatible tool.

### Improvements
- SQLite is now configured with WAL journal mode and `synchronous=NORMAL`, allowing concurrent readers during writes and improving performance under load.
- New `COMMUNITY_STRATEGIES` option: `LEIDEN_DIRECTED`. Uses the Leiden algorithm with a directed null model (Leicht & Newman 2008): the expected weight of an edge A→B is proportional to A's out-degree × B's in-degree rather than total degree squared.
- `LEIDEN` now symmetrizes the graph before community detection (consistent with `LOUVAIN`). Previously it passed a directed graph, making it functionally equivalent to `LEIDEN_DIRECTED`.
- `FA2_ITERATIONS` default reduced from 20,000 to 5,000.
- Documentation now has a new structure and a navigation menu.

### Backward incompatibility
- `export_network` option rework: `--table-format`, `--nograph`, and the previous `--3d` flag are replaced by four individual flags: `--3dgraph` (add 3D graph), `--xlsx` (add Excel output), `--2dgraph` (generate 2D graph), `--html` (generate HTML tables). Default output is data files only.

### Fixes
- Progress lines in the terminal are now truncated to fit the terminal width instead of wrapping.
- `--refresh-messages-stats` now downloads missing media for messages that were crawled before image or video download was enabled. Already-downloaded media is skipped.
- All summary counts and chart time series now consistently apply both the `organization__is_interesting` flag and the `CHANNEL_TYPES` filter. Previously, message counts, date range, forwards, and chart data were computed over all channels, ignoring both filters.


## [0.8] - 2026-03-28
*3D graph and network comparison. Fixes.*

### New features
- After each `get_channels` run, in-degree and out-degree are refreshed for all interesting channels. The citation degree is now also refreshed for non-interesting channels that are forwarded or mentioned (via `t.me/` links) by interesting ones — previously only channels reached via forwards were updated, and t.me/username references were missed. The field that receives the citation count is `in_degree` when `REVERSED_EDGES=True` (citations arrive as incoming graph edges) or `out_degree` when `REVERSED_EDGES=False` (citations leave as outgoing edges).
- New `EDGE_WEIGHT_STRATEGY` option controls how edge weights are computed from forward and citation counts. `NONE` = all edges have equal weight (unweighted graph); `TOTAL` = raw count of forwards + citations; `PARTIAL_MESSAGES` = raw count divided by the total number of messages posted by the channel; `PARTIAL_REFERENCES` = raw count divided by the number of messages that are either forwarded from another source or contain at least one citation (default).
- `export_network --3dgraph` generates `graph/graph3d.html`: a Three.js 3D graph alongside the regular 2D Sigma.js map. Supports mouse rotation, zoom, pan, and node click to inspect connections. ForceAtlas2 runs in 3D using the vectorised O(n²) back-end. Spheres are shaded with Lambert lighting for improved depth readability.
- `export_network --compare PROJECT_DIR` accepts the `graph/` output directory of a previous export (the one containing `index.html`) and produces a full side-by-side comparison:
  - The compare network's `data/`, graph files, `*_table.html`, and `*.xlsx` are copied into the current `graph/` directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, etc.). Internal links inside the copied HTML files are rewritten to their `_2` equivalents.
  - `graph/network_compare_table.html` is generated with a 3-column whole-network metrics table (Metric / This network / Compare network), a modularity-by-strategy comparison table, and interactive scatter plots with this network's nodes in blue and the compare network's nodes in red. A "Normalize axes [0–1] per network" toggle min-max scales each network's values independently, making size-dependent measures (degree, fans, message count) directly comparable across networks of different sizes.
  - `graph/index.html` gains a "Compare network" section listing all copied `_2` files and linking to the comparison page.

### Improvements
- `search_channels` now prints progress and results (was fully silent): each search term with found/new counts, and a summary on completion.
- `get_channels` and `export_network` now use colour to distinguish section headers (cyan) from step detail lines (plain), warnings (yellow), and final success (green).
- New `GRAPH_OUTPUT_DIR` option sets the directory where `export_network` writes all output files (default: `graph`). Relative paths are resolved from the project root. When the Django development server is running, the output is also served at `http://localhost:8000/graph/`, so a separate HTTP server is no longer needed for local preview.
- Various performance improvements across the backend and frontend.

### Fixes
- `telegram_location` was silently discarded on every crawl: the field was assigned from the Telegram API response but missing from `update_fields` in `set_more_channel_details`, so location data was never persisted.
- `has_been_pinned` was never updated by `--refresh-messages-stats`: the refresh path uses `QuerySet.update()`, which bypasses `Message.save()` where `has_been_pinned` is set. Messages that first became pinned after their initial crawl would show `pinned=True` after a refresh but `has_been_pinned=False`, losing the historical record once they were unpinned. The refresh now explicitly sets `has_been_pinned=True` when the Telegram API reports a message as currently pinned.
- A message that both forwards from channel B and contains a `t.me/B` link (common when editors include inline attribution) was counted in both `forwarded_counts` and `reference_counts` in the graph builder, doubling that edge's contribution to the weight. References to a channel that is already the `forwarded_from` source of the same message are now excluded from `reference_counts`.
- `refresh_degrees()` for interesting channels only counted forwards toward their in/out-degree totals, while `refresh_cited_degree()` for non-interesting channels counted both forwards and `t.me/` references. This made the same field mean different things depending on whether a channel was interesting. Both paths now count forwards and references, matching the edge construction in the graph builder.
- `refresh_degrees()` did not respect `REVERSED_EDGES`: it always stored "cited by" in `in_degree` and "cites" in `out_degree` regardless of the setting, while `refresh_cited_degree()` correctly swapped the two fields when `REVERSED_EDGES=False`. The two paths are now consistent.
- When `DRAW_DEAD_LEAVES=True` with `REVERSED_EDGES=False`, no dead leaves were ever drawn: `refresh_cited_degree()` stores citations in `out_degree` in that configuration, but the dead-leaves inclusion filter always checked `in_degree__gt=0`. The filter now checks the correct field for the active edge direction.
- Dead-leaf nodes with no citations in the active date window appeared as isolated ghost nodes when `DRAW_DEAD_LEAVES=True` was combined with `--startdate`/`--enddate`: they were selected based on their all-time cached degree rather than the date-filtered edge set. Dead leaves that end up with no edges after date filtering are now removed from the graph and the output tables.
- Amplification factor only counted forwards from channels with `is_interesting=True`, but when `DRAW_DEAD_LEAVES=True` the graph includes edges from dead-leaf channels, so a channel heavily forwarded by dead leaves showed low amplification while appearing well-connected in the graph. The measure now counts forwards from all channels present in the graph, keeping it consistent with the edge structure.


## [0.7] - 2026-03-23
*Widening the selection of whole-network measures. Adding more node measures and comparing them.*

### New features
- Three new node measures for political research, all available in `NETWORK_MEASURES` and included in `ALL`:
  - `BURTCONSTRAINT` — Burt's constraint (structural hole brokerage; low = cross-community broker)
  - `AMPLIFICATION` — forwards received from other channels / own message count
  - `CONTENTORIGINALITY` — 1 − (forwarded messages / total messages); measures how much a channel produces vs. redistributes
- `export_network --nograph` skips the graph mini-site (layout computation, `data.json`, media copy) and produces only the tabular output.
- `network_table.html` now includes WCC count, largest WCC fraction, SCC count, largest SCC fraction, the four directed degree assortativity coefficients (in→in, in→out, out→in, out→out), Freeman centralization for each configured network measure, and partition modularity per strategy.
- `community_table.html`: each strategy section now has a collapsible channel list showing all channels grouped by community. `community_table.xlsx` strategy sheets now include a Channels column.
- Whole-network metrics moved out of `community_table` into a dedicated `network_table.html` / `network_table.xlsx`; `community_table` now contains only per-community rows.
- `network_table.html` now features an interactive scatter plot where any two measures can be compared on log-log axes, with a power-law trend line. The pair of measures is selected dynamically via dropdowns.
- `export_network` now always generates `graph/index.html`: a landing page listing every available output file (map, channel table, network table, community table, XLSX downloads) with a short description of each and links to the relevant documentation sections. The page is generated regardless of `--nograph` or `--table-format`.

### Improvements
- Graph mini-site no longer depends on jQuery; all DOM interactions rewritten in vanilla JS.
- Stats charts (messages, views, forwards, subscribers, avg involvement) are now rendered client-side with Chart.js instead of Bokeh, using a filled line style better suited to time-series data. Django views return JSON; the browser draws the charts. Removes the `bokeh` dependency.
- Graph export data is now split into typed JSON files under `graph/data/`: `channels.json` (per-node metadata, measures, and community assignments), `channel_position.json` (spatial layout and edges), `communities.json` (strategy definitions and per-community metrics), `network_metrics.json` (whole-network metrics and modularity). The graph mini-site and all HTML tables read these files at load time rather than having data baked in at export time.
- All three HTML tables (`channel_table.html`, `network_table.html`, `community_table.html`) are now static shells that load and render data client-side from `graph/data/*.json`; the HTML files themselves never need to be regenerated — only the data files change between exports.
- Graph mini-site assets reorganised into subdirectories: `graph.html` (was `index.html`), `css/graph.css`, `css/tables.css`, `js/graph.js`, `js/tables_sort.js`, `js/channel_table.js`, `js/community_table.js`, `js/network_table.js`.

## [0.6] - 2026-03-21
*Tabular data for communities. Filtering out Telegram service messages.*

### New features
- New chart on the homepage and channel detail pages: **Average involvement per month** — shows the average views per message for each month, with 0 for months with no messages.
- `get_channels` now accepts `--fromid ID` to restrict crawling to channels whose database id is less than or equal to `ID`.
- `export_network` now generates `community_table.html` and `community_table.xlsx`: a whole-network structural summary (nodes, edges, density, reciprocity, average clustering coefficient, average shortest path length, diameter) followed by per-community metrics for each active detection strategy. The HTML table is sortable; the Excel file has a Network Summary sheet plus one sheet per strategy.
- Graph mini-site: **Data** button in the menu bar opens a dialog linking to `channel_table.html` and `community_table.html`.
- `PROJECT_TITLE` option sets a title shown in all output files.
- New options for `COMMUNITY_STRATEGIES`: `WEAKCC` (weakly connected components) and `STRONGCC` (strongly connected components).
- Sidebar channel list now has a live search input to filter channels by name.
- New **Search messages** page (`/search/`) with full-text search across all channels and paginated results.

### Improvements
- Graph mini-site redesigned.
- New `scripts/delete_unused_messages.py`: removes messages belonging to channels outside the active crawl scope; run before `VACUUM` to reclaim disk space.
- `COMMUNITIES_PALETTE` renamed `COMMUNITY_PALETTE` for consistency.
- Tabular export files renamed: `table.html` to `channel_table.html`, `table.xlsx` to `channel_table.xlsx`.
- Telegram service messages (inactivity notices, pin events, etc.) are no longer saved during crawling. Running `get_channels --refresh-messages-stats` will delete any already-stored service messages.
- `--table-format` option values renamed from `xls` / `html+xls` to `xlsx` / `html+xlsx` for consistency with the actual file extension.
- Improved semantic and accessibility for all HTML output.
- Improved appearance for all HTML table output.
- Organization admin list now shows and allows inline editing of the `is_interesting` flag.
- `get_channels` with `--refresh-messages-stats` now skips messages that were freshly crawled in the same run.

### Fixes
- `get_channels` with `--refresh-messages-stats` option was overwriting some of its own output.


## [0.5] - 2026-03-18
*Ability to update already-crawled messages. More reliable spatial layout.*

### New features
- Before applying ForceAtlas2 for spatial layout, Kamada-Kawai is now used to seed initial node positions, improving layout reproducibility across runs.
- New option for `NETWORK_MEASURES`: `KATZ` (Katz centrality).
- New option for `NETWORK_MEASURES`: `BRIDGING` (bridging centrality: betweenness × neighbour-community Shannon entropy). Accepts an optional community strategy parameter: `BRIDGING(LOUVAIN)`, `BRIDGING(LEIDEN)`, etc.
- New option for `NETWORK_MEASURES`: `ALL` (expands to all available measures).
- New option for `COMMUNITY_STRATEGIES`: `ALL` (runs all available detection algorithms simultaneously).
- New `--seo` flag for `export_network`: makes the output mini-site search-engine friendly (sets `index, follow` robots tags, writes a permissive `robots.txt`). Without the flag, the output actively discourages indexing. Meta descriptions are always written regardless of this flag.
- `get_channels` now accepts `--refresh-messages-stats` to update view counts, forward counts, and pinned status on already-crawled messages. Accepts an integer (refresh the N most recent messages per channel) or a date in `YYYY-MM-DD` format (refresh all messages from that date to the present). Omitting a value refreshes all messages.
- Graph mini-site: social sharing section added to the About dialog, with a copyable URL and direct share buttons for major platforms.
- Webapp channel detail page: collapsible, lazily loaded charts for message history, views, forwards sent, and forwards received per month; summary cards showing message count, total views, date range, forwards sent, and forwards received.
- Webapp stats page: summary cards for total channels, messages collected, total subscribers, date range, and total forwards; additional charts for forwards per month, views per month, and cumulative subscribers.
- Channel media type (photo, video, audio, document) is now recorded during crawling regardless of whether file download is enabled; undownloaded attachments are shown as placeholder frames in the channel detail view.

### Improvements
- `COMMUNITIES_STRATEGY` renamed `COMMUNITY_STRATEGIES` for grammatical consistency.
- Channel metadata (subscriber count, about text, location) is now persisted immediately when fetched, rather than only at the end of the crawl; location is refreshed on every run.
- `is_lost` flag is cleared automatically when a previously unreachable channel is successfully crawled again.
- Webapp interface redesigned with a clean light theme, Inter font, semantic HTML, and refined card and sidebar components.
- Graph mini-site About dialog now links to `ANALYSIS.md` on GitHub for measure and strategy documentation, replacing inline explanatory text.


## [0.4] - 2026-03-15
*Reworking graph mini-site. Tabular output added.*

### New features
- Project name changed from `TNExp` to `Pulpit`.
- New option for `COMMUNITIES_STRATEGY`: `LEIDEN`.
- New option for `NETWORK_MEASURES`: `OUTDEGCENTRALITY`.
- New option for `NETWORK_MEASURES`: `HARMONICCENTRALITY`.
- `CHANNEL_TYPES` option allows to define which kind of channels you want to explore.
- `search_channels` command now accepts `--amount` option to limit how many search terms are processed per run.
- `export_network` command now accepts `--startdate` and `--enddate` options to operate on limited time windows.
- `export_network` command now produces tabular output alongside the graph mini-site.

### Improvements
- Improved resilience against internet connection fails during crawling.
- Expanded documentation.
- Graph mini-site has a simpler file structure.
- Graph mini-site upgraded to Bootstrap 5.3, jQuery 4.0 and Sigma 3.0.
- Graph mini-site moved from Font Awesome to Bootstrap Icons.
- Graph mini-site using CDNs instead of local libraries.


## [0.3.1] - 2026-03-08
### Fixes
- `KCORE` communities are now following their natural order, starting from the innermost core.


## [0.3] - 2026-03-08
*Improving network measures.*

### New features
- Multiple community strategies can be applied simultaneously via `COMMUNITIES_STRATEGY`.
- HITS Hub, HITS Authority, Betweenness Centrality, and In-degree Centrality network measures added to graph export and node detail panel.
- `NETWORK_MEASURES` option controls which measures are calculated and exported. Default is `PAGERANK`.
- About dialog in the graph mini-site: shows a description of Pulpit, a link to the GitHub repository, graph statistics, and explanatory text for all computed measures and active community strategies.
- Labels visibility option in the graph Options panel: Always, On size (default), or Never.
- Clicking a channel name in the connections list (inbound, outbound, or mutual) navigates to that channel's detail and highlights its network.

### Improvements
- Channels that resolve to user accounts are now flagged and skipped during crawling and graph export.
- Channel `about` field is now included in admin search.
- Isolated nodes are grouped into a single community in Louvain and Infomap strategies.
- `KCORE` community strategy now produces finer-grained results using k-shell decomposition.
- The local web server no longer breaks when `export_network` is re-run.
- `export_network` produces a leaner graph mini-site with unused assets removed.
- `export_network` now prints step-by-step progress so you can follow what is happening.
- Graph mini-site upgraded to Bootstrap 5.
- Node detail panel shows only the measures that were actually computed for the current export.

### Backward incompatibility
- IE is no longer supported in graph mini-site.


## [0.2] - 2026-03-03
*Optimizing crawling.*

### New features
- Stats page showing month-by-month global channel activity.
- `get_channels` gained a `--fixholes` option to detect and fill gaps in message history.

### Improvements
- `get_channels` output is more detailed and informative.
- `get_channels` now resolves previously unresolved channel references.
- Profile pictures are downloaded only once.
- `FloodWaitError` handling in the crawler is more robust.


## [0.1.2] - 2026-03-02
### Fixes
- Direct channel references in messages are now correctly processed.


## [0.1.1] - 2026-02-23
### Fixes
- The measure selection menu now works correctly.


## [0.1] - 2026-02-21
*First official release of Pulpit.*

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Workflow](WORKFLOW.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

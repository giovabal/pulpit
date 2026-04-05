# Configuration

Pulpit is configured through a `.env` file in the project root. Copy `env.example` as a starting point and fill in at least the three Telegram credentials before running any management command. All other settings have defaults that work for a first run; refer to the sections below when you want to change how channels are crawled, how the graph is weighted, or how communities are detected and coloured.

All options go in `.env`. Copy `env.example` as a starting point.

## Telegram

| Option | Description | Default |
| :----- | :---------- | ------: |
| `TELEGRAM_API_ID` | API ID from Telegram | **required** |
| `TELEGRAM_API_HASH` | API hash from Telegram | **required** |
| `TELEGRAM_PHONE_NUMBER` | Phone number linked to your Telegram account | **required** |
| `TELEGRAM_CRAWLER_GRACE_TIME` | Seconds to wait between API requests | `1` |
| `TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL` | Max messages to fetch per channel per run. Set to `None` to fetch all messages with no limit. | `100` |
| `TELEGRAM_CRAWLER_DOWNLOAD_IMAGES` | Download images attached to messages | `False` |
| `TELEGRAM_CRAWLER_DOWNLOAD_VIDEO` | Download videos attached to messages | `False` |
| `TELEGRAM_CONNECTION_RETRIES` | How many times Telethon retries a failed connection before giving up | `10` |
| `TELEGRAM_RETRY_DELAY` | Seconds to wait between connection retry attempts | `5` |
| `TELEGRAM_FLOOD_SLEEP_THRESHOLD` | Telethon automatically sleeps through flood-wait errors shorter than this value (seconds); errors longer than this are raised as exceptions instead | `60` |

> **Note on message statistics:** view counts, forward counts, and pinned status are recorded when a message is first crawled and are not automatically updated on subsequent runs. Use `--refresh-messages-stats` to re-fetch and update these fields: omit a value to refresh all messages, pass an integer N to refresh the N most recent messages per channel, or pass a date (`YYYY-MM-DD`) to refresh all messages from that date to the present. The `_updated` timestamp on each refreshed message is set to the time of the refresh.

## Project

| Option | Description | Default |
| :----- | :---------- | ------: |
| `PROJECT_TITLE` | Project name used in the `<title>` tag of all HTML files produced by `export_network` (`graph.html`, `channel_table.html`, `network_table.html`, `community_table.html`) | `Pulpit project` |
| `GRAPH_OUTPUT_DIR` | Directory where `export_network` writes all output files. Relative paths are resolved from the project root. When the Django development server is running, the output is also served at `http://localhost:8000/graph/` regardless of this setting. | `graph` |
| `WEB_ACCESS` | Access control for the web interface. `ALL` — no login required anywhere (default, suitable for local use). `OPEN` — all pages are public except `/admin/` and `/operations/`, which require a staff account. `PROTECTED` — all pages require login; `/admin/` and `/operations/` additionally require a staff account. Staff accounts are Django users with `is_staff = True`, created via `python manage.py createsuperuser` or in the admin. | `ALL` |

> **User accounts:** `WEB_ACCESS=ALL` requires no accounts. For `OPEN` or `PROTECTED`, create a staff account first with `python manage.py createsuperuser`. Staff accounts (`is_staff=True`) can reach `/admin/` and `/operations/`; regular accounts can reach everything else in `PROTECTED` mode but are blocked from admin and operations. The login form is always served at `/login/` regardless of mode. After logging in, a **Log out** button appears in the top navigation bar next to the user's name; the **Admin** button is shown only to staff.

## Graph layout

| Option | Description | Default |
| :----- | :---------- | ------: |
| `FA2_ITERATIONS` | Number of ForceAtlas2 iterations | `5000` |
| `LAYOUT` | Desired graph orientation: `HORIZONTAL` or `VERTICAL`. When the computed layout's aspect ratio does not match, the graph is automatically rotated 90°. | `HORIZONTAL` |

## Network analysis

| Option | Description | Default |
| :----- | :---------- | ------: |
| `REVERSED_EDGES` | When `True`, a forward of Y's content by X produces a Y → X edge (i.e. influence flows toward the source) | `True` |
| `EDGE_WEIGHT_STRATEGY` | How edge weights are computed from forward and citation counts. `NONE` = all edges have equal weight (unweighted graph); `TOTAL` = raw count of forwards + citations; `PARTIAL_MESSAGES` = raw count divided by the total number of messages posted by the channel; `PARTIAL_REFERENCES` = raw count divided by the number of messages that are either forwarded from another source or contain at least one citation | `PARTIAL_REFERENCES` |
| `RECENCY_WEIGHTS` | Integer N or `None`. When set, messages up to N days old carry full weight (1.0); older messages decay as `exp(−(age−N)/N)`. At 2N days a message carries ~37% weight; at 3N days ~14%; at 5N days ~1%. Use this to surface channels that are currently active rather than historically prominent. Compatible with all `EDGE_WEIGHT_STRATEGY` values. | `None` |
| `SPREADING_RUNS` | Number of Monte Carlo SIR simulations per node for the `SPREADING` measure. Higher values reduce variance but scale linearly with runtime. | `200` |
| `NETWORK_MEASURES` | Comma-separated list of centrality measures to compute and expose in the graph. Available values: `PAGERANK` (PageRank), `HITSHUB` (HITS Hub score), `HITSAUTH` (HITS Authority score), `BETWEENNESS` (betweenness centrality), `FLOWBETWEENNESS` (random-walk betweenness — Newman 2005; symmetrises the graph and integrates over all paths, not just shortest ones; computed on the largest connected component), `INDEGCENTRALITY` (in-degree centrality), `OUTDEGCENTRALITY` (out-degree centrality), `HARMONICCENTRALITY` (harmonic centrality), `KATZ` (Katz centrality), `SPREADING` (SIR spreading efficiency — Monte Carlo; slow, controlled by `SPREADING_RUNS`), `BRIDGING` or `BRIDGING(STRATEGY)` (bridging centrality — requires community detection; the strategy in parentheses sets the community basis, defaulting to `LEIDEN` when omitted; the chosen strategy must also appear in `COMMUNITY_STRATEGIES`), `ALL` (all of the above, using `LEIDEN` as the BRIDGING community basis) | `PAGERANK` |
| `CHANNEL_TYPES` | Comma-separated list of Telegram entity types to include in the graph. `CHANNEL` = broadcast channels (admin-only posting); `GROUP` = supergroups and gigagroups (group chats); `USER` = user accounts and bots identified during crawling. | `CHANNEL` |

## Community detection

| Option | Description | Default |
| :----- | :---------- | ------: |
| `COMMUNITY_STRATEGIES` | Comma-separated list of community detection algorithms to apply: `ORGANIZATION` (uses the admin-defined organizations as communities), `LEIDEN` (Leiden modularity), `LEIDEN_DIRECTED` (Leiden with directed null model — Leicht & Newman 2008; recommended when citation direction is semantically meaningful), `LOUVAIN` (Louvain modularity), `KCORE` (k-shell decomposition), `INFOMAP` (information-flow-based clustering), `ALL` (all of the above). Multiple strategies can be selected simultaneously; the user can switch between them in the graph viewer. | `ORGANIZATION` |
| `COMMUNITY_PALETTE` | Color palette for communities. Use `ORGANIZATION` to take colors from the admin, or any palette name from [python-graph-gallery.com/color-palette-finder](https://python-graph-gallery.com/color-palette-finder/) (case-sensitive) | `ORGANIZATION` |

## Drawing

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DRAW_DEAD_LEAVES` | Include channels that are not marked as interesting but are referenced by interesting ones. These appear as leaf nodes — they add context but can significantly increase the graph size. | `False` |
| `DEAD_LEAVES_COLOR` | Color for dead-leaf nodes, in hex format | `#596a64` |

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Workflow](WORKFLOW.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

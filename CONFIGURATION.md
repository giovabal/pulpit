# Configuration

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

## Graph layout

| Option | Description | Default |
| :----- | :---------- | ------: |
| `FA2_ITERATIONS` | Number of ForceAtlas2 iterations | `20000` |
| `LAYOUT` | Desired graph orientation: `HORIZONTAL` or `VERTICAL`. When the computed layout's aspect ratio does not match, the graph is automatically rotated 90°. | `HORIZONTAL` |

## Network analysis

| Option | Description | Default |
| :----- | :---------- | ------: |
| `REVERSED_EDGES` | When `True`, a forward of Y's content by X produces a Y → X edge (i.e. influence flows toward the source) | `True` |
| `NETWORK_MEASURES` | Comma-separated list of centrality measures to compute and expose in the graph. Available values: `PAGERANK` (PageRank), `HITSHUB` (HITS Hub score), `HITSAUTH` (HITS Authority score), `BETWEENNESS` (betweenness centrality), `INDEGCENTRALITY` (in-degree centrality), `OUTDEGCENTRALITY` (out-degree centrality), `HARMONICCENTRALITY` (harmonic centrality), `KATZ` (Katz centrality), `BRIDGING` or `BRIDGING(STRATEGY)` (bridging centrality — requires community detection; the strategy in parentheses sets the community basis, defaulting to `LEIDEN` when omitted; the chosen strategy must also appear in `COMMUNITY_STRATEGIES`), `ALL` (all of the above, using `LEIDEN` as the BRIDGING community basis) | `PAGERANK` |
| `CHANNEL_TYPES` | Comma-separated list of Telegram entity types to include in the graph. `CHANNEL` = broadcast channels (admin-only posting); `GROUP` = supergroups and gigagroups (group chats); `USER` = user accounts and bots identified during crawling. | `CHANNEL` |

## Community detection

| Option | Description | Default |
| :----- | :---------- | ------: |
| `COMMUNITY_STRATEGIES` | Comma-separated list of community detection algorithms to apply: `ORGANIZATION` (uses the admin-defined organizations as communities), `LEIDEN` (Leiden modularity), `LOUVAIN` (Louvain modularity), `KCORE` (k-shell decomposition), `INFOMAP` (information-flow-based clustering), `ALL` (all of the above). Multiple strategies can be selected simultaneously; the user can switch between them in the graph viewer. | `ORGANIZATION` |
| `COMMUNITY_PALETTE` | Color palette for communities. Use `ORGANIZATION` to take colors from the admin, or any palette name from [python-graph-gallery.com/color-palette-finder](https://python-graph-gallery.com/color-palette-finder/) (case-sensitive) | `ORGANIZATION` |

## Drawing

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DRAW_DEAD_LEAVES` | Include channels that are not marked as interesting but are referenced by interesting ones. These appear as leaf nodes — they add context but can significantly increase the graph size. | `False` |
| `DEAD_LEAVES_COLOR` | Color for dead-leaf nodes, in hex format | `#596a64` |

---

← [README](README.md)

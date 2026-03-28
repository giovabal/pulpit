# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules

- **NEVER run `git add`, `git commit`, or `git push` unless the user explicitly says so in that message.** After finishing any code change — however large or small — stop completely. Do not commit. Do not push. Do not combine them with implementation in the same response. Wait for the user to send a separate message asking for a commit or push.
- Run `ruff check . --fix && ruff format .` before declaring any code change done.
- Smoke-test changes with a quick `python -c "..."` call where practical before finishing.

## Commands

```bash
# Setup
sh setup.sh                          # Create .venv and install dependencies

# Linting (run before committing)
ruff check . --fix && ruff format .

# Database and server
python manage.py migrate
python manage.py runserver           # Web UI at localhost:8000

# Crawling workflow
python manage.py search_channels             # Find channels via search terms (all terms)
python manage.py search_channels --amount N  # Limit to N search terms
python manage.py get_channels                # Crawl channels (add --fixholes to fill gaps)
python manage.py get_channels --fromid 42    # Only crawl channels with database id <= 42
python manage.py get_channels --refresh-messages-stats               # Also refresh views/forwards/pinned on all messages per channel
python manage.py get_channels --refresh-messages-stats 200           # Same but only the 200 most recent per channel
python manage.py get_channels --refresh-messages-stats 2024-01-01    # Same but only messages from that date to present
python manage.py export_network              # default: 2D graph + HTML tables
python manage.py export_network --seo        # same but mini-site is search-engine friendly
python manage.py export_network --3d         # also produce 3D graph
python manage.py export_network --xlsx       # also produce Excel spreadsheets
python manage.py export_network --no-html    # skip HTML tables
python manage.py export_network --no-graph   # skip graph (tables only)

# View graph (from repo root)
cd graph && python -m http.server 8001
# Open http://localhost:8001/
```

## Architecture

**Pulpit** crawls Telegram channels, analyzes their network relationships, and generates an interactive force-directed graph visualization.

### Data flow

1. User adds `SearchTerm` entries in Django admin
2. `search_channels` management command finds channels via Telegram API and creates `Channel` records
3. User assigns channels to `Organization` objects and marks them `is_interesting=True` in admin
4. `get_channels` command uses `TelegramCrawler` to fetch messages and resolve references between channels
5. `export_network` command builds the graph, applies community detection, runs the spatial layout, and writes output to `graph/`

### Key modules

- **`network/layout.py`** — Spatial layout pipeline: Kamada-Kawai seeds initial positions, then `pyforceatlas2` runs ForceAtlas2. Two public functions (`kamada_kawai_positions`, `forceatlas2_positions`) plus a convenience wrapper `compute_layout`.
- **`network/exporter.py`** — Builds `GraphData` from the NetworkX graph; applies network measures (PageRank, HITS, betweenness, in-degree, out-degree, harmonic centrality); writes `graph/data.json` and the accessory config file; writes `graph/channel_table.html` / `graph/channel_table.xlsx` (one row per channel), `graph/network_table.html` / `graph/network_table.xlsx` (whole-network structural metrics), and `graph/community_table.html` / `graph/community_table.xlsx` (structural metrics per community, one table/sheet per strategy).
- **`network/community.py`** — Community detection strategies: ORGANIZATION, LOUVAIN, LEIDEN, KCORE, INFOMAP, WEAKCC, STRONGCC.
- **`network/graph_builder.py`** — Builds the NetworkX `DiGraph` from Django ORM objects.
- **`network/management/commands/export_network.py`** — Orchestrates the full export: validates settings, builds graph, runs community detection, runs layout, applies measures, writes output files and optional tables (channel_table, network_table, and community_table, HTML/XLSX).
- **`webapp/crawler.py`** (`TelegramCrawler`) — Telethon-based Telegram API client. Handles rate limiting, flood-wait errors, message hole detection, and media downloads.
- **`webapp/models/`** — `Channel`, `Message` (with `references` ManyToMany back to Channel), `Organization`, `SearchTerm`, and media models.

### Network measures

Configured via `NETWORK_MEASURES` in `.env` (comma-separated). Valid values:

| Key | Description |
| :-- | :---------- |
| `PAGERANK` | PageRank score (default) |
| `HITSHUB` | HITS hub score |
| `HITSAUTH` | HITS authority score |
| `BETWEENNESS` | Betweenness centrality |
| `INDEGCENTRALITY` | Normalized in-degree centrality |
| `OUTDEGCENTRALITY` | Normalized out-degree centrality |
| `HARMONICCENTRALITY` | Normalized harmonic centrality |
| `KATZ` | Katz centrality |
| `BRIDGING` or `BRIDGING(STRATEGY)` | Bridging centrality (betweenness × neighbour-community Shannon entropy); defaults to `LEIDEN` when no strategy is specified; the chosen strategy must also be in `COMMUNITY_STRATEGIES` |
| `BURTCONSTRAINT` | Burt's constraint (0–1); low = structural hole broker, high = embedded in dense clique; `null` for isolated nodes |
| `AMPLIFICATION` | Amplification factor = forwards received from interesting channels / own message count; respects `--startdate`/`--enddate` |
| `CONTENTORIGINALITY` | Content originality = 1 − (forwarded messages / total messages); `null` if no messages; respects `--startdate`/`--enddate` |
| `ALL` | Expand to all measures above; `BRIDGING` uses `LEIDEN` as community basis |

### Edge construction

Edges between channels are built from two sources:
- `Message.forwarded_from` — channel that was forwarded
- `Message.references` — channels mentioned via `t.me/[username]` regex

Edge weight = (forwards + references) / total channel messages. Direction is controlled by `REVERSED_EDGES` env var.

### Code style

- Python 3.12, line length 120, double quotes (see `ruff.toml`)
- `ruff` for both linting and formatting

### Configuration

All runtime options go in `.env` (copy from `env.example`). Required: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE_NUMBER`.

Key optional settings: `COMMUNITY_STRATEGIES` (default `ORGANIZATION`), `NETWORK_MEASURES` (default `PAGERANK`), `FA2_ITERATIONS` (default `20000`), `REVERSED_EDGES` (default `True`), `DRAW_DEAD_LEAVES` (default `False`).

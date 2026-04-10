# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules

- **NEVER run `git add`, `git commit`, or `git push` unless the user explicitly requests that exact operation in their message.** Each operation requires its own explicit instruction: "commit" authorises a commit only; "push" authorises a push only; "commit and push" authorises both. After finishing any code change — however large or small — stop completely. Do not commit. Do not push. Do not revert and push. Wait for the user to send a separate message.
- Run `ruff check . --fix && ruff format .` before declaring any code change done.
- Smoke-test changes with a quick `python -c "..."` call where practical before finishing.

## Commands

```bash
sh setup.sh                          # Create .venv and install dependencies
python manage.py migrate
python manage.py runserver           # Web UI at localhost:8000
python manage.py search_channels     # Find channels via search terms
python manage.py get_channels        # Crawl channels and resolve references
python manage.py export_network      # Build graph, detect communities, export
```

See WORKFLOW.md for all flags and options.

## Architecture

**Pulpit** crawls Telegram channels, analyzes their network relationships, and generates an interactive force-directed graph visualization.

### Data flow

1. User adds `SearchTerm` entries in Django admin
2. Operations panel (`/operations/`) or `search_channels` finds channels via Telegram API → `Channel` records
3. User assigns channels to `Organization` objects, marks `is_interesting=True`
4. Operations panel or `get_channels` fetches messages and resolves cross-channel references
5. Operations panel or `export_network` builds the graph, detects communities, runs layout, writes output to `graph/`

### Key modules

- **`crawler/channel_crawler.py`** (`ChannelCrawler`) — Core Telegram crawler: rate limiting, flood-wait handling, message fetching, reference resolution orchestration.
- **`crawler/client.py`** — `TelegramAPIClient` wrapper around Telethon.
- **`crawler/hole_fixer.py`** — Detects and fills gaps in per-channel message ID sequences.
- **`crawler/media_handler.py`** — Media download and storage.
- **`crawler/reference_resolver.py`** — Resolves `t.me/` references to `Channel` records.
- **`network/graph_builder.py`** — Builds the NetworkX `DiGraph` from Django ORM objects.
- **`network/measures.py`** — All centrality and influence measures; `apply_*` functions called from `export_network`.
- **`network/community.py`** — Community detection: ORGANIZATION, LOUVAIN, LEIDEN, LEIDEN_DIRECTED, KCORE, INFOMAP, WEAKCC, STRONGCC.
- **`network/layout.py`** — Spatial layout: Kamada-Kawai seed → ForceAtlas2 (`pyforceatlas2`).
- **`network/exporter.py`** — Builds `GraphData`; writes `graph/data.json` and config; GEXF export.
- **`network/tables.py`** — Writes channel, network, and community HTML/XLSX tables.
- **`network/management/commands/export_network.py`** — Orchestrates the full export pipeline.
- **`runner/tasks.py`** — Task manager for Operations panel: launch management commands as subprocesses, stream log output, track status (idle/running/done/failed), abort via SIGTERM.
- **`runner/views.py`** — Operations panel views: `OpsView`, `RunTaskView`, `AbortTaskView`, `TaskStatusView`.
- **`webapp_engine/middleware.py`** (`WebAccessMiddleware`) — Enforces `WEB_ACCESS` policy: `ALL` (no-op), `OPEN` (staff required for `/operations/`), `PROTECTED` (login required everywhere; staff required for `/operations/`). Django admin's own auth handles `/admin/` in non-`ALL` modes.
- **`webapp/context_processors.py`** — Exposes `WEB_ACCESS` to all templates.
- **`webapp/models/`** — `Channel`, `Message` (with `references` M2M back to `Channel`), `Organization`, `SearchTerm`, media models.

### Network measures

Configured via `NETWORK_MEASURES` in `.env` (comma-separated).

| Key | Description |
| :-- | :---------- |
| `PAGERANK` | PageRank score (default) |
| `HITSHUB` | HITS hub score |
| `HITSAUTH` | HITS authority score |
| `BETWEENNESS` | Betweenness centrality |
| `FLOWBETWEENNESS` | Random-walk (current-flow) betweenness — Newman 2005; graph symmetrised, computed on largest connected component |
| `INDEGCENTRALITY` | Normalized in-degree centrality |
| `OUTDEGCENTRALITY` | Normalized out-degree centrality |
| `HARMONICCENTRALITY` | Harmonic centrality |
| `KATZ` | Katz centrality |
| `BRIDGING` or `BRIDGING(STRATEGY)` | Betweenness × neighbour-community Shannon entropy; defaults to `LEIDEN`; strategy must also be in `COMMUNITY_STRATEGIES` |
| `BURTCONSTRAINT` | Burt's constraint (0–1); low = structural hole broker; `null` for isolated nodes |
| `AMPLIFICATION` | Forwards received from interesting channels / own message count |
| `CONTENTORIGINALITY` | 1 − (forwarded messages / total messages); `null` if no messages |
| `SPREADING` | SIR spreading efficiency — mean fraction infected when node seeds; Monte Carlo; runs set by `SPREADING_RUNS` (default 200) |
| `ALL` | All of the above; `BRIDGING` uses `LEIDEN` as community basis |

### Edge construction

- `Message.forwarded_from` — channel whose content was forwarded
- `Message.references` — channels mentioned via `t.me/[username]`

Edge weight = (forwards + references) / total messages from source channel. Direction controlled by `REVERSED_EDGES`.

### Code style

- Python 3.12, line length 120, double quotes (see `ruff.toml`)
- `ruff` for linting and formatting

### Configuration

All options in `.env` (copy from `env.example`). Required: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE_NUMBER`.

Key optional: `COMMUNITY_STRATEGIES` (default `ORGANIZATION`), `NETWORK_MEASURES` (default `PAGERANK`), `FA2_ITERATIONS` (default `5000`), `REVERSED_EDGES` (default `True`), `DRAW_DEAD_LEAVES` (default `False`), `SPREADING_RUNS` (default `200`).

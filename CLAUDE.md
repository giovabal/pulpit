# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
python manage.py get_channels        # Crawl channels (add --fixholes to fill gaps)
python manage.py export_network      # Generate graph JSON

# View graph (from repo root)
cd graph && python -m http.server 8001
# Open http://localhost:8001/telegram_graph/
```

## Architecture

**Pulpit** crawls Telegram channels, analyzes their network relationships, and generates an interactive force-directed graph visualization.

### Data flow

1. User adds `SearchTerm` entries in Django admin
2. `search_channels` management command finds channels via Telegram API and creates `Channel` records
3. User assigns channels to `Organization` objects and marks them `is_interesting=True` in admin
4. `get_channels` command uses `TelegramCrawler` to fetch messages and resolve references between channels
5. `export_network` command uses `RelationalGraph` to build the graph, apply community detection, run ForceAtlas2 layout, and write `graph/telegram_graph/data.json`

### Key modules

- **`webapp/crawler.py`** (`TelegramCrawler`) — Telethon-based Telegram API client. Handles rate limiting, flood-wait errors, message hole detection, and media downloads.
- **`webapp/relational_graph.py`** (`RelationalGraph`) — Builds a NetworkX graph from channels/messages. Applies ORGANIZATION/LOUVAIN/KCORE/INFOMAP community detection, ForceAtlas2 layout, and outputs JSON for the web visualization.
- **`webapp/models/`** — `Channel`, `Message` (with `references` ManyToMany back to Channel), `Organization`, `SearchTerm`, and media models.

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

Key optional settings: `COMMUNITIES_STRATEGY` (default `ORGANIZATION`), `NETWORK_MEASURES` (default `PAGERANK`), `FA2_ITERATIONS` (default `20000`), `REVERSED_EDGES` (default `True`), `DRAW_DEAD_LEAVES` (default `False`).

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
python manage.py crawl_channels        # Crawl channels and resolve references
python manage.py structural_analysis      # Build graph, detect communities, export
```

See WORKFLOW.md for all flags and options.

## Architecture

**Pulpit** crawls Telegram channels, analyzes their network relationships, and generates an interactive force-directed graph visualization.

### Data flow

1. User adds `SearchTerm` entries in Django admin
2. Operations panel (`/operations/`) or `search_channels` finds channels via Telegram API → `Channel` records
3. User assigns channels to `Organization` objects, marks `is_interesting=True`
4. Operations panel or `crawl_channels` fetches messages and resolves cross-channel references
5. Operations panel or `structural_analysis` builds the graph, detects communities, runs layout, writes output to `graph/`

### Key modules

- **`crawler/channel_crawler.py`** (`ChannelCrawler`) — Core Telegram crawler: rate limiting, flood-wait handling, message fetching, reference resolution orchestration.
- **`crawler/client.py`** — `TelegramAPIClient` wrapper around Telethon.
- **`crawler/hole_fixer.py`** — Detects and fills gaps in per-channel message ID sequences.
- **`crawler/media_handler.py`** — Media download and storage.
- **`crawler/reference_resolver.py`** — Resolves `t.me/` references to `Channel` records.
- **`network/graph_builder.py`** — Builds the NetworkX `DiGraph` from Django ORM objects.
- **`network/measures/`** — All centrality and influence measures; `apply_*` functions split across `_centrality.py`, `_content.py`, `_spreading.py`; registry in `_registry.py`.
- **`network/community.py`** — Community detection: ORGANIZATION, LOUVAIN, LABELPROPAGATION, LEIDEN, LEIDEN_DIRECTED, KCORE, INFOMAP, WEAKCC, STRONGCC.
- **`network/layout.py`** — Spatial layout: Kamada-Kawai seed → ForceAtlas2 (`pyforceatlas2`).
- **`network/exporter.py`** — Builds `GraphData`; writes `data/*.json`, config, and GEXF/GraphML exports.
- **`network/tables.py`** — Writes channel, network, and community HTML/XLSX tables.
- **`network/management/commands/structural_analysis.py`** — Orchestrates the full export pipeline. Writes atomically: all output goes to `exports/<name>.tmp/`, which is renamed to `exports/<name>/` only after `summary.json` is written as the final step. A stale `.tmp` directory from an interrupted run is removed at the start of the next export with the same name.
- **`runner/tasks.py`** — Task manager for Operations panel: launch management commands as subprocesses, stream log output, track status (idle/running/done/failed), abort via SIGTERM.
- **`runner/views.py`** — Operations panel views: `OpsView`, `RunTaskView`, `AbortTaskView`, `TaskStatusView`.
- **`backoffice/views.py`** — Staff-only section views for `/manage/`: Channels, Organizations, Groups, Search Terms, Events, Users, Vacancies.
- **`backoffice/api/views.py`** — DRF viewsets backing each section: `ChannelViewSet` (list/retrieve/update + bulk-assign), `OrganizationViewSet`, `ChannelGroupViewSet`, `SearchTermViewSet`, `EventTypeViewSet`, `EventViewSet`, `UserViewSet` (full CRUD; email = username), `MessageViewSet` (list/destroy with channel, forwarded-only, and text filters), `ChannelVacancyViewSet` (full CRUD).
- **`backoffice/api/serializers.py`** — Serializers for all backoffice viewsets.
- **`backoffice/api/permissions.py`** (`BackofficePermission`) — Allows all requests when `WEB_ACCESS=ALL`; requires `is_staff` otherwise.
- **`webapp_engine/middleware.py`** (`WebAccessMiddleware`) — Enforces `WEB_ACCESS` policy: `ALL` (no-op), `OPEN` (staff required for `/operations/` and `/manage/`), `PROTECTED` (login required everywhere; staff required for `/operations/` and `/manage/`). Django admin's own auth handles `/admin/` in non-`ALL` modes.
- **`webapp/context_processors.py`** — Exposes `WEB_ACCESS` to all templates.
- **`webapp/models/`** — `Channel`, `Message` (with `references` M2M back to `Channel`), `Organization`, `SearchTerm`, media models, `ChannelVacancy` (channel + closure_date + note; one per channel).
- **`webapp/views.py`** (`VacanciesView`) — `/channels/vacancies/` lists analyst-designated vacancy channels. `ChannelDetailView` passes the vacancy to the template so the Vacancy Analysis card is rendered. `VacancyAnalysisView` (`GET /channel/<pk>/vacancy-analysis/`) is the JSON endpoint that drives the card: it accepts `months_before`, `months_after`, and `only_after_vacancy` parameters, identifies orphaned amplifiers (interesting channels that forwarded from the vacancy in the before window), then scores replacement candidates using three academically grounded metrics — Jaccard amplifier similarity (Small 1973), structural equivalence cosine score (Lorrain & White 1971), and brokerage role Jaccard (Gould & Fernandez 1989). Results are returned sorted by first activity date and rendered in a client-side sortable table.
- **`events/models.py`** — `EventType` (name, description, hex color; default red) and `Event` (date, subject, FK to `EventType`). Both registered in Django admin.
- **`events/views.py`** (`EventsDataView`) — `GET /events/data/` returns all events as a JSON array `[{date, subject, action, color}, …]`.
- **`webapp/templates/webapp/index.html`** — `buildEventAnnotations(labels, events)` groups events by month and builds `chartjs-plugin-annotation` vertical-line annotations; `renderChart(canvas, data, events)` passes them to every Chart.js instance. Lines are dashed, colored by `EventType.color`; hovering shows a popup with date, action and subject.

### Network measures

Configured via `--measures` on `structural_analysis` (comma-separated).

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
| `CLOSENESS` | Closeness centrality (Wasserman-Faust); measures how easily the rest of the network can reach this channel |
| `KATZ` | Katz centrality |
| `BRIDGING` or `BRIDGING(STRATEGY)` | Betweenness × neighbour-community Shannon entropy; defaults to `LEIDEN`; strategy must also be in `--community-strategies` |
| `BURTCONSTRAINT` | Burt's constraint (0–1); low = structural hole broker; `null` for isolated nodes |
| `EGODENSITY` | Density of directed edges among immediate neighbours (predecessors ∪ successors, ego excluded); 0 = neighbours share no connections (hub between disconnected sources); 1 = fully connected clique (echo chamber); `null` for fewer than 2 neighbours |
| `LOCALCLUSTERING` | Directed local clustering coefficient (Fagiolo 2007); fraction of directed triangles through the node relative to all possible directed triads; 0 for nodes with total degree < 2 |
| `AMPLIFICATION` | Forwards received from interesting channels / own message count |
| `CONTENTORIGINALITY` | 1 − (forwarded messages / total messages); `null` if no messages |
| `DIFFUSIONLAG` | Average hours from original post date to forward date; `null` for channels with no dated forwards; low = early adopter, high = late amplifier |
| `SPREADING` | SIR spreading efficiency — mean fraction infected when node seeds; Monte Carlo; runs set by `--spreading-runs` (default 200) |
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

Key optional: `REVERSED_EDGES` (default `True`), `COMMUNITY_PALETTE` (default `ORGANIZATION`), `DEAD_LEAVES_COLOR` (default `#596a64`). Analysis options (measures, community strategies, edge weights, channel types, etc.) are command-line flags on `crawl_channels` and `structural_analysis`; see WORKFLOW.md.

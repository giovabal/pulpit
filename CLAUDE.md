# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules

- **NEVER run `git add`, `git commit`, or `git push` unless the user explicitly requests that exact operation in their message.** Each operation requires its own explicit instruction: "commit" authorises a commit only; "push" authorises a push only; "commit and push" authorises both. After finishing any code change — however large or small — stop completely. Do not commit. Do not push. Do not revert and push. Wait for the user to send a separate message.
- Run `ruff check . --fix && ruff format .` before declaring any code change done.
- Smoke-test changes with a quick `python -c "..."` call where practical before finishing.
- When you touch any first-party JavaScript (`webapp_engine/map/js/`, `backoffice/static/`, `webapp/static/`), run `npm run lint:js` (ESLint flat config in `eslint.config.mjs`; requires `npm install` once). Inline `<script>` JS in Django templates is not in scope of this linter.
- When you touch the static-export HTML files (`webapp_engine/map/*.html`), run `npm run lint:html` to catch accessibility regressions (requires `npm install` once). Django templates are not in scope of this linter.
- `npm run lint` runs both JS and HTML linters.

## Commands

```bash
sh setup.sh                          # Create .venv and install dependencies
python manage.py migrate
python manage.py runserver           # Web UI at localhost:8000
python manage.py search_channels     # Find channels via search terms
python manage.py crawl_channels        # Crawl channels and resolve references
python manage.py structural_analysis      # Build graph, detect communities, export
python manage.py purge_out_of_target_messages --dry-run   # Preview cleanup of out-of-target channels' messages + in-target channels' out-of-period messages
python manage.py purge_orphan_media --dry-run             # Preview cleanup of media files with no DB reference
```

See [docs/workflow.md](docs/workflow.md) for all flags and options.

## Architecture

**Pulpit** crawls Telegram channels, analyzes their network relationships, and generates an interactive force-directed graph visualization.

### Data flow

1. User adds `SearchTerm` entries in Django admin
2. Operations panel (`/operations/`) or `search_channels` finds channels via Telegram API → `Channel` records
3. User attributes channels to `Organization` objects over time via `ChannelAttribution` periods (the `/manage/` channel editor); a channel is *in-target* during any period whose organization has `is_in_target=True`
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
- **`network/robustness/`** — Robustness analysis package: `disparity_filter.py` (Serrano-Boguñá-Vespignani backbone extraction), `metrics.py` (attack curves, weighted R-index, critical threshold, weighted global efficiency), `attacks.py` (static + dynamic removal-order strategies), `null_model.py` (weight-rewiring null + z-score), `modular.py` (intra/inter community edge survival), `runner.py` (`run_robustness` orchestrator + `RobustnessConfig`). Output is a single JSON-serialisable dict written to `data/robustness.json`. Opt-in via `--robustness` on `structural_analysis`; `--robustness-alpha`/`-runs`/`-null`/`-dynamic`/`-seed`/`-sample` tune the run.
- **`network/management/commands/structural_analysis.py`** — Orchestrates the full export pipeline. Writes atomically: all output goes to `exports/<name>.tmp/`, which is renamed to `exports/<name>/` only after `summary.json` is written as the final step. A stale `.tmp` directory from an interrupted run is removed at the start of the next export with the same name.
- **`runner/tasks.py`** — Task manager for Operations panel: launch management commands as subprocesses, stream log output, track status (idle/running/done/failed), abort via SIGTERM.
- **`runner/views.py`** — Operations panel views: `OpsView`, `RunTaskView`, `AbortTaskView`, `TaskStatusView`.
- **`backoffice/views.py`** — Staff-only section views for `/manage/`: Channels, Organizations, Groups, Search Terms, Events, Users, Vacancies, Maintenance.
- **`backoffice/api/views.py`** — DRF viewsets backing each section: `ChannelViewSet` (list/retrieve/update; exposes read-only `current_organization_*` + nested `attributions`; `bulk-assign` replaces each selected channel's attribution timeline with one period), `ChannelAttributionViewSet` (full CRUD with overlap validation; `?channel=` filter — drives the per-channel periods editor), `OrganizationViewSet`, `ChannelGroupViewSet`, `SearchTermViewSet`, `EventTypeViewSet`, `EventViewSet`, `UserViewSet` (full CRUD; email = username), `MessageViewSet` (list/destroy with channel, forwarded-only, and text filters), `ChannelVacancyViewSet` (full CRUD).
- **`backoffice/api/maintenance.py`** — `GET /manage/api/maintenance/` returns engine, on-disk size, and the catalog of available strategies; `POST /manage/api/maintenance/optimize/` runs the selected strategies (default = all) sequentially, stopping at the first failure, and returns per-step timings plus size before/after. Supports SQLite (`ANALYZE`, `PRAGMA optimize`, `wal_checkpoint(TRUNCATE)`, `VACUUM`) and PostgreSQL (`ANALYZE`, `VACUUM ANALYZE`).
- **`backoffice/api/serializers.py`** — Serializers for all backoffice viewsets.
- **`backoffice/api/permissions.py`** (`BackofficePermission`) — Allows all requests when `WEB_ACCESS=ALL`; requires `is_staff` otherwise.
- **`webapp_engine/middleware.py`** (`WebAccessMiddleware`) — Enforces `WEB_ACCESS` policy: `ALL` (no-op), `OPEN` (staff required for `/operations/` and `/manage/`), `PROTECTED` (login required everywhere; staff required for `/operations/` and `/manage/`). Django admin's own auth handles `/admin/` in non-`ALL` modes.
- **`webapp/context_processors.py`** — Exposes `WEB_ACCESS` to all templates.
- **`webapp/models/`** — `Channel`, `Message` (with `references` M2M back to `Channel` and `grouped_id` for Telegram media-group albums), `Organization`, **`ChannelAttribution`** (the time-bounded channel→organization link: `channel` + `organization` + optional inclusive `start`/`end` dates, both `None` = open; non-overlapping per channel, enforced in `clean()`/serializer/admin), `SearchTerm`, media models, `ChannelVacancy` (channel + closure_date + note; one per channel). `Channel.in_target_periods` are the periods whose org is in-target; `Channel.current_organization`/`current_attribution` resolve the period active today (else most-recent-past) for display. There is no longer a `Channel.organization` FK or `out_of_target_after` field — both folded into `ChannelAttribution`. `Message` exposes `is_album`, `album_size`, and `album_pictures` / `album_videos` / `album_audios` / `album_stickers` / `album_other_media` that gather sibling media across messages sharing the same `(channel_id, grouped_id)`.
- **`webapp/views.py`** (`VacanciesView`) — `/channels/vacancies/` lists analyst-designated vacancy channels. `ChannelDetailView` passes the vacancy to the template so the Vacancy Analysis card is rendered. `VacancyAnalysisView` (`GET /channel/<pk>/vacancy-analysis/`) is the JSON endpoint that drives the card: it accepts `months_before`, `months_after`, and `only_after_vacancy` parameters, identifies orphaned amplifiers (in-target channels that forwarded from the vacancy in the before window), then scores replacement candidates using three academically grounded metrics — Jaccard amplifier similarity (Small 1973), structural equivalence cosine score (Lorrain & White 1971), and brokerage role Jaccard (Gould & Fernandez 1989). Organisations of forwarded-from channels are resolved **as of each forward's date** via `ChannelAttribution.build_cache`/`org_at` (attribution is time-bounded). Results are returned sorted by first activity date and rendered in a client-side sortable table.
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
| `BRIDGING` or `BRIDGING(STRATEGY)` | Betweenness × neighbour-community Shannon entropy; defaults to `LEIDEN_DIRECTED` (directional brokerage); strategy must also be in `--community-strategies`. The bridging-basis dropdown in the Operations panel (Linked parameters fieldset) is shared with the bridging robustness attack — both use the same basis |
| `BURTCONSTRAINT` | Burt's constraint (0–1); low = structural hole broker; `null` for isolated nodes |
| `EGODENSITY` | Density of directed edges among immediate neighbours (predecessors ∪ successors, ego excluded); 0 = neighbours share no connections (hub between disconnected sources); 1 = fully connected clique (echo chamber); `null` for fewer than 2 neighbours |
| `LOCALCLUSTERING` | Directed local clustering coefficient (Fagiolo 2007); fraction of directed triangles through the node relative to all possible directed triads; 0 for nodes with total degree < 2 |
| `AMPLIFICATION` | Forwards received from in-target channels / own message count |
| `CONTENTORIGINALITY` | 1 − (forwarded messages / total messages); `null` if no messages |
| `DIFFUSIONLAG` | Median hours from original post date to forward date (within a reaction window, default 30 days; set `--diffusion-window 0` to disable); `null` for channels with no dated forwards; low = early adopter, high = late amplifier |
| `SPREADING` | SIR spreading efficiency — mean fraction infected when node seeds; Monte Carlo; runs set by `--spreading-runs` (default 200) |
| `ALL` | All of the above; `BRIDGING` uses `LEIDEN` as community basis |

### Edge construction

- `Message.forwarded_from` — channel whose content was forwarded
- `Message.references` — channels mentioned via `t.me/[username]`

Edge weight = (forwards + references) / total messages from source channel. Direction controlled by `REVERSED_EDGES`.

Only messages dated **within a channel's in-target attribution periods** contribute — the single chokepoint is `network/utils.channel_cutoff_q()` (a period-aware `Q(Exists(ChannelAttribution …))`), with `channel_period_date_q(channel)` as the cheap single-channel variant. A graph node's representative organisation (ORGANIZATION community, node colour, the "Organization" column in tables/CSV/GEXF/GraphML) is the in-target org whose period covers the most days inside the analysis window, tie-broken by earliest start (`network/graph_builder.resolve_window_organization`). `to_inspect` channels are crawled in full regardless of periods but enter the graph only as dead leaves.

### Code style

- Python 3.12, line length 120, double quotes (see `ruff.toml`)
- `ruff` for linting and formatting

### Configuration

Configuration is split across four files:

| File | Content | Gitignored | Example | Format |
|:-----|:--------|:----------:|:-------:|:-------|
| `configuration/.env` | Credentials + deployment (Telegram creds, DB, secret key, web access, locale) | ✓ | `configuration/env.example` | KEY=value |
| `configuration/.operations-crawl` | Crawler behaviour and per-channel defaults for `crawl_channels` | ✓ | — | TOML |
| `configuration/.operations-structural` | Outputs, layouts, measures, communities, vacancy, and robustness defaults for `structural_analysis` | ✓ | — | TOML |
| `.system` (repo root) | `APP_VERSION`, `REPOSITORY_URL` — managed by the project, do not edit | ✗ | — | KEY=value |

Required (in `configuration/.env`): `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE_NUMBER`.

Both `.operations-*` files are optional: built-in defaults live in `webapp_engine/config/defaults.py` and apply when a file is missing or omits a key. Each file starts with a `pulpit_version = "X.Y"` field so future Django data migrations can detect the writing release and rewrite the file when key names change. Click **Save as defaults** in the Operations panel under either form to persist the current selections — `tomlkit` writes the file with comments preserved and a refreshed `generated_at` header.

Key options:
- `[graph]` in `.operations-structural` — `reversed_edges` (default `true`), `community_palette` (default `ORGANIZATION`; non-organisation strategies fall back to `vaporwave` *reversed* — so the most-vivid colours land on the largest communities; an explicit `community_palette = "vaporwave"` is kept in canonical order), `dead_leaves_color` (default `#596a64`), `output_dir` (default `graph`).
- `[scope].channel_types` in `.operations-crawl` (default `["CHANNEL"]`) — channel types in scope; matches `DEFAULT_CHANNEL_TYPES`.
- `[downloads]` in `.operations-crawl` — `images` / `video` / `audio` / `stickers` / `other_media` (each default `false`). Each can be overridden per run with the matching `--download-X` / `--no-download-X` CLI flag, or via the **Media types** sidebar fieldset on the Operations panel (applies to `--get-new-messages`, `--fixholes`, and `--fix-missing-media` — the three operations that fetch messages from Telegram).

Media is dispatched into five disjoint models: `MessagePicture`, `MessageVideo` (with `is_animated` and `is_round` flags for GIFs/animations and round videos), `MessageAudio` (with `is_voice` flag), `MessageSticker` (with `is_animated` flag), and `MessageOtherMedia`. Analysis options (measures, community strategies, etc.) are command-line flags on `crawl_channels` and `structural_analysis`; see [docs/workflow.md](docs/workflow.md).

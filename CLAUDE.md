# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules

- **NEVER run `git add`, `git commit`, or `git push` unless the user explicitly requests that exact operation in their message.** Each operation requires its own explicit instruction: "commit" authorises a commit only; "push" authorises a push only; "commit and push" authorises both. After finishing any code change — however large or small — stop completely. Do not commit. Do not push. Do not revert and push. Wait for the user to send a separate message.
- Run `ruff check . --fix && ruff format .` before declaring any code change done.
- Smoke-test changes with a quick `python -c "..."` call where practical before finishing.
- When you touch any first-party JavaScript (`webapp_engine/map/js/`, `backoffice/static/`, `webapp/static/`), run `npm run lint:js` (ESLint flat config in `eslint.config.mjs`; requires `npm install` once). Inline `<script>` JS in Django templates is not in scope of this linter.
- When you touch the static-export HTML files (`webapp_engine/map/*.html`), run `npm run lint:html` to catch accessibility regressions (requires `npm install` once). Django templates are not in scope of this linter.
- `npm run lint` runs both JS and HTML linters.
- CHANGELOG entries should be informative but short: one tight paragraph (or a few bullets for larger changes) that names *what* shipped and *why it matters*, not a feature-by-feature walkthrough. Avoid long flag inventories and configuration dumps — link to the relevant docs instead.

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
- **`network/community.py`** — Community detection: ORGANIZATION, LABELPROPAGATION, LEIDEN, LEIDEN_DIRECTED, LEIDEN_CPM_COARSE, LEIDEN_CPM_FINE, KCORE, INFOMAP, INFOMAP_MEMORY, MCL, WALKTRAP, STRONGCC.
- **`network/layout.py`** — Spatial layout: Kamada-Kawai seed → ForceAtlas2 (`pyforceatlas2`).
- **`network/exporter.py`** — Builds `GraphData`; writes `data/*.json`, config, and GEXF/GraphML exports.
- **`network/tables.py`** — Writes channel, network, and community HTML/XLSX tables.
- **`network/robustness/`** — Robustness analysis package: `disparity_filter.py` (Serrano-Boguñá-Vespignani backbone extraction), `metrics.py` (attack curves, weighted R-index, critical threshold, weighted global efficiency), `attacks.py` (static + dynamic removal-order strategies), `null_model.py` (strength-preserving configuration-model null + z-score), `modular.py` (intra/inter community edge survival), `runner.py` (`run_robustness` orchestrator + `RobustnessConfig`). Output is a single JSON-serialisable dict written to `data/robustness.json`. Opt-in via `--robustness` on `structural_analysis`; `--robustness-alpha`/`-runs`/`-null`/`-dynamic`/`-seed`/`-sample` tune the run.
- **`network/management/commands/structural_analysis.py`** — Orchestrates the full export pipeline. Writes atomically: all output goes to `exports/<name>.tmp/`, which is renamed to `exports/<name>/` only after `summary.json` is written as the final step. A stale `.tmp` directory from an interrupted run is removed at the start of the next export with the same name.
- **`runner/tasks.py`** — Task manager for Operations panel: launch management commands as subprocesses, stream log output, track status (idle/running/done/failed), abort via SIGTERM.
- **`runner/views.py`** — Operations panel views: `OpsView`, `RunTaskView`, `AbortTaskView`, `TaskStatusView`.
- **`backoffice/views.py`** — Staff-only section views for `/manage/`: Channels, Organizations, Groups, Search Terms, Events, Users, Vacancies, Project, Maintenance.
- **`backoffice/api/views.py`** — DRF viewsets backing each section: `ChannelViewSet` (list/retrieve/update; exposes read-only `current_organization_*` + nested `attributions`; `bulk-assign` replaces each selected channel's attribution timeline with one period), `ChannelAttributionViewSet` (full CRUD with overlap validation; `?channel=` filter — drives the per-channel periods editor), `OrganizationViewSet`, `ChannelGroupViewSet`, `SearchTermViewSet`, `EventTypeViewSet`, `EventViewSet`, `UserViewSet` (full CRUD; email = username), `MessageViewSet` (list/destroy with channel, forwarded-only, and text filters), `ChannelVacancyViewSet` (full CRUD), and `ProjectView` (a `RetrieveUpdateAPIView` at `GET/PUT /manage/api/project/` backing the singleton project dossier — not a router viewset, since there is exactly one row).
- **`backoffice/api/maintenance.py`** — `GET /manage/api/maintenance/` returns engine, on-disk size, and the catalog of available strategies; `POST /manage/api/maintenance/optimize/` runs the selected strategies (default = all) sequentially, stopping at the first failure, and returns per-step timings plus size before/after. Supports SQLite (`ANALYZE`, `PRAGMA optimize`, `wal_checkpoint(TRUNCATE)`, `VACUUM`) and PostgreSQL (`ANALYZE`, `VACUUM ANALYZE`).
- **`backoffice/api/serializers.py`** — Serializers for all backoffice viewsets.
- **`backoffice/api/permissions.py`** (`BackofficePermission`) — Allows all requests when `WEB_ACCESS=ALL`; requires `is_staff` otherwise.
- **`webapp_engine/middleware.py`** (`WebAccessMiddleware`) — Enforces `WEB_ACCESS` policy: `ALL` (no-op), `OPEN` (staff required for `/operations/` and `/manage/`), `PROTECTED` (login required everywhere; staff required for `/operations/` and `/manage/`). Django admin's own auth handles `/admin/` in non-`ALL` modes.
- **`webapp/context_processors.py`** — Exposes `WEB_ACCESS` to all templates.
- **`webapp/models/`** — `Channel`, `Message` (with `references` M2M back to `Channel` and `grouped_id` for Telegram media-group albums), `Organization`, **`ChannelAttribution`** (the time-bounded channel→organization link: `channel` + `organization` + optional inclusive `start`/`end` dates, both `None` = open; non-overlapping per channel, enforced in `clean()`/serializer/admin), `SearchTerm`, media models, `ChannelVacancy` (channel + closure_date + note; one per channel), `Project` (single-row dossier: `title` + free-text `description`/`criteria`/`notes`; `save()` pins `pk=1` and `Project.load()` is the canonical accessor — it replaces the old `.env` `PROJECT_TITLE`, read at export time by `structural_analysis`/`compare_analysis`). `Channel.in_target_periods` are the periods whose org is in-target; `Channel.current_organization`/`current_attribution` resolve the period active today (else most-recent-past) for display. There is no longer a `Channel.organization` FK or `out_of_target_after` field — both folded into `ChannelAttribution`. `Message` exposes `is_album`, `album_size`, and `album_pictures` / `album_videos` / `album_audios` / `album_stickers` / `album_other_media` that gather sibling media across messages sharing the same `(channel_id, grouped_id)`.
- **`webapp/views.py`** (`VacanciesView`) — `/channels/vacancies/` lists analyst-designated vacancy channels. `ChannelDetailView` passes the vacancy to the template so the Vacancy Analysis card is rendered. `VacancyAnalysisView` (`GET /channel/<pk>/vacancy-analysis/`) is the JSON endpoint that drives the card: it accepts `months_before`, `months_after`, and `only_after_vacancy` parameters, identifies orphaned amplifiers (in-target channels that forwarded from the vacancy in the before window), then scores replacement candidates using three academically grounded metrics — amplifier coverage (the asymmetric overlap |A ∩ B| / |A|, i.e. recall — not a Jaccard despite the legacy `AMPLIFIER_JACCARD` token), neighbour-set equivalence (the binary Ochiai cosine of the in/out neighbour sets, averaged; labelled "Neighbour-set Equivalence" — distinct from the *weighted* Lorrain & White 1971 structural-equivalence matrix), and brokerage-overlap Jaccard of bridged org-pairs (operationalising the brokerage concept of Gould & Fernandez 1989, *not* their brokerage census; labelled "Brokerage overlap"). Organisations of forwarded-from channels are resolved **as of each forward's date** via `ChannelAttribution.build_cache`/`org_at` (attribution is time-bounded). Results are returned sorted by first activity date and rendered in a client-side sortable table. The interactive card and the structural-analysis export share one scorer — both call `network.vacancy_analysis._scores_abc` (and `_shift_months`) on `Message.objects.alive()` — so they agree by construction. All message queries (orphaned-amplifier detection, candidate selection, and the A/B/C scorers, in both the card and the export) are **period-aware** via `channel_cutoff_q()`: a message counts only when its channel was in an in-target period at the message date, matching the graph pipeline's chokepoint.
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
| `INDEGCENTRALITY` | Freeman-normalised in-degree centrality (Freeman 1978; Wasserman & Faust 1994 §5): `deg_in(v) / (n−1)`, the count of *distinct* citing channels normalised by the star-graph maximum. **Unweighted** — `nx.in_degree_centrality` discards edge weights, so the ranking is invariant to `--edge-weight-strategy`; the weighted counterpart is the **In-strength** column `in_deg`. Feeds Freeman centralisation in `community_stats` (the star bound is exact for it) |
| `OUTDEGCENTRALITY` | Freeman-normalised out-degree centrality (Freeman 1978; Wasserman & Faust 1994 §5): `deg_out(v) / (n−1)`, the count of *distinct* cited channels normalised by the out-star maximum — the *expansiveness* dual of `INDEGCENTRALITY`. **Unweighted** — `nx.out_degree_centrality` discards edge weights, so the ranking is invariant to `--edge-weight-strategy`; the weighted counterpart is the **Out-strength** column `out_deg`. Feeds Freeman centralisation in `community_stats` (the star bound is exact for it) |
| `HARMONICCENTRALITY` | Harmonic centrality (Marchiori & Latora 2000; Rochat 2009; Boldi & Vigna 2014): `C_H(u) = Σ_v 1/d(v, u)` ÷ (n−1) — mean reciprocal *incoming* distance, i.e. how easily the rest of the network reaches `u` (NetworkX's in-direction, kept on Pulpit's as-built amplifier→source orientation, so it scores as a closeness-style prestige / multi-hop generalisation of in-degree). Weighted over `distance = 1/weight` (Opsahl 2010), so not bounded to [0, 1] |
| `BRIDGINGCENTRALITY` | **Bridging Centrality** (Hwang et al. 2008): betweenness × bridging coefficient, where the bridging coefficient `(1/d(v)) / Σ_{i∈N(v)} (1/d(i))` uses undirected, unweighted degree; high = a low-degree node wedged between high-degree regions (a topological bridge). Purely degree-based — needs no community basis. Distinct from `BRIDGING` |
| `BRIDGING(basis=STRATEGY)` | **Community Bridging** (base key `community_bridging`): betweenness × neighbour-community participation coefficient (Guimerà & Amaral 2005); `basis` defaults to `LEIDEN_DIRECTED` (directional brokerage) and must also be in `--community-strategies`. The basis is **per-instance** — picked on the measure chip in the Operations panel (legacy positional `BRIDGING(STRATEGY)` still parses). The robustness community-bridging attack has its **own** separate basis dropdown. *Not* the Bridging Centrality of Hwang et al. (2008) — see `BRIDGINGCENTRALITY` |
| `BURTCONSTRAINT` | Burt's constraint (Burt 1992, 2004): `c(v) = Σ_w (p_vw + Σ_q p_vq · p_qw)²` with p the row-normalised mutual weight; low = structural-hole broker, high = embedded in redundant ego-network. Typically in [0, 1] (theoretical max ≈ 1.125, Burt 1992 ch. 2). `nx.constraint` symmetrises direction internally (`mutual_weight(u,v) = w(u→v) + w(v→u)`, `N(v) = preds ∪ succs`), so the score is **direction-invariant** — `--edge-weight-strategy` matters, the as-built citation orientation does not. `null` for isolated nodes |
| `LOCALCLUSTERING` | Directed local clustering coefficient (Fagiolo 2007): `c^D(u) = T^D(u) / [2 · (d^tot · (d^tot − 1) − 2 d^↔)]`, the count of directed triangles through `u` summed over the four pattern types (cycle, middleman, in-triangle, out-triangle) divided by the maximum allowed by `u`'s degree configuration. In `[0, 1]`; 0 for isolated nodes and nodes with total degree < 2. Pulpit calls `nx.clustering(graph)` *without* a `weight` argument, so it is **unweighted** — `--edge-weight-strategy` does not affect the ranking. Fagiolo's formula sums all 8 directed triangle orientations symmetrically, so the score is also **direction-invariant** (same value on `G` and `G.reverse()`), like `BURTCONSTRAINT` |
| `CORENESS` | K-core coreness (Kitsak et al. 2010): deepest k-core a node survives in; computed on the symmetrised, self-loop-free, unweighted graph (matches `detect_kcore`); high = dense reinforcing nucleus, low = peripheral amplifier |
| `COLLECTIVEINFLUENCE` | Collective Influence (Morone & Makse 2015, *Nature*): `(k_i−1)·Σ_{j∈∂Ball(i,ℓ)}(k_j−1)` over the frontier at distance exactly ℓ=2 (constant `_CI_RADIUS`); optimal-percolation key-spreader score on the symmetrised, self-loop-free, unweighted projection (matches `CORENESS`), so direction- and weight-invariant. Degree-0/1 nodes score 0. Read ordinally; excluded from `CENTRALITY_MEASURE_KEYS` (no star max). The per-node dual of the robustness dismantling order |
| `TROPHICLEVEL` | Hierarchical trophic level (MacKay, Johnson & Sansom 2020): solves `(diag(u) − (W+Wᵀ)) h = w_in − w_out`, shifted to min 0 per weakly-connected component; structural source→sink position, well-defined on cyclic graphs (unlike Levine 1980) |
| `MODULEROLE(basis=STRATEGY)` | Guimerà & Amaral (2005) within-module role: emits numeric `within_module_z` (within-community degree z-score) + categorical `module_role` label (7 roles from the z/P plane). Dispatched specially (needs a community partition); `basis` is per-instance — an explicit value (any strategy, incl. `organization`), else blank/auto-resolved (prefers `leiden_directed`, then first available). `module_role` is **not** in `measures_labels` — it is exported as a string column like `organization` (channels.json node_keys, CSV, XLSX, a "Role" column in `channel_table.js`); `within_module_z` flows the normal numeric measure path |
| `BROKERAGEROLES(basis=STRATEGY)` | Gould-Fernandez (1989) brokerage census: classifies every directed citation 2-path `i→v→j` (broker `v`) by the groups of `i`,`v`,`j` into coordinator/gatekeeper/representative/consultant/liaison. Dispatched specially (needs a partition); `basis` per-instance — explicit, else blank/auto-resolved preferring `organization`, then `leiden_directed`, then first available. Emits numeric `brokerage_total` (the only `measures_labels` entry) + categorical `brokerage_role` (dominant role by raw count, rides alongside like `module_role`); the five raw role counts (`brokerage_coordinator`…`brokerage_liaison`) reach channels.json node_keys, `nodes.csv`, and GEXF/GraphML but **not** the channel table (HTML/XLSX). Unweighted, as-built citation direction; excluded from `CENTRALITY_MEASURE_KEYS` |
| `AMPLIFICATION` | Forwards received from in-target channels / own message count |
| `CONTENTORIGINALITY` | 1 − (forwarded messages / total messages); `null` if no messages |
| `DIFFUSIONLAG(window=DAYS)` | Median hours from original post date to forward date (within a reaction `window`, default 30 days; `0` disables); `null` for channels with no dated forwards; low = early adopter, high = late amplifier. A bare `DIFFUSIONLAG` inherits `--diffusion-window` |
| `SPREADING(runs=N)` | SIR spreading efficiency — mean fraction infected when node seeds; Monte Carlo, `runs` per node (default 200). A bare `SPREADING` inherits `--spreading-runs` |
| `ALL` | All of the above (both `BRIDGINGCENTRALITY` and `BRIDGING(basis=LEIDEN_DIRECTED)`), each parameterised measure once with default parameters |

**Measure tokens & parameters.** `--measures` is an *ordered* comma-separated list parsed by `network.measures.parse_measures` into `MeasureInstance` objects. Five measures take parameters — `SPREADING(runs=…)`, `DIFFUSIONLAG(window=…)`, `BRIDGING(basis=…)`, `MODULEROLE(basis=…)`, `BROKERAGEROLES(basis=…)` (keyword args; legacy positional `BRIDGING(STRATEGY)` still parses) — and may appear **more than once** with different parameters; the other 15 are drop-once. Every parameterised-measure node-attribute key is **parameter-suffixed** (`spreading_efficiency_runs_200`, `community_bridging_basis_leiden_directed`, plus the role companions `module_role_*` / `brokerage_*_*`) so repeated instances never collide. `network.measures.canonical_measure_key` strips the suffix back to the base (used by `CENTRALITY_/BEHAVIOURAL_MEASURE_KEYS` matching and `channel_table.js` column grouping); `role_companions` derives a role measure's categorical companion keys from its numeric column. The Operations panel selects measures via a drag-and-drop builder (palette → ordered drop-zone, parameterised chips repeatable with inline parameter inputs); the suffixing/canonicalisation logic is mirrored in `webapp_engine/map/js/channel_table.js`.

### Edge construction

- `Message.forwarded_from` — channel whose content was forwarded
- `Message.references` — channels mentioned via `t.me/[username]`

Edge weight has four strategies (`--edge-weight-strategy`): `NONE` (unweighted — every citation worth 1), `TOTAL` (raw forwards+references count), `PARTIAL_MESSAGES` (count divided by the *amplifier*'s total messages — what fraction of everything the citing channel posted was about the cited one), and the default `PARTIAL_REFERENCES` (count divided by the *amplifier*'s citing messages — the ones carrying a `forwarded_from` or a `t.me/` reference, so the amplifier's purely original posts don't dilute the denominator). **Direction is fixed: a forward of source Y's content by amplifier X produces an X→Y edge (the citation convention — citing → cited). `Channel.in_degree` therefore counts how many channels cite/forward this one (audience); `out_degree` counts how many channels it cites/forwards (curatorial activity). Measures whose academic definition runs the other way — SIR `SPREADING` (Kitsak et al. 2010) and `TROPHICLEVEL` (MacKay 2020) — reverse the graph internally so content cascades flow source→amplifier; `BURTCONSTRAINT` symmetrises direction internally (Burt's framework is direction-agnostic); `LOCALCLUSTERING` (Fagiolo 2007) keeps the directed graph but its formula sums all 8 directed triangle orientations symmetrically, so the score is direction-invariant in practice (same value on `G` and `G.reverse()`); `COLLECTIVEINFLUENCE` (Morone-Makse 2015) is computed on the symmetrised projection (direction-invariant, like `CORENESS`); every other measure (PageRank, HITS, betweenness/harmonic, bridging, `BROKERAGEROLES` brokerage census, vacancy PPR, ORGANIZATION/Leiden communities, k-core) treats edges in the as-built citation direction.**

Only messages dated **within a channel's in-target attribution periods** contribute — the single chokepoint is `network/utils.channel_cutoff_q()` (a period-aware `Q(Exists(ChannelAttribution …))`), with `channel_period_date_q(channel)` as the cheap single-channel variant. A graph node's representative organisation (ORGANIZATION community, node colour, the "Organization" column in tables/CSV/GEXF/GraphML) is the in-target org whose period covers the most days inside the analysis window, tie-broken by earliest start (`network/graph_builder.resolve_window_organization`). `to_inspect` channels are crawled in full regardless of periods but enter the graph only as dead leaves.

### Code style

- Python 3.12–3.14 (all fully supported), line length 120, double quotes (see `ruff.toml`)
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
- `[graph]` in `.operations-structural` — `community_palette` (default `ORGANIZATION`; non-organisation strategies fall back to `vaporwave` *reversed* — so the most-vivid colours land on the largest communities; an explicit `community_palette = "vaporwave"` is kept in canonical order), `dead_leaves_color` (default `#596a64`), `output_dir` (default `graph`).
- `[scope].channel_types` in `.operations-crawl` (default `["CHANNEL"]`) — channel types in scope; matches `DEFAULT_CHANNEL_TYPES`.
- `[downloads]` in `.operations-crawl` — `images` / `video` / `audio` / `stickers` / `other_media` (each default `false`). Each can be overridden per run with the matching `--download-X` / `--no-download-X` CLI flag, or via the **Media types** sidebar fieldset on the Operations panel (applies to `--get-new-messages`, `--fixholes`, and `--fix-missing-media` — the three operations that fetch messages from Telegram).

Media is dispatched into five disjoint models: `MessagePicture`, `MessageVideo` (with `is_animated` and `is_round` flags for GIFs/animations and round videos), `MessageAudio` (with `is_voice` flag), `MessageSticker` (with `is_animated` flag), and `MessageOtherMedia`. Analysis options (measures, community strategies, etc.) are command-line flags on `crawl_channels` and `structural_analysis`; see [docs/workflow.md](docs/workflow.md).

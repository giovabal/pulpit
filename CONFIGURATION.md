# Configuration

Pulpit's configuration lives in four files, each with a single responsibility:

| File | Content | Format | Bootstrapped from |
| :--- | :------ | :----- | :---------------- |
| `configuration/.env` | Credentials and deployment — Telegram API keys, Telegram-client tuning, database, secret key, web-access policy, locale, project identity. | `KEY=value` (dotenv) | `configuration/env.example` |
| `configuration/.operations-crawl` | Bundled baseline that pre-populates the **Crawl Channels** form. Committed in git as the "Pulpit defaults". | TOML | — (built-in defaults) |
| `configuration/.operations-structural` | Bundled baseline that pre-populates the **Structural Analysis** form. Committed in git as the "Pulpit defaults". | TOML | — (built-in defaults) |
| `configuration/.operations-{crawl,structural}-{timestamp}` | Optional named snapshots written by **Save as defaults**. Gitignored. | TOML | — |
| `.system` (repo root) | `APP_VERSION` and `REPOSITORY_URL`. Managed by the project — do not edit. | `KEY=value` | — |

`setup.sh` and `setup.bat` copy `configuration/env.example` into `configuration/.env` on first install. Both `.operations-*` baselines are committed in the repository, so a fresh checkout already has working form defaults; built-in factory-empty defaults from `webapp_engine/config/defaults.py` apply when the file is missing or omits a key.

**The `.operations-*` files only pre-populate the Operations-panel form.** They are no longer consulted by the CLI. A bare `python manage.py crawl_channels` / `structural_analysis` invocation does nothing — every option you want set must be passed as an explicit flag. Panel-driven runs are unaffected because the panel emits explicit `--flag` / `--no-flag` pairs for every toggle. The easiest way to discover the right flag combination is the **Write CLI command** button in the Operations panel.

Each TOML file starts with a `[meta]` block:

```toml
[meta]
title = "Pulpit defaults"
pulpit_version = "0.21"
generated_at = "2026-05-21T00:00:00Z"
```

The title identifies the snapshot in the **Load defaults** picker; `pulpit_version` lets future Django data migrations recognise the writing release and rewrite the file in place when section/key names change.

Fill in at least the three Telegram credentials in `configuration/.env` before running any management command. All other settings have working defaults.

See [docs/operations-defaults.md](docs/operations-defaults.md) for the end-to-end walk-through of how the form, the CLI, and the snapshot files relate.

---

# `configuration/.env` — credentials and deployment

## Telegram credentials

| Option | Description | Default |
| :----- | :---------- | ------: |
| `TELEGRAM_API_ID` | API ID from Telegram | **required** |
| `TELEGRAM_API_HASH` | API hash from Telegram | **required** |
| `TELEGRAM_PHONE_NUMBER` | Phone number linked to your Telegram account | **required** |

See [Getting started § Telegram API credentials](docs/getting-started.md#telegram-api-credentials) for the registration walk-through.

## Telegram client tuning

Optional knobs for the Telethon client. Defaults match the previous `[telegram]` section of `.operations-crawl` (now removed).

| Option | Description | Default |
| :----- | :---------- | ------: |
| `TELEGRAM_SESSION_NAME` | Telethon session file name (no `.session` extension) | `anon` |
| `TELEGRAM_CONNECTION_RETRIES` | How many times Telethon retries a failed connection before giving up | `10` |
| `TELEGRAM_RETRY_DELAY` | Seconds to wait between connection retry attempts | `5` |
| `TELEGRAM_FLOOD_SLEEP_THRESHOLD` | Telethon auto-sleeps through flood-wait errors shorter than this value (seconds); errors longer than this are raised as exceptions | `60` |
| `TELEGRAM_IGNORE_FLOODWAIT` | `False` = sleep `TELEGRAM_FLOODWAIT_SLEEP_SECONDS` on FloodWait; `True` = skip the operation silently and continue | `True` |
| `TELEGRAM_FLOODWAIT_SLEEP_SECONDS` | Seconds to sleep when `TELEGRAM_IGNORE_FLOODWAIT=False` and a long flood-wait fires | `900` |
| `TELEGRAM_CRAWLER_GRACE_TIME` | Seconds to wait between API requests | `1` |

---

## Database

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DB_ENGINE` | Backend: `sqlite`, `postgresql`, `mysql`, `mariadb`, or `oracle` | `sqlite` |
| `DB_NAME` | SQLite: filename (resolved from project root). Oracle: service name or full DSN. All others: database name. | `db.sqlite3` |
| `DB_USER` | All non-SQLite backends: database user | _(empty)_ |
| `DB_PASSWORD` | All non-SQLite backends: database password | _(empty)_ |
| `DB_HOST` | All non-SQLite backends: host | `localhost` |
| `DB_PORT` | All non-SQLite backends: port | `5432` (PostgreSQL), `3306` (MySQL/MariaDB), `1521` (Oracle) |

Each non-SQLite backend requires its driver — install separately before running:

```sh
pip install psycopg2-binary   # PostgreSQL
pip install mysqlclient        # MySQL or MariaDB
pip install oracledb           # Oracle
```

> SQLite is the default and works out of the box; it is configured with WAL journal mode and `synchronous=NORMAL` for better concurrency. Server-based backends are recommended when running Pulpit on a shared server or when the database may be accessed by multiple processes concurrently. MySQL and MariaDB connections use `utf8mb4` charset; create the database with `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` to match. For Oracle, `DB_NAME` accepts a service name (`ORCL`), an Easy Connect string (`host/service`), or a full TNS alias defined in `tnsnames.ora`.

---

## Project and access control

| Option | Description | Default |
| :----- | :---------- | ------: |
| `PROJECT_TITLE` | Project name used in the `<title>` tag of all HTML files produced by `structural_analysis` | `Pulpit project` |
| `WEB_ACCESS` | Access control for the web interface: `ALL` (no login required, default), `OPEN` (public pages open; `/operations/` and `/manage/` require staff), `PROTECTED` (all pages require login; `/operations/` and `/manage/` additionally require staff). **Comments must live on their own line**, not inline after the value — `python-decouple` does not strip inline `#` comments. | `ALL` |
| `SECRET_KEY` | Django secret key. Generated by `setup.sh` / `setup.bat` on first install. Rotate before any non-local deployment. | _(generated)_ |
| `DEBUG` | Django debug mode. Leave `True` for local use; set `False` for any deployment. | `True` |
| `ALLOWED_HOSTS` | Comma-separated list of hostnames Django will serve. Required when `DEBUG=False`. | _(empty)_ |
| `LANGUAGE_CODE` | Django language code. | `en-us` |
| `TIME_ZONE` | Django time zone. | `UTC` |

> **User accounts:** `WEB_ACCESS=ALL` requires no accounts. For `OPEN` or `PROTECTED`, create a staff account first with `python manage.py createsuperuser`. Staff accounts (`is_staff=True`) can reach `/admin/`, `/operations/`, and `/manage/`; regular accounts can reach everything else in `PROTECTED` mode but are blocked from those paths. The login form is always at `/login/`. See [Getting started § Access control](docs/getting-started.md#access-control) for the full guide.

---

# `configuration/.operations-crawl` — crawler form defaults

TOML file. Built-in factory-empty defaults live in `webapp_engine/config/defaults.py:CRAWL_DEFAULTS`; the committed baseline at `configuration/.operations-crawl` overrides them with the curated "Pulpit defaults" set. The file pre-populates the **Crawl Channels** form only — the CLI does not consult it. Click **Save as defaults** below the form (with a title) to write a new timestamped snapshot alongside this baseline; **Load defaults** lets you pick any saved snapshot back.

## `[downloads]` — media type toggles

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `downloads.images` | Download images attached to messages | `false` |
| `downloads.video` | Download videos (including GIFs/animations and round videos) attached to messages | `false` |
| `downloads.audio` | Download audio attached to messages — both voice notes and uploaded audio documents | `false` |
| `downloads.stickers` | Download stickers attached to messages (static webp, animated TGS, video webm) | `false` |
| `downloads.other_media` | Download non-photo, non-video, non-audio, non-sticker documents (PDFs, archives, etc.) | `false` |

> **Message statistics:** view counts, forward counts, reply counts, and reactions are recorded when a message is first crawled and are not automatically updated on subsequent runs. Use `--refresh-messages-stats` on `crawl_channels` to re-fetch them; combine with `--refresh-limit N`, `--refresh-from YYYY-MM-DD`, and `--refresh-to YYYY-MM-DD` to restrict the scope.

## `[scope]` — channel-type filter

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `scope.channel_types` | Telegram entity types considered monitored: any of `CHANNEL` (broadcast), `GROUP` (supergroups/gigagroups), `USER`. Pre-populates the **Channel types** fieldset of the Crawl Channels form. | `["CHANNEL"]` |

## `[channels]` — channel-pass step toggles

Pre-populates the *1. Channels* fieldset of the Crawl Channels form. The CLI flag for each (`--get-channels-info`, `--update-type-excluded-info`, `--mine-about-texts`, `--fetch-recommended`, `--retry-lost-and-private`) and its `--no-X` counterpart are emitted by the panel on Run.

| Path | Step | Built-in default |
| :--- | :--- | ---------------: |
| `channels.get_channels_info` | Update channel metadata (profile pictures, subscriber counts, about text, …) | `false` |
| `channels.update_type_excluded_info` | When `get_channels_info` runs, also refresh metadata for in-target channels whose type is excluded by the current `scope.channel_types` filter | `false` |
| `channels.mine_about_texts` | Scan channel descriptions for `t.me/` links and ingest referenced channels | `false` |
| `channels.fetch_recommended` | Ask Telegram for related-channel suggestions and add them to the database | `false` |
| `channels.retry_lost_and_private` | Re-attempt channels previously marked inaccessible | `false` |

## `[messages]` — message-pass step toggles

| Path | Step | Built-in default |
| :--- | :--- | ---------------: |
| `messages.get_new_messages` | Download messages published since the last crawl | `false` |
| `messages.fetch_replies` | Fetch reply threads from linked discussion groups | `false` |
| `messages.refresh_messages_stats` | Re-fetch view counts, forward counts, edited text, reactions, fact-check labels | `false` |
| `messages.fix_holes` | Scan per-channel message ID sequences for gaps and refetch missing messages | `false` |
| `messages.fix_missing_media` | Re-download photos and videos that were never saved or are missing from disk | `false` |
| `messages.retry_lost_messages` | Bulk-refetch every message currently marked `is_lost=True`; rows Telegram returns are unmarked | `false` |
| `messages.retry_references` | Re-attempt `t.me/` references that could not be resolved in a previous run | `false` |
| `messages.force_retry_unresolved_references` | Together with `messages.retry_references`, also retries references previously marked permanently unresolvable | `false` |

> The loader silently translates the pre-0.21 spellings `messages.fixholes` → `messages.fix_holes` and `messages.force_retry_unresolved` → `messages.force_retry_unresolved_references` at parse time, so older snapshots load unchanged; re-saving them through the panel rewrites the file with the canonical keys.

## `[degrees]` — bulk degree-recompute toggles

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `degrees.in_degrees` | Recompute in-degree and out-degree for all in-target channels (pure DB; no Telegram connection) | `false` |
| `degrees.out_degrees` | Recompute citation degree for out-of-target channels referenced by in-target ones | `false` |

---

# `configuration/.operations-structural` — structural-analysis form defaults

TOML file. Built-in factory-empty defaults live in `webapp_engine/config/defaults.py:STRUCTURAL_DEFAULTS`; the committed baseline at `configuration/.operations-structural` overrides them with the curated "Pulpit defaults" set. The file pre-populates the **Structural Analysis** form only — the CLI does not consult it.

## `[graph]` — palette and base options

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `graph.reversed_edges` | When `true`, a forward of Y's content by X produces a Y→X edge (influence flows toward the source) | `true` |
| `graph.community_palette` | Colour palette for communities. Any palette name from [python-graph-gallery.com/color-palette-finder](https://python-graph-gallery.com/color-palette-finder/) (case-sensitive — explicit palette names are kept in their canonical order). The legacy value `"ORGANIZATION"` is silently translated to `"vaporwave"` *reversed* at load time. Empty `""` disables palette rendering. | `""` |
| `graph.community_palette_reversed` | Reverse the palette so the most-vivid colours land on the largest communities | `false` |
| `graph.dead_leaves_color` | Hex colour for dead-leaf nodes (out-of-target channels that an in-target one has forwarded from or mentioned via a `t.me/` link) | `#596a64` |
| `graph.output_dir` | Directory where `structural_analysis` writes all output files. Relative paths resolve from the project root. | `graph` |

## `[outputs]` — what to write

| Path | Effect | Built-in default |
| :--- | :----- | ---------------: |
| `outputs.graph` | Write `graph.html` (interactive 2D map) | `false` |
| `outputs.graph_3d` | Write `graph3d.html` (Three.js 3D map) | `false` |
| `outputs.html` | Write HTML tables (channel, network, community) | `false` |
| `outputs.xlsx` | Write Excel workbooks alongside HTML tables | `false` |
| `outputs.gexf` | Write `network.gexf` (Gephi-compatible) | `false` |
| `outputs.graphml` | Write `network.graphml` (igraph / Cytoscape) | `false` |
| `outputs.csv` | Write `nodes.csv` and `edges.csv` | `false` |
| `outputs.seo` | Set indexable robots meta tags on the export HTML | `false` |
| `outputs.vertical_layout` | Orient the graph viewport vertically | `false` |
| `outputs.structural_similarity` | Generate the pairwise structural similarity matrix | `false` |
| `outputs.consensus_matrix` | Generate the community-detection consensus matrix (requires ≥ 2 non-ORGANIZATION strategies in `communities.strategies`) | `false` |
| `outputs.draw_dead_leaves` | Include dead leaves in the graph: out-of-target channels that an in-target one has forwarded from or mentioned via a `t.me/` link | `false` |
| `outputs.timeline_step` | Timeline granularity: `"none"` or `"year"` | `"none"` |

## `[layouts]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `layouts.layouts_2d` | 2D layouts to pre-compute. Available: `FA2`, `CIRCULAR`, `KAMADA_KAWAI`, `COMMUNITY_SHELL`, `TSNE`, `UMAP`, `HYPERBOLIC`. Use `["ALL"]` for every layout. | `[]` |
| `layouts.layouts_3d` | 3D layouts to pre-compute. Available: `FA2`, `SPECTRAL`, `SPRING`, `KAMADA_KAWAI`, `TSNE`, `UMAP`. Use `["ALL"]` for every layout. | `[]` |

> Pre-0.21 spellings `layouts.two_d` and `layouts.three_d` are silently translated to the canonical names on load.

## `[computation]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `computation.fa2_iterations` | ForceAtlas2 iteration count. Either an integer (e.g. `5000`) or a multiplier of the channel count expressed as `"Nx"` (e.g. `"7x"` → 7 × channels in the graph). Floored at 100 regardless. Empty `""` disables FA2. | `""` |
| `computation.community_distribution_threshold` | Minimum % a community must reach in at least one organisation row to appear in the cross-tabulation tables. `0` keeps every community. | `0` |
| `computation.leiden_coarse_resolution` | CPM resolution γ for `LEIDEN_CPM_COARSE` (few large communities) | `0.01` |
| `computation.leiden_fine_resolution` | CPM resolution γ for `LEIDEN_CPM_FINE` (many small communities) | `0.05` |
| `computation.mcl_inflation` | Inflation parameter r for `MCL` (typical range 1.5–4.0) | `2.0` |
| `computation.spreading_runs` | Monte Carlo SIR simulations per node for `SPREADING` | `200` |
| `computation.diffusion_window` | Reaction window in days for `DIFFUSIONLAG`. `0` = no window. | `30` |

## `[measures]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `measures.selected` | Measures to compute. See [Network measures](docs/network-measures.md) for the catalogue. Use `["ALL"]` to enable every measure. | `[]` |
| `measures.bridging_basis` | Community partition driving the BRIDGING measure (entropy across neighbour communities) and the `bridging` robustness strategy. Empty → uses `LEIDEN_DIRECTED`. Must be in `communities.strategies` and cannot be `ORGANIZATION`; otherwise Save/Run is rejected with HTTP 400. | `""` |

## `[communities]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `communities.strategies` | Community detection strategies. See [Community detection](docs/community-detection.md). Use `["ALL"]` for every strategy. | `[]` |

## `[network_stats]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `network_stats.groups` | Whole-network statistic groups. Available: `SIZE`, `PATHS`, `COHESION`, `COMPONENTS`, `DEGCORRELATION`, `CENTRALIZATION`, `CONTENT`. Use `["ALL"]` for every group. See [Whole-network statistics](docs/whole-network-statistics.md). | `[]` |

## `[edges]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `edges.weight_strategy` | Edge-weighting method: `PARTIAL_REFERENCES`, `PARTIAL_MESSAGES`, `TOTAL`, `NONE`. Empty `""` disables edge weighting. | `""` |
| `edges.include_mentions` | Treat inline `t.me/` mentions as edges alongside forwards | `false` |
| `edges.include_self_references` | Include self-loop edges where a channel forwards or mentions itself | `false` |
| `edges.recency_weights` | Recency decay half-life in days as an integer string. Empty string `""` = weight all messages equally. | `""` |

## `[scope]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `scope.include_lost` | Include channels currently flagged `is_lost=True` | `false` |
| `scope.include_private` | Include channels currently flagged `is_private=True` | `false` |

## `[vacancy]`

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `vacancy.measures` | Vacancy-succession algorithms. Available: `AMPLIFIER_JACCARD`, `STRUCTURAL_EQUIV`, `BROKERAGE`, `CASCADE_OVERLAP`, `PPR`, `TEMPORAL`. Empty list disables vacancy analysis. See [Vacancy analysis](docs/vacancy-analysis.md). | `[]` |
| `vacancy.months_before` | Look-back window (months) for orphaned-amplifier detection | `12` |
| `vacancy.months_after` | Forward window (months) for candidate adoption | `24` |
| `vacancy.max_candidates` | Maximum candidates ranked per vacancy | `30` |
| `vacancy.ppr_alpha` | Damping factor α for Personalized PageRank | `0.85` |

## `[robustness]`

Resistance to node removal: residual-size R-index per attack strategy, z-score against a weight-rewiring null model, and intra/inter community edge survival. See [Robustness analysis](docs/robustness-analysis.md).

There is no `robustness.enabled` knob — robustness analysis runs iff `robustness.strategies` is non-empty (`SA_ROBUSTNESS = bool(strategies)` in `settings.py`). The Operations panel's strategy checkboxes drive both the strategy list and the master switch.

| Path | Description | Built-in default |
| :--- | :---------- | ---------------: |
| `robustness.alpha` | Serrano-Boguñá-Vespignani disparity-filter threshold applied before the attacks. Values in `(0, 1)` keep statistically significant edges only; `0` disables the filter and uses the full graph | `0.05` |
| `robustness.runs` | Number of independent random-failure runs averaged for the `random` strategy | `100` |
| `robustness.null` | Number of weight-rewiring null-model simulations per strategy; `0` disables the null model (no z-scores) | `20` |
| `robustness.strategies` | Attack strategies. Static: `random`, `in_strength`, `out_strength`, `pagerank`, `katz`, `hits_hub`, `hits_authority`, `harmonic`, `closeness`, `betweenness`, `flow_betweenness`, `burt_constraint`, `bridging[(<community-strategy>)]`, `spreading`. Dynamic (re-rank per removal): `in_strength_dyn`, `out_strength_dyn`, `pagerank_dyn`, `katz_dyn`, `hits_hub_dyn`, `hits_authority_dyn`, `betweenness_dyn`. Use `["ALL"]` for every strategy. Bridging defaults to `LEIDEN_DIRECTED` as the community basis (directional brokerage); override via `measures.bridging_basis`. | `[]` |
| `robustness.seed` | Single seed driving every stochastic component of the robustness analysis | `42` |
| `robustness.sample` | Source-sample size for the R_reach metric on graphs larger than this many nodes | `500` |

---

# Snapshots — `configuration/.operations-{stem}-{timestamp}`

Every click of **Save as defaults** writes a new TOML file alongside the committed baseline:

```
configuration/.operations-crawl-2026-05-21T14-32-00Z
configuration/.operations-structural-2026-05-21T14-35-12Z
```

The filename's timestamp is UTC, second-precision. Same-second collisions advance by 1 s so concurrent saves never silently overwrite. These files are gitignored and never modify the committed baseline. They never affect form pre-population at startup — they're only loaded on demand when you pick one from the **Load defaults** picker.

Each snapshot's `[meta]` block records the title you typed in the Save modal (max 120 characters; required), the Pulpit version that produced it, and the UTC timestamp the writer stamped at write time. The `Load defaults` picker reads these to label each row.

Cross-field constraints are enforced server-side before a snapshot is written and again before any panel-driven Run, returning HTTP 400 + a clear error message on rejection. Currently enforced for `structural_analysis`:

- BRIDGING basis (explicit `measures.bridging_basis` or the implicit `LEIDEN_DIRECTED` default) must be a known community-detection strategy other than `ORGANIZATION`, and must appear in `communities.strategies`.
- `consensus_matrix` requires at least two non-`ORGANIZATION` strategies in `communities.strategies`.

For `compare_analysis` and `search_channels` the Run path additionally validates: `project_dir` / `compare_target` non-empty; `--amount` positive.

---

# `.system` — project-managed metadata

A small, committed file containing `APP_VERSION` and `REPOSITORY_URL`. These values are surfaced in the About modal and the export footer, and the writer stamps `APP_VERSION` into every `.operations-*` file it writes. The project maintains them — do not edit.

---

# Why two formats?

`.env` uses dotenv (`KEY=value`) because that's the universal convention for environment variables — Docker Compose's `env_file`, CI/CD secret injectors, IDE runtime configs, and `direnv` all read it natively. Pulpit's `.env` carries exactly what the convention serves: credentials and per-deployment switches.

The `.operations-*` files use TOML because their schema is hierarchical (per-section), typed (booleans, integers, floats, strings, lists), and benefits from comment preservation across rewrites (`tomlkit`). TOML is the modern Python project-config standard (`pyproject.toml`). YAML's indentation-sensitive type inference would be a hand-edit hazard; JSON disallows comments; INI loses both types and comments on rewrite; Python config files are an execution-time security hole.

The split mirrors the audience: `.env` is sysadmin / deployment territory; `.operations-*` is analyst territory. They have different update cadences and different sets of consumers, and keeping them in their respective natural formats avoids forcing one user group to learn the other's idiom.

---

← [README](README.md) · [Getting started](docs/getting-started.md) · [Workflow](docs/workflow.md) · [Operations defaults](docs/operations-defaults.md) · [Changelog](CHANGELOG.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

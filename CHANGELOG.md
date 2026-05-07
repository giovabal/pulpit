# Changelog

## [0.18] - To be announced
*Alternative graph layouts and styles. A few more measures and channels details. Polls and quizzes.*

### New features
- **Alternative 2D graph layouts** — `structural_analysis` gains an `--extra-layouts` flag (values: `CIRCULAR`, `SPECTRAL`, `SPRING`, `ALL`) that pre-computes additional spatial layouts alongside ForceAtlas2 and stores each as `data/channel_position_<algo>.json`. When extras are present, a **Layout** dropdown appears in the Options panel of `graph.html`, letting users switch between them with a smooth animated transition at viewing time — no re-export required. Available as checkboxes in a dedicated **Extra 2D layouts** fieldset in the Operations panel.
- **Layouts, themes, and coloured-edges toggle in 3D graph** — `graph3d.html` now matches the Options panel of `graph.html`. The *Analysis* tab gains a **Layout** dropdown (ForceAtlas2 + any extras from `--extra-layouts`, with a 600 ms animated transition; reuses the same 2D layout JSON files with z = 0). The *Styles* tab gains a **Theme** selector (dark / light / minimal / print, shared via `localStorage` with the 2D graph) and a **Coloured edges** toggle. Theme changes update the Three.js scene background, edge opacity, and CSS label colours immediately.
- **Structural similarity matrix (`structural_similarity.html`)** — new standalone page generated with `--structural-similarity` (CLI) or the matching Operations panel checkbox. Shows a lower-triangle SVG heatmap of pairwise cosine similarity between all channels, where each channel's feature vector spans all computed network measures (PageRank, betweenness, degree, Burt's constraint, spreading efficiency, content originality, etc.). Measures are min-max normalised per column before cosine computation so every dimension contributes equally; `None` values (e.g. `burt_constraint` on isolated nodes) are treated as 0; diagonal forced to 1.0. Color scale: white → steel-blue. Interactive sort: by community (block-diagonal view) or by any individual measure. Pre-computed in Python and stored as `data/structural_similarity.json` (lower-triangle float matrix). Documented in `docs/whole-network-statistics.md` and `docs/export-formats.md`. Also fixes a pre-existing issue where `--html`, `--consensus-matrix`, and any other HTML-only output would silently fail to copy `js/` and `css/` static assets unless `--2dgraph` was also selected.
- **Partition agreement matrix (NMI) in `network_table.html`** — when two or more community strategies are active, a new section shows the Normalised Mutual Information between every pair of strategies as a heatmap matrix. NMI = 1 means the two partitions are identical up to label permutation; NMI = 0 means they are statistically independent. Each pair is computed on the intersection of channels assigned in both strategies, which handles `ORGANIZATION` (which silently skips unassigned channels) correctly. The matrix also appears in `network_table.xlsx`. Formula: NMI(U,V) = 2·I(U;V) / (H(U)+H(V)) (Kvalseth 1987; Fred & Jain 2003). Documented in `docs/whole-network-statistics.md`.
- **`--self-references` flag** — `structural_analysis` gains a `--self-references` / `--no-self-references` flag (default: off). When on, cases where a channel forwards from or mentions itself are included as self-loop edges and contribute to edge weights and centrality measures. Off by default because self-loops carry no network-structural information and have no effect on most centrality measures. Available as an **Include self-references** checkbox in the Edge weights fieldset of the Operations panel.
- **Self-reference filter on Forwards received tab** — the *Forwards received* tab on channel detail pages gains a select control with three options: *Include self-references* (default), *Do not include self-references*, and *Show only self-references*. A self-reference occurs when a channel re-posts its own content, making it appear among its own forwards received. The selection is preserved across pagination.
- **Self-loop rendering in 3D graph** — when `--self-references` is on, self-loop edges were previously invisible in `graph3d.html` because the Bézier control point collapsed to the node position. They now render as a small arch above the node, sized proportionally to the node's radius (`arm = 1× radius`, `peak = 3.5× radius`).
- **Custom and sticker reactions tallied under a `"custom"` bucket** — `_save_reactions()` previously skipped custom-emoji and sticker reactions entirely, understating total reaction counts on channels whose communities use custom emoji packs. All non-standard reactions are now aggregated into a single `MessageReaction` row with `emoji="custom"` and the summed count. Plain emoji reactions are stored individually as before.
- **Separate forward and mention edge weights in GEXF, GraphML, and CSV exports** — `weight_forwards` and `weight_mentions` are now stored as distinct edge attributes alongside the combined `weight` in all three export formats. Both carry the raw forward/mention counts (before any normalisation) from which `weight` is derived, letting analysts distinguish deliberate reposting (forwards) from inline link citations (mentions) in downstream tools such as Gephi, R/igraph, and pandas.
- **CSV export** (`--csv`) — `structural_analysis` gains a `--csv` flag that writes two files alongside the existing outputs: `nodes.csv` (one row per channel, same columns as `channel_table.xlsx` — label, URL, subscribers, messages, in/out-degree, all computed measures, community assignments, activity period) and `edges.csv` (five columns: `source_label`, `target_label`, `weight`, `weight_forwards`, `weight_mentions`, where `weight_forwards` and `weight_mentions` are the raw forward/mention counts before normalisation). Available as a **CSV files** checkbox in the Operations panel alongside the GEXF and GraphML options.
- **Label propagation** (`LABELPROPAGATION`) — new community detection strategy. Uses the semi-synchronous label propagation algorithm (Cordasco & Gargano 2010 / Raghavan et al. 2007): each node starts with a unique label and iteratively adopts the majority label of its neighbours until convergence. Parameter-free, deterministic, and runs in near-linear time — suited as a fast baseline for large graphs where Infomap or MCL are slow. The graph is symmetrised to undirected before running; edge weights are not used.
- **Local clustering coefficient** (`LOCALCLUSTERING`) — new node measure for `structural_analysis`. Computes the directed local clustering coefficient (Fagiolo 2007) for each channel: the fraction of directed triangles through the node relative to all possible directed triads. A high score means the channel is directly embedded in closed citation cycles — mutual amplification loops with specific neighbours. Pairs with `EGODENSITY` to distinguish channels at the edge of a clique (high ego density, low clustering) from active participants in circular amplification (high on both). Nodes with total degree < 2 receive 0.0. Available in `--measures` and the Operations panel Measures grid.
- **Closeness centrality** (`CLOSENESS`) — new node measure for `structural_analysis`. Computes in-closeness centrality for each channel: the Wasserman-Faust normalised score reflecting how easily the rest of the network can reach this channel along citation paths. Channels with high closeness are structurally well-positioned to receive information quickly — they sit at the convergence of many short incoming paths. Isolated nodes and nodes outside the main component receive 0.0. Available in `--measures` and the Operations panel Measures grid.

- **Reply threads stored and displayed** — `crawl_channels` gains a `--fetch-replies` flag (step 10 in the Operations panel). For each interesting channel with a `linked_chat_id`, it iterates the linked discussion group with `reply_to=<post_id>` and upserts individual reply messages as `MessageReply` records (sender name, date, text, views). Re-running is idempotent. A new JSON endpoint (`GET /channel/<pk>/message/<telegram_id>/replies/`) serves stored replies; `fetched=false` signals that replies exist but have not been crawled yet. On every post card a pill button **💬 N** appears when `replies > 0`; clicking it lazy-loads the replies panel inline with a spinner, rendering each reply as a small card.
- **"More details" panel on post cards** — every message now has a circular ⓘ button in the footer that toggles a collapsible panel showing the new Telethon-sourced message metadata: reply count, reply-to message ID, original source post ID (provenance), forwarded-from user name, silent flag, and Telegram's built-in fact-check annotation (with a "Needs check" badge when flagged). Falls back to "No additional details available" when all fields are absent.
- **Poll and quiz storage** — the crawler now captures Telegram polls and quizzes. Each poll message gets a `Poll` record (question text, closed/quiz/multiple-choice/public-voters flags, optional close date) plus one `PollAnswer` row per option (answer text, vote count, and — for quizzes — a `correct` flag). Total voter count and the quiz solution text are also stored. Poll data is created on the initial crawl and updated on every stats refresh so vote counts stay current. Messages with a poll get `media_type = "poll"`. The `Poll` model is accessible in Django admin with an inline answer table.

### Improvements
- **Extended Telethon fields on `Channel` and `Message`** — 14 additional fields that Telethon already exposes are now persisted at zero extra API cost. On `Channel` (all from `ChannelFull`): `boosts_applied` and `boosts_unrestrict` (boost count and headroom — proxy for engaged fan base), `kicked_count` and `banned_count` (moderation intensity), `antispam` (Telegram's automated anti-spam active), `has_scheduled` (editorial planning signal), `pinned_msg_id` (currently pinned message ID), `migrated_from_chat_id` (channel origin — was it upgraded from a group?). On `Message`: `replies` (comment/reply count, refreshed alongside views and forwards), `silent` (sent without notification), `reply_to_msg_id` (enables reply-thread analysis), `fwd_from_channel_post` (original message ID in the source channel — provenance tracing), `fwd_from_from_name` (display name when forwarded from a user rather than a channel), `post_author` (author's name), `edit_date` (edits made after initial amplification), `factcheck` (Telegram's built-in fact-check annotation, stored as JSON with `need_check`, `country`, and `text` — useful for disinformation research).
- **Stats refresh also updates message text, webpage metadata, and fact-check labels** — `refresh_message_stats` previously re-fetched views, forwards, replies, pinned state, edit date, post author, and reactions, but not fields that can silently change after publication. It now also updates `message` (edited text), `webpage_url` and `webpage_type` (link-preview metadata), and `factcheck` (fact-check annotations that Telegram can add or remove at any time after a post goes live).
- **README rewritten** — restructured as a comprehensive landing page for both non-technical and specialist readers. Adds a *Questions you can answer* section with concrete per-channel, community, and over-time questions linked to specific measures; expands the outputs table to reflect all current files; splits the measures reference into three thematic groups (Influence & reach / Position & brokerage / Content & dynamics); adds a dedicated Vacancy Analysis section with the full scoring table; updates the community detection table with a direction-aware column; and corrects the measure count from 14 to 15.

### Fixes
- **Stats refresh no longer downloads missing media** — `refresh_message_stats` was silently triggering photo and video downloads for messages that had no locally stored media, turning a lightweight stats update into a potentially expensive media fetch. It now strictly updates counters and text fields and leaves media untouched.
- **"N new messages" count no longer includes service events** — Telegram service events (pin changes, admin promotions, linked-group updates, etc.) have their own message IDs and were previously counted as new messages even though they are never stored in the database. The completed-channel status line now only counts messages that were actually written to the DB.

## [0.17] - 2026-04-05
*Vacancy succession batch analysis. Documentation rewrite. Channel details.*

### New features
- **Automatic linked group discovery** — when `crawl_channels` fetches extended metadata for a channel, any linked discussion group returned in the API response is automatically added to the database if not already present. Newly created groups inherit the parent channel's organisation. Channel groups are also propagated. Channel detail pages for discussion groups now show a **Parent channel** link pointing back to their broadcast channel (resolved from either the group's own `linked_chat_id` or the reverse lookup).
- **`uninteresting_after` date cutoff on channels** — each `Channel` gains an optional `uninteresting_after` date field. When set, messages written after that date are silently ignored everywhere: the crawler skips them during both the initial fetch and the stats-refresh pass; the graph builder, all network measures, community stats, and degree computations exclude them; channel detail panels, message lists, and all per-channel time-series charts only show messages up to the cutoff; the channel activity period is bounded accordingly. The field is settable from the channel edit page in the backoffice (`/manage/channels/<id>/`).
- **Vacancy succession batch export** — `structural_analysis` gains a new `--vacancy-measures` flag that scores replacement candidates for every vacancy in the database in one pass and embeds the results in the export. Six algorithms are available:
  - **`AMPLIFIER_JACCARD`** — fraction of orphaned amplifiers that forwarded from the candidate after the closure date (Small 1973).
  - **`STRUCTURAL_EQUIV`** — cosine similarity of shared in-neighbours (amplifiers) and out-neighbours (sources); measures static positional equivalence (Lorrain & White 1971).
  - **`BROKERAGE`** — Jaccard of (source-org × amplifier-org) pairs; measures whether the candidate replicates the same inter-organisational brokerage role (Gould & Fernandez 1989).
  - **`CASCADE_OVERLAP`** — Jaccard of SIR diffusion reach sets: who did the vacancy's content reach before closure vs. who does the candidate's content reach after? Monte Carlo, reuses `--spreading-runs`. Computationally intensive (Kermack & McKendrick 1927; Watts & Dodds 2007).
  - **`PPR`** — Personalized PageRank on the reversed graph with teleportation concentrated on the orphaned amplifiers; scores how deeply the candidate is embedded in their upstream content supply chain (Haveliwala 2002). Damping factor tunable via `--vacancy-ppr-alpha`.
  - **`TEMPORAL`** — coverage-weighted inverse mean days-to-first-adoption with a 30-day half-life; rewards candidates adopted quickly by many orphaned channels.
  - `ALL` selects all six. When at least one measure is selected, `data/vacancy_analysis.json` and `vacancy_analysis.html` are written; the export `index.html` gains a **Vacancy Analysis** section linking to the page.
- **Vacancy Analysis fieldset in Operations panel** — the Structural Analysis card now includes a **Vacancy Analysis** fieldset with six measure checkboxes, four parameter inputs (Months before, Months after, Max candidates, PPR α), and a link from Cascade Overlap to the shared **Spreading runs** parameter. All six measures are pre-checked automatically when any vacancy exists in the database; all are unchecked when none exist.
- **All / None buttons in Operations fieldset legends** — the **Measures**, **Community strategies**, **Network stat groups**, and **Vacancy Analysis** fieldsets in the Structural Analysis card each gain two small **All** / **None** buttons inline in the legend. Clicking them toggles all checkboxes in that group in one click.
- **Reset button in Operations panel** — a Reset button appears next to Abort whenever a task is in `failed` or `done` state. Clicking it clears the task status back to `idle` (deletes the meta file) and hides the log panel without reloading the page.
- **`structural_analysis --no-mentions`** — new `--mentions`/`--no-mentions` flag (default: on). When off, t.me/ reference links are excluded from edge construction and only true message forwards are used to build the graph. Available as an **Include mentions as edges** checkbox in the Edge weights section of the Operations panel.
- **`crawl_channels` metadata pass for type-excluded channels** — when `--get-new-messages` is run with `--channel-types` set to a subset, interesting channels excluded by type now still receive profile picture and participant count updates.
- **Reactions per month chart** on channel detail page — stacked bar chart showing the top 8 emoji reactions month by month, loaded lazily like other channel panels.
- **Forwards card edge count** on home page — the Forwards summary card now shows the number of distinct inter-channel connections (unique forwarded-from pairs) as secondary information.
- **Two-tab message view on channel detail page** — the message list is now split into two tabs: *Messages* (own messages, with a new *Forwards only* filter option) and *Forwards received* (messages from other monitored channels that forwarded this channel's content, each showing the amplifying channel). Tab selection and filters are preserved across pagination.

### Improvements
- **Documentation rewritten for non-technical readers** — `docs/getting-started.md` and `docs/workflow.md` are rewritten for journalists, activists, and researchers with no programming background. Prerequisites now include plain-English explanations and download links; install steps are numbered with context for each command; Telegram credentials reframed as account linking; database setup simplified to SQLite-first with server-database migration moved to an Advanced section; troubleshooting section added. Workflow now leads with human goals rather than command names; `is_interesting` and other internal jargon removed from the main text; options tables trimmed to first-run essentials; all CLI commands consolidated into a single appendix.
- **Detail-page button in manage channels list** — each row in the backoffice channels list (`/manage/channels/`) now shows an eye-icon button on hover that opens the channel's detail page on the main site.
- **Extended channel metadata** — 13 new fields fetched at zero extra API cost and displayed in the channel detail meta row: `noforwards` (content protection), `forum`, `join_to_send`, `join_request`, `level` (boost level) from the Channel object; `extra_usernames`, `linked_chat_id` (resolved to a link when the channel is in the DB), `available_min_id` (oldest accessible message — signals deleted history), `slowmode_seconds`, `admins_count`, `online_count`, `requests_pending`, `theme_emoticon` from ChannelFull. Fields indicating data loss (`noforwards`, `available_min_id`) are highlighted in amber.
- **Message auto-delete timer (`message_ttl`) stored per channel** — Telegram's per-channel message TTL (in seconds) is fetched from `ChannelFull.ttl_period` and persisted on every crawl. When set, the channel detail page shows an amber "Auto-delete: 1 week" (or equivalent) meta item.
- **`restriction_reason` stored per channel** — Telegram's per-platform restriction metadata (platform, reason, text) is now persisted as a JSON field and updated on every crawl. Individual restrictions are shown as meta items on the channel detail page (e.g. `ios: porno`).
- **Lost and private channels are now first-class in the web UI** — their detail pages show the full set of panels, charts, and message lists (same as active channels); in the channel list they appear before the type-excluded section with their profile picture, ungreyed, without a toggle; the graph builder includes lost channels in the analysis. A new **Retry lost & private** option in the `crawl_channels` Scope panel includes those channels in the crawl scope: each is resolved at its turn, its flag is updated, and if now accessible it is crawled normally.
- Full documentation rewrite: new `docs/` directory with nine interconnected Markdown files ([Getting started](docs/getting-started.md), [Workflow](docs/workflow.md), [Network measures](docs/network-measures.md), [Community detection](docs/community-detection.md), [Whole-network statistics](docs/whole-network-statistics.md), [Vacancy analysis](docs/vacancy-analysis.md), [Web interface](docs/web-interface.md), [Export formats](docs/export-formats.md)); README rewritten as a landing page for researchers, journalists, and activists; academic references hyperlinked throughout; image placeholders for up to 20 screenshots.
- Messages are now sorted newest-first by default on all listing views (home feed, message search, channel detail).

### Fixes
- Fixed `ValueError: The 'picture' attribute has no file associated with it` in the channel detail template and graph builder when a `ProfilePicture` or `MessagePicture` row exists but its `ImageField` has no file.
- Removed the **Cumulative subscribers** chart from the home page; `participants_count` is a current snapshot and cannot produce meaningful historical data.
- **`is_private` / `is_lost` disambiguation** — `ChannelPrivateError` from a bare numeric lookup is now treated as ambiguous (Telegram returns it for both genuinely private and deleted channels). The crawler runs the full access_hash + username fallback chain before deciding; a stale `access_hash` (ChannelInvalidError) clears the tentative private flag so the username lookup is always attempted. Only a confirmed `ChannelPrivateError` from the fallbacks marks a channel as private; all other unresolvable paths mark it as lost.
- **`crawl_channels` operations panel: visibility and scope fixes** — reference retry, mine-about-texts, fetch-recommended, and fix-missing-media steps now all respect the DB id filter; only Refresh degrees remains global (tooltip explains why). Non-TTY progress output (operations panel) now emits newlines so steps are visible during long runs. `GetChannelRecommendationsRequest` failures on restricted channels are caught and skipped. Refresh degrees emits progress lines during the slow query phase.
- **Crawl step numbering corrected** — the Operations panel now numbers the crawl steps in actual execution order: Fetch recommended channels moves to step 7, Fix missing media to step 8, and Refresh degrees to step 9 (last). Degrees are recomputed after all channel-discovery steps so the result reflects any channels added by Mine about texts or Fetch recommended channels.
- **Channel count consistency between home page and structural analysis** — the home page now counts lost channels (`is_lost=True`) alongside active ones, matching the graph builder; the graph builder now excludes private channels (`is_private=True`), matching the home page. Previously the two counts diverged because each applied a different subset of the `interesting()` manager's filters.

### Backward incompatibility
- **`get_channels` renamed to `crawl_channels`** — the management command, Operations panel card title, runner tasks, and all documentation now use the name `crawl_channels`.

## [0.16] - 2026-05-01
*Vacancy Analysis. Multiple, atomic and reproducible exports.*

### New features
- **Vacancy analysis** — analysts manually designate channels as structural vacancies via a new `ChannelVacancy` model (channel, closure date, note), managed from the backoffice under **Manage → Vacancies**. The **Channels → Vacancies** page (`/channels/vacancies/`) lists all vacancies with in-degree, out-degree, and orphaned-amplifier count. On the channel detail page, any channel with a vacancy record gains a **Vacancy Analysis** card: a small form with configurable *Months before* (default 12), *Months after* (default 24), and *Only after vacancy* controls; submitting re-runs the analysis and populates a sortable table of replacement candidates — channels forwarded by the orphaned amplifiers after the closure date, scored by three academically validated metrics: **Structural equivalence** (cosine similarity of in- and out-neighbor vectors; Lorrain & White 1971) and **Brokerage role** (Jaccard similarity of organisation-pair sets bridged before vs. after; Gould & Fernandez 1989). All table columns — Channel, First activity, Structural equivalence, Brokerage, Amplifiers, Last forwarded — are sortable by clicking the header.
- **Lateral navigation menu in horizontal graph layout** — when a graph is exported with the default horizontal layout (`--vertical-layout` not set), the navigation bar in `graph.html` and `graph3d.html` is now a vertical pill docked to the left edge of the screen, vertically centred. When `--vertical-layout` is used the bar remains at the bottom centre as before. The layout flag is injected as `window.VERTICAL_LAYOUT` into each HTML file at export time so the correct layout is applied without a network round-trip.
- **ChannelGroup `note` field** — channel groups gain a free-text `note` field (in addition to the existing `description`). Visible and editable in the backoffice Groups section as an inline column in the table and a textarea in both the add form and the inline edit row. Exposed by the `/manage/api/groups/` API.
- **`export_network` renamed to `structural_analysis`** — the management command and Operations panel card are now called `structural_analysis` / **Structural Analysis** to better reflect that the step does far more than export: it builds the graph, computes all centrality and influence measures, runs community detection, and lays out the network before writing any output.
- **Ego network density** (`EGODENSITY`) — new node measure for `structural_analysis`. For each channel, computes the density of directed edges among its immediate neighbours (predecessors ∪ successors, ego excluded): 0 means none of the neighbours connect to each other (the channel is a hub between disconnected sources); 1 means they form a fully connected clique (echo chamber). `null` for nodes with fewer than two neighbours. Directional (uses edge direction in the neighbour subgraph). Available in `--measures` and the Operations panel Measures grid.
- **`compare_networks` renamed to `compare_analysis`** — the management command and Operations panel card are now called `compare_analysis` / **Compare Analysis**.
- **Operations panel pipeline ordering** — the four task cards (Search Channels, Get Channels, Structural Analysis, Compare Analysis) are now displayed in workflow order and numbered 1–4 with a badge on each card icon. Faint arrow connectors between cards make the sequential nature explicit.
- **Get Channels numbered crawl steps** — the options in the Crawl fieldset are now listed vertically in execution order and numbered 1–9: Get new messages, Fix message holes, Retry unresolved references, Force-retry dead references, Refresh message stats, Mine about texts, Refresh degrees, Fetch recommended channels, Fix missing media.
- **Mine about texts and Refresh degrees as selectable options** — two steps that previously ran unconditionally after every `crawl_channels` call are now opt-in: **Mine about texts** (scan `about` fields for `t.me/` links and fetch unknown channels, `--mine-about-texts`) and **Refresh degrees** (recompute stored in-degree and out-degree for all interesting and cited channels, `--refresh-degrees`). Both appear as numbered steps in the Operations panel Crawl list.
- **Refresh message stats moved into the pipeline** — the Refresh message stats checkbox is now step 5 in the numbered crawl pipeline rather than a separate fieldset, and the Refresh limit input remains visually connected to it via the linked-parameter pattern.
- **Retry unresolved references as a selectable option** — the reference-resolution step (`get_missing_references`) is now opt-in via a new **Retry unresolved references** checkbox (Operations panel step 3) and `--retry-references` CLI flag. Previously it ran unconditionally on every `crawl_channels` invocation. Force-retry dead references (step 4) is now visually linked to it: the chip greys out and its checkbox is disabled when Retry unresolved references is unchecked.
- **Linked-parameter pattern extended to flag chips** — the `data-requires-flag` dependency wiring that disables inputs when a controlling checkbox is off now also works for flag chips (checkbox labels), not just text/number inputs. Used by Force-retry dead references depending on Retry unresolved references.
- **Refresh message stats linked parameter** — the Refresh limit input in Get Channels is now wired as a linked parameter of the Refresh message stats checkbox: the input greys out when the checkbox is off. The checkbox also gains a sliders icon indicating it has a linked parameter, consistent with the pattern used in Measures and Community strategies.
- **Named exports** — `structural_analysis` now writes to `exports/<name>/` instead of a single shared `graph/` directory, so multiple exports can coexist without overwriting each other. The `--name` flag sets the export name; if omitted, a `YYYYMMDD-HHMMSS` timestamp is used. A `summary.json` is written to every export root capturing the name, timestamp, node/edge counts, and all CLI options used.
- **Options import from previous exports** — the Structural Analysis card in the Operations panel has a *Previous exports* picker that lists all exports by name and date. Selecting one restores every form control (measures, community strategies, filters, layout options, etc.) from that export's `summary.json`, making it easy to replicate or tweak a past run.
- **Export name field with timestamp default** — the *Export name* input in the Operations panel is pre-filled with the current timestamp on page load so every run is named without manual input.
- **Multi-export `/data/` page** — `/data/` detects all exports in `exports/*/` and, when more than one exists, shows a pill-style picker at the top of the page. Selecting an export via `?export=<name>` updates all graph, table, and comparison card links to point to that export's files, served at `/exports/<name>/`.
- **Atomic export writes** — `structural_analysis` now writes to a `<name>.tmp` staging directory and renames it to `<name>` only after every output file, including `summary.json`, has been written successfully. Aborting or crashing an in-progress run leaves the previous export with the same name untouched (or nothing, on the first run). A stale `.tmp` directory from a previous interrupted run is removed automatically at the start of the next run. `GraphDirsView` and `ExportsListView` in the Operations panel skip `.tmp` and `.old` directories, so staging and backup artefacts never appear as selectable exports.
- **Compare Analysis `--target`** — `compare_analysis` gains a required `--target <name>` flag that specifies which named export to write comparison files into (`exports/<name>/`). The Operations panel Compare Analysis card gains a matching *Target export* field with a picker.

### Backward incompatibility
- The `graph/` output directory is no longer used. All exports go to `exports/`. The `/graph/` static route has been removed.
- `export_network` is renamed to `structural_analysis`. Update any scripts, aliases, or cron jobs accordingly.
- `compare_networks` is renamed to `compare_analysis`. Update any scripts, aliases, or cron jobs accordingly.


## [0.15] - 2026-04-29
*Competition vs. cohesion metrics. Custom backoffice admin. Reactions.*

### New features
- **E-I Index and Inter-community Edge Ratio** — two new metrics for evaluating structural competition versus cohesion. The **E-I Index** (Krackhardt & Stern 1988) is computed per community as *(external − internal) / (external + internal)*; range −1 (fully cohesive) to +1 (fully competitive). A weighted **Mean E-I Index** summarises the whole network's balance. The **Inter-community Edge Ratio** is the raw fraction of all directed edges that cross community boundaries. Both appear in the strategy table in `network_table.html` and `network_table.xlsx`; E-I Index also appears as a column in `community_table.html` and `community_table.xlsx`. Documented in `ANALYSIS.md`.
- **Network cohesion metrics** — four new academically validated measures appear in a dedicated *Cohesion* group in the Network Statistics table and XLSX: **Transitivity** (global clustering coefficient, fraction of closed triads; Luce & Perry 1949 / Watts & Strogatz 1998), **Global Efficiency** (mean reciprocal directed path length over all node pairs, handles disconnected graphs gracefully; Latora & Marchiori 2001), **Algebraic Connectivity** (Fiedler value λ₂ of the graph Laplacian, zero for disconnected graphs, larger for more robust networks; Fiedler 1973), and **In/Out-degree CV** (coefficient of variation of the degree distributions, quantifies hub concentration; Pastor-Satorras & Vespignani 2001). All four are documented in `ANALYSIS.md`.
- **Directed Avg Path Length and Directed Diameter** — the mean and maximum directed shortest-path distances computed on the largest strongly connected component (SCC), following edge direction. Complement the existing undirected path metrics. A ‡ footnote appears when the SCC is smaller than the full graph.
- **Backoffice admin** (`/manage/`) — new staff-only app replacing Django admin for day-to-day data management. Powered by a Django REST Framework JSON API (`/manage/api/`). Six sections: **Channels** (searchable/filterable table with inline org assignment, group chip management, and bulk assign/group operations for hundreds of channels at once), **Organizations** (inline CRUD with color picker and is_interesting toggle), **Groups** (inline CRUD), **Search Terms** (add-by-Enter list), **Events** (event types + events with date and type filters), **Users** (create/edit/delete Django users; email is used as the username). A *Manage* button appears in the top navigation for staff users.
- **Message reactions** — emoji reactions are now collected for every message during crawling (initial fetch and stats refresh) and stored in a new `MessageReaction` model. Per-message reactions appear as inline chips in the channel detail message list. A channel-level breakdown of the top 10 emoji reactions by total count is shown just above the stats graphs, and a *Total reactions* summary card is added when reactions are present.
- **Selectable whole-network stat groups** (`--network-stat-groups` / *Network stat groups* in the Operations panel): the seven groups of whole-network structural metrics (`SIZE`, `PATHS`, `COHESION`, `COMPONENTS`, `DEGCORRELATION`, `CENTRALIZATION`, `CONTENT`) can now be selected independently, mirroring how `--measures` and `--community-strategies` work. Default is `ALL`. Each group gates both the computation and the table output; deselecting `PATHS` (path lengths, reciprocity, clustering) and `COHESION` (global efficiency, algebraic connectivity) skips the expensive O(n·m) BFS and eigendecomposition steps on large networks.
- **ChannelGroup model** — channels can now be assigned to one or more named groups via Django admin. Groups appear as checkbox filters in the Get Channels and Export Network Operations panel cards; selecting one or more groups restricts the run to channels in those groups. CLI flags `--channel-groups` (comma-separated) are added to both `crawl_channels` and `export_network`.
- **Ad-hoc search terms in the Operations panel**: the Search Channels card now has an *Extra search terms* textarea (one term per line). Terms entered there are searched alongside the database terms for the current run only. A *Save to database* checkbox (enabled only when the textarea has content) persists the terms as new `SearchTerm` records (lowercased, deduplicated) before the task launches. The `search_channels` management command gains a corresponding `--extra-term` flag that can be repeated.

## [0.14] - 2026-04-27
*Year-by-year timeline export. Layout improvements.*

### New features
- **Timeline export** (`--timeline-step year` / *Timeline by year* in the Operations panel): repeats the full export pipeline for each calendar year present in the message data. Produces per-year data directories (`data_YYYY/`) and optional per-year HTML tables and spreadsheets. A `data/timeline.json` index is written listing every generated year.
- **Year switcher in `graph.html` and `graph3d.html`**: when `data/timeline.json` is present, a compact year navigator appears in the bottom navigation bar of both the 2D and 3D graphs: **[←]** / **[→]** step through years in order, **[All]** returns to the full-range view, and the current-year button opens a scrollable dropup list for direct access to any year. All year datasets are preloaded during the initial spinner; switching is instant. The 3D graph animates the camera smoothly to the new year's bounding box alongside the node transition.
- **Timeline sparklines in `network_table.html`**: when a year-by-year timeline has been exported, each row in the Network Statistics table shows a mini bar chart between the metric label and its value. The first bar represents the full-range ("All") value in blue; subsequent bars show each year's value in gray. The active view's bar is highlighted in solid blue. Hovering a bar shows the exact value.
- **In-page year switcher for all three HTML tables**: `channel_table.html`, `network_table.html`, and `community_table.html` now share a single-page year navigator identical in spirit to the graph views. Clicking a year button re-fetches and re-renders the page content without a reload; fetched data is cached so revisiting a year is instant. The degree-distribution and scatter charts on the Network Statistics page update in place when the year changes.
- **Timeline XLSX as multi-sheet workbooks**: when a year-by-year timeline is exported, the three spreadsheet files (`channel_table.xlsx`, `network_table.xlsx`, `community_table.xlsx`) now contain one sheet per time range — **All** for the full-range view plus one sheet per calendar year — instead of producing separate per-year files. The community table uses one sheet per year, with all strategies listed sequentially within each sheet.
- **In-page year switcher for `consensus_matrix.html`**: the consensus matrix page now follows the same single-page year-switching pattern as the other table pages.
- **On-demand per-channel sparklines in `channel_table.html`**: each channel row gains a small bar-chart button (visible when a timeline is present). Clicking it lazily fetches all per-year `channels.json` files in parallel (cached after the first load) and expands inline mini bar charts next to every numeric measure cell, showing how that channel's metrics evolved year by year. The Users column is excluded (subscriber counts are not per-year). Open rows survive year switches — charts re-render with the newly selected year highlighted.
- **Compare Networks directory scanner**: the *Project directory* field in the Compare Networks panel now has a **Find exports** button. It queries a new `/operations/graph-dirs/` endpoint that scans sibling directories for valid graph exports, reading `data/meta.json` to surface project title, export date, and node count. Results appear as a scrollable picker; clicking a row fills the path input.

### Improvements
- New fonts and reworked details for most of the webapp and HTML output.
- Operations panel: measures and community strategies now rendered as chip checkboxes instead of a multi-select list. Each chip carries a directional (`→`) or undirectional (`↔`) icon indicating whether the algorithm uses edge direction or symmetrises the graph first. ORGANIZATION carries no icon as it is metadata-based.

## [0.13] - 2026-04-20
*New community detection algorithms. Consensus matrix. Events timeline.*

### New features
- `LEIDEN_CPM_COARSE` and `LEIDEN_CPM_FINE`: Leiden optimisation with the **Constant Potts Model** (CPM) objective (Traag et al. 2011). Unlike modularity, CPM has no resolution limit — communities are defined as groups whose internal edge density exceeds a resolution parameter γ. The two variants differ only in their default γ (`--leiden-coarse-resolution`, default 0.01; `--leiden-fine-resolution`, default 0.05). Lower γ gives few, large communities; higher γ gives more, smaller ones. Both symmetrise the graph to undirected (same as `LEIDEN`).
- `MCL`: **Markov Clustering** (van Dongen 2000). Alternates matrix expansion (random-walk diffusion) and inflation (contrast amplification) until convergence. Works natively on the directed weighted graph without symmetrisation. The inflation parameter r controls granularity (`--mcl-inflation`, default 2.0; typical range 1.5–4.0).
- `INFOMAP_MEMORY`: **Second-order (memory) Infomap** (Rosvall et al., Nature Communications 2014). Builds a state network of directed-edge contexts — each state node represents "currently at channel B, having arrived from channel A" — and minimises the map equation on it. Captures sequential forwarding patterns invisible to first-order Infomap. Source nodes receive virtual entry states so they participate in the flow.
- `WALKTRAP`: **Walktrap** (Pons & Latapy 2006). Computes short random-walk distances between channels (4 steps) and applies Ward's agglomerative clustering, producing a full dendrogram cut at the modularity-maximising partition. Symmetrises to undirected.
- All four strategies are available in the Operations panel strategy selector and included in the `ALL` shortcut. The three tunable parameters (CPM resolutions, MCL inflation) are exposed as numeric inputs in the Operations panel Computation section.
- **Consensus matrix** (`consensus_matrix.html`): a new standalone page showing a lower-triangle balloon plot where each cell represents a channel pair. The balloon size grows and the colour shifts from blue to red as more non-ORGANIZATION community detection strategies agree in placing the pair in the same community. Channels are sorted by plurality community assignment then by name. A legend shows one circle per agreement level; hovering a cell shows a tooltip. Generated only when `export_network --consensus-matrix` is passed (or the matching checkbox in the Operations panel is ticked). Requires at least one non-ORGANIZATION strategy.
- `data/meta.json` now includes `has_consensus_matrix` (bool) and `community_distribution_threshold` (int). When `has_consensus_matrix` is true, the Community Statistics page injects a **Consensus matrix** button into its navigation bar automatically.
- **Event markers on home-page charts**: each time-series chart on the home page now draws a dashed vertical line for every event whose date falls within the chart's time span. The line color matches the EventType color. Hovering the line shows a popup listing all events in that month (date, action type, subject).
- **Configurable organisation × community distribution threshold** (`--community-distribution-threshold N`, default 10): communities below this percentage in every organisation row are hidden from the cross-tab tables. The threshold is stored in `data/meta.json` and read by the JS at page load, so changing it on re-export is reflected without editing any HTML. Previously hard-coded at 5 %; the new default is 10 %. The value can also be set from the Operations panel (Distribution threshold % field).

### Fixes
- **`ChannelCrawler`: `is_private` not cleared on normal crawl completion**: the non-rate-limited completion path set `is_lost=False` but omitted `is_private=False`, leaving a stale `is_private=True` on channels that had previously been private but were later made accessible. The rate-limited early-exit paths already cleared both flags; the normal path now does the same.
- **`ChannelCrawler`: `is_lost` not cleared when a seed is identified as a user account**: when the `ValueError` fallback determined a numeric seed was a user account, only `is_user_account=True` was set. If the channel had previously been marked `is_lost=True` (e.g. from an earlier failed lookup), that flag persisted. Now `is_lost=False` is set alongside `is_user_account=True`, consistent with the private-channel paths.


## [0.12] - 2026-04-16
*A smoother Telegram interaction. Organisation/community overlapping. Fixes.*

### New features
- Community Statistics table: each algorithm section now includes a collapsible **Organisation × community distribution** panel with two side-by-side cross-tabulation tables. Rows are organisations, columns are community groups. The first table shows what share of each organisation's nodes fall into each community (rows sum to 100%); the second shows what share of each community's nodes come from each organisation (columns sum to 100%). The panel is only shown when the graph contains channels from more than one organisation.
- Network Statistics table: when the graph includes more than one channel type (broadcast channels, groups, user accounts), per-type node counts are now shown as separate rows directly below the total node count.
- Channel list: date range filter to show only channels active in a given period.
- Channel list: two new filter toggles — **Show lost** and **Show private** — reveal channels marked `is_lost` or `is_private` in dedicated sections (both hidden by default); each row carries an inline badge for quick identification.
- Channel detail: **Lost** (red) and **Private** (yellow) badges now appear alongside the existing Verified / Scam / Fake / Restricted badges when the channel has those flags set.
- `crawl_channels`: new `--get-new-messages` flag; message fetching is now opt-in (on by default in the webapp).
- `crawl_channels`: new `--ids` flag replaces the old `--fromid`. Accepts comma-separated IDs and ranges (e.g. `-30, 50-80, 99, 120-`): exact IDs, inclusive ranges, open-ended lower/upper bounds. Tokens are OR-ed; the Operations panel Scope field has been updated to a single text input matching this syntax.
- New `TELEGRAM_SESSION_NAME` setting (default: `anon`) replaces the previously hard-coded Telethon session file name; set it to match an existing `.session` file when running multiple instances.
- New `IGNORE_FLOODWAIT` setting (default: `True`). When set to `False`, any `FloodWaitError` above the auto-sleep threshold causes the crawler to pause for `TELEGRAM_FLOODWAIT_SLEEP_SECONDS` (default: `900`) before continuing instead of immediately skipping to the next item.

### Improvements
- `ChannelCrawler`: when Telethon's session has lost the `access_hash` for a channel, the fallback now first tries a direct `GetChannels` lookup using the `access_hash` stored in the DB before falling back to username resolution. This avoids `ResolveUsernameRequest` flood waits for channels that have no stored username, and reduces unnecessary username lookups for those that do.
- `set_more_channel_details` and `refresh_message_stats` now clear `is_lost` and `is_private` on the channel when they succeed, since a reachable channel is by definition neither lost nor private.
- `Channel` model: new `is_private` boolean field distinguishes channels that returned a `ChannelPrivateError` (marked `is_private=True`) from channels that could not be found at all (marked `is_lost=True`). Both are excluded from all downstream queries — `Channel.objects.interesting()`, the graph builder, `crawl_channels` crawl targets — so private channels are never re-crawled or included in the network.
- `TelegramAPIClient.wait()` now adds a random jitter of up to 0.5 s to each grace-time sleep, reducing the risk of synchronised API bursts across consecutive requests.
- `hole_fixer`: missing IDs are now streamed lazily via a new `iter_hole_ranges()` generator instead of being materialised as a full list, keeping memory usage flat even for channels with very large gaps in their message history.
- `ChannelCrawler`: deferred forwarded-channel lookups (`_pending_forwards`) are now persisted to a new `Message.pending_forward_telegram_id` DB field instead of held only in memory. A hard crash mid-crawl no longer silently discards those links; `_resolve_pending_forwards()` reads from the DB and picks up any leftover entries from previous runs automatically.

### Fixes
- SQLite: enabled WAL journal mode via a `connection_created` signal in `WebappConfig.ready()` and raised the busy-timeout to 30 s. Previously, a concurrent admin save during a crawl could immediately raise `database is locked`; with WAL + timeout the lock contention window shrinks to milliseconds and the write retries automatically before giving up.
- `ChannelCrawler.get_message`: `forwarded_from` and `pending_forward_telegram_id` are now written to the DB immediately after they are determined, before any further processing. Previously they were only persisted by the final `message.save()`; a process kill in that window would leave the message in DB with no forward data and no recovery path (since the message is already within the known ID range and skipped on rerun).
- `crawl_channels`: unresolvable PeerUser entities no longer print a full traceback; a clean warning is emitted instead.
- `crawl_channels` / `ChannelCrawler`: when a numeric Telegram ID cannot be resolved because Telethon has no cached `access_hash`, resolution now falls back to the stored username (via `ResolveUsername`) before giving up; channels are only marked `is_user_account` or `is_lost` after both attempts fail.
- `ChannelCrawler`: `get_entity()` calls for previously-unseen forwarded channels are no longer issued inline during message iteration. They are deferred to a post-crawl pass (`_resolve_pending_forwards`) where each lookup is spaced by the configured grace time, eliminating the burst of API requests that triggered flood waits on channels with many novel forward sources.
- `crawl_channels`: if crawling a channel raises `FloodWaitError`, `_resolve_pending_forwards()` is now guaranteed to run via `try/finally`, preventing deferred forwarded-channel lookups from being silently lost on interruption.
- `ReferenceResolver`: `resolve_message_references()` now collects all references into a set before resolving, eliminating duplicate API calls when the same username appears in both the message text and a `t.me/` entity URL.
- `MediaHandler`: `download_message_picture()` and `download_message_video()` now catch `FileMigrateError`, `FileReferenceExpiredError`, `FileReferenceInvalidError`, and `Message.DoesNotExist`; these transient Telegram errors are logged as warnings instead of interrupting the crawl.
- `MediaHandler._download_media`: file downloads are now wrapped with `asyncio.wait_for` (120 s timeout) run via `client.loop.run_until_complete`, using `inspect.unwrap` to reach the raw async coroutine beneath Telethon's sync shim. Previously, a stalled Telegram CDN transfer would cause Telethon's asyncio event loop to spin at 100% CPU and hang the entire crawl indefinitely.
- Operations panel command output now always shows a subtle vertical scrollbar.
- `crawl_channels` and `search_channels` no longer inherit from `AsyncBaseCommand`; they use plain `BaseCommand` since both commands are fully synchronous. This eliminates spurious `Task was destroyed but it is pending!` and `ResourceWarning: unclosed StreamWriter` noise caused by `AsyncBaseCommand` creating an event loop that conflicted with Telethon's internal async cleanup.

## [0.11] - 2026-04-11
*Reworking commands options. Reworking tables presentation.*

### New features
- Channel detail page now includes a lazy-loaded **Domains & emails** panel listing all non-Telegram domains and email addresses found in the channel's messages, sorted by frequency.
- Channel detail page now includes a lazy-loaded **Channel connections** panel with two tables: channels mentioned by this channel (forwards sent + t.me references) and channels that mention it (forwards received + t.me references from interesting channels), each row linking to the internal page and to Telegram.
- Network Statistics table now includes a lazy-loaded **degree distribution** bar chart (bins of 10 links), switchable between forwards received and forwards sent.
- Network Comparison table now includes the same degree distribution chart showing both networks side by side, and power-law trend lines for each network in the measure comparison scatter plot.
- New `DEFAULT_CHANNEL_TYPES` `.env` option (comma-separated; default `CHANNEL`): sets which Telegram entity types are considered monitored throughout the app — used as the default for `crawl_channels --channel-types` and `export_network --channel-types`, and applied by `Channel.objects.interesting()` everywhere channels are filtered by monitoring status. Operations panel channel-type checkboxes reflect the setting on page load.
- `crawl_channels` now accepts `--channel-types` (same values and default as `export_network`).
- `crawl_channels --fix-missing-media`: after crawling, identifies photo and video messages whose media file is absent from disk or was never downloaded, and re-fetches them from Telegram. Available as a checkbox in the Operations panel.

### Improvements
- Generated HTML tables overhauled for scientific rigor: metric grouping with labeled sub-headers, normalization range annotations (e.g. "Density (0–1)"), interpretive tooltips on all column headers, em-dash for undefined values, `†` footnote symbol for WCC-only metrics, column reordering with group separators (Network position / Influence / Structural / Content / Communities), merged Activity column, rank column (#), 3 significant figures for continuous measures, diverging heatmap for Burt's Constraint, mean ± SD footer row, default sort by size in community table, External Fraction and Modularity Contribution columns in community table, table preambles populated from a new `data/meta.json` export artifact, and locale-aware thousands separators.
- Network Statistics and Network Comparison tables: added **Edges / Nodes** row after Edges in the whole-network metrics summary.
- Generated table pages footer now shows the Pulpit logo instead of plain text.
- `crawl_channels` now permanently marks unresolvable message references (deleted or invalid channels) with a dead flag so they are skipped on subsequent runs, avoiding redundant Telegram API calls. A new `--force-retry-unresolved-references` flag (and matching Operations panel checkbox) overrides this and retries all references including dead ones.

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
- `FETCH_RECOMMENDED_CHANNELS` `.env` option removed; use `crawl_channels --fetch-recommended-channels` instead.
- `FA2_ITERATIONS` and `LAYOUT` `.env` options removed; use `export_network --fa2-iterations N` and `export_network --vertical-layout` instead.
- `NETWORK_MEASURES`, `COMMUNITY_STRATEGIES`, `EDGE_WEIGHT_STRATEGY`, `RECENCY_WEIGHTS`, `SPREADING_RUNS`, `DRAW_DEAD_LEAVES`, and `CHANNEL_TYPES` `.env` options removed; pass them as `export_network` flags instead. Defaults are unchanged: `--measures PAGERANK`, `--community-strategies ORGANIZATION`, `--edge-weight-strategy PARTIAL_REFERENCES`, `--channel-types CHANNEL`; `--recency-weights`, `--spreading-runs`, and `--draw-dead-leaves` are opt-in.

## [0.10] - 2026-04-07
*Commands management. Access control. Multiple database support.*

### New features
- New **Operations panel** (`/operations/`) in the webapp for launching and monitoring management commands (`crawl_channels`, `search_channels`, `export_network`) directly from the browser. Each task runs as a background subprocess; live output streams into a terminal-style log panel with 1-second polling. Commands can be aborted via SIGTERM.
- New `WEB_ACCESS` setting with three modes: `ALL` (default, no auth required), `OPEN` (admin and operations require a staff account), `PROTECTED` (all pages require login; admin and operations require staff). Includes a login form styled consistently with the rest of the webapp. Staff accounts are managed through Django's user system (`python manage.py createsuperuser`).
- PostgreSQL, MySQL, MariaDB, and Oracle support via `DB_ENGINE` in `.env`. SQLite remains the default. Each backend requires its own driver installed separately (`psycopg2-binary`, `mysqlclient`, or `oracledb`). MySQL/MariaDB connections use `utf8mb4` charset.
- `export_network --graphml` writes `graph/network.graphml` with all computed measures and community assignments embedded as node attributes, compatible with R/igraph, NetworkX, yEd, and any GraphML-aware tool.

### Improvements
- Message options (sort / content-type filter) for the search bar.
- Channels page: organization filter select and 4-column grid layout.
- `crawl_channels` now mines the `about` field of all channels in the DB for `t.me/` links after the main crawl loop, fetching any referenced channels not yet in the database (zero extra API calls for already-known channels).
- `crawl_channels` optionally fetches Telegram-recommended channels for each interesting channel (`FETCH_RECOMMENDED_CHANNELS=True` in `.env`).
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
- After each `crawl_channels` run, in-degree and out-degree are refreshed for all interesting channels. The citation degree is now also refreshed for non-interesting channels that are forwarded or mentioned (via `t.me/` links) by interesting ones — previously only channels reached via forwards were updated, and t.me/username references were missed. The field that receives the citation count is `in_degree` when `REVERSED_EDGES=True` (citations arrive as incoming graph edges) or `out_degree` when `REVERSED_EDGES=False` (citations leave as outgoing edges).
- New `EDGE_WEIGHT_STRATEGY` option controls how edge weights are computed from forward and citation counts. `NONE` = all edges have equal weight (unweighted graph); `TOTAL` = raw count of forwards + citations; `PARTIAL_MESSAGES` = raw count divided by the total number of messages posted by the channel; `PARTIAL_REFERENCES` = raw count divided by the number of messages that are either forwarded from another source or contain at least one citation (default).
- `export_network --3dgraph` generates `graph/graph3d.html`: a Three.js 3D graph alongside the regular 2D Sigma.js map. Supports mouse rotation, zoom, pan, and node click to inspect connections. ForceAtlas2 runs in 3D using the vectorised O(n²) back-end. Spheres are shaded with Lambert lighting for improved depth readability.
- `export_network --compare PROJECT_DIR` accepts the `graph/` output directory of a previous export (the one containing `index.html`) and produces a full side-by-side comparison:
  - The compare network's `data/`, graph files, `*_table.html`, and `*.xlsx` are copied into the current `graph/` directory with `_2` suffixes (`data_2/`, `graph_2.html`, `channel_table_2.html`, etc.). Internal links inside the copied HTML files are rewritten to their `_2` equivalents.
  - `graph/network_compare_table.html` is generated with a 3-column whole-network metrics table (Metric / This network / Compare network), a modularity-by-strategy comparison table, and interactive scatter plots with this network's nodes in blue and the compare network's nodes in red. A "Normalize axes [0–1] per network" toggle min-max scales each network's values independently, making size-dependent measures (degree, fans, message count) directly comparable across networks of different sizes.
  - `graph/index.html` gains a "Compare network" section listing all copied `_2` files and linking to the comparison page.

### Improvements
- `search_channels` now prints progress and results (was fully silent): each search term with found/new counts, and a summary on completion.
- `crawl_channels` and `export_network` now use colour to distinguish section headers (cyan) from step detail lines (plain), warnings (yellow), and final success (green).
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
- `crawl_channels` now accepts `--fromid ID` to restrict crawling to channels whose database id is less than or equal to `ID`.
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
- Telegram service messages (inactivity notices, pin events, etc.) are no longer saved during crawling. Running `crawl_channels --refresh-messages-stats` will delete any already-stored service messages.
- `--table-format` option values renamed from `xls` / `html+xls` to `xlsx` / `html+xlsx` for consistency with the actual file extension.
- Improved semantic and accessibility for all HTML output.
- Improved appearance for all HTML table output.
- Organization admin list now shows and allows inline editing of the `is_interesting` flag.
- `crawl_channels` with `--refresh-messages-stats` now skips messages that were freshly crawled in the same run.

### Fixes
- `crawl_channels` with `--refresh-messages-stats` option was overwriting some of its own output.


## [0.5] - 2026-03-18
*Ability to update already-crawled messages. More reliable spatial layout.*

### New features
- Before applying ForceAtlas2 for spatial layout, Kamada-Kawai is now used to seed initial node positions, improving layout reproducibility across runs.
- New option for `NETWORK_MEASURES`: `KATZ` (Katz centrality).
- New option for `NETWORK_MEASURES`: `BRIDGING` (bridging centrality: betweenness × neighbour-community Shannon entropy). Accepts an optional community strategy parameter: `BRIDGING(LOUVAIN)`, `BRIDGING(LEIDEN)`, etc.
- New option for `NETWORK_MEASURES`: `ALL` (expands to all available measures).
- New option for `COMMUNITY_STRATEGIES`: `ALL` (runs all available detection algorithms simultaneously).
- New `--seo` flag for `export_network`: makes the output mini-site search-engine friendly (sets `index, follow` robots tags, writes a permissive `robots.txt`). Without the flag, the output actively discourages indexing. Meta descriptions are always written regardless of this flag.
- `crawl_channels` now accepts `--refresh-messages-stats` to update view counts, forward counts, and pinned status on already-crawled messages. Accepts an integer (refresh the N most recent messages per channel) or a date in `YYYY-MM-DD` format (refresh all messages from that date to the present). Omitting a value refreshes all messages.
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
- `crawl_channels` gained a `--fixholes` option to detect and fill gaps in message history.

### Improvements
- `crawl_channels` output is more detailed and informative.
- `crawl_channels` now resolves previously unresolved channel references.
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

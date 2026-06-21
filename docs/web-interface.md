# Web interface

Pulpit's browser interface is the primary way to browse collected data, monitor operations, and manage the corpus. This document describes each section of the interface.

The Operations panel is the dashboard you use to launch data collection and analysis. Click Run, watch the log stream in real time, then open the Data tab when done to see the outputs.

---

## Home page — `/`

<figure>
<img src="../webapp_engine/static/screenshot_15.jpg" alt="Home page: project-level summary cards, with open Reactions per month chart.">
<figcaption><em>Home page: project-level summary cards, time-series charts, with open Reactions per month chart.</em></figcaption>
</figure>
<br>

The landing page gives a project-level snapshot of the monitored corpus:

- **Summary cards** — two rows of cards. Row 1: channels (with the to-inspect count), messages collected (with replies), media (with a per-type breakdown), and total views (with subscribers). Row 2: forwards sent, mentions sent, and the date range of the message archive. Lost messages are excluded from every aggregate so the totals match the crawl scope. The cards are built from several cached aggregates and memoised for fast page loads on large databases.
- **Time-series charts** — month-by-month aggregates across the whole corpus: messages sent, active channels, forwards, views, reactions, and average involvement. Each chart is rendered by the same Chart.js component used on channel detail pages, including the dashed vertical-line event annotations (see [Workflow § Events](workflow.md#mark-events-on-charts)).
- **Recent messages** — a feed of the latest posts collected, with a link to each source channel and the same post-card layout used elsewhere (views, forwards, reactions, edit indicator, replies pill).

---

## Channel list — `/channels/`

<figure>
<img src="../webapp_engine/static/screenshot_10.jpg" alt="Channel list">
<figcaption><em>Channel list with label filter, sort controls, and group chips.</em></figcaption>
</figure>
<br>

A paginated list of all channels in the database. Filters and controls:

- **Search** — filter by channel name or username
- **Label filter** — show only channels with a specific (primary-group, in-target) label
- **Source filter** — show channels belonging to a specific ChannelSource
- **Sort** — by name, tag name, first activity, last activity, followers (subscriber count), message count, or label
- **Channel chips** — each card shows the channel's current label colour, subscriber count, message count, and group chips

A channel shows its network position data once crawled while it has an in-target **label period** — a time-bounded `ChannelLabel` whose `Label` has `is_in_target` set (see the channel editor below).

---

## Channel detail — `/channel/<id>/`

<figure>
<img src="../webapp_engine/static/screenshot_11.jpg" alt="Channel detail page">
<figcaption><em>Channel detail page: subscriber history, message volume chart, network stats card, and message list.</em></figcaption>
</figure>
<br>

Each channel has a dedicated detail page with:

- **Subscriber history chart** — subscriber count over time with event annotations (vertical lines for any configured events whose date falls within the chart period)
- **Message volume chart** — message activity over time, also annotated with events
- **Network stats card** — in-degree, out-degree, all computed measures for this channel from the latest export
- **Vacancy Analysis card** — appears when the channel has a registered vacancy (see [Vacancy analysis](vacancy-analysis.md))
- **Message list** — paginated list of crawled messages with timestamps and forward indicators. Each post card shows views, forwards, reactions, and the post date. When a message has been edited after original publication, a pencil icon and "Edited" label appear in the footer (exact edit timestamp on hover). When a channel has "Sign messages" enabled, the post author's name appears on the card below the message body.
- **Forwarded-from filter** — show only forwarded messages or only original posts
- **Lost messages filter** — tristate control (Exclude / Include / Only; default Exclude). Lost messages are rows that Telegram no longer returns; they remain in the database but are excluded from every aggregate, edge weight, and citation measure. Switching to *Include* or *Only* renders them faded with a strikethrough body and a small "lost" chip in the footer.

<figure>
<img src="../webapp_engine/static/screenshot_12.jpg" alt="Channel detail showing vacancy analysis">
<figcaption><em>Channel detail page: Vacancy Analysis card showing replacement candidates with scores.</em></figcaption>
</figure>
<br>

---

## Vacancies list — `/channels/vacancies/`

Lists all channels registered as vacancies with:

- Last-known in-degree and out-degree
- Orphaned amplifier count (channels that forwarded this channel before its closure date)
- Closure date

See [Vacancy analysis](vacancy-analysis.md) for the full documentation.

---

## Exports browser — `/operations/exports/`

The export browser. Shows all completed exports ordered by date. For each export:

- Node and edge counts, export date, all options used
- Links to `index.html`, `graph.html`, `graph3d.html`, table files, and downloads

Use this page as the starting point for sharing or exploring results without navigating to the file system.

---

## Operations panel — `/operations/`

<figure>
<img src="../webapp_engine/static/screenshot_13.jpg" alt="Operations panel">
<figcaption><em>Operations panel: four numbered pipeline steps as task cards with real-time log output.</em></figcaption>
</figure>
<br>

The operations panel presents the four pipeline tasks as numbered cards:

1. **Search Channels** — find new channels by keyword
2. **Crawl Channels** — crawl messages and resolve references
3. **Structural Analysis** — build the graph and write output files
4. **Compare Analysis** — compare two network exports

For each task:

- **Run** — starts the task as a subprocess; the log streams in real time in the panel
- **Abort** — sends SIGTERM to the running process
- **Options** — expand to set task-specific parameters (see [Workflow](workflow.md) for a full reference)
- **Status indicator** — idle / running / done / failed
- **Import from export** — pre-fill the Structural Analysis options from a previous export's `summary.json` to reproduce or extend it
- **Retry lost messages** — a Crawl Channels option that bulk-refetches every message currently marked as lost; rows Telegram returns are unmarked and their stats refreshed
- **Export name overwrite confirmation** — when the typed export name collides with an export already on disk, clicking *Run* on Structural Analysis opens a confirmation modal before launching the task; cancelling leaves the form untouched

---

## Graph viewer features

The exported `graph.html` and `graph3d.html` files are self-contained interactive maps you open from the Data page. Beyond search, pan/zoom, community filtering, and the Options panel, the viewer surfaces the active configuration through a small ambient widget:

- **Info bar** — a collapsible pill at the bottom-centre of both the 2D and 3D viewers. By default it appears as a small half-transparent sliders icon. Clicking it expands horizontally into compact chips for Layout, Community strategy, Size metric, Theme, Labels mode, Coloured/Plain edges, and (when filtering) the active community group. Chips update live whenever an option is changed in the Options panel; click the icon again to collapse it back.

---

## Backoffice — `/manage/`

Staff-only management interface for corpus administration. Accessible only to users with `is_staff = True`.

<figure>
<img src="../webapp_engine/static/screenshot_09.jpg" alt="Backoffice channels view">
<figcaption><em>Backoffice channels view: bulk label assignment and group chip management.</em></figcaption>
</figure>
<br>

### Channels — `/manage/channels/`

Bulk management of the channel database:

- **Assign label** — select multiple channels and replace their periods *within one label's group* with a single period under one label in one action
- **Source chips** — add or remove ChannelSource memberships inline
- **Edit individual** — click through to edit a channel's details, its **label periods** (label + optional start/end, non-overlapping within a partition group), `to_inspect` flag, and vacancy record
- **Filter** — by label, group, in-target status, entity type

### Labels — `/manage/labels/`

Create and edit label groups and their labels. Labels live in *groups* (a *partition* group holds at most one label per channel at a time; exactly one group is *primary*). Key fields:

- **Name** — label name used throughout the interface
- **Color** — hex colour used to draw the node when the graph is coloured by this label's group (the `LABELGROUP<id>` community); the **Recolor** button applies a colorcet palette across a group
- **In target** — when checked, a channel's periods under this label are included in crawls and exports (`is_in_target`)

### Sources — `/manage/sources/`

ChannelSources are tags you apply to channels for flexible filtering. They are independent of labels — a channel can be in any number of sources, regardless of its label periods. Use sources to define subsets for targeted analysis (e.g. run an export with `--channel-sources activist,media` to analyse only those channels).

### Search terms — `/manage/search-terms/`

Add or remove search keywords for channel discovery. Terms are processed in order of oldest check date.

### Events and event types — `/manage/events/`

Manage the events and event type entries used for chart annotations (event types are managed within the Events page). See [Workflow § Events](workflow.md#mark-events-on-charts).

### Users — `/manage/users/`

Create and manage user accounts. The email address is used as the username. Set `is_staff = True` to grant access to the Operations panel and backoffice. Staff accounts can be created on the command line with `python manage.py createsuperuser`.

### Vacancies — `/manage/vacancies/`

Register channel vacancies for structural replacement analysis. See [Vacancy analysis](vacancy-analysis.md).

### Maintenance — `/manage/maintenance/`

Staff-only database maintenance. The page reports the active engine, the database's current on-disk size, and a checklist of optimization strategies available for that engine. Pick one or more (or accept the default of all) and click **Run optimization** to execute them sequentially; the page reports per-step timing and the size before and after.

| Engine | Available strategies |
| :----- | :------------------- |
| **SQLite** | `ANALYZE`, `PRAGMA optimize`, `PRAGMA wal_checkpoint(TRUNCATE)`, `VACUUM` |
| **PostgreSQL** | `ANALYZE`, `VACUUM ANALYZE` (executed with autocommit, since `VACUUM` cannot run inside a transaction) |

The same catalog and the current database size are available programmatically through `GET /manage/api/maintenance/`; running an optimization is `POST /manage/api/maintenance/optimize/`. Strategies are run in the order listed; the run stops at the first failure and returns the partial timing report.

---

## Access control

The interface respects the `WEB_ACCESS` setting in `.env`:

| Mode | Effect |
| :--- | :----- |
| `ALL` | No login required anywhere |
| `OPEN` | Public pages remain open; `/operations/` and `/manage/` require staff |
| `PROTECTED` | All pages require login; `/operations/` and `/manage/` additionally require staff |

A **Log out** button appears in the top navigation bar when a user is logged in. The **Manage** button is shown only to staff. See [Getting started § Access control](getting-started.md#access-control) for setup instructions.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

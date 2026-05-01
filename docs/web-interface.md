# Web interface

Pulpit's browser interface is the primary way to browse collected data, monitor operations, and manage the corpus. This document describes each section of the interface.

The Operations panel is the dashboard you use to launch data collection and analysis. Click Run, watch the log stream in real time, then open the Data tab when done to see the outputs.

---

## Channel list — `/channels/`

<figure>
<img src="../webapp_engine/static/screenshot_10.jpg" alt="Channel list">
<figcaption>Channel list with organisation filter, sort controls, and group chips.</figcaption>
</figure>

A paginated list of all channels in the database. Filters and controls:

- **Search** — filter by channel name or username
- **Organisation filter** — show only channels assigned to a specific organisation
- **Group filter** — show channels belonging to a specific ChannelGroup
- **Sort** — by name, subscriber count, message count, in-degree, or out-degree
- **Channel chips** — each card shows the channel's organisation colour, subscriber count, message count, and group chips

Channels marked `is_interesting = True` via their organisation show their network position data once crawled.

---

## Channel detail — `/channel/<id>/`

<figure>
<img src="../webapp_engine/static/screenshot_11.jpg" alt="Channel detail page">
<figcaption>Channel detail page: subscriber history, message volume chart, network stats card, and message list.</figcaption>
</figure>

Each channel has a dedicated detail page with:

- **Subscriber history chart** — subscriber count over time with event annotations (vertical lines for any configured events whose date falls within the chart period)
- **Message volume chart** — message activity over time, also annotated with events
- **Network stats card** — in-degree, out-degree, all computed measures for this channel from the latest export
- **Vacancy Analysis card** — appears when the channel has a registered vacancy (see [Vacancy analysis](vacancy-analysis.md))
- **Message list** — paginated list of crawled messages with timestamps and forward indicators
- **Forwarded-from filter** — show only forwarded messages or only original posts

<figure>
<img src="../webapp_engine/static/screenshot_12.jpg" alt="Channel detail showing vacancy analysis">
<figcaption>Channel detail page: Vacancy Analysis card showing replacement candidates with scores.</figcaption>
</figure>

---

## Vacancies list — `/channels/vacancies/`

Lists all channels registered as vacancies with:

- Last-known in-degree and out-degree
- Orphaned amplifier count (channels that forwarded this channel before its death date)
- Death date

See [Vacancy analysis](vacancy-analysis.md) for the full documentation.

> **[PLACEHOLDER: `images/vacancy-list.png`]** Vacancies list: all registered vacant channels with in-degree, orphaned amplifier counts, and death date.

---

## Data page — `/data/`

The export browser. Shows all completed exports ordered by date. For each export:

- Node and edge counts, export date, all options used
- Links to `index.html`, `graph.html`, `graph3d.html`, table files, and downloads

Use this page as the starting point for sharing or exploring results without navigating to the file system.

---

## Operations panel — `/operations/`

<figure>
<img src="../webapp_engine/static/screenshot_13.jpg" alt="Operations panel">
<figcaption>Operations panel: four numbered pipeline steps as task cards with real-time log output.</figcaption>
</figure>

The operations panel presents the four pipeline tasks as numbered cards:

1. **Search Channels** — find new channels by keyword
2. **Get Channels** — crawl messages and resolve references
3. **Export Network** — build the graph and write output files
4. **Compare Analysis** — compare two network exports

For each task:

- **Run** — starts the task as a subprocess; the log streams in real time in the panel
- **Abort** — sends SIGTERM to the running process
- **Options** — expand to set task-specific parameters (see [Workflow](workflow.md) for a full reference)
- **Status indicator** — idle / running / done / failed
- **Import from export** — pre-fill the Export Network options from a previous export's `summary.json` to reproduce or extend it

---

## Backoffice — `/manage/`

Staff-only management interface for corpus administration. Accessible only to users with `is_staff = True`.

<figure>
<img src="../webapp_engine/static/screenshot_09.jpg" alt="Backoffice channels view">
<figcaption>Backoffice channels view: bulk organisation assignment and group chip management.</figcaption>
</figure>

### Channels — `/manage/channels/`

Bulk management of the channel database:

- **Assign organisation** — select multiple channels and assign them to an organisation in one action
- **Group chips** — add or remove ChannelGroup memberships inline
- **Edit individual** — click through to edit a channel's details, is_interesting status, and vacancy record
- **Filter** — by organisation, group, is_interesting status, entity type

### Organisations — `/manage/organizations/`

Create and edit organisations. Key fields:

- **Name** — label used throughout the interface
- **Color** — hex color used in the graph when `COMMUNITY_PALETTE=ORGANIZATION`
- **Is interesting** — when checked, all channels in this organisation are included in crawls and exports

### Groups — `/manage/channel-groups/`

ChannelGroups are labels you apply to channels for flexible filtering. They are independent of organisations — a channel can be in any number of groups and belong to one organisation. Use groups to define subsets for targeted analysis (e.g. run an export with `--channel-groups activist,media` to analyse only those channels).

### Search terms — `/manage/search-terms/`

Add or remove search keywords for channel discovery. Terms are processed in order of oldest check date.

### Events and event types — `/manage/events/`, `/manage/event-types/`

Manage the events and event type entries used for chart annotations. See [Workflow § Events](workflow.md#events-optional).

### Users — `/manage/users/`

Create and manage user accounts. The email address is used as the username. Set `is_staff = True` to grant access to the Operations panel and backoffice. Staff accounts can be created on the command line with `python manage.py createsuperuser`.

### Vacancies — `/manage/vacancies/`

Register channel vacancies for structural replacement analysis. See [Vacancy analysis](vacancy-analysis.md).

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

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md) · [Roadmap](roadmap.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

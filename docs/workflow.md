# Workflow

This guide walks you through the four steps of a Pulpit research project, from finding channels to opening the finished network map in a browser.

**The pipeline:**

```
1. Find channels  →  2. Organise  →  3. Collect messages  →  4. Generate the map
```

Everything is done through the browser interface at [http://localhost:8000](http://localhost:8000). You do not need to use the terminal for normal research work.

---

## Before you start

Make sure Pulpit is running:

```sh
python manage.py runserver
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Step 1 — Add keywords to find channels

Go to **Manage** in the navigation bar, then choose **Search terms**.

Click **Add search term** and type a keyword — for example, a political party name, a topic, or a country name. Add as many terms as you need to cover the scope of your research. You can add more at any time.

> **Tip:** use terms in the same language as the channels you are looking for. Telegram's search is language-sensitive.

Once your terms are saved, go back to the home page and click **Operations** in the navigation bar. This is the control panel where you launch all data collection steps.

---

## Step 2 — Search for channels

In the Operations panel, find the **Search Channels** card (Step 1) and click **Run**.

Pulpit searches Telegram for channels matching your keywords and saves the results. You will see a live log of what is happening. When it finishes, the status badge changes from *running* to *done*.

The first time Pulpit connects to Telegram, it will send a verification code to your Telegram app. Enter it in the terminal when prompted.

> **Nothing found?** Try broader or different keywords. Telegram's search only matches channel names and descriptions, not message content.

---

## Step 3 — Organise your channels

Go to **Manage → Channels**. You will see a list of all channels Pulpit found. Your job here is to decide which ones matter for your research and assign each a label.

### What is an organisation?

An "organisation" in Pulpit is a category label you define — for example *Far right*, *Mainstream conservative*, *Pro-government*, *Independent media*, or any grouping that makes sense for your project. Every channel you want to analyse must belong to an organisation.

### How to assign channels

1. In the Channels list, find a channel you want to include.
2. Click on the channel's name or ID to open its edit page.
3. Choose an organisation from the **Organisation** dropdown.
4. Click **Save**.

Repeat for all the channels you want in your analysis. Channels without an organisation are not collected or included in the map.

**To create organisations:** go to **Manage → Organisations**, click **Add**, give the organisation a name and a colour, and make sure **Is interesting** is ticked. Only organisations marked as interesting are included in data collection.

> **Tip:** you can also assign organisations in bulk. In the Channels list, tick the checkboxes next to several channels, then use the **Bulk assign** bar at the bottom of the page to set the organisation for all of them at once.

**Interesting override (optional):** each channel has an **Override** field that lets you force its interesting status independently of its organisation:

| Value | Meaning |
| :---- | :------ |
| **Auto** (default) | Interesting status follows the organisation — no change from normal behaviour. |
| **Yes** | Always treated as interesting, even if unassigned or in a non-interesting organisation. |
| **No** | Always excluded, even if its organisation is marked as interesting. |

Set it from the **Override** column in the Channels list (inline dropdown) or from the channel edit page. Use *Yes* to include a one-off channel without reorganising, and *No* to temporarily suspend a channel without removing it from its organisation.

**Channel groups (optional):** channel groups let you tag channels with one or more labels — for example *activists*, *media*, *state-affiliated* — independent of their organisation. A channel can belong to any number of groups.

To create groups go to **Manage → Channel groups** and click **Add**. To assign a channel to a group, open its edit page and pick from the **Groups** field.

Groups act as a scope filter: when you select one or more groups in the Operations panel (Crawl Channels or Structural Analysis), only channels belonging to at least one of the selected groups are processed. Leaving all boxes unchecked means all interesting channels are included, as usual.

Use groups when you want to run separate analyses on a subset of your corpus without changing organisations — for example, crawl only state-affiliated channels, or generate a graph limited to media outlets.

---

## Step 4 — Collect messages

In the Operations panel, find the **Crawl Channels** card (Step 2) and click **Run**.

Pulpit downloads messages from all the channels you organised, and traces every cross-channel link — when one channel forwards a message from another, or mentions another channel by name.

This step can take a while, especially on a first run. The log shows progress channel by channel. When it finishes, the status changes to *done*.

### What the options do (expand Options to see them)

The options panel is organised into three independent groups — each is its own pass over the channels in scope.

**1. Channels** — update channel metadata without touching messages.

| Option | When to use it |
| :----- | :------------- |
| **Get channels info** | On by default. Updates profile pictures, subscriber counts, about text, and other channel details. |
| **Mine about texts** | Scan channel descriptions for links to other Telegram channels and add any new ones to your database. |
| **Fetch recommended channels** | Ask Telegram for its own channel suggestions and add them to the database. New channels are saved but not automatically crawled. |
| **Retry lost & private** | Re-attempt channels previously marked as inaccessible. If a channel is now reachable its flag is cleared. |

**2. Messages** — download and update message content.

| Option | When to use it |
| :----- | :------------- |
| **Get new messages** | On by default. Downloads messages published since the last crawl. |
| **Fetch replies** | Fetch reply threads from linked discussion groups for posts that have replies. |
| **Refresh message stats** | Periodically re-fetch view counts, forward counts, and reactions for already-downloaded messages. Use the *Limit*, *From date*, and *To date* fields to restrict which messages are refreshed. |
| **Fix message holes** | Scan message ID sequences for gaps and fill them in. Can run without *Get new messages*. |
| **Fix missing media** | Re-download photos and videos that were never saved or are missing from disk. |
| **Retry unresolved references** | Re-attempt t.me/ links that could not be resolved in a previous run. |

**3. Refresh degrees** — recalculate citation counts (no Telegram connection needed).

| Option | When to use it |
| :----- | :------------- |
| **In target channels** | On by default. Recomputes in-degree and out-degree for all interesting channels. |
| **Out of target channels** | On by default. Recomputes citation degree for non-interesting channels referenced by interesting ones. |

**Limiting the scope:** you can restrict the crawl to a subset of channels in two ways:

- **DB id filter** — enter specific channel IDs (e.g. `5, 10-20, 50`). Find a channel's ID in the Manage → Channels list.
- **Channel groups** — tick one or more groups in the **Channel groups** fieldset. Only channels belonging to at least one selected group are crawled. Leave all unchecked to crawl all interesting channels.

> **The first connection to Telegram:** if this is your first run, Telegram will send a verification code to your phone. Enter it in the terminal when prompted.

---

## Step 5 — Generate the map

In the Operations panel, find the **Structural Analysis** card (Step 3) and click **Run**.

This step builds the network graph, runs community-detection algorithms to identify clusters of channels, and produces the output files. By default it writes the data files needed to power the interactive map.

### What you get

Before clicking Run, expand **Options** and choose which outputs you want:

| Output | What it is |
| :----- | :--------- |
| **2D graph** | An interactive map (`graph.html`) you can open in a browser — search, zoom, filter by cluster, click channels for details. This is the main output most people want. |
| **3D graph** | The same map in a rotatable 3D view (`graph3d.html`). |
| **HTML tables** | Sortable tables listing every channel with its network scores, and tables summarising each cluster. |
| **Excel spreadsheets** | The same tables as `.xlsx` files you can open in Excel or Google Sheets. |
| **GEXF / GraphML** | Files for network analysis software like Gephi or Cytoscape. |

> **Tip:** tick at least **2D graph** and **HTML tables** for a first run. That gives you the interactive map and a spreadsheet-style overview.

### Choosing how clusters are detected

Under **Community strategies**, select the algorithm Pulpit uses to group channels into clusters:

- **Organisation** (default) — clusters follow the organisations you defined in Step 3. A good starting point to see whether your categories map onto the actual citation patterns.
- **Leiden** or **Leiden Directed** — mathematical community detection based on citation patterns, independent of your labels. Often reveals groupings you did not expect.

You can select multiple strategies at once; the map lets you switch between them without re-exporting.

### Other useful analysis options

| Option | What it does |
| :----- | :----------- |
| **Measures** | Which influence scores to compute for each channel (PageRank, betweenness, etc.). Start with the default (PageRank). See [Network measures](network-measures.md) for what each one means. |
| **Start date / End date** | Limit the analysis to a specific time period — for example, the six months before an election. |
| **Channel groups** | Restrict the graph to channels belonging to at least one selected group. Leave all unchecked to include all interesting channels. |
| **Export name** | Give this export a name (e.g. `march-2024`). If you leave it blank, the date and time are used. You can keep multiple exports and compare them. |
| **Draw dead leaves** | Include channels that are *referenced by* your monitored channels but not themselves monitored. Useful for seeing what outside content your corpus amplifies. |

When the export finishes, click **Data** in the navigation bar to browse your exports and open the map.

---

## What else you can do

### Timeline: see how the network changed over time

Enable **Timeline by year** in the Structural Analysis options. Pulpit repeats the full analysis once per calendar year found in your data and adds a year navigator to the graph — click the arrows to step through time and watch the network evolve.

### Compare two networks

Run a second export — perhaps with a later date range or a different set of channels. Then go to the **Compare Analysis** card (Step 4) in the Operations panel, set the target export, and click Run. Pulpit generates a side-by-side comparison showing which channels gained or lost influence between the two snapshots.

### Mark events on charts

Go to **Manage → Event types** to define categories like *Election* or *Policy change*, then **Manage → Events** to add specific dates and descriptions. Pulpit draws vertical lines at those dates on all channel activity charts, making it easy to see whether the event affected a channel's behaviour.

---

## Viewing your results

Go to **Data** (`/data/`) to see all your exports. Click an export name to open its index page, which links to the interactive map, tables, and any other files you generated.

You can also share an export by copying the whole `exports/<name>/` folder to a web server or to a colleague's machine. The files are self-contained and work without an internet connection.

---

## Advanced: running from the command line

If you prefer to work in a terminal — for example to automate or schedule runs — every operation has a CLI equivalent.

> **Windows users:** use **PowerShell** for these examples — it supports `#` comments just like bash. In Command Prompt, replace `#` comment lines with `rem`. All `python manage.py ...` commands work identically on both platforms.

```sh
# Start the server
python manage.py runserver

# Search for channels
python manage.py search_channels
python manage.py search_channels --amount 15
python manage.py search_channels --extra-term "keyword"

# Collect messages — the three independent groups
python manage.py crawl_channels --get-channels-info           # 1. update channel metadata only
python manage.py crawl_channels --get-new-messages            # 2. fetch new messages only
python manage.py crawl_channels --in-degrees --out-degrees    # 3. refresh degrees only (no Telegram connection)

# Combine as needed
python manage.py crawl_channels --get-channels-info --get-new-messages
python manage.py crawl_channels --get-new-messages --fixholes
python manage.py crawl_channels --get-new-messages --retry-references
python manage.py crawl_channels --get-new-messages --fetch-replies
python manage.py crawl_channels --mine-about-texts
python manage.py crawl_channels --fetch-recommended-channels
python manage.py crawl_channels --refresh-messages-stats
python manage.py crawl_channels --refresh-messages-stats --refresh-from 2024-01-01 --refresh-to 2024-06-30
python manage.py crawl_channels --refresh-messages-stats --refresh-limit 200
python manage.py crawl_channels --ids "5, 10-20, 50"
python manage.py crawl_channels --get-new-messages --channel-groups media,activists

# Generate the map
python manage.py structural_analysis --2dgraph --html
python manage.py structural_analysis --2dgraph --html --xlsx
python manage.py structural_analysis --2dgraph --3dgraph --html --xlsx
python manage.py structural_analysis --gexf --graphml
python manage.py structural_analysis --csv
python manage.py structural_analysis --measures PAGERANK,BETWEENNESS
python manage.py structural_analysis --measures ALL
python manage.py structural_analysis --community-strategies LEIDEN_DIRECTED
python manage.py structural_analysis --community-strategies ALL
python manage.py structural_analysis --startdate 2023-01-01 --enddate 2023-12-31
python manage.py structural_analysis --name my-export
python manage.py structural_analysis --2dgraph --timeline-step year
python manage.py structural_analysis --2dgraph --html --channel-groups media,activists

# Compare two exports
python manage.py compare_analysis /path/to/exports/<other-name>
# Windows: use backslashes or quote the path
# python manage.py compare_analysis exports\<other-name>
```

See `python manage.py <command> --help` for the full list of flags for any command.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

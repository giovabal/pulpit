# TNExp

TNExp (Telegram Network Explorer) crawls Telegram channels, maps the relationships between them, and produces an interactive force-directed graph you can explore in a browser.

See the [changelog](CHANGELOG.md) for release history.

![Example graph](webapp_engine/static/example.jpg)

## How it works

1. You provide search terms; TNExp finds matching Telegram channels via the API.
2. You review the results in the admin interface and group channels into **Organizations** — thematic clusters (e.g. by political leaning, country, topic).
3. TNExp crawls the selected channels, collecting messages and resolving cross-channel references (forwards and `t.me/` links).
4. A graph is built from those references, communities are detected and colored, a ForceAtlas2 layout is applied, and the result is exported as an interactive HTML map.


## Installation

See [INSTALLATION.md](INSTALLATION.md) for requirements, setup steps, and database initialisation.


## Workflow

> On some systems replace `python` with `python3` or `py`.

### 1. Start the admin interface

```sh
python manage.py runserver
```

Open [http://localhost:8000/admin/](http://localhost:8000/admin/).

### 2. Add search terms

In the admin, go to **Search Terms** and add keywords. These are used to discover channels by name.

### 3. Discover channels

```sh
python manage.py search_channels
```

Runs up to 15 pending search terms and saves the matching channels to the database.

### 4. Organise channels

Back in the admin, open **Channels** and assign each channel you want to analyse to an **Organization**. Mark the organization as `is_interesting = True`. Channels without an interesting organization are ignored during crawling and graph export.

### 5. Crawl channels

```sh
python manage.py get_channels
```

Downloads messages for all interesting channels. Re-run at any time to fetch new messages.

To also fill gaps in message history (messages that were deleted or missed on a previous run):

```sh
python manage.py get_channels --fixholes
```

### 6. Export the graph

```sh
python manage.py export_network
```

Builds the graph, applies community detection and layout, and writes the result to `graph/telegram_graph/`.

### 7. View the graph

```sh
cd graph
python -m http.server 8001
```

Open [http://localhost:8001/telegram_graph/](http://localhost:8001/telegram_graph/) in your browser.


## Configuration

See [CONFIGURATION.md](CONFIGURATION.md) for the full list of options.

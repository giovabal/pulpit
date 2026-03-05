# TNExp

TNExp (Telegram Network Explorer) crawls Telegram channels, maps the relationships between them, and produces an interactive force-directed graph you can explore in a browser.

See the [changelog](CHANGELOG.md) for release history.


## How it works

1. You provide search terms; TNExp finds matching Telegram channels via the API.
2. You review the results in the admin interface and group channels into **Organizations** — thematic clusters (e.g. by political leaning, country, topic).
3. TNExp crawls the selected channels, collecting messages and resolving cross-channel references (forwards and `t.me/` links).
4. A graph is built from those references, communities are detected and colored, a ForceAtlas2 layout is applied, and the result is exported as an interactive HTML map.


## Requirements

- Python 3.12 (earlier versions may work)
- A Telegram account with the app installed on your phone
- Telegram API credentials — register at [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id); set **Platform** to `Web`

TNExp is developed and primarily used on GNU/Linux. Windows 10+ is also supported; you will need **Visual Studio Build Tools** with the "Desktop development with C++" workload installed.


## Installation

```sh
git clone <repo-url>
cd TNExp
sh setup.sh          # creates a virtual environment and installs dependencies
```

Or manually:

```sh
pip install -r requirements.txt
```

Copy the example configuration and fill in your credentials:

```sh
cp env.example .env
# edit .env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE_NUMBER
```


## Workflow

> On some systems replace `python` with `python3` or `py`.

### 1. Initialise the database

```sh
python manage.py migrate
```

### 2. Start the admin interface

```sh
python manage.py runserver
```

Open [http://localhost:8000/admin/](http://localhost:8000/admin/).

### 3. Add search terms

In the admin, go to **Search Terms** and add keywords. These are used to discover channels by name.

### 4. Discover channels

```sh
python manage.py search_channels
```

Runs up to 15 pending search terms and saves the matching channels to the database.

### 5. Organise channels

Back in the admin, open **Channels** and assign each channel you want to analyse to an **Organization**. Mark the organization as `is_interesting = True`. Channels without an interesting organization are ignored during crawling and graph export.

### 6. Crawl channels

```sh
python manage.py get_channels
```

Downloads messages for all interesting channels. Re-run at any time to fetch new messages.

To also fill gaps in message history (messages that were deleted or missed on a previous run):

```sh
python manage.py get_channels --fixholes
```

### 7. Export the graph

```sh
python manage.py export_network
```

Builds the graph, applies community detection and layout, and writes the result to `graph/telegram_graph/`.

### 8. View the graph

```sh
cd graph
python -m http.server 8001
```

Open [http://localhost:8001/telegram_graph/](http://localhost:8001/telegram_graph/) in your browser.


## Configuration

All options go in `.env`. Copy `env.example` as a starting point.

### Telegram

| Option | Description | Default |
| :----- | :---------- | ------: |
| `TELEGRAM_API_ID` | API ID from Telegram | **required** |
| `TELEGRAM_API_HASH` | API hash from Telegram | **required** |
| `TELEGRAM_PHONE_NUMBER` | Phone number linked to your Telegram account | **required** |
| `TELEGRAM_CRAWLER_GRACE_TIME` | Seconds to wait between API requests | `1` |
| `TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL` | Max messages to fetch per channel per run; set to `None` for no limit | `100` |
| `TELEGRAM_CRAWLER_DOWNLOAD_IMAGES` | Download images attached to messages | `False` |
| `TELEGRAM_CRAWLER_DOWNLOAD_VIDEO` | Download videos attached to messages | `False` |

### Graph layout

| Option | Description | Default |
| :----- | :---------- | ------: |
| `FA2_ITERATIONS` | Number of ForceAtlas2 iterations | `20000` |
| `LAYOUT` | Desired graph orientation: `HORIZONTAL` or `VERTICAL`. When the computed layout's aspect ratio does not match, the graph is automatically rotated 90°. | `HORIZONTAL` |

### Network analysis

| Option | Description | Default |
| :----- | :---------- | ------: |
| `REVERSED_EDGES` | When `True`, a forward of Y's content by X produces a Y → X edge (i.e. influence flows toward the source) | `True` |

### Community detection

| Option | Description | Default |
| :----- | :---------- | ------: |
| `COMMUNITIES_STRATEGY` | Algorithm used to assign nodes to communities: `ORGANIZATION` (uses admin groups), `LOUVAIN`, `KCORE`, or `INFOMAP` | `ORGANIZATION` |
| `COMMUNITIES_PALETTE` | Color palette for communities. Use `ORGANIZATION` to take colors from the admin, or any palette name from [python-graph-gallery.com/color-palette-finder](https://python-graph-gallery.com/color-palette-finder/) (case-sensitive) | `ORGANIZATION` |

### Drawing

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DRAW_DEAD_LEAVES` | Include uninteresting channels that receive inbound links from interesting ones. Makes the graph more complete but significantly larger. | `False` |
| `DEAD_LEAVES_COLOR` | Color for dead-leaf nodes, in hex format | `#596a64` |

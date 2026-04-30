# Configuration

Pulpit is configured through a `.env` file in the project root. Copy `env.example` as a starting point and fill in at least the three Telegram credentials before running any management command. All other settings have defaults that work for a first run; refer to the sections below when you want to change how channels are crawled, how the graph is weighted, or how communities are detected and coloured.

All options go in `.env`. Copy `env.example` as a starting point.

## Telegram

| Option | Description | Default |
| :----- | :---------- | ------: |
| `TELEGRAM_API_ID` | API ID from Telegram | **required** |
| `TELEGRAM_API_HASH` | API hash from Telegram | **required** |
| `TELEGRAM_PHONE_NUMBER` | Phone number linked to your Telegram account | **required** |
| `TELEGRAM_CRAWLER_GRACE_TIME` | Seconds to wait between API requests | `1` |
| `TELEGRAM_CONNECTION_RETRIES` | How many times Telethon retries a failed connection before giving up | `10` |
| `TELEGRAM_RETRY_DELAY` | Seconds to wait between connection retry attempts | `5` |
| `TELEGRAM_FLOOD_SLEEP_THRESHOLD` | Telethon automatically sleeps through flood-wait errors shorter than this value (seconds); errors longer than this are raised as exceptions instead | `60` |
| `TELEGRAM_CRAWLER_MESSAGES_LIMIT_PER_CHANNEL` | Max messages to fetch per channel per run; `0` = no limit | `100` |
| `TELEGRAM_CRAWLER_DOWNLOAD_IMAGES` | Download images attached to messages | `False` |
| `TELEGRAM_CRAWLER_DOWNLOAD_VIDEO` | Download videos attached to messages | `False` |

> **Note on message statistics:** view counts, forward counts, and pinned status are recorded when a message is first crawled and are not automatically updated on subsequent runs. Use `--refresh-messages-stats` to re-fetch and update these fields: omit a value to refresh all messages, pass an integer N to refresh the N most recent messages per channel, or pass a date (`YYYY-MM-DD`) to refresh all messages from that date to the present. The `_updated` timestamp on each refreshed message is set to the time of the refresh.

## Database

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DB_ENGINE` | Database backend: `sqlite`, `postgresql`, `mysql`, `mariadb`, or `oracle` | `sqlite` |
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

> SQLite is the default and works out of the box; it is configured with WAL journal mode and `synchronous=NORMAL` for better concurrency. The server-based backends are recommended when running Pulpit on a shared server or when the database may be accessed by multiple processes concurrently. MySQL and MariaDB connections use `utf8mb4` charset; create the database with `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` to match. For Oracle, `DB_NAME` accepts a service name (`ORCL`), an Easy Connect string (`host/service`), or a full TNS alias defined in `tnsnames.ora`.

## Project

| Option | Description | Default |
| :----- | :---------- | ------: |
| `PROJECT_TITLE` | Project name used in the `<title>` tag of all HTML files produced by `structural_analysis` (`graph.html`, `channel_table.html`, `network_table.html`, `community_table.html`) | `Pulpit project` |
| `GRAPH_OUTPUT_DIR` | Directory where `structural_analysis` writes all output files. Relative paths are resolved from the project root. When the Django development server is running, the output is also served at `http://localhost:8000/graph/` regardless of this setting. | `graph` |
| `WEB_ACCESS` | Access control for the web interface. `ALL` — no login required anywhere (default, suitable for local use). `OPEN` — all pages are public except `/admin/`, `/operations/`, and `/manage/`, which require a staff account. `PROTECTED` — all pages require login; `/admin/`, `/operations/`, and `/manage/` additionally require a staff account. Staff accounts are Django users with `is_staff = True`, created via `python manage.py createsuperuser` or in the backoffice. | `ALL` |

> **User accounts:** `WEB_ACCESS=ALL` requires no accounts. For `OPEN` or `PROTECTED`, create a staff account first with `python manage.py createsuperuser`. Staff accounts (`is_staff=True`) can reach `/admin/`, `/operations/`, and `/manage/`; regular accounts can reach everything else in `PROTECTED` mode but are blocked from those paths. The login form is always served at `/login/` regardless of mode. After logging in, a **Log out** button appears in the top navigation bar next to the user's name; the **Manage** button is shown only to staff.

## Network analysis

| Option | Description | Default |
| :----- | :---------- | ------: |
| `REVERSED_EDGES` | When `True`, a forward of Y's content by X produces a Y → X edge (i.e. influence flows toward the source) | `True` |
| `DEFAULT_CHANNEL_TYPES` | Comma-separated Telegram entity types considered monitored: `CHANNEL` (broadcast), `GROUP` (supergroups/gigagroups), `USER`. Used as the default for `get_channels --channel-types`, `structural_analysis --channel-types`, and the definition of "interesting" channels throughout the app. | `CHANNEL` |


## Community detection

| Option | Description | Default |
| :----- | :---------- | ------: |
| `COMMUNITY_PALETTE` | Color palette for communities. Use `ORGANIZATION` to take colors from the admin, or any palette name from [python-graph-gallery.com/color-palette-finder](https://python-graph-gallery.com/color-palette-finder/) (case-sensitive) | `ORGANIZATION` |

## Drawing

| Option | Description | Default |
| :----- | :---------- | ------: |
| `DEAD_LEAVES_COLOR` | Color for dead-leaf nodes, in hex format | `#596a64` |

---

← [README](README.md) · [Installation](INSTALLATION.md) · [Workflow](WORKFLOW.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

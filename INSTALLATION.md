# Installation

## Requirements

- Python 3.12 (earlier versions may work)
- A Telegram account with the app installed on your phone
- Telegram API credentials — register at [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id); set **Platform** to `Web`

Pulpit is developed and primarily used on GNU/Linux. Windows 10+ is also supported; you will need **Visual Studio Build Tools** with the "Desktop development with C++" workload installed.

## Install dependencies

```sh
git clone https://github.com/giovabal/pulpit
cd pulpit
sh setup.sh          # creates a virtual environment and installs dependencies
```

Or manually:

```sh
pip install -r requirements.txt
```

## Configure credentials

Copy the example configuration and fill in your credentials:

```sh
cp env.example .env
# edit .env: set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE_NUMBER
```

See [CONFIGURATION.md](CONFIGURATION.md) for the full list of options.

## Initialise the database

By default Pulpit uses SQLite. To use a server-based backend, set `DB_ENGINE` in `.env` and install the corresponding driver:

```sh
pip install psycopg2-binary   # PostgreSQL
pip install mysqlclient        # MySQL or MariaDB
```

Then run migrations for whichever backend you configured:

```sh
python manage.py migrate
```

## Migrating between database engines

Django's `dumpdata` / `loaddata` commands transfer all data between any two supported backends. Media files (channel avatars) live on disk and do not need to be migrated.

### SQLite → PostgreSQL

```sh
# 1. Dump all data from the current SQLite database
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json

# 2. Switch .env to the new backend
#    DB_ENGINE=postgresql  DB_NAME=...  DB_USER=...  DB_PASSWORD=...  DB_HOST=...

# 3. Create the PostgreSQL database (if it doesn't exist yet)
createdb -U <user> <dbname>

# 4. Create the schema on the new database
python manage.py migrate

# 5. Load the data
python manage.py loaddata data.json
```

### SQLite → MySQL / MariaDB

```sh
# 1. Dump all data from SQLite
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json

# 2. Switch .env to the new backend
#    DB_ENGINE=mysql  DB_NAME=...  DB_USER=...  DB_PASSWORD=...  DB_HOST=...

# 3. Create the MySQL / MariaDB database with utf8mb4 charset
mysql -u <user> -p -e "CREATE DATABASE <dbname> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 4. Create the schema
python manage.py migrate

# 5. Load the data
python manage.py loaddata data.json
```

### Any engine → any other engine

The same two-step pattern works for any combination: dump from the source, point `.env` at the target, run `migrate`, then `loaddata`. The steps above for PostgreSQL and MySQL/MariaDB show the only engine-specific differences (how to create the database before running `migrate`).

> `--exclude contenttypes` and `--exclude auth.permission` are necessary: these tables are populated automatically by `migrate` and re-importing them causes primary-key conflicts. `--natural-foreign --natural-primary` improves cross-database compatibility by using named keys instead of raw integer IDs.

## Access control

By default (`WEB_ACCESS=ALL`) the interface is fully open — no login required. This is suitable for running Pulpit locally on your own machine.

If the server is reachable on a network, set `WEB_ACCESS` in `.env` to restrict access:

- **`OPEN`** — read-only pages (Network, Channels, Data) remain public. The Admin and Operations panel require a **staff** account.
- **`PROTECTED`** — all pages require login. Admin and Operations additionally require a **staff** account.

In either restricted mode, create at least one staff account before starting the server:

```sh
python manage.py createsuperuser
```

This account can log in to both `/admin/` and `/operations/`. You can also create regular (non-staff) accounts in the admin; in `PROTECTED` mode they can view pages but not administer or operate the system.

## Next steps

Start the server and open the browser interface:

```sh
python manage.py runserver   # open http://localhost:8000
```

The **Operations panel** (`/operations/`) lets you launch and monitor all data collection and export tasks directly from the browser. See [WORKFLOW.md](WORKFLOW.md) for the complete step-by-step guide.

---

← [README](README.md) · [Workflow](WORKFLOW.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

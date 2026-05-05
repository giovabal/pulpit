# Getting started

Pulpit is a Python/Django application. This guide covers requirements, installation, configuration, and the first run.

---

## Requirements

- **Python 3.12** (earlier versions may work but are not tested)
- **A Telegram account** with the app installed on your phone or desktop
- **Telegram API credentials** — you will register them once at [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id)

Pulpit is developed and primarily used on GNU/Linux. Windows 10+ is supported; you will need **Visual Studio Build Tools** with the "Desktop development with C++" workload installed before running `setup.sh`.

---

## Install

```sh
git clone https://github.com/giovabal/pulpit
cd pulpit
sh setup.sh      # creates a virtual environment and installs all dependencies
source .venv/bin/activate
```

Or install manually into an existing environment:

```sh
pip install -r requirements.txt
```

---

## Get Telegram API credentials

Think of this as connecting Pulpit to your Telegram account — exactly like authorising any third-party app on your phone. Telegram will send you a verification code the first time you run a data collection command.

1. Go to [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id)
2. Log in with your Telegram account
3. Create a new application — set **Platform** to `Web`; the name and URL are for your reference only
4. You will receive an **API ID** (an integer) and an **API hash** (a hex string)
5. Copy these, along with the phone number linked to your Telegram account

---

## Configure

Copy the example configuration and fill in your credentials:

```sh
cp env.example .env
```

Open `.env` and set the three required values:

```
TELEGRAM_API_ID=<your API ID>
TELEGRAM_API_HASH=<your API hash>
TELEGRAM_PHONE_NUMBER=<your phone number, with country code, e.g. +39123456789>
```

All other settings have sensible defaults and can be left as-is for a first run. See [CONFIGURATION.md](../CONFIGURATION.md) for the full reference.

---

## Initialise the database

By default Pulpit uses SQLite, which requires no configuration beyond what you have already done.

```sh
python manage.py migrate
```

### Using a server-based database

If you need PostgreSQL, MySQL, MariaDB, or Oracle — for example because Pulpit runs on a shared server accessed by multiple processes — set `DB_ENGINE` in `.env` and install the corresponding driver:

```sh
pip install psycopg2-binary   # PostgreSQL
pip install mysqlclient        # MySQL or MariaDB
pip install oracledb           # Oracle
```

Then configure the connection in `.env` (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`) and run `migrate`.

### Migrating between database engines

Django's `dumpdata` / `loaddata` commands transfer all data between any two supported backends. Media files (channel avatars) live on disk and do not need to be migrated.

**SQLite → PostgreSQL:**

```sh
# 1. Dump all data from the current SQLite database
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json

# 2. Switch .env to the new backend
#    DB_ENGINE=postgresql  DB_NAME=...  DB_USER=...  DB_PASSWORD=...  DB_HOST=...

# 3. Create the PostgreSQL database
createdb -U <user> <dbname>

# 4. Create the schema on the new database
python manage.py migrate

# 5. Load the data
python manage.py loaddata data.json
```

**SQLite → MySQL / MariaDB:**

```sh
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json
# Switch .env: DB_ENGINE=mysql  DB_NAME=...
mysql -u <user> -p -e "CREATE DATABASE <dbname> CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python manage.py migrate && python manage.py loaddata data.json
```

**SQLite → Oracle:**

```sh
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json
# Switch .env: DB_ENGINE=oracle  DB_NAME=ORCL  DB_USER=...  DB_PASSWORD=...  DB_HOST=...
# Create the Oracle user/schema as DBA, then:
python manage.py migrate && python manage.py loaddata data.json
```

The same pattern works for any combination: dump from the source, point `.env` at the target, run `migrate`, then `loaddata`.

> `--exclude contenttypes` and `--exclude auth.permission` are necessary — these tables are populated automatically by `migrate` and re-importing them causes primary-key conflicts.

---

## First run

```sh
python manage.py runserver
```

Open [http://localhost:8000](http://localhost:8000). The browser interface drives the entire workflow from here.

---

## Access control

By default (`WEB_ACCESS=ALL`) the interface is fully open — no login required. This is appropriate for running Pulpit locally on your own machine.

If the server is reachable on a network, restrict access in `.env`:

| Setting | Effect |
| :------ | :----- |
| `WEB_ACCESS=ALL` | No login required anywhere (default) |
| `WEB_ACCESS=OPEN` | Public pages remain open; `/operations/` and `/manage/` require a staff account |
| `WEB_ACCESS=PROTECTED` | All pages require login; `/operations/` and `/manage/` additionally require staff |

In either restricted mode, create at least one staff account before starting the server:

```sh
python manage.py createsuperuser
```

This account can log in to both `/admin/` and `/operations/`. Regular (non-staff) accounts can view pages in `PROTECTED` mode but cannot launch operations or administer data.

---

## What's next

With the server running and credentials configured, proceed to [Workflow](workflow.md) for a step-by-step guide to finding channels, crawling data, and exporting the network.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

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

```sh
python manage.py migrate
```

## Access control

By default (`WEB_ACCESS=ALL`) the interface is fully open — no login required. This is suitable for running Pulpit locally on your own machine.

If the server is reachable on a network, set `WEB_ACCESS` in `.env` to restrict access:

- **`OPEN`** — read-only pages (Network, Channels, Data) remain public. The Admin and Ops panel require a **staff** account.
- **`PROTECTED`** — all pages require login. Admin and Ops additionally require a **staff** account.

In either restricted mode, create at least one staff account before starting the server:

```sh
python manage.py createsuperuser
```

This account can log in to both `/admin/` and `/ops/`. You can also create regular (non-staff) accounts in the admin; in `PROTECTED` mode they can view pages but not administer or operate the system.

## Next steps

Start the server and open the browser interface:

```sh
python manage.py runserver   # open http://localhost:8000
```

The **Ops panel** (`/ops/`) lets you launch and monitor all data collection and export tasks directly from the browser. See [WORKFLOW.md](WORKFLOW.md) for the complete step-by-step guide.

---

← [README](README.md) · [Workflow](WORKFLOW.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md) · [Screenshots](SCREENSHOTS.md)

<img src="webapp_engine/static/pulpit_logo.svg" alt="" width="80">

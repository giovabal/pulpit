# Getting started

This guide walks you through installing Pulpit, connecting it to your Telegram account, and opening it in a browser for the first time. You do not need programming experience to follow these steps.

---

## Before you begin

You will need two things:

**1. Python** — the programming language Pulpit runs on. Download the installer from [python.org/downloads](https://www.python.org/downloads/) and run it. Choose version 3.12, 3.13, or 3.14 — Pulpit fully supports all three. On the download page, click the button for your operating system (Windows, Mac, or Linux).

> **Windows users:** During the Python installer, tick the box that says **"Add Python to PATH"** before clicking Install. If you miss this step, the terminal commands below will not work.

**2. A Telegram account** — Pulpit connects to Telegram using your account credentials. You will need the phone number linked to your Telegram account.

> **Git is optional.** The recommended install below is a plain download — no Git needed. Git is only required for the [alternative install](#alternative-install-with-git), which makes updating Pulpit easier later on. If you want it, download it from [git-scm.com/downloads](https://git-scm.com/downloads), run the installer with the default options, and — on Mac, if prompted — accept the Xcode Command Line Tools.

---

## Step 1 — Download Pulpit

The recommended way to install Pulpit is to download the latest **stable release** — a tested, fixed snapshot of the project.

1. Open the **[releases page](https://github.com/giovabal/pulpit/releases/latest)** in your browser.
2. Under **Assets**, click **Source code (zip)** to download it.
3. Unzip the downloaded file. This gives you a folder named something like `pulpit-0.25` (the number is the version). Move it wherever you'd like to keep it — your Documents folder is fine.

Now open a terminal (on Windows: search for **Command Prompt** or **PowerShell**; on Mac: search for **Terminal**; on Linux: you know what to do), move into that folder, and run the setup script:

**macOS / Linux**
```sh
cd path/to/pulpit-0.25
sh setup.sh
```

**Windows**
```cmd
cd path\to\pulpit-0.25
setup.bat
```

- `cd …` moves you into the folder you just unzipped. *(Tip: type `cd` followed by a space, then drag the folder onto the terminal window to fill in its path automatically.)*
- `sh setup.sh` (or `setup.bat` on Windows) checks your Python version, installs dependencies, creates a `.env` configuration file, and prepares the database. This may take a minute or two.

> **Updating later:** to move to a newer release, download the latest zip again and re-run the setup script in the new folder. Pulpit will show an "update available" hint in the interface when a newer version is published.

### Alternative: install with Git

If you already use [Git](https://git-scm.com/downloads), you can clone the repository instead of downloading the zip. This makes updating as simple as `git pull` later, but it gives you the **latest development code** rather than the stable release — newer features, with the occasional rough edge.

Open a terminal and run these commands one at a time, pressing Enter after each:

```sh
git clone https://github.com/giovabal/pulpit
cd pulpit
sh setup.sh
```

- `git clone` downloads a copy of Pulpit into a new folder called `pulpit`.
- `cd pulpit` moves you into that folder.
- `sh setup.sh` runs the same setup as the download method above.

> **Windows users:** run `setup.bat` instead of `sh setup.sh`.

---

## Step 2 — Get Telegram API credentials

Think of this step as authorising Pulpit to use your Telegram account — the same way you might authorise a third-party app on your phone. Pulpit will send a verification code to your Telegram app the first time it connects.

**To get your credentials:**

1. Go to [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id) and log in with your Telegram account.
2. Create a new application. You can set **Platform** to `Web`; the app name and URL are for your reference only and do not affect anything.
3. After saving, the page shows your **API ID** (a short number) and **API hash** (a long string of letters and numbers). Keep this page open — you will paste these values in the next step.

> **Is this safe?** Yes. You are not giving your password to anyone. The API ID and hash are credentials Telegram provides for you to build tools on top of your own account. Pulpit only accesses channels whose messages are publicly readable — the same ones anyone can view in the Telegram app.

---

## Step 3 — Fill in your credentials

The setup script (`setup.sh` on Mac/Linux, `setup.bat` on Windows) already created your credentials file:

- **`configuration/.env`** — credentials and deployment settings. Open it and fill in your Telegram credentials. Also holds optional Telegram-client tuning (`TELEGRAM_SESSION_NAME`, `TELEGRAM_CONNECTION_RETRIES`, `TELEGRAM_FLOOD_SLEEP_THRESHOLD`, etc.); see the commented block in `configuration/env.example`. Sensible defaults apply when these are unset.

Crawler and analysis form defaults ship in two committed TOML files under `configuration/` — **`.operations-crawl`** and **`.operations-structural`** — that pre-populate the Operations panel. You don't need to edit them by hand. After you've configured a Crawl Channels or Structural Analysis form to taste, click **Save as defaults**, type a title, and a timestamped snapshot is written alongside the baseline. Click **Load defaults** on a later visit to pick from any saved snapshot (the committed baseline is always available as "Pulpit defaults"). See [Operations defaults & configuration](operations-defaults.md) for the full picture.

Open `configuration/.env` in any text editor (Notepad on Windows; TextEdit on Mac; any editor on Linux). Find these three lines and replace the placeholders with your values:

```
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_PHONE_NUMBER=+39123456789
```

Use the phone number linked to your Telegram account, including the country code (e.g. `+1` for USA, `+44` for UK, `+39` for Italy). Save the file.

All other settings have sensible defaults. You do not need to change anything else for a first run.

---

## Step 4 — Start Pulpit

```sh
python manage.py runserver
```

You should see a message ending with `Starting development server at http://127.0.0.1:8000/`. Open your browser and go to:

**[http://localhost:8000](http://localhost:8000)**

You are now looking at the Pulpit interface. Proceed to [Workflow](workflow.md) for a guided walkthrough of the four-step pipeline.

> **Leaving Pulpit running:** the server keeps running until you stop it. To stop it, press **Ctrl + C** in the terminal. To start it again later, run `python manage.py runserver` from inside your Pulpit folder (the one you unzipped or cloned).

---

## Access control

If you are running Pulpit on your own laptop or desktop, you do not need to change anything here — the default settings are fine.

If you plan to run Pulpit on a server that other people can reach over a network, you can restrict who can access the interface. Set the `WEB_ACCESS` value in your `configuration/.env` file:

| Value | Effect |
| :---- | :----- |
| `ALL` (default) | No login required. Fine for personal use on your own machine. |
| `OPEN` | The channel browser and graphs are public; the Operations panel and Manage section require an account. |
| `PROTECTED` | Everything requires a login. The Operations panel and Manage section additionally require an administrator account. |

To create an administrator account before starting the server:

```sh
python manage.py createsuperuser
```

Follow the prompts to set a username and password. This account can log in to all restricted pages.

---

## Troubleshooting

**"python: command not found" or "python is not recognised"**
Python is not installed or not on your PATH. Re-install Python and make sure to tick "Add Python to PATH" during setup (Windows), or use `python3` instead of `python` (Mac/Linux).

**"git: command not found"** *(only if you chose the Git install)*
Git is not installed. Either install it from [git-scm.com/downloads](https://git-scm.com/downloads), or use the recommended [stable-release download](#step-1--download-pulpit) instead — it doesn't need Git.

**"No module named …"**
The setup script may not have run completely. Try: `pip install -r requirements.txt`.

**Missing `configuration/.env`**
Run `setup.sh` (or `setup.bat`) — it creates it from `configuration/env.example` automatically. If you prefer to create it manually: `cp configuration/env.example configuration/.env` (use `copy` on Windows). The `.operations-crawl` / `.operations-structural` files are committed in the repository and pre-populate the Operations-panel form on first run; "Save as defaults" later writes timestamped snapshots alongside them. See [Operations defaults & configuration](operations-defaults.md).

**The server starts but the browser shows an error**
Check the terminal for error messages. If the error mentions missing tables, run `python manage.py migrate` manually — this can happen if `setup.sh` was interrupted before it finished.

---

## Advanced: using a server database

The default SQLite database is a single file and works well for personal research. If you need to run Pulpit on a shared server accessed by multiple users or processes simultaneously, you can switch to PostgreSQL, MySQL/MariaDB, or Oracle.

Install the corresponding Python driver:

```sh
pip install psycopg2-binary   # PostgreSQL
pip install mysqlclient        # MySQL or MariaDB
pip install oracledb           # Oracle
```

Then set `DB_ENGINE` and the connection fields in `.env` (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`) and run `python manage.py migrate` on the new database.

To move existing data from SQLite to another engine:

**macOS / Linux**
```sh
# 1. Export all data from SQLite
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    -o data.json

# 2. Point .env at the new database and run migrate
python manage.py migrate

# 3. Import the data
python manage.py loaddata data.json
```

**Windows**
```cmd
rem 1. Export all data from SQLite
python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission -o data.json

rem 2. Point .env at the new database and run migrate
python manage.py migrate

rem 3. Import the data
python manage.py loaddata data.json
```

The `--exclude` flags are required — those tables are populated automatically by `migrate` and re-importing them causes conflicts.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Layouts](graph-layouts.md) · [Vacancy analysis](vacancy-analysis.md) · [Robustness](robustness-analysis.md) · [Interesting messages](interesting-messages.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

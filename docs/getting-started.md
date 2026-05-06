# Getting started

This guide walks you through installing Pulpit, connecting it to your Telegram account, and opening it in a browser for the first time. You do not need programming experience to follow these steps.

---

## Before you begin

You will need three things:

**1. Python** — the programming language Pulpit runs on. Download the installer from [python.org/downloads](https://www.python.org/downloads/) and run it. Choose version 3.12 or later. On the download page, click the button for your operating system (Windows, Mac, or Linux).

> **Windows users:** During the Python installer, tick the box that says **"Add Python to PATH"** before clicking Install. If you miss this step, the terminal commands below will not work.

**2. Git** — a tool for downloading code. Download it from [git-scm.com/downloads](https://git-scm.com/downloads) and run the installer with the default options. On Mac, if prompted to install the Xcode Command Line Tools, accept.

**3. A Telegram account** — Pulpit connects to Telegram using your account credentials. You will need the phone number linked to your Telegram account.

---

## Step 1 — Download Pulpit

Open a terminal (on Windows: search for **Command Prompt** or **PowerShell**; on Mac: search for **Terminal**; on Linux: you know what to do).

Run these commands one at a time, pressing Enter after each:

```sh
git clone https://github.com/giovabal/pulpit
cd pulpit
sh setup.sh
```

- `git clone` downloads a copy of Pulpit to a new folder called `pulpit` on your computer.
- `cd pulpit` moves you into that folder.
- `sh setup.sh` installs Pulpit's dependencies (this may take a minute or two).

> **Windows note:** if `sh setup.sh` does not work, run `setup.bat` instead.

---

## Step 2 — Get Telegram API credentials

Think of this step as authorising Pulpit to use your Telegram account — the same way you might authorise a third-party app on your phone. Pulpit will send a verification code to your Telegram app the first time it connects.

**To get your credentials:**

1. Go to [core.telegram.org/api/obtaining_api_id](https://core.telegram.org/api/obtaining_api_id) and log in with your Telegram account.
2. Create a new application. You can set **Platform** to `Web`; the app name and URL are for your reference only and do not affect anything.
3. After saving, the page shows your **API ID** (a short number) and **API hash** (a long string of letters and numbers). Keep this page open — you will paste these values in the next step.

> **Is this safe?** Yes. You are not giving your password to anyone. The API ID and hash are credentials Telegram provides for you to build tools on top of your own account. Pulpit only accesses channels whose messages are publicly readable — the same ones anyone can view in the Telegram app.

---

## Step 3 — Create the configuration file

In the `pulpit` folder, copy the example settings file:

```sh
cp env.example .env
```

> **Windows users:** use `copy env.example .env` instead of `cp`.

Open the new `.env` file in any text editor (Notepad works fine on Windows; TextEdit on Mac; any editor on Linux). Find these three lines and replace the placeholders with your values:

```
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_PHONE_NUMBER=+39123456789
```

Use the phone number linked to your Telegram account, including the country code (e.g. `+1` for USA, `+44` for UK, `+39` for Italy). Save the file.

All other settings have sensible defaults. You do not need to change anything else for a first run.

---

## Step 4 — Prepare the database

Pulpit stores everything — channels, messages, settings — in a database file on your computer. Run this command to create it:

```sh
python manage.py migrate
```

You should see a series of lines like `Applying webapp.0001_initial... OK`. Once it finishes, the database is ready.

---

## Step 5 — Start Pulpit

```sh
python manage.py runserver
```

You should see a message ending with `Starting development server at http://127.0.0.1:8000/`. Open your browser and go to:

**[http://localhost:8000](http://localhost:8000)**

You are now looking at the Pulpit interface. Proceed to [Workflow](workflow.md) for a guided walkthrough of the four-step pipeline.

> **Leaving Pulpit running:** the server keeps running until you stop it. To stop it, press **Ctrl + C** in the terminal. To start it again later, run `python manage.py runserver` from inside the `pulpit` folder.

---

## Access control

If you are running Pulpit on your own laptop or desktop, you do not need to change anything here — the default settings are fine.

If you plan to run Pulpit on a server that other people can reach over a network, you can restrict who can access the interface. Set the `WEB_ACCESS` value in your `.env` file:

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

**"git: command not found"**
Git is not installed. Download it from [git-scm.com/downloads](https://git-scm.com/downloads).

**"No module named …"**
The setup script may not have run completely. Try: `pip install -r requirements.txt`.

**The server starts but the browser shows an error**
Make sure you ran `python manage.py migrate` before `python manage.py runserver`. If the problem persists, check the terminal for error messages.

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

The `--exclude` flags are required — those tables are populated automatically by `migrate` and re-importing them causes conflicts.

---

← [README](../README.md) · [Getting started](getting-started.md) · [Workflow](workflow.md) · [Measures](network-measures.md) · [Communities](community-detection.md) · [Network stats](whole-network-statistics.md) · [Vacancy analysis](vacancy-analysis.md) · [Web interface](web-interface.md) · [Exports](export-formats.md)

<img src="../webapp_engine/static/pulpit_logo.svg" alt="" width="80">

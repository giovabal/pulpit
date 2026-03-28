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

## Next steps

You are ready to start collecting data. See [WORKFLOW.md](WORKFLOW.md) for the complete step-by-step guide.

---

← [README](README.md) · [Workflow](WORKFLOW.md) · [Configuration](CONFIGURATION.md) · [Analysis](ANALYSIS.md) · [Changelog](CHANGELOG.md)

@echo off
setlocal enabledelayedexpansion

rem Require Python 3.12. Newer interpreters cannot install this project: the numpy<2 pin
rem (kept for graph-tool ABI compatibility, see requirements.txt) has no wheels for 3.13+.
python -c "import sys; exit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>nul
if errorlevel 1 (
    echo Error: Python 3.12 is required. Download from https://python.org/downloads
    exit /b 1
)

rem Create virtual environment if it does not exist
if not exist ".venv" (
    python -m venv .venv
)

rem Activate the environment
call .venv\Scripts\activate.bat

rem Upgrade pip and install requirements
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements_dev.txt

rem Bootstrap configuration\.env from configuration\env.example if not present
if not exist "configuration" mkdir configuration
if not exist "configuration\.env" (
    if exist "configuration\env.example" (
        copy configuration\env.example configuration\.env >nul
        echo.
        echo Created configuration\.env from configuration\env.example.
        echo Edit configuration\.env and fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE_NUMBER before running the server.
    ) else (
        echo Warning: configuration\env.example not found -- create configuration\.env manually before running the server.
    )
)

rem Crawler and structural-analysis defaults live in webapp_engine\config\defaults.py.
rem A configuration\.operations-crawl or configuration\.operations-structural file is
rem only created when the user clicks "Save as defaults" in the Operations panel
rem (or hand-writes one). Until then, the built-in defaults apply.

rem Install dev tooling (html-validate for the static-export HTML lint).
rem npm is optional -- skip with a friendly note if it is not on PATH.
where npm >nul 2>&1
if errorlevel 1 (
    echo Note: npm not found -- skipping html-validate install.
    echo Install Node.js to enable 'npm run lint:html'.
) else (
    call npm install --no-audit --no-fund --loglevel=error
)

rem Apply database migrations
python manage.py migrate

echo.
echo Setup complete. The virtual environment is active in this session.
echo Start the server with:
echo   python manage.py runserver

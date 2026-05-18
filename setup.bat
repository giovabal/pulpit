@echo off
setlocal enabledelayedexpansion

rem Require Python 3.12
python -c "import sys; exit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>nul
if errorlevel 1 (
    echo Error: Python 3.12 required. Download from https://python.org/downloads
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

rem Bootstrap .env from env.example if not present
if not exist ".env" (
    if exist "env.example" (
        copy env.example .env >nul
        echo.
        echo Created .env from env.example.
        echo Edit .env and fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_PHONE_NUMBER before running the server.
    ) else (
        echo Warning: env.example not found -- create .env manually before running the server.
    )
)

rem Bootstrap .analysis-defaults from analysis-defaults.example if not present
if not exist ".analysis-defaults" (
    if exist "analysis-defaults.example" (
        copy analysis-defaults.example .analysis-defaults >nul
        echo Created .analysis-defaults from analysis-defaults.example.
        echo Edit .analysis-defaults to tune crawling and analysis options.
    ) else (
        echo Warning: analysis-defaults.example not found -- .analysis-defaults will use built-in defaults.
    )
)

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

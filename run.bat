@echo off
setlocal

rem Start Pulpit: activate the virtual environment, launch the Django
rem development server, and open the home page in your default browser.
rem
rem Usage: run.bat [PORT]   (PORT defaults to 8000)

rem Move to the project root (the folder containing this script).
cd /d "%~dp0"

set "HOST=127.0.0.1"
if "%~1"=="" (set "PORT=8000") else (set "PORT=%~1")
set "URL=http://%HOST%:%PORT%/"

rem Make sure the virtual environment exists before doing anything else.
if not exist ".venv\Scripts\activate.bat" (
    echo Error: virtual environment not found ^(.venv^).
    echo Run setup.bat first to create it.
    exit /b 1
)

rem Activate the virtual environment.
call ".venv\Scripts\activate.bat"

echo Starting Pulpit at %URL%
echo The browser will open automatically once the server is ready.
echo Press Ctrl+C to stop the server.

rem Launch a detached helper that waits for the server to start accepting
rem connections, then opens the home page in the default browser. Fall back to
rem opening immediately if PowerShell is unavailable.
where powershell >nul 2>&1
if errorlevel 1 goto :open_now

start "" /min powershell -NoProfile -WindowStyle Hidden -Command "$n=0; do { Start-Sleep -Milliseconds 400; $n++ } until ((Test-NetConnection -ComputerName %HOST% -Port %PORT% -InformationLevel Quiet) -or ($n -ge 75)); Start-Process '%URL%'"
goto :run_server

:open_now
start "" %URL%

:run_server
rem Start the development server (blocks until you press Ctrl+C).
python manage.py runserver %HOST%:%PORT%

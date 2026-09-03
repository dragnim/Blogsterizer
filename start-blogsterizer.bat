@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install Python 3.11 or later, then run this file again.
        pause
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo The Blogsterizer requires Python 3.11 or later.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating the local Python environment...
    %PYTHON_CMD% -m venv .venv
)

call .venv\Scripts\activate.bat

if not exist .venv\.blogsterizer-0.5.0-installed (
    echo Installing The Blogsterizer...
    python -m pip install -e .
    if errorlevel 1 (
        echo Installation failed.
        pause
        exit /b 1
    )
    type nul > .venv\.blogsterizer-0.5.0-installed
)

rem Give the server a moment to start before opening the browser.
start "" /b python -c "import time, webbrowser; time.sleep(2); webbrowser.open('http://127.0.0.1:8000')"
python -m uvicorn app.main:app --reload

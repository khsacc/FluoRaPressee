@echo off
REM Create a virtual environment (.venv) and install dependencies.
REM Run this once after cloning the repository.

setlocal

cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Is Python installed and on PATH?
        exit /b 1
    )
) else (
    echo .venv already exists, skipping creation.
)

echo Installing dependencies...
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\pip.exe install -r requirements.txt

echo.
echo Setup complete. Use run.bat (hardware) or run_debug.bat (no hardware) to launch the app.

endlocal

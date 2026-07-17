@echo off
REM Launch the app using the .venv virtual environment (requires real hardware + PICam Runtime).

cd /d "%~dp0"

if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\python.exe main.py

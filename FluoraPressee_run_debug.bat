@echo off
REM Launch the app in debug mode (simulated camera/spectrometer, no hardware needed).

cd /d "%~dp0"

if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\python.exe main.py --debug

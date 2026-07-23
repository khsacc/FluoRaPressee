@echo off
REM Complete setup for Ocean Optics users: create .venv, install all application
REM dependencies plus seabreeze, and install the Windows SeaBreeze drivers.
REM This script replaces setup.bat for Ocean Optics users.

setlocal

cd /d "%~dp0"

REM Driver installation is a persistent machine-wide change. Check elevation before
REM doing any package installation so a non-elevated run does not perform half a setup.
fltmc >nul 2>&1
if errorlevel 1 (
    echo ERROR: Ocean Optics setup requires Administrator privileges.
    echo Right-click setup_oceanoptics.bat and choose "Run as administrator".
    exit /b 1
)

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

echo Installing application and Ocean Optics dependencies...
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
call .venv\Scripts\python.exe -m pip install -r requirements-oceanoptics.txt
if errorlevel 1 exit /b 1
call .venv\Scripts\python.exe -m pip check
if errorlevel 1 exit /b 1

echo Running seabreeze_os_setup to install the Windows SeaBreeze drivers...
call .venv\Scripts\seabreeze_os_setup.exe
if errorlevel 1 (
    echo ERROR: seabreeze_os_setup failed. The Ocean Optics driver was not confirmed.
    exit /b 1
)

echo Verifying that SeaBreeze can enumerate the instrument...
call .venv\Scripts\python.exe -c "from seabreeze.spectrometers import list_devices; d=list_devices(); print('Detected:', d); raise SystemExit(0 if d else 1)"
if errorlevel 1 (
    echo ERROR: SeaBreeze still cannot detect an instrument. Unplug/reconnect it and run this script again.
    exit /b 1
)

echo.
echo Ocean Optics setup complete. Set "model": "OceanOptics" in spectrometerConfig.json to use it.

endlocal

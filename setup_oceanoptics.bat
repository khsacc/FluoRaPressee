@echo off
REM Install optional Ocean Optics (seabreeze) support into the existing .venv.
REM Run setup.bat first to create the virtual environment; this script only adds the
REM Ocean Optics dependency on top of it. See work\work_OceanOptics.md for background.

setlocal

cd /d "%~dp0"

if not exist .venv (
    echo No .venv found. Run setup.bat first.
    exit /b 1
)

echo Installing Ocean Optics (seabreeze) dependencies...
call .venv\Scripts\pip.exe install -r requirements-oceanoptics.txt
if errorlevel 1 exit /b 1

REM Driver installation is a persistent machine-wide change.  seabreeze_os_setup tries
REM to start a second elevated process when this shell is not elevated, then returns
REM before that process finishes; the old script consequently printed a false success.
fltmc >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Windows driver installation requires Administrator privileges.
    echo Right-click setup_oceanoptics.bat and choose "Run as administrator".
    exit /b 1
)

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

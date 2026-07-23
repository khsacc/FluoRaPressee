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

echo Running seabreeze_os_setup (installs Windows driver configuration if needed)...
call .venv\Scripts\seabreeze_os_setup.exe
if errorlevel 1 (
    echo seabreeze_os_setup failed or was not needed on this OS; see the python-seabreeze documentation.
)

echo.
echo Ocean Optics setup complete. Set "model": "OceanOptics" in spectrometerConfig.json to use it.

endlocal

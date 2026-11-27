# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FluoRaPressée (work/work_updater.md 方針11/12, Step 3).

Build through packaging/build_windows.ps1 rather than calling PyInstaller directly,
so that src/_build_info.py exists and the smoke tests run.

One onedir build with three executables sharing one `_internal` folder:

    FluoRaPressee.exe                     live GUI (windowed)
    FluoRaPressee-Analysis.exe            Analysis Mode (windowed)
    FluoRaPressee-OceanOpticsDriver.exe   Ocean Optics driver installer (console,
                                          asks for administrator rights)

Every hardware backend is included; which one is used is still decided by
spectrometerConfig.json's "model". Vendor SDKs/runtimes (Andor SDK, PICam,
ShamrockCIF.dll) are not bundled - their licences do not allow it.
"""

import os

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ICON = os.path.join(REPO, "logo", "app_icon.ico")
ICON = ICON if os.path.exists(ICON) else None

DATAS = [
    (os.path.join(REPO, "calibrationStandards"), "calibrationStandards"),
] + [
    # Only the window icon: logo/ also holds large artwork sources.
    (path, "logo") for path in (
        os.path.join(REPO, "logo", "app_icon.ico"),
        os.path.join(REPO, "logo", "app_icon.png"),
    ) if os.path.exists(path)
]

# Only PyQt6 may be loaded (see src/hardware/pylablib_loader.py).
EXCLUDES = ["PyQt5", "PySide2", "PySide6", "tkinter"]

LIVE_HIDDEN = (
    # uvicorn picks its loop/protocol/lifespan implementations by name at run time.
    collect_submodules("uvicorn")
    # pyLabLib device modules are imported by name through pylablib_loader.
    + collect_submodules("pylablib.devices.Andor")
    + collect_submodules("pylablib.devices.PrincetonInstruments")
    # seabreeze is imported lazily, only when an Ocean Optics model is configured.
    + collect_submodules("seabreeze")
    # pythonnet (Princeton Instruments calibration, src/hardware/princeton_calibration.py).
    + ["pythonnet", "clr", "clr_loader"]
    + ["src._build_info"]
)
DRIVER_HIDDEN = collect_submodules("seabreeze") + ["src._build_info"]
ANALYSIS_HIDDEN = ["src._build_info"]

SEABREEZE_BINARIES = collect_dynamic_libs("seabreeze")


def analysis(script, hiddenimports, binaries=()):
    return Analysis(
        [script],
        pathex=[REPO],
        binaries=list(binaries),
        datas=DATAS,
        hiddenimports=hiddenimports,
        excludes=EXCLUDES,
        noarchive=False,
    )


def executable(an, name, console, uac_admin=False):
    return EXE(
        PYZ(an.pure),
        an.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=ICON,
        uac_admin=uac_admin,
        upx=False,
    )


a_live = analysis(os.path.join(REPO, "main.py"), LIVE_HIDDEN, SEABREEZE_BINARIES)
a_analysis = analysis(os.path.join(REPO, "analysis_main.py"), ANALYSIS_HIDDEN)
a_driver = analysis(
    os.path.join(SPECPATH, "oceanoptics_driver.py"), DRIVER_HIDDEN, SEABREEZE_BINARIES
)

exe_live = executable(a_live, "FluoRaPressee", console=False)
exe_analysis = executable(a_analysis, "FluoRaPressee-Analysis", console=False)
# Console so the progress is visible; uac_admin so that starting it from the Start
# menu asks for the administrator rights the driver installation needs.
exe_driver = executable(
    a_driver, "FluoRaPressee-OceanOpticsDriver", console=True, uac_admin=True
)

coll = COLLECT(
    exe_live, a_live.binaries, a_live.datas,
    exe_analysis, a_analysis.binaries, a_analysis.datas,
    exe_driver, a_driver.binaries, a_driver.datas,
    strip=False,
    upx=False,
    name="FluoRaPressee",
)

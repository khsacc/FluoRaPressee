# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FluoraPressée is a PyQt6 desktop GUI for controlling Andor/Princeton Instruments spectrometer+camera
rigs and analyzing the resulting spectra for high-pressure experiments (ruby
fluorescence pressure scale, Raman shift, etc.). It is a lab instrument-control tool, not a library or
service. 

## Running the app

```bash
python main.py            # normal mode — requires real hardware + Andor SDK installed
python main.py --debug    # debug mode — simulates camera/spectrometer, no hardware needed
```

Dependencies are listed in `requirements.txt` (no `pyproject.toml`): `PyQt6`, `pyqtgraph`, `numpy`,
`scipy`, plus `pylablib` (Andor/Princeton camera SDK wrappers; its optional Qt5 GUI import is blocked
by `src/pylablib_loader.py`, so only PyQt6 is loaded into the process) and `pyserial` (Princeton
spectrometer serial control)
for hardware mode, plus `fastapi`/`uvicorn`/`pydantic` for the optional HTTP API layer (see
Architecture below). Install with `pip install -r requirements.txt`. The app targets Windows (Andor
SDK is Windows-only, and `ShamrockCIF.dll` at repo root is loaded via `ctypes` for Shamrock
spectrometer control), but `--debug` mode runs fine cross-platform for UI development.

Automated tests use the standard-library `unittest` runner. Run them headlessly with
`QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`, then verify GUI changes by
running the app in `--debug` mode and exercising the relevant UI flow.

It is not required to verify screenshots once you made changes to GUI. If something is needed to be checked, ask the user. 

## Architecture

**Entry point**: `main.py` sets `QT_OPENGL=software`, prints startup info, ensures
`spectrometerConfig.json` exists (prompting the user for grating grooves/mm if not — see
`check_and_create_config()` in `src/app_bootstrap.py`), then constructs `SpectrometerGUI` from
`src/ui.py`.

**`src/ui.py`** (`SpectrometerGUI`) now holds only `__init__` (widget construction and signal wiring)
and `closeEvent`; every event handler and piece of application state (calibration coefficients,
background data, sequential-save state, fit results, etc.) lives in one of the Mixin classes under
`src/ui_mixins/`, which `SpectrometerGUI` multiply inherits from:
- `config_mixin.py` (`ConfigMixin`): spectrometer config file / local UI cache load-save, per-grating ROI defaults.
- `file_io_mixin.py` (`FileIOMixin`): background acquisition/mismatch checks, save/load dialogs, calibration loading.
- `spectrometer_control_mixin.py` (`SpectrometerControlMixin`): wavelength/Raman mode switching, grating/centre-wavelength Apply flow, neon calibration launch.
- `sequential_mixin.py` (`SequentialMixin`): sequential (continuous) measurement start/stop/progress and directory selection.
- `acquisition_mixin.py` (`AcquisitionMixin`): camera thread interaction — single-shot/continuous measurement, exposure/temperature/ROI, accumulation and frame handling.
- `display_mixin.py` (`DisplayMixin`): plot/image rendering, peak fitting invocation and result display, mouse-hover readout.
- `pressure_dialog_mixin.py` (`PressureDialogMixin`): opening/syncing the pressure calculator window.

The live GUI and hardware-free Analysis Mode both use
`src/fitting_config_widget.py` (`FittingConfigWidget`) for the complete fitting-settings panel;
keep control choices, labels, ranges, and defaults in that shared widget rather than duplicating them
in either window. `src/analysis_ui.py` embeds the existing `PressureCalculatorWindow` directly in its
right-hand panel (`embedded=True`), while the live GUI continues to use the same class as a dialog.

Mixins are plain Python classes (no `QObject` base) that assume they're mixed into `SpectrometerGUI`,
so they freely call `self.xxx` across mixin boundaries — all methods end up on the same instance at
runtime. When making UI changes, find the mixin that owns the relevant behavior (or `__init__` for
widget/layout changes); when making analysis/calibration/pressure logic changes, prefer the dedicated
modules below and keep the mixins as thin callers.

**Hardware abstraction (factory pattern)**: `src/camera.py` and `src/spectrometer.py` are *not* classes
— they're factory functions (`CameraThread(config, debug)`, `SpectrometerController(config, debug)`)
that read `config["model"]` (from `spectrometerConfig.json`, default `"Andor"`) and return either the
`*_andor.py` or `*_princeton.py` implementation. `src/ui.py` and other consumers only ever import from
`src.camera`/`src.spectrometer`, never the `_andor`/`_princeton` files directly. Adding a third hardware
backend means adding a new `camera_<vendor>.py` / `spectrometer_<vendor>.py` pair with the same public
interface and extending these two factory functions.

- `camera_andor.py` / `camera_princeton.py`: `QThread` subclasses that poll the detector in a loop and
  emit `data_ready`/`temperature_ready`/etc. signals back to the GUI thread. Settings changes (exposure,
  temperature, ROI) are relayed to the thread via locked instance variables set by the GUI and read at
  the top of each loop iteration — not via direct hardware calls from the GUI thread.
- `spectrometer_andor.py` drives the Shamrock unit via `ctypes` + `ShamrockCIF.dll`.
  `spectrometer_princeton.py` drives it over serial (`pyserial`).
- **Debug mode**: every hardware class has a `debug=True` path that fabricates a synthetic ruby-like
  double-peak spectrum (with noise) instead of touching hardware. This is the primary way to develop
  and test UI/analysis changes without a spectrometer attached.

**Analysis/calibration/pressure modules** are plain Python classes with no PyQt dependency, so they're
usable standalone or from scripts:
- `src/analysis.py` (`DataAnalyzer`): 1-5 peak fitting (Gauss, Lorentz, Pseudo-Voigt, Moffat)
  with Constant/Linear/Quadratic baselines and BIC-based Auto Polynomial selection.
- `src/calibration.py` (`CalibrationCore`): pixel→wavelength/Raman-shift polynomial calibration from
  detected reference peaks; `src/calibration_ui.py` wraps it in a `QDialog`.
- `src/calibration_helper.py` (`ReferenceHelperWindow`): reference neon-line lookup dialog backed by
  the pre-generated spectra JSON in `calibrationHelper/` (produced by
  `calibrationHelper/generateCalibrationHelper.py`).
- `src/configuration_catalog.py` (`ConfigurationCatalog`): Qt-independent, versioned configuration
  storage. Immutable JSON records contain hardware compatibility, grating, centre position, ROI,
  display state, and calibration; a SQLite catalog indexes active/history versions without scanning
  every JSON file. A slot is identified by hardware namespace + grating + target centre + ROI, and
  saving another calibration for the same slot atomically makes the new record active. Both the GUI
  and future API discovery endpoints must call this class rather than duplicating selection rules.
  Hardware identity requires an exact saved serial when available and otherwise falls back to an
  exact model match; model identity is indexed in catalog schema v2.
- `src/configuration_browser.py` (`ConfigurationBrowserDialog`): the GUI's Load Configuration
  selector. It shows active, hardware-compatible catalog summaries by default and can expose
  compatible history explicitly; it never browses arbitrary legacy configuration JSON files.
- `src/pressureCalc.py` (`PressureCalculator`): static methods mapping peak shift → pressure (GPa) for
  several sensors (Ruby, Sm2+:SrB4O7, diamond, cBN, zircon) and published calibration scales, with
  per-scale temperature-validity ranges; `src/pressureCalc_ui.py` wraps it in a `QDialog`.
- `src/file_io.py` (`DataFileIO`): spectrum, background, fitting-result, and sequential-result file
  I/O, deliberately isolated with **no Qt dependency**. Versioned spectrometer configuration
  persistence is the separate responsibility of `ConfigurationCatalog`.

**Config/state files** (generated at runtime, not checked in): `spectrometerConfig.json` (grating list,
default ROIs, `flip_x`, hardware `model`) at the repo root, plus a local UI cache read/written by
`_load_local_cache`/`_save_local_cache` in `src/ui_mixins/config_mixin.py` (last save/sequential
directories, etc.). Versioned measurement configurations are stored below the user's application-data
directory in `FluoraPressee/configurations/`: canonical records under `records/YYYY/MM/` and the
query-oriented `catalog.sqlite3` index. Exposure, accumulation, sample/material, dark,
fit, and pressure settings deliberately do not belong to these records.

**Optional HTTP API layer** (`src/api/`, `src/ui_mixins/api_mixin.py`): exposes a subset of
`SpectrometerGUI`'s functionality over HTTP so other machines on the same LAN can trigger
measurements. It only starts when the user explicitly clicks "Start API Server" in the GUI's "API
Server" panel (`ApiMixin.start_api_server`/`on_start_api_server_clicked`) — the intended workflow is
to finish calibration and basic setup in the GUI first, then activate the API for remote-triggered
acquisition. While the API server is running, the GUI's measurement/config controls are disabled
(only display controls like plot style/auto-rescale remain interactive) via
`SequentialMixin._lock_ui`/`_unlock_ui`, which tracks a set of lock "reasons" (sequential run, API
server) so either one alone can hold the lock; stopping the API server is how the operator regains
full local control.

- `src/api/gui_bridge.py` (`GuiBridge`): marshals calls from the API's worker threads onto the Qt GUI
  thread via a `pyqtSignal`, since almost all of `SpectrometerGUI`'s state lives in QWidgets and Qt
  forbids touching them off-thread. Acquisition uses a two-phase Future-based handoff
  (`ApiMixin._api_start_acquire`/`api_acquire`) rather than blocking the GUI thread on the result, to
  avoid deadlocking the Qt event loop — see the module docstring for why.
- `src/api/schemas.py` / `src/api/server.py` (`create_app`): Pydantic request/response models and the
  FastAPI app factory (routes, `X-API-Key` header auth). `src/ui_mixins/api_mixin.py` (`ApiMixin`)
  implements the actual logic each route calls into (`api_acquire`, `api_fit`, `api_pressure`,
  `api_apply_calibration`, `api_get_status`, the read-only hardware/config endpoints) independent of
  the GUI's own `radio_bg_on`/`chk_flip_x`/fit-panel widgets, so a remote request never depends on or
  mutates what the operator is currently looking at. `GET /hardware/camera` and
  `GET /hardware/spectrometer` use cached metadata by default; `refresh=true` performs an exclusive
  live status query. `GET /config` distinguishes active startup hardware settings from values saved
  for the next restart and redacts secret-like keys.
- Background (dark) subtraction over the API defaults to rejecting a mismatched exposure/ROI outright
  (`BackgroundMismatchError` → HTTP 422) rather than silently subtracting an invalid dark frame;
  callers can opt into subtracting anyway (`dark.ignore_mismatch`) or supply their own dark spectrum
  directly (`dark.mode="provided"`). Remote re-acquisition of a fresh dark frame is not implemented —
  the app has no shutter control, so that needs to land in the GUI first.
- See `manuals/API.md` for the full endpoint reference and `work/work_API.md` for the implementation
  history/design rationale.

## Notes on the code

- Comments and many log/print messages are in Japanese; the README is bilingual (`README.md` /
  `README_ja.md`). Match the existing language when editing a given file's comments.
- `manuals/` contains user-facing manual images and the API reference (`manuals/API.md`), not
  internal developer docs (those live in `work/`).

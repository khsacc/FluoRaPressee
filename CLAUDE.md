# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FluoRaPressée is a PyQt6 desktop GUI for controlling Andor/Princeton Instruments spectrometer+camera
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
by `src/hardware/pylablib_loader.py`, so only PyQt6 is loaded into the process) and `pyserial` (Princeton
spectrometer serial control)
for hardware mode, plus `fastapi`/`uvicorn`/`pydantic` for the optional HTTP API layer (see
Architecture below). Install with `pip install -r requirements.txt`. The app targets Windows (Andor
SDK is Windows-only, and `ShamrockCIF.dll` at repo root is loaded via `ctypes` for Shamrock
spectrometer control), but `--debug` mode runs fine cross-platform for UI development.

Automated tests use the standard-library `unittest` runner. Run them headlessly with
`QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v`, then verify GUI changes by
running the app in `--debug` mode and exercising the relevant UI flow.

It is not required to verify screenshots once you made changes to GUI. If something is needed to be checked, ask the user. 

**Distribution (Windows builds)**: users get a PyInstaller onedir build wrapped in an Inno Setup
installer, published as a GitHub Release (design and rationale: `work/work_updater.md`).
`packaging/build_windows.ps1 [-Installer]` is the single build procedure (CI and by hand): it writes
the untracked `src/_build_info.py`, runs `--smoke-test` from source, runs PyInstaller with
`packaging/FluoRaPressee.spec` (three exes sharing one `_internal`: live GUI, Analysis Mode, and the
console `FluoRaPressee-OceanOpticsDriver.exe` from `packaging/oceanoptics_driver.py`), smoke-tests the
built exes, then optionally runs `packaging/FluoRaPressee.iss`. `main.py --smoke-test` /
`analysis_main.py --smoke-test` import every backend and the API server without touching hardware and
exit 0/1. `.github/workflows/release.yml` builds a v* tag and creates a **draft** release (drafts are
invisible to the update check). The version lives only in `src/version.py` (PEP 440; the tag must be
`v<version>`). Development PCs never install the app; installer behaviour is tested in Windows
Sandbox/VMs (`packaging/install_test.ps1` really installs, CI only). The installer's `AppId` GUID in
the `.iss` must never change.

## Architecture

**Directory layout**: `src/` holds only one entry-adjacent file at its top level —
`app_bootstrap.py` (startup bootstrap called directly by `main.py`) — with everything else grouped by
concern:
- `src/hardware/`: camera/spectrometer factories and vendor drivers, plus read-only status/diagnostics
  under `src/hardware/status/`.
- `src/core/`: Qt-independent analysis/calibration/pressure/file-I/O/configuration logic.
- `src/ui/`: the GUI itself — main window, shared widgets/dialogs, mixins (`src/ui/ui_mixins/`), and
  menu-bar dialogs (`src/ui/menu/`).
- `src/api/`: the optional HTTP API layer (see below).

**Entry points**: `main.py` first calls `src.core.app_logging.setup_stdio()` (a windowed build has
`sys.stdout is None`; output then goes to a per-process `logs/app-<kind>-<time>-<pid>.log`), sets
`QT_OPENGL=software`, prints startup info, migrates legacy repo-root files
(`src.core.app_paths.prepare_user_data`), takes the installer mutex (frozen builds only) and, in
hardware mode, the PC-wide instrument mutex (`src/core/runtime_env.py`), then ensures
`spectrometerConfig.json` exists (prompting the user for grating grooves/mm if not — see
`check_and_create_config()` in `src/app_bootstrap.py`), then constructs `SpectrometerGUI` from
`src/ui/main_window.py` (`src/ui/__init__.py` re-exports it, so `from src.ui import SpectrometerGUI`
still works). `analysis_main.py` is a second, hardware-free entry point that launches Analysis Mode
(`src/ui/analysis_ui.py`) directly, deliberately without importing `src/hardware/` or `src/api/` at all.

**`src/ui/main_window.py`** (`SpectrometerGUI`) now holds only `__init__` (widget construction and
signal wiring) and `closeEvent`; every event handler and piece of application state (calibration
coefficients, background data, sequential-save state, fit results, etc.) lives in one of the Mixin
classes under `src/ui/ui_mixins/`, which `SpectrometerGUI` multiply inherits from:
- `config_mixin.py` (`ConfigMixin`): spectrometer config file / local UI cache load-save, per-grating ROI defaults.
- `file_io_mixin.py` (`FileIOMixin`): background acquisition/mismatch checks, save/load dialogs, calibration loading.
- `spectrometer_control_mixin.py` (`SpectrometerControlMixin`): wavelength/Raman mode switching, grating/centre-wavelength Apply flow, neon calibration launch.
- `sequential_mixin.py` (`SequentialMixin`): sequential (continuous) measurement start/stop/progress and directory selection.
- `acquisition_mixin.py` (`AcquisitionMixin`): camera thread interaction — single-shot/continuous measurement, exposure/temperature/ROI, accumulation and frame handling.
- `display_mixin.py` (`DisplayMixin`): plot/image rendering, peak fitting invocation and result display, mouse-hover readout.
- `pressure_dialog_mixin.py` (`PressureDialogMixin`): opening/syncing the pressure calculator window.
- `api_mixin.py` (`ApiMixin`): implements the HTTP API's route logic (see the API section below).

Dialogs launched from the menu bar — configuration manager, hardware config, camera/instrument status —
live in `src/ui/menu/` as their own `QDialog` subclasses, separate from the mixins above.
First-run/hardware-change setup goes through `src/ui/config_wizard.py`, which uses
`src/hardware/status/hardware_probe.py` to pre-fill detected hardware.

The live GUI and hardware-free Analysis Mode both use
`src/ui/fitting_config_widget.py` (`FittingConfigWidget`) for the complete fitting-settings panel;
keep control choices, labels, ranges, and defaults in that shared widget rather than duplicating them
in either window. `src/ui/analysis_ui.py` embeds the existing `PressureCalculatorWindow` directly in its
right-hand panel (`embedded=True`), while the live GUI continues to use the same class as a dialog.

Mixins are plain Python classes (no `QObject` base) that assume they're mixed into `SpectrometerGUI`,
so they freely call `self.xxx` across mixin boundaries — all methods end up on the same instance at
runtime. When making UI changes, find the mixin that owns the relevant behavior (or `main_window.py`
for widget/layout changes); when making analysis/calibration/pressure logic changes, prefer the
dedicated modules under `src/core/` and keep the mixins as thin callers.

**Hardware abstraction (factory pattern)**: `src/hardware/camera.py` and `src/hardware/spectrometer.py`
are *not* classes — they're factory functions (`CameraThread(config, debug)`,
`SpectrometerController(config, debug)`) that read `config["model"]` (from `spectrometerConfig.json`,
default `"Andor"`) and return the `_andor`, `_princeton`, or `_oceanoptics` implementation.
`src/ui/main_window.py` and other consumers only ever import from `src.hardware.camera`/
`src.hardware.spectrometer`, never the vendor-specific files directly. Adding another hardware backend
means adding a new `camera_<vendor>.py` / `spectrometer_<vendor>.py` pair with the same public
interface and extending these two factory functions.

- `camera_andor.py` / `camera_princeton.py` / `camera_oceanoptics.py`: `QThread` subclasses that poll
  the detector in a loop and emit `data_ready`/`temperature_ready`/etc. signals back to the GUI thread.
  Settings changes (exposure, temperature, ROI) are relayed to the thread via locked instance variables
  set by the GUI and read at the top of each loop iteration — not via direct hardware calls from the
  GUI thread.
- `spectrometer_andor.py` drives the Shamrock unit via `ctypes` + `ShamrockCIF.dll`.
  `spectrometer_princeton.py` drives it over serial (`pyserial`). `spectrometer_oceanoptics.py` drives
  Ocean Optics units via `seabreeze`.
- `accumulation.py` (`AccumulationCombiner`): combines raw detector frames from one accumulation cycle
  into a single summed frame, with optional cosmic-ray spike rejection; pure NumPy, no Qt dependency.
- `src/hardware/status/` holds read-only status/diagnostics collection, kept separate from the driver
  classes above: `instrument_status.py` (shared snapshot helpers/schema), `andor_camera_status.py` /
  `andor_spectrometer_status.py` (pyLabLib/Shamrock diagnostics), `hardware_probe.py` (pre-fills the
  first-run setup wizard from connected hardware), `oceanoptics_diagnostics.py` (SeaBreeze
  discovery-failure hints).
- **Debug mode**: every hardware class has a `debug=True` path that fabricates a synthetic ruby-like
  double-peak spectrum (with noise) instead of touching hardware. This is the primary way to develop
  and test UI/analysis changes without a spectrometer attached.

**Analysis/calibration/pressure modules** (`src/core/`) are plain Python classes with no PyQt
dependency, so they're usable standalone or from scripts:
- `analysis.py` (`DataAnalyzer`): 1-5 peak fitting (Gauss, Lorentz, Pseudo-Voigt, Moffat)
  with Constant/Linear/Quadratic baselines and BIC-based Auto Polynomial selection.
- `calibration.py` (`CalibrationCore`): pixel→wavelength/Raman-shift polynomial calibration from
  detected reference peaks; `src/ui/calibration_ui.py` wraps it in a `QDialog`.
- `calibration_reference.py`: Qt-independent emission-line catalogue loading and automatic
  measured-peak/literature-line matching. `src/ui/calibration_ui.py` overlays the selected Ne I, Ar I,
  Hg I (or locally added) catalogues directly in the calibration dialog; confirmed assignments are
  retained when catalogue visibility changes. Catalogue JSON lives in `calibrationStandards/`.
  `calibration_helper.py` and `calibrationHelper/` remain only as legacy example-spectrum data
  and are no longer part of the active calibration UI.
- `configuration_catalog.py` (`ConfigurationCatalog`): Qt-independent, versioned configuration
  storage. Immutable JSON records contain hardware compatibility, grating, centre position, ROI,
  display state, and calibration (including the raw spectrum the operator fit peaks against, in
  `calibration.raw_spectrum`); a SQLite catalog indexes active/history versions without scanning
  every JSON file. A slot is identified by hardware namespace + grating + target centre + ROI, and
  saving another calibration for the same slot atomically makes the new record active. Both the GUI
  and future API discovery endpoints must call this class rather than duplicating selection rules.
  Hardware identity requires an exact saved serial when available and otherwise falls back to an
  exact model match; model identity is indexed in catalog schema v2.
  `src/ui/configuration_browser.py` (`ConfigurationBrowserDialog`) is the GUI's Load Configuration
  selector built on top of it: it shows active, hardware-compatible catalog summaries by default and
  can expose compatible history explicitly; it never browses arbitrary legacy configuration JSON files.
- `pressureCalc.py` (`PressureCalculator`): static methods mapping peak shift → pressure (GPa) for
  several sensors (Ruby, Sm2+:SrB4O7, diamond, cBN, zircon) and published calibration scales, with
  per-scale temperature-validity ranges; `src/ui/pressureCalc_ui.py` wraps it in a `QDialog`. The
  pressure error is the quadrature sum of three parts reported separately — peak position,
  zero-pressure peak position (propagated through the temperature correction's slope when one is
  applied), and scale coefficients; `tests/test_zero_peak_error.py` checks every scale's analytic
  zero-peak term against a numerical derivative. Temperature-scale coefficient errors are propagated
  only where a covariance is known (`ruby_kobayashi_2026`'s `debye_param_covariance`) and are counted
  in the scale part.
- `file_io.py` (`DataFileIO`): spectrum, background, fitting-result, and sequential-result file
  I/O, deliberately isolated with **no Qt dependency**. Versioned spectrometer configuration
  persistence is the separate responsibility of `ConfigurationCatalog`.
- `measurement_metadata.py`: builds measurement metadata (a frozen snapshot of hardware state at the
  end of an acquisition cycle) without making live hardware calls, on top of
  `src/hardware/status/instrument_status.py`.

**Config/state files** (generated at runtime, not checked in) all live in one per-user folder,
`src.core.app_paths.user_data_dir()` (`%LOCALAPPDATA%\FluoraPressee\` on Windows), for source runs and
installed builds alike; the env var `FLUORAPRESSEE_DATA_DIR` moves all of it (tests, wizard trials).
Never write into the install folder, and never hard-code a working-directory-relative path — ask
`app_paths` (evaluated on every call). Contents: `spectrometerConfig.json` (grating list, default ROIs,
`flip_x`, hardware `model`), the local UI cache `local_cache.json` (`src/ui/local_cache.py`, read/written
by `_load_local_cache`/`_save_local_cache` in `src/ui/ui_mixins/config_mixin.py` under an inter-process
file lock, since the live GUI and Analysis Mode may run together), `api_clients.json`, user-added
`calibrationStandards/` (loaded after the bundled ones, `app_paths.bundled_resource_path`), `logs/`,
and versioned measurement configurations in `configurations/`: canonical records under
`records/YYYY/MM/` and the query-oriented `catalog.sqlite3` index. Files a source checkout used to keep
at the repo root are migrated once (copied, original renamed `*.migrated`) only when running from source
without `FLUORAPRESSEE_DATA_DIR` (`app_paths.legacy_migration_enabled`). Data written by a newer version
(catalog `schema_version`, `api_clients.json` `version`) is refused untouched
(`src/core/data_versions.py`); bump a format version only for incompatible changes. Exposure, accumulation, sample/material, dark,
fit, and pressure settings deliberately do not belong to these records.

**Optional HTTP API layer** (`src/api/`, `src/ui/ui_mixins/api_mixin.py`): exposes a subset of
`SpectrometerGUI`'s functionality over HTTP so other machines on the same LAN can trigger
measurements. The intended workflow is to finish calibration and basic setup in the GUI first, then
let the API drive acquisition. The GUI's "API Server" panel selects one of three modes
(`ApiMixin.apply_api_mode`, persisted in the local UI cache as `api_mode`):

- `off` — not listening.
- `standby` — listening continuously; the measurement/config controls are locked only while a request
  actually owns the instrument.
- `locked` — listening continuously with the controls locked for the whole run (identical to the
  original "Start API Server" behaviour).

A persisted non-`off` mode restarts listening automatically, but only from the camera-init handlers
(`AcquisitionMixin.on_camera_initialized`/`on_camera_init_failed` call
`ApiMixin.maybe_autostart_api_server` last) — both handlers re-enable the central widget
unconditionally, so listening must not begin before them or the UI lock is broken.

The lock itself is `SequentialMixin._lock_ui`/`_unlock_ui`, which tracks a set of lock "reasons"
(sequential run, API server, an in-flight API request) so any one of them alone can hold it. Both
helpers are idempotent, which is only sound because every path that re-enabled a widget behind the
lock's back has been closed — see `work/work_API_standby.md` 方針4 and
`tests/test_ui_lock_reasons.py` before adding a `setEnabled(True)` anywhere in `src/ui/`.

The per-request lock reason `api_active` is derived from a single choke point rather than applied by
hand: `AcquisitionMixin._try_acquire_gate(owner)` takes it when `owner == "api"`, and
`_release_acquisition_gate()` schedules its release on a ~1 s debounce timer (`_api_unlock_timer`), so
a burst of back-to-back requests holds the lock continuously instead of flickering the controls.
Focus is captured on lock and restored on unlock. **Both gate methods must only ever be called from
the GUI thread** — that invariant is why `_gate_owner` needs no lock of its own.

Switching to `off` means "stop accepting new requests", not "abort what is running": `_api_accepting`
goes false (new requests get 503) and a `QTimer` watches the uvicorn thread until it really exits,
rather than blocking the GUI thread on `join()`.

- `src/api/gui_bridge.py` (`GuiBridge`): marshals calls from the API's worker threads onto the Qt GUI
  thread via a `pyqtSignal`, since almost all of `SpectrometerGUI`'s state lives in QWidgets and Qt
  forbids touching them off-thread. Acquisition uses a two-phase Future-based handoff
  (`ApiMixin._api_start_acquire`/`api_acquire`) rather than blocking the GUI thread on the result, to
  avoid deadlocking the Qt event loop — see the module docstring for why.
- `src/core/api_clients.py`: Qt-independent storage and authorisation for named API clients (one key
  per paired application, optional per-client IP allow-list with CIDR support). Stored under the
  user's application-data directory (`FluoraPressee/api_clients.json`, atomic write, `0600` on POSIX);
  the legacy single-key `fluora_pressee_api_key.json` at the repo root is migrated verbatim on first
  load and then deleted (source runs without `FLUORAPRESSEE_DATA_DIR` only). The list is held as an immutable tuple and replaced wholesale on edit, so API
  worker threads read it without a lock. `src/ui/menu/api_clients_dialog.py` is the management dialog
  (menu "API → Manage Clients").
- `src/api/schemas.py` / `src/api/server.py` (`create_app`): Pydantic request/response models and the
  FastAPI app factory (routes, `X-API-Key` header auth, per-client IP checks, and `expose_docs` which
  defaults to False because FastAPI's own `/docs`+`/openapi.json` are not behind the key dependency).
  `src/ui/ui_mixins/api_mixin.py` (`ApiMixin`)
  implements the actual logic each route calls into (`api_acquire`, `api_fit`, `api_pressure`,
  configuration list/get/resolve/apply, `api_get_status`, and the read-only hardware/config
  endpoints) independent of
  the GUI's own `radio_bg_on`/`chk_flip_x`/fit-panel widgets, so a remote request never depends on or
  mutates what the operator is currently looking at. `GET /hardware/camera` and
  `GET /hardware/spectrometer` use cached metadata by default; `refresh=true` performs an exclusive
  live status query. `GET /config` distinguishes active startup hardware settings from values saved
  for the next restart and redacts secret-like keys.
- `GET /configurations` uses the exact catalog discovery rules used by the GUI. Acquisition requests
  may optionally supply an immutable `configuration_id`; when supplied, configuration movement and
  acquisition share one exclusion-gate ownership, while omission preserves the current instrument
  and axis state. `axis_mode="pixel"` positions the configuration without applying its calibration.
  The inline-coefficient `POST /calibration` route is deprecated.
- Every response carries an opaque `instrument_state_token` (`AcquisitionMixin.instrument_state_token`,
  bumped by `_bump_instrument_state()` from every state change that can alter an acquisition's
  result). A request may send it back as `expected_state_token` to be rejected with 409 if anything
  changed meanwhile. It is compared at exactly one point — right after the gate is taken and before
  anything is changed — which is what lets `configuration_id` and `expected_state_token` be combined.
  The acquire response's state is snapshotted inside the gate (`_api_acquire_snapshot`), both for
  correctness under multiple clients and because it cuts the `gui_bridge.call()` round trips per
  `/acquire` from three to one.
- Background (dark) subtraction over the API defaults to rejecting a mismatched exposure/ROI outright
  (`BackgroundMismatchError` → HTTP 422) rather than silently subtracting an invalid dark frame;
  callers can opt into subtracting anyway (`dark.ignore_mismatch`) or supply their own dark spectrum
  directly (`dark.mode="provided"`). Remote re-acquisition of a fresh dark frame is not implemented —
  the app has no shutter control, so that needs to land in the GUI first.
- A camera that is not running answers acquisition requests with 503 (`CameraNotReadyError`) rather
  than taking the gate, and an acquisition that times out is cleaned up by `_api_abort_acquire`
  (camera stopped first, then the gate released) — without that the GUI would stay locked forever,
  since the lock is derived from the gate.
- See `docs-site/docs/api/` for the full endpoint reference (one page per endpoint/group, published as
  the "API" section of the online manual), `work/work_API.md` for the original implementation
  history/design rationale, and `work/work_API_standby.md` for the Standby-mode design (gate audit,
  UI-lock derivation, named keys, state token).

## Notes on the code

- Comments and many log/print messages are in Japanese; the README is bilingual (`README.md` /
  `README_ja.md`). Match the existing language when editing a given file's comments.
- **Updates**: `src/core/update_check.py` (Qt-free) reads GitHub Releases and picks the newest
  non-draft release newer than `__version__` that carries `FluoRaPressee-Setup-<version>.exe`;
  `src/ui/menu/help_menu.py` (`HelpMenu`, shared by the live GUI and Analysis Mode) checks at most once
  per 24 h in the background and only adds a Help-menu item. The app never downloads or runs the
  installer; the installer itself detects a running FluoRaPressée via the
  `Global\FluoRaPresseeRunning:<install dir>` mutex.
- User-facing manual content (installation, usage, API reference) lives in `docs-site/` (a Docusaurus
  site published to GitHub Pages; manual screenshots live under `docs-site/static/img/manual/`), not
  internal developer docs (those live in `work/`).
  - In the markdown files in `docs-site/`, LaTeX notation ($...$, $$...$$) can be used.

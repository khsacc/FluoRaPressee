"""Where FluoRaPressée keeps user data and finds its bundled files.

See work/work_updater.md 方針3-5. User data lives in one per-user folder whether
the app runs from source or as an installed build, and the environment variable
FLUORAPRESSEE_DATA_DIR moves all of it (tests, wizard trials, trying a local build).
Nothing is ever written to the install folder, which is what lets the installer
replace `_internal` wholesale on every update.

Every function is evaluated on each call - fixing a path at import time would make
the environment variable and test patches ineffective.

Qt-independent.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from src.core.runtime_env import is_frozen, repo_root

ENV_DATA_DIR = "FLUORAPRESSEE_DATA_DIR"

SPECTROMETER_CONFIG_NAME = "spectrometerConfig.json"
LOCAL_CACHE_NAME = "local_cache.json"
LEGACY_API_KEY_NAME = "fluora_pressee_api_key.json"
SHAMROCK_DLL_NAME = "ShamrockCIF.dll"

# Files a source checkout used to keep in the repository root (方針4).
LEGACY_USER_FILES = (SPECTROMETER_CONFIG_NAME, LOCAL_CACHE_NAME)
# spectrometerConfig.json keys holding file-system paths (方針4 パスの補正).
HARDWARE_PATH_KEYS = ("dll_path", "PIcam_dll_path")


def _platform_base_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def data_dir_override() -> str | None:
    value = os.environ.get(ENV_DATA_DIR, "").strip()
    return value or None


def user_data_dir() -> Path:
    override = data_dir_override()
    if override:
        return Path(override).expanduser()
    return _platform_base_dir() / "FluoraPressee"


def spectrometer_config_path() -> Path:
    return user_data_dir() / SPECTROMETER_CONFIG_NAME


def local_cache_path() -> Path:
    return user_data_dir() / LOCAL_CACHE_NAME


def user_calibration_standards_dir() -> Path:
    return user_data_dir() / "calibrationStandards"


def logs_dir() -> Path:
    return user_data_dir() / "logs"


def configurations_dir() -> Path:
    return user_data_dir() / "configurations"


def api_clients_path() -> Path:
    return user_data_dir() / "api_clients.json"


def bundled_resource_path(relative) -> Path:
    """A file shipped with the app: inside the build, or in the source tree."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable))))
    else:
        base = repo_root()
    return base / relative


# ---------------------------------------------------------------------------
# Migration from the repository root (方針4)
# ---------------------------------------------------------------------------

def legacy_migration_enabled() -> bool:
    """The single rule for every automatic migration out of the repository root.

    Only a source checkout has a repository root to migrate from, and an explicit
    FLUORAPRESSEE_DATA_DIR means "keep away from my real data" - migrating then would
    copy the real settings into a scratch folder and rename (or, for the API key,
    delete) the originals.
    """
    return not is_frozen() and data_dir_override() is None


def legacy_api_key_path() -> Path | None:
    """The old single-key file to migrate, or None when migration is off."""
    if not legacy_migration_enabled():
        return None
    return repo_root() / LEGACY_API_KEY_NAME


def normalize_hardware_paths(config: dict, base_dir) -> dict:
    """Make spectrometerConfig.json's paths absolute against the folder it came from.

    Relative paths used to resolve against the working directory, which was the
    folder holding the config file. Moving the file changes that, so (方針4):

    - absolute paths stay as they are;
    - relative paths become absolute against `base_dir`, whether or not the target
      exists (keeping their original meaning);
    - an empty dll_path is filled with `base_dir` only if ShamrockCIF.dll is there
      (the field holds the folder containing the DLL, as the wizard writes it). An
      existing value is never swapped for another DLL.
    """
    result = dict(config)
    base = os.path.abspath(str(base_dir))
    for key in HARDWARE_PATH_KEYS:
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        if not os.path.isabs(value):
            result[key] = os.path.normpath(os.path.join(base, value))
    if not (isinstance(result.get("dll_path"), str) and result["dll_path"].strip()):
        if os.path.isfile(os.path.join(base, SHAMROCK_DLL_NAME)):
            result["dll_path"] = base
    return result


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def write_json_atomic(path, data, *, indent=4, ensure_ascii=False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    _atomic_write_bytes(path, text.encode("utf-8"))


def migrate_legacy_user_files(source_dir, data_dir, log=print) -> dict[str, str]:
    """Move spectrometerConfig.json / local_cache.json out of the repository root.

    Idempotent. For each file: copy to `data_dir` if it is not there yet (correcting
    paths in spectrometerConfig.json), then rename the original to "<name>.migrated"
    so it can be restored by hand but cannot silently drift from the new copy. When
    both exist, the new location wins and the old file is left alone with a warning.

    Returns {file name: "migrated" | "both" | "failed"} for files that were found.
    """
    source_dir = Path(source_dir)
    data_dir = Path(data_dir)
    results: dict[str, str] = {}
    for name in LEGACY_USER_FILES:
        old = source_dir / name
        new = data_dir / name
        if not old.is_file():
            continue
        if new.exists():
            log(
                f"Warning: both {old} and {new} exist. Using {new}; "
                f"{old} is left untouched."
            )
            results[name] = "both"
            continue
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            if name == SPECTROMETER_CONFIG_NAME:
                payload = old.read_bytes()
                try:
                    config = json.loads(payload.decode("utf-8"))
                except Exception as exc:
                    log(f"Warning: {old} could not be parsed ({exc}); copying it unchanged.")
                    _atomic_write_bytes(new, payload)
                else:
                    if isinstance(config, dict):
                        config = normalize_hardware_paths(config, source_dir)
                    write_json_atomic(new, config)
            else:
                temp = new.with_name(f"{new.name}.{os.getpid()}.tmp")
                shutil.copy2(old, temp)
                os.replace(temp, new)
            os.replace(old, old.with_name(name + ".migrated"))
        except Exception as exc:
            log(f"Warning: could not migrate {old} to {new}: {exc}")
            results[name] = "failed"
            continue
        log(f"Moved {name} to {new} (the original was renamed to {name}.migrated).")
        results[name] = "migrated"
    return results


def prepare_user_data(log=print) -> None:
    """Run the start-up migration, or say why it was skipped (方針4)."""
    if legacy_migration_enabled():
        migrate_legacy_user_files(repo_root(), user_data_dir(), log=log)
        return
    if is_frozen():
        return
    leftovers = [
        name for name in (*LEGACY_USER_FILES, LEGACY_API_KEY_NAME)
        if (repo_root() / name).is_file()
    ]
    if leftovers:
        log(
            f"{ENV_DATA_DIR} is set, so files in the repository root "
            f"({', '.join(leftovers)}) were not migrated."
        )

"""Small local UI-state cache shared by the live GUI and Analysis Mode.

Plain JSON read/modify/write against local_cache.json in the user-data folder
(src/core/app_paths.py), with no Qt dependency, so it can be used from any entry
point.

Several processes may write it at once (the live GUI and Analysis Mode, or two
`--debug` live GUIs), so every load and save holds an exclusive lock on
local_cache.json.lock from the read until the atomic replace (work/work_updater.md
方針13). Without the lock, two processes reading the same old content would make the
later save erase the earlier one's change; an atomic replace alone cannot prevent
that. Loads lock too, because Windows refuses os.replace() onto a file another
process has open.

The cache is expendable, so a lock that cannot be had within a few seconds is given
up rather than freezing the GUI: a load then reads without the lock, a save is
skipped with a warning.
"""

import contextlib
import json
import os
import sys
import time

from src.core.app_paths import local_cache_path

LOCK_TIMEOUT_S = 3.0
_LOCK_POLL_S = 0.05


class _LockTimeout(Exception):
    pass


def _try_lock(handle):
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _locked(path, timeout=None):
    timeout = LOCK_TIMEOUT_S if timeout is None else timeout
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise _LockTimeout(str(lock_path))
                time.sleep(_LOCK_POLL_S)
        try:
            yield
        finally:
            try:
                _unlock(handle)
            except OSError:
                pass


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path, data):
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise


def load_local_cache():
    path = local_cache_path()
    try:
        with _locked(path):
            return _read(path)
    except _LockTimeout:
        print("Warning: local cache is locked by another process; reading it unlocked.")
    except OSError:
        pass
    return _read(path)


def save_local_cache(key, value):
    path = local_cache_path()
    try:
        with _locked(path):
            data = _read(path)
            data[key] = value
            _write_atomic(path, data)
    except _LockTimeout:
        print(f"Warning: local cache is locked by another process; {key!r} was not saved.")
    except Exception as e:
        print(f"Failed to save local cache: {e}")

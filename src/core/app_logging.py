"""Standard output for windowed builds: one log file per process (work/work_updater.md 方針9).

A PyInstaller windowed build has `sys.stdout is None`, so the existing
`sys.stdout.reconfigure()` call would crash at start-up and every print() would
vanish. Here stdout/stderr are pointed at a log file of this process's own:

    logs/app-<kind>-<YYYYMMDD-HHMMSS>-<PID>.log

One shared app.log rotated at start-up was rejected: the live GUI and Analysis Mode
may run together, and Windows refuses to rename a file another process has open.

Neither creating nor pruning logs may ever stop the application from starting.

Imports nothing from Qt, so main.py can call it before anything heavy is loaded.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

LOG_PREFIX = "app-"
MAX_AGE_DAYS = 30
MAX_FILES = 100

_current_log_path: Path | None = None


class _DiscardingWriter:
    """Last-resort stream: accepts writes and drops them."""

    encoding = "utf-8"
    errors = "replace"

    def write(self, text):
        return len(text)

    def writelines(self, lines):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False

    def writable(self):
        return True

    def reconfigure(self, **_kwargs):
        pass


def current_log_path() -> Path | None:
    """The log file this process writes to, or None (console / no log)."""
    return _current_log_path


def _default_logs_dir() -> Path:
    from src.core.app_paths import logs_dir

    return logs_dir()


def _open_log(kind, directory, now, pid):
    try:
        directory = Path(directory) if directory is not None else _default_logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        path = directory / f"{LOG_PREFIX}{kind}-{stamp}-{pid or os.getpid()}.log"
        # Line-buffered so a crash still leaves everything up to the last line.
        stream = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
        return stream, path
    except Exception:
        pass
    try:
        return open(os.devnull, "w", encoding="utf-8", errors="replace"), None
    except Exception:
        return _DiscardingWriter(), None


def cleanup_old_logs(directory, keep=None, now_ts=None,
                     max_age_days=MAX_AGE_DAYS, max_files=MAX_FILES) -> None:
    """Delete app-*.log older than `max_age_days`, and all but the newest `max_files`.

    Every failure is ignored file by file: on Windows a log another process still
    has open cannot be deleted, and simply waits for a later start-up.
    """
    try:
        directory = Path(directory)
        now_ts = time.time() if now_ts is None else now_ts
        entries = []
        for path in directory.glob(f"{LOG_PREFIX}*.log"):
            try:
                entries.append((path.stat().st_mtime, path))
            except OSError:
                continue
        entries.sort(key=lambda item: item[0], reverse=True)
        keep = Path(keep) if keep is not None else None
        for index, (mtime, path) in enumerate(entries):
            if keep is not None and path == keep:
                continue
            too_old = now_ts - mtime > max_age_days * 86400
            if too_old or index >= max_files:
                try:
                    path.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _install_excepthook():
    def hook(exc_type, exc, tb):
        try:
            print(f"Uncaught exception at {datetime.now().isoformat(timespec='seconds')}:",
                  file=sys.stderr)
            traceback.print_exception(exc_type, exc, tb, file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            pass

    sys.excepthook = hook


def setup_stdio(kind: str, *, logs_dir=None, now=None, pid=None) -> Path | None:
    """Prepare stdout/stderr for `kind` ("live" or "analysis"). Returns the log path.

    With a console (source runs, the console-mode driver tool) nothing changes
    except `errors="replace"`, as before. Without one, both streams go to this
    process's log file and uncaught exceptions are written there too.
    """
    global _current_log_path

    if sys.stdout is not None and sys.stderr is not None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass
        return None

    stream, path = _open_log(kind, logs_dir, now, pid)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    _current_log_path = path
    _install_excepthook()
    if path is not None:
        cleanup_old_logs(path.parent, keep=path)
    return path

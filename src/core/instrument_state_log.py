"""Persistent, bounded diagnostics for changes to the API instrument-state token."""

import logging
from logging.handlers import RotatingFileHandler

from src.core.api_clients import default_api_clients_path


def make_instrument_state_logger():
    """Use the per-user application-data directory, independent of the working directory.

    A logging failure must never prevent the spectrometer from starting or changing
    settings. The log records state reasons and tokens, never API credentials.
    """
    path = default_api_clients_path().parent / "logs" / "instrument_state.log"
    logger = logging.getLogger("fluorapressee.instrument_state")
    if logger.handlers:
        return logger
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3,
                                      encoding="utf-8")
    except OSError as exc:
        print(f"Warning: instrument-state log unavailable at {path}: {exc}")
        return None
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

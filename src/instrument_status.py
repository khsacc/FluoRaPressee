"""Shared data helpers for read-only instrument status snapshots."""
from __future__ import annotations

from datetime import datetime
from enum import Enum


SCHEMA_VERSION = 1


def json_value(value):
    """Convert common SDK return values into JSON-serializable values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.name
    if hasattr(value, "_asdict"):
        return {str(k): json_value(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [json_value(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return str(value)


def item(key, label, value=None, unit=None, state="ok", error=None):
    return {
        "key": key,
        "label": label,
        "value": json_value(value),
        "unit": unit,
        "state": state,
        "error": str(error) if error else None,
    }


def safe_item(key, label, getter, unit=None, transform=None):
    try:
        value = getter()
        if transform is not None:
            value = transform(value)
        return item(key, label, value, unit)
    except Exception as exc:
        state = "unsupported" if "notsupported" in type(exc).__name__.lower() else "error"
        return item(key, label, state=state, error=exc)


def device_snapshot(backend, sections, available=True, error=None):
    return {
        "backend": backend,
        "available": bool(available),
        "error": str(error) if error else None,
        "sections": sections,
    }


def unavailable_device(backend, message):
    return device_snapshot(backend, {}, available=False, error=message)


def legacy_camera_snapshot(snapshot, backend="camera"):
    """Normalize the older Princeton {section: [(label, value)]} format."""
    if isinstance(snapshot, dict) and "sections" in snapshot:
        return snapshot
    sections = {}
    for section, rows in (snapshot or {}).items():
        converted = []
        for index, row in enumerate(rows):
            label, value = row
            converted.append(item(f"legacy_{index}", label, value))
        sections[section] = converted
    return device_snapshot(backend, sections)


def make_report(camera, spectrograph):
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "camera": camera,
        "spectrograph": spectrograph,
    }


def display_value(entry):
    if entry.get("state") == "unsupported":
        return "N/A (not supported)"
    if entry.get("state") == "error":
        return "Unavailable"
    value = entry.get("value")
    if isinstance(value, bool):
        text = "Yes" if value else "No"
    elif isinstance(value, float):
        text = f"{value:.6g}"
    elif isinstance(value, (dict, list)):
        text = _compact_value(value)
    elif value is None:
        text = "N/A"
    else:
        text = str(value)
    return f"{text} {entry['unit']}" if entry.get("unit") else text


def _compact_value(value):
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_compact_value(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_compact_value(v) for v in value)
    return str(value)

"""Small local UI-state cache shared by the live GUI and Analysis Mode.

Plain JSON read/modify/write against local_cache.json in the working directory,
with no Qt dependency, so it can be used from any entry point.
"""

import json

_CACHE_PATH = "local_cache.json"


def load_local_cache():
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_local_cache(key, value):
    try:
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        data[key] = value
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to save local cache: {e}")

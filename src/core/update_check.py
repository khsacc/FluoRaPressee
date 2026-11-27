"""Finding a newer release on GitHub (work/work_updater.md 方針7, Step 6).

Notification only: this module never downloads or runs anything. It reads the
Releases list and picks the newest release that is newer than the running version
and carries the installer.

Qt-independent; the network call is injectable so tests never go online.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    from packaging.version import InvalidVersion, Version
except ImportError:  # a checkout updated with git pull but not pip install yet
    InvalidVersion = ValueError
    Version = None

RELEASES_URL = "https://api.github.com/repos/khsacc/FluoraPressee/releases?per_page=20"
# Development aid, not for users: a local JSON file or another URL to read instead.
FEED_ENV = "FLUORAPRESSEE_UPDATE_FEED"
# A generic client name; nothing about the user or the machine is sent.
USER_AGENT = "FluoRaPressee-Updater"
TIMEOUT_S = 10

INSTALLER_NAME_RE = re.compile(r"^FluoRaPressee-Setup-(?P<version>.+)\.exe$")


class UpdateCheckError(Exception):
    """The release list could not be fetched or understood."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    installer_name: str
    installer_url: str
    release_url: str
    notes: str
    prerelease: bool
    published_at: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data) -> "UpdateInfo | None":
        try:
            return cls(**{name: data[name] for name in cls.__dataclass_fields__
                          if name in data})
        except Exception:
            return None


def parse_version(text) -> "Version | None":
    if Version is None or not isinstance(text, str):
        return None
    text = text.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    try:
        return Version(text)
    except InvalidVersion:
        return None


def default_include_prerelease(current_version: str) -> bool:
    """Beta users want the next beta; release users only want releases."""
    current = parse_version(current_version)
    return bool(current is not None and current.is_prerelease)


def fetch_releases(url: str | None = None, timeout: float = TIMEOUT_S,
                   opener=urllib.request.urlopen) -> list:
    """GET the release list. /releases/latest is avoided: it skips pre-releases.

    urllib honours the Windows proxy settings and HTTPS_PROXY by itself.
    """
    source = url or os.environ.get(FEED_ENV, "").strip() or RELEASES_URL
    try:
        if "://" not in source and Path(source).is_file():
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        else:
            request = urllib.request.Request(source, headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with opener(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateCheckError(
                "GitHub refused the request (rate limit). Please try again later."
            ) from exc
        raise UpdateCheckError(f"GitHub returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"Could not reach GitHub: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateCheckError(f"Could not read the release list: {exc}") from exc
    if not isinstance(data, list):
        raise UpdateCheckError("The release list has an unexpected format.")
    return data


def _installer_asset(release: dict, version) -> dict | None:
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        match = INSTALLER_NAME_RE.match(str(asset.get("name") or ""))
        if not match or not asset.get("browser_download_url"):
            continue
        if parse_version(match.group("version")) == version:
            return asset
    return None


def select_update(releases, current_version: str,
                  include_prerelease: bool) -> UpdateInfo | None:
    """The newest usable release newer than `current_version`, or None.

    Skips drafts, pre-releases (unless included), tags that are not PEP 440, and
    releases without FluoRaPressee-Setup-<version>.exe attached.
    """
    current = parse_version(current_version)
    if current is None:
        return None
    best = None
    best_version = None
    for release in releases or []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        version = parse_version(release.get("tag_name"))
        if version is None:
            continue
        if (release.get("prerelease") or version.is_prerelease) and not include_prerelease:
            continue
        if version <= current:
            continue
        asset = _installer_asset(release, version)
        if asset is None:
            continue
        if best_version is None or version > best_version:
            best_version = version
            best = UpdateInfo(
                version=str(version),
                tag=str(release.get("tag_name")),
                installer_name=str(asset.get("name")),
                installer_url=str(asset.get("browser_download_url")),
                release_url=str(release.get("html_url") or ""),
                notes=str(release.get("body") or ""),
                prerelease=bool(release.get("prerelease") or version.is_prerelease),
                published_at=release.get("published_at"),
            )
    return best


def check_for_update(current_version: str, include_prerelease: bool | None = None,
                     fetch=fetch_releases) -> UpdateInfo | None:
    if Version is None:
        raise UpdateCheckError(
            "The 'packaging' module is missing. Run: pip install -r requirements.txt"
        )
    if include_prerelease is None:
        include_prerelease = default_include_prerelease(current_version)
    return select_update(fetch(), current_version, include_prerelease)


def is_newer(info: UpdateInfo | None, current_version: str) -> bool:
    """Whether a remembered result still describes an update for this version."""
    if info is None:
        return False
    candidate = parse_version(info.version)
    current = parse_version(current_version)
    return candidate is not None and current is not None and candidate > current

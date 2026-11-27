"""Choosing the release to offer (work/work_updater.md Step 6). Never goes online."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from src.core.update_check import (
    FEED_ENV,
    UpdateCheckError,
    UpdateInfo,
    check_for_update,
    default_include_prerelease,
    fetch_releases,
    is_newer,
    select_update,
)

BASE = "https://github.com/khsacc/FluoraPressee/releases"


def release(tag, *, draft=False, prerelease=False, asset=True, asset_version=None, body=""):
    version = asset_version or tag.lstrip("v")
    assets = []
    if asset:
        assets.append({
            "name": f"FluoRaPressee-Setup-{version}.exe",
            "browser_download_url": f"{BASE}/download/{tag}/FluoRaPressee-Setup-{version}.exe",
        })
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "html_url": f"{BASE}/tag/{tag}",
        "body": body,
        "assets": assets,
        "published_at": "2026-11-21T00:00:00Z",
    }


RELEASES = [
    release("v0.3.0", draft=True),                 # drafts are invisible to users
    release("v0.2.1", asset=False),                # no installer attached
    release("v0.2.0b2", prerelease=True),
    release("not-a-version"),
    release("v0.1.9"),                             # older than current
    release("v0.2.0", body="## Changes"),
    release("v0.1.0b1", prerelease=True),          # the running version itself
]


class SelectUpdateTests(unittest.TestCase):
    def test_newest_release_with_an_installer_wins(self):
        info = select_update(RELEASES, "0.1.0b1", include_prerelease=False)
        self.assertEqual(info.version, "0.2.0")
        self.assertEqual(info.notes, "## Changes")

    def test_prereleases_are_considered_only_when_asked(self):
        releases = [release("v0.2.0b2", prerelease=True), release("v0.1.5")]
        self.assertEqual(select_update(releases, "0.1.0b1", True).version, "0.2.0b2")
        self.assertEqual(select_update(releases, "0.1.0b1", False).version, "0.1.5")

    def test_same_or_older_version_is_not_offered(self):
        releases = [release("v0.1.0b1", prerelease=True), release("v0.0.9")]
        self.assertIsNone(select_update(releases, "0.1.0b1", True))

    def test_development_build_is_not_offered_its_own_version(self):
        self.assertIsNone(
            select_update([release("v0.1.0b1", prerelease=True)], "0.1.0b1+dev.g1234abcd", True)
        )

    def test_installer_must_match_the_tag(self):
        releases = [release("v0.2.0", asset_version="0.1.9")]
        self.assertIsNone(select_update(releases, "0.1.0", False))

    def test_urls_are_taken_from_the_chosen_release(self):
        info = select_update(RELEASES, "0.1.0b1", include_prerelease=False)
        self.assertEqual(info.installer_name, "FluoRaPressee-Setup-0.2.0.exe")
        self.assertEqual(info.installer_url,
                         f"{BASE}/download/v0.2.0/FluoRaPressee-Setup-0.2.0.exe")
        self.assertEqual(info.release_url, f"{BASE}/tag/v0.2.0")

    def test_default_follows_the_running_version(self):
        self.assertTrue(default_include_prerelease("0.1.0b1"))
        self.assertFalse(default_include_prerelease("0.1.0"))

    def test_check_uses_the_default_prerelease_rule(self):
        releases = [release("v0.1.0b2", prerelease=True)]
        self.assertEqual(check_for_update("0.1.0b1", fetch=lambda: releases).version, "0.1.0b2")
        self.assertIsNone(check_for_update("0.1.0", fetch=lambda: releases))


class RememberedResultTests(unittest.TestCase):
    def test_round_trip_and_staleness(self):
        info = select_update(RELEASES, "0.1.0b1", include_prerelease=False)
        restored = UpdateInfo.from_dict(json.loads(json.dumps(info.to_dict())))
        self.assertEqual(restored, info)
        self.assertTrue(is_newer(restored, "0.1.0b1"))
        self.assertFalse(is_newer(restored, "0.2.0"), "already updated")
        self.assertIsNone(UpdateInfo.from_dict({"version": "1.0"}))


class FetchTests(unittest.TestCase):
    def test_local_feed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "releases.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(RELEASES, handle)
            with patch.dict(os.environ, {FEED_ENV: path}):
                self.assertEqual(len(fetch_releases()), len(RELEASES))

    def test_request_identifies_only_the_client(self):
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(request, timeout):
            seen["headers"] = dict(request.header_items())
            seen["timeout"] = timeout
            return Response(b"[]")

        with patch.dict(os.environ, {FEED_ENV: ""}):
            self.assertEqual(fetch_releases(opener=opener), [])
        self.assertEqual(seen["headers"].get("User-agent"), "FluoRaPressee-Updater")
        self.assertEqual(seen["timeout"], 10)

    def test_network_errors_become_update_check_errors(self):
        def offline(_request, timeout):
            raise urllib.error.URLError("offline")

        with patch.dict(os.environ, {FEED_ENV: ""}), self.assertRaises(UpdateCheckError):
            fetch_releases(opener=offline)

    def test_unexpected_payload_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "releases.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"message": "Not Found"}, handle)
            with self.assertRaises(UpdateCheckError):
                fetch_releases(url=path)


if __name__ == "__main__":
    unittest.main()

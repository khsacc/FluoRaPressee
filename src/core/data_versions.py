"""Refusing data formats written by a newer FluoRaPressée (work/work_updater.md 方針14).

A released build's reading code can never be fixed afterwards, and downgrades are
allowed, so an old build will meet files a newer one wrote. Editing such a file as if
it were the old format would leave it damaged even after going back to the new
version. The rule is therefore: read the version first, and if it is newer than this
build understands, change nothing and say why.
"""

from __future__ import annotations


class UnsupportedDataVersionError(Exception):
    """A file's format version is newer than (or not one) this build supports."""

    def __init__(self, what: str, found, supported: int):
        self.what = what
        self.found = found
        self.supported = supported
        super().__init__(
            f"{what} has format version {found!r}, but this version of FluoRaPressée "
            f"supports up to {supported}. It was probably written by a newer "
            "FluoRaPressée; please use that version. The file has not been changed."
        )


def check_supported_version(found, supported: int, what: str) -> int:
    """Return `found` if this build can use it, otherwise raise.

    A value that is not an integer is treated the same as an unknown newer version:
    rebuilding the file from scratch could destroy data a newer build put there.
    """
    if isinstance(found, bool) or not isinstance(found, int):
        raise UnsupportedDataVersionError(what, found, supported)
    if found > supported:
        raise UnsupportedDataVersionError(what, found, supported)
    return found

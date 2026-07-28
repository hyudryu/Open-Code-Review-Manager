"""Semver parsing and comparison for OpenCodeReview version checking.

Supports basic semver: ``MAJOR.MINOR.PATCH`` with optional prerelease
suffixes (e.g. ``1.2.3-beta.1``).  Only stable releases are considered
"newer" than prereleases at the same base version.
"""

from __future__ import annotations

import re

__all__ = ["parse_version", "is_newer", "semver_key"]

#: Regex that captures the three numeric components and an optional
#: prerelease suffix.  Inspired by semver.org but deliberately loose
#: enough to match what ``ocr version`` actually emits.
_PATTERN = re.compile(
    r"^"
    r"(?P<major>\d+)"
    r"\.(?P<minor>\d+)"
    r"\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"$"
)


def parse_version(version: str) -> dict[str, int | str | None] | None:
    """Return a normalised version dict or *None* if the string is invalid.

    Returns ``{"major": ..., "minor": ..., "patch": ..., "prerelease": ...}``.
    """

    match = _PATTERN.match(version.strip())
    if not match:
        return None
    return {
        "major": int(match.group("major")),
        "minor": int(match.group("minor")),
        "patch": int(match.group("patch")),
        "prerelease": match.group("prerelease"),
    }


def semver_key(version: str) -> tuple[int, int, int, int, str | None]:
    """Return a sortable key suitable for ``<`` / ``>`` comparisons.

    Stable releases sort *after* prereleases of the same base version
    (e.g. ``1.2.3`` > ``1.2.3-beta.1``).
    """

    parsed = parse_version(version)
    if parsed is None:
        return (0, 0, 0, 1, version)  # bogus version sorts low

    major, minor, patch = parsed["major"], parsed["minor"], parsed["patch"]
    pre = parsed["prerelease"]
    # prerelease = 0 (sorts before stable), stable = 1
    pre_flag = 0 if pre else 1
    return (major, minor, patch, pre_flag, pre)


def is_newer(current: str, latest: str) -> bool:
    """Return ``True`` when *latest* is strictly greater than *current*.

    Both strings must be parseable semver; otherwise returns ``False``.
    """

    cur_key = semver_key(current)
    lat_key = semver_key(latest)
    # Only compare when both are parseable
    if cur_key == (0, 0, 0, 1, current) or lat_key == (0, 0, 0, 1, latest):
        return False
    return lat_key > cur_key

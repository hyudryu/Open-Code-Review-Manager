"""Filesystem directory browser for the server-backed folder picker.

The web client cannot read absolute filesystem paths from a browser file
picker, so this service lists real directories on the backend host. The
picker navigates up/down and pastes the chosen absolute path into the form.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.schemas.system import DirBrowseOut, DirEntryOut
from app.services.errors import ValidationFailedError

# Keep the response small and fast even on huge directories.
MAX_ENTRIES = 500


class SystemBrowseService:
    """List the subdirectories of a host path for the folder picker."""

    async def browse(self, path: str | None) -> DirBrowseOut:
        target = self._resolve_target(path)
        parent = self._parent_of(target)

        entries: list[DirEntryOut] = []
        truncated = False
        try:
            names = sorted(
                (e.name for e in os.scandir(target) if e.is_dir()),
                key=str.lower,
            )
        except PermissionError as exc:
            raise ValidationFailedError(
                "This directory could not be read.",
                detail=str(exc),
                next_action="Pick a directory you have permission to read.",
            ) from exc

        for name in names:
            # Reduce noise: hide dot-directories such as .git, .vscode.
            if name.startswith("."):
                continue
            if len(entries) >= MAX_ENTRIES:
                truncated = True
                break
            entries.append(DirEntryOut(name=name, path=str(target / name)))

        return DirBrowseOut(
            path=str(target),
            parent=parent,
            entries=entries,
            truncated=truncated,
        )

    def _resolve_target(self, path: str | None) -> Path:
        """Resolve and validate the requested directory."""

        raw = (path or "").strip()
        if not raw:
            target = Path.home()
        else:
            target = Path(raw).expanduser()
        try:
            target = target.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValidationFailedError(
                "That directory does not exist.",
                detail=str(Path(raw) if raw else target),
                next_action="Navigate to an existing directory.",
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise ValidationFailedError(
                "That path could not be resolved.",
                detail=str(exc),
                next_action="Provide a valid absolute directory path.",
            ) from exc

        if not target.is_dir():
            raise ValidationFailedError(
                "That path is not a directory.",
                detail=str(target),
                next_action="Pick a directory, not a file.",
            )
        return target

    def _parent_of(self, target: Path) -> str | None:
        """Return the parent directory string, or None at a filesystem root."""

        parent = target.parent
        # On Windows, ``C:\\`` has parent ``C:\\``; on POSIX ``/`` has parent ``/``.
        # ``samefile`` also short-circuits symlink cycles where parent == child.
        try:
            if parent == target or parent.samefile(target):
                return None
        except OSError:
            return None
        return str(parent)

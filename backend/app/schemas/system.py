"""Directory-browsing schemas for the server-backed folder picker.

A web browser cannot expose the absolute filesystem path of a folder chosen
via ``<input type="file" webkitdirectory>`` (the value the picker needs). The
local backend already has filesystem access, so the picker browses the
server's filesystem instead.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DirEntryOut(BaseModel):
    """A single subdirectory under the browsed path."""

    name: str
    path: str


class DirBrowseOut(BaseModel):
    """Result of listing a directory for the folder picker."""

    path: str
    parent: str | None = Field(
        default=None,
        description="Parent directory, or null at a filesystem/drive root.",
    )
    entries: list[DirEntryOut]
    truncated: bool = Field(
        default=False,
        description="True if the directory had more entries than the cap.",
    )

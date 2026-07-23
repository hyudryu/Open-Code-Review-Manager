"""Folder / project / branch schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class FolderCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    absolute_path: str = Field(min_length=1)
    scan_depth: int = Field(default=2, ge=0, le=6)
    auto_discover: bool = True


class FolderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    scan_depth: int | None = Field(default=None, ge=0, le=6)
    auto_discover: bool | None = None


class FolderOut(ORMModel):
    id: str
    display_name: str
    absolute_path: str
    scan_depth: int
    auto_discover: bool
    last_scanned_at: datetime | None
    created_at: datetime


class ScannedRepoOut(BaseModel):
    path: str
    name: str
    has_git_file: bool
    already_registered: bool


class FolderScanOut(BaseModel):
    folder_id: str
    root: str
    repos: list[ScannedRepoOut]
    errors: list[str]


class RegisterScannedRequest(BaseModel):
    paths: list[str] = Field(min_length=1)


class ProjectCreate(BaseModel):
    absolute_path: str = Field(min_length=1)
    folder_id: str | None = None
    display_name: str | None = None


class ProjectUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    default_branch: str | None = None
    remote_name: str | None = None
    is_available: bool | None = None


class ProjectOut(ORMModel):
    id: str
    folder_id: str | None
    display_name: str
    absolute_path: str
    default_branch: str | None
    remote_name: str | None
    remote_url: str | None
    current_branch: str | None
    is_dirty: bool
    is_available: bool
    last_branch_refresh_at: datetime | None
    created_at: datetime


class BranchOut(ORMModel):
    id: str
    name: str
    full_ref: str
    kind: str
    remote_name: str | None
    commit_sha: str | None
    commit_subject: str | None
    commit_timestamp: datetime | None
    is_default: bool
    is_current: bool


class RefreshBranchesOut(BaseModel):
    branches: list[BranchOut]
    fetch_error: str | None = None

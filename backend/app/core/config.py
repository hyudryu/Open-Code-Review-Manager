"""Application settings for the OCR Control Center backend.

All settings are overridable through environment variables prefixed with
``OCR_CC_`` or through a ``.env`` file in the backend directory. Paths are
stored as :class:`pathlib.Path` and expanded cross-platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8787


def _default_data_dir() -> Path:
    return Path.home() / ".ocr-control-center"


def _split_roots(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return raw
    # Allow both os.pathsep (';' on Windows, ':' elsewhere) and newlines.
    parts: list[str] = []
    for chunk in raw.replace("\n", os.pathsep).split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


class Settings(BaseSettings):
    """Runtime configuration. Construct once and pass down explicitly."""

    model_config = SettingsConfigDict(
        env_prefix="OCR_CC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ocr-control-center"
    app_version: str = "0.1.0"

    # --- paths -------------------------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir)
    allowed_roots: list[Path] = Field(default_factory=list)
    path_restrictions_enabled: bool = False

    # --- network -----------------------------------------------------------
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT

    # --- executables -------------------------------------------------------
    ocr_executable: Path | None = None
    git_executable: Path | None = None

    # --- queue limits ------------------------------------------------------
    global_concurrency: int = 1
    per_project_concurrency: int = 1
    default_provider_concurrency: int = 2
    max_queued_jobs: int = 200
    cancel_grace_seconds: float = 10.0
    session_poll_seconds: float = 1.0

    # --- webhooks -----------------------------------------------------------
    webhook_poll_seconds: float = 2.0
    webhook_timeout_seconds: float = 15.0
    webhook_max_response_bytes: int = 64_000
    webhook_require_https: bool = True
    webhook_allow_private_networks: bool = False
    webhook_replay_window_seconds: int = 300

    # --- retention ---------------------------------------------------------
    artifact_retention_days: int = 30
    keep_worktrees: bool = False

    # --- subprocess timeouts ----------------------------------------------
    git_timeout_seconds: float = 60.0
    git_fetch_timeout_seconds: float = 300.0
    ocr_probe_timeout_seconds: float = 15.0
    ocr_process_timeout_seconds: float = 86400.0

    # --- database ----------------------------------------------------------
    database_url: str | None = None

    # --- logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 3

    # --- security ----------------------------------------------------------
    csrf_token: str | None = None  # generated at startup when unset
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            f"http://{_DEFAULT_HOST}:{_DEFAULT_PORT}",
            f"http://localhost:{_DEFAULT_PORT}",
        ]
    )

    @field_validator("allowed_roots", mode="before")
    @classmethod
    def _parse_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return _split_roots(value)
        return value

    @field_validator("data_dir", "ocr_executable", "git_executable", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    # --- derived paths -----------------------------------------------------

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser()

    @property
    def database_path(self) -> Path:
        return self.resolved_data_dir / "ocrcc.db"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        # sqlite+aiosqlite URL; forward slashes work on all platforms.
        return "sqlite+aiosqlite:///" + self.database_path.as_posix()

    @property
    def jobs_dir(self) -> Path:
        return self.resolved_data_dir / "jobs"

    @property
    def worktrees_dir(self) -> Path:
        return self.resolved_data_dir / "worktrees"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "backend.log"

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def job_home(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "home"

    def worktree_path(self, project_id: str, job_id: str) -> Path:
        return self.worktrees_dir / project_id / job_id

    def ensure_directories(self) -> None:
        for path in (self.resolved_data_dir, self.jobs_dir, self.worktrees_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def is_windows(self) -> bool:
        return sys.platform.startswith("win")


_current: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton (tests override via ``set_settings``)."""

    global _current
    if _current is None:
        _current = Settings()
        _current.ensure_directories()
    return _current


def set_settings(settings: Settings) -> None:
    """Replace the cached settings instance (used by tests)."""

    global _current
    settings.ensure_directories()
    _current = settings

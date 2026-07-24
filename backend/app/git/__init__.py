"""Git integration (all git access goes through GitService)."""

from app.git.service import (
    DEFAULT_EXCLUDED_DIR_NAMES,
    BranchEntry,
    GitError,
    GitNotFoundError,
    GitService,
    GitTimeoutError,
    RefNotFoundError,
    RepoInfo,
    RepoValidationError,
    ScanResult,
    ScannedRepo,
    WorktreeEntry,
)

__all__ = [
    "DEFAULT_EXCLUDED_DIR_NAMES",
    "BranchEntry",
    "GitError",
    "GitNotFoundError",
    "GitService",
    "GitTimeoutError",
    "RefNotFoundError",
    "RepoInfo",
    "RepoValidationError",
    "ScanResult",
    "ScannedRepo",
    "WorktreeEntry",
]

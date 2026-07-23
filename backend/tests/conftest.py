"""Shared fixtures: temp settings, git repo factory, in-memory secrets."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

from app.core.config import Settings, set_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.secrets import InMemorySecretStore, set_secret_store  # noqa: E402
from app.git.service import GitService  # noqa: E402
from app.ocr.adapter import OCRAdapter  # noqa: E402

configure_logging("WARNING")


@pytest.fixture()
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Keep git from discovering any repository ABOVE the test temp dir
    # (developer machines may have e.g. a dotfiles repo at the user home,
    # which would otherwise make every temp dir look like a work tree).
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    s = Settings(
        data_dir=tmp_path / "data",
        allowed_roots=[tmp_path],
        path_restrictions_enabled=True,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
    )
    s.ensure_directories()
    set_settings(s)
    set_secret_store(InMemorySecretStore())
    return s


@pytest.fixture()
def git_service(settings: Settings) -> GitService:
    return GitService(settings)


@pytest.fixture()
def adapter(settings: Settings) -> OCRAdapter:
    return OCRAdapter(settings)


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def make_repo(tmp_path: Path):
    """Factory creating initialized git repos with one commit on ``main``."""

    def _make(name: str = "repo", *, branch: str = "main") -> Path:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-b", branch)
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "hello.py").write_text("print('hello')\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "initial commit")
        return repo

    return _make


@pytest.fixture()
def repo(make_repo) -> Path:
    return make_repo("repo")

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

FAKE_OCR_SCRIPT = r'''
"""Fake ocr binary for tests: argv-driven, no network, no shell."""
import json
import os
import sys
import time
import uuid

REVIEW_HELP = """usage: ocr review [options]
  --repo PATH
  --from REF  --to REF  --commit SHA
  --format FORMAT (json)
  --audience AUDIENCE (agent)
  --resume SESSION
  --background TEXT
  --background-file PATH
  --exclude LIST
  --preview
  --model MODEL
  --rule PATH
  --tools PATH
  --concurrency N
  --timeout MINUTES
  --max-tools N
  --max-git-procs N
"""

ROOT_HELP = """usage: ocr <command>
  review   run a review
  llm      llm utilities (llm test, llm providers)
  scan     scan
  rules    rules check
  viewer   viewer
  config   config set
"""


def main(argv):
    if not argv or argv[0] == "--help":
        print(ROOT_HELP)
        return 0
    if argv[0] == "version":
        print("ocr version 9.9.9-fake")
        return 0
    if argv[0] == "review" and "--help" in argv:
        print(REVIEW_HELP)
        return 0
    if argv[0] == "llm" and len(argv) > 1 and argv[1] == "test":
        if os.environ.get("FAKE_OCR_LLM_FAIL"):
            print("connection refused", file=sys.stderr)
            return 1
        print("llm ok: " + os.environ.get("OCR_LLM_MODEL", "none"))
        return 0
    if argv[0] in {"review", "scan"} and "--preview" in argv:
        print(json.dumps({
            "files": [
                {"path": "hello.py", "status": "modified", "insertions": 3,
                 "deletions": 1, "will_review": True},
                {"path": "big.bin", "status": "added", "insertions": 0,
                 "deletions": 0, "will_review": False, "exclude_reason": "binary"},
            ],
            "total_files": 2, "reviewable_count": 1, "excluded_count": 1,
            "total_insertions": 3, "total_deletions": 1,
        }))
        return 0
    if argv[0] in {"review", "scan"}:
        return run_review(argv)
    print("unknown command", file=sys.stderr)
    return 2


def run_review(argv):
    home = os.environ.get("HOME", ".")
    session_id = "sess-" + uuid.uuid4().hex[:12]
    sessions = os.path.join(home, ".opencodereview", "sessions")
    os.makedirs(sessions, exist_ok=True)
    session_file = os.path.join(sessions, session_id + ".jsonl")

    def emit(record):
        record.setdefault("sessionId", session_id)
        with open(session_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    if os.environ.get("FAKE_OCR_NO_SESSION") != "1":
        emit({"type": "session_start"})
        emit({"type": "file_started", "filePath": "hello.py"})
        emit({
            "type": "llm_response",
            "filePath": "hello.py",
            "taskType": "main_task",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
        emit({"type": "file_completed", "filePath": "hello.py", "comments": 1})

    if os.environ.get("FAKE_OCR_EARLY_LOG"):
        print("review started")

    sleep = float(os.environ.get("FAKE_OCR_SLEEP", "0"))
    if sleep:
        time.sleep(sleep)

    if os.environ.get("FAKE_OCR_FAIL"):
        print("simulated OCR failure", file=sys.stderr)
        return 3

    result = {
        "status": "completed_with_warnings" if os.environ.get("FAKE_OCR_WARNINGS") else "completed",
        "session_id": session_id,
        "comments": [
            {
                "path": "hello.py",
                "content": "Consider adding a docstring.",
                "start_line": 1,
                "end_line": 1,
                "existing_code": "print('hello')",
                "suggestion_code": "def main():\n    print('hello')",
                "thinking": "secret chain-of-thought",
            }
        ],
        "warnings": ([{"file": "hello.py", "message": "file skipped", "type": "skip"}]
                     if os.environ.get("FAKE_OCR_WARNINGS") else []),
        "summary": {
            "files_reviewed": 1, "comments": 1, "input_tokens": 100,
            "output_tokens": 50, "total_tokens": 150, "elapsed": "0.1s",
        },
    }
    if os.environ.get("FAKE_OCR_EMPTY_FINDINGS"):
        result["comments"] = []
        result["summary"]["comments"] = 0
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


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
        session_poll_seconds=0.05,
        webhook_poll_seconds=0.05,
        cancel_grace_seconds=0.5,
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


# ---------------------------------------------------------------------------
# Stage 2 fixtures: database, fake OCR binary, runtime wiring
# ---------------------------------------------------------------------------


@pytest.fixture()
async def db(settings: Settings):
    """Migrated database + engine; torn down after the test."""

    from app.db.migrate import run_migrations_async
    from app.db.session import dispose_engine, init_engine

    url = settings.resolved_database_url
    await run_migrations_async(url)
    init_engine(url)
    yield url
    await dispose_engine()


@pytest.fixture()
def fake_ocr(settings: Settings) -> Path:
    """Register the fake ocr script as the custom OCR executable."""

    script = settings.resolved_data_dir / "fake_ocr.py"
    script.write_text(FAKE_OCR_SCRIPT, encoding="utf-8")
    settings.ocr_executable = script
    return script


@pytest.fixture()
def runtime(settings: Settings, db):
    """Fresh service singletons + event bus bound to the test settings."""

    from app.queue.bus import EventBus, set_event_bus
    from app.services.deps import reset_service_singletons

    reset_service_singletons()
    bus = EventBus()
    set_event_bus(bus)
    yield bus
    reset_service_singletons()


@pytest.fixture()
def make_worker(settings: Settings, runtime):
    """Factory for a QueueWorker wired like production (webhooks included)."""

    from app.core.secrets import get_secret_store
    from app.queue.worker import QueueWorker, set_current_worker
    from app.services.deps import get_git_service, get_ocr_adapter
    from app.webhooks.service import WebhookService

    workers: list[QueueWorker] = []

    def _make() -> QueueWorker:
        async def dispatcher(session, job, event_type):
            await WebhookService(session, settings=settings).dispatch_event(
                session, job, event_type
            )

        worker = QueueWorker(
            settings,
            get_git_service(),
            get_ocr_adapter(),
            get_secret_store(),
            webhook_dispatcher=dispatcher,
            poll_seconds=0.05,
        )
        set_current_worker(worker)
        workers.append(worker)
        return worker

    yield _make
    set_current_worker(None)


@pytest.fixture()
async def project(db, runtime, repo: Path):
    """A registered project backed by the temp git repo."""

    from app.db.session import session_scope
    from app.services.projects import ProjectService

    async with session_scope() as session:
        service = ProjectService(session)
        project = await service.create(absolute_path=str(repo))
        return project.id, project.absolute_path

"""Pull request discovery + PR review jobs.

Covers: GitHub remote-URL parsing, PR listing via the GitHub API
(``httpx.MockTransport``), the ``git ls-remote refs/pull/*/head`` fallback,
and job creation with ``mode="pr"`` (immutable SHA snapshot + range argv).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from app.db.session import session_scope
from app.services.errors import ValidationFailedError
from app.services.jobs import JobService
from app.services.projects import ProjectService
from app.services.pull_requests import (
    PrService,
    parse_github_remote,
    parse_ls_remote_output,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# remote URL parsing (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/octo/hello", ("octo", "hello")),
        ("https://github.com/octo/hello.git", ("octo", "hello")),
        ("https://github.com/octo/hello/", ("octo", "hello")),
        ("http://github.com/octo/hello.git", ("octo", "hello")),
        ("git@github.com:octo/hello", ("octo", "hello")),
        ("git@github.com:octo/hello.git", ("octo", "hello")),
        ("ssh://git@github.com/octo/hello", ("octo", "hello")),
        ("ssh://git@github.com/octo/hello.git", ("octo", "hello")),
        ("https://github.com/octo/hello.world", ("octo", "hello.world")),
    ],
)
def test_parse_github_remote_accepts_github_forms(url, expected) -> None:
    assert parse_github_remote(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://gitlab.com/octo/hello.git",
        "git@gitlab.com:octo/hello.git",
        "https://github.com/octo",
        "C:/code/local-repo",
        "/var/repos/mirror.git",
    ],
)
def test_parse_github_remote_rejects_non_github(url) -> None:
    assert parse_github_remote(url) is None


# ---------------------------------------------------------------------------
# ls-remote output parsing (pure)
# ---------------------------------------------------------------------------


def test_parse_ls_remote_output() -> None:
    output = (
        ("a" * 40) + "\trefs/pull/12/head\n"
        + ("b" * 40) + "\trefs/pull/3/head\n"
        + ("c" * 40) + "\trefs/pull/9/merge\n"  # merge refs are not heads
        + "not-a-sha\trefs/pull/5/head\n"
    )
    prs = parse_ls_remote_output(output)
    assert [pr.number for pr in prs] == [3, 12]  # sorted, merge ref skipped
    assert prs[0].head_sha == "b" * 40
    assert prs[0].base_ref is None
    assert prs[0].base_sha is None
    assert prs[0].source == "git"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def github_project(db, runtime, make_repo):
    """Project whose origin points at a GitHub URL (API path)."""

    repo = make_repo("ghrepo")
    _git(repo, "remote", "add", "origin", "https://github.com/octo/hello.git")
    async with session_scope() as session:
        project = await ProjectService(session).create(absolute_path=str(repo))
        return project.id, project.absolute_path


@pytest.fixture()
async def local_remote_project(db, runtime, make_repo, tmp_path):
    """Project cloned from a local "remote" (git fallback path).

    The remote publishes ``refs/pull/3/head``; the clone owns the head commit
    object (it is the remote's main HEAD), so detached-worktree creation at
    execution time can resolve the captured target SHA.
    """

    remote = make_repo("remote")
    head_sha = _git(remote, "rev-parse", "HEAD")
    _git(remote, "update-ref", "refs/pull/3/head", head_sha)
    local = tmp_path / "local"
    subprocess.run(
        ["git", "clone", str(remote), str(local)],
        capture_output=True, text=True, check=True,
    )
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test User")
    async with session_scope() as session:
        project = await ProjectService(session).create(absolute_path=str(local))
        return project.id, project.absolute_path, head_sha


PR_PAYLOAD = [
    {
        "number": 7,
        "title": "Improve review prompts",
        "head": {"ref": "feature/prompts", "sha": "f" * 40},
        "base": {"ref": "main", "sha": "e" * 40},
        "user": {"login": "octocat"},
        "updated_at": "2025-01-02T03:04:05Z",
    }
]


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# listing via the GitHub API
# ---------------------------------------------------------------------------


async def test_list_prs_via_api(github_project) -> None:
    project_id, _ = github_project

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo/hello/pulls"
        assert request.url.params["state"] == "open"
        assert request.headers["user-agent"] == "ocr-control-center"
        return httpx.Response(200, json=PR_PAYLOAD)

    transport = _mock_transport(handler)
    async with session_scope() as session:
        service = PrService(session, http_transport=transport)
        listing = await service.list_open_prs(project_id)

    assert listing.source == "api"
    assert listing.warning is None
    assert len(listing.prs) == 1
    pr = listing.prs[0]
    assert pr.number == 7
    assert pr.title == "Improve review prompts"
    assert pr.head_ref == "feature/prompts"
    assert pr.head_sha == "f" * 40
    assert pr.base_ref == "main"
    assert pr.base_sha == "e" * 40
    assert pr.author == "octocat"
    assert pr.updated_at is not None
    assert pr.source == "api"


async def test_list_prs_api_token_never_required_but_used_when_set(
    github_project, monkeypatch
) -> None:
    project_id, _ = github_project
    monkeypatch.setenv("OCR_CC_GITHUB_TOKEN", "secret-token-123")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-token-123"
        return httpx.Response(200, json=[])

    transport = _mock_transport(handler)
    async with session_scope() as session:
        service = PrService(session, http_transport=transport)
        listing = await service.list_open_prs(project_id)
    assert listing.source == "api"
    assert listing.prs == []


async def test_list_prs_api_error_falls_back_to_git(github_project) -> None:
    project_id, _ = github_project

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    transport = _mock_transport(handler)
    async with session_scope() as session:
        service = PrService(session, http_transport=transport)
        listing = await service.list_open_prs(project_id)

    # The origin URL is a real GitHub URL, so the fallback runs
    # `git ls-remote https://github.com/...` which cannot succeed offline;
    # the service degrades gracefully with an actionable warning.
    assert listing.source == "none"
    assert listing.prs == []
    assert listing.warning is not None


# ---------------------------------------------------------------------------
# listing via the git fallback
# ---------------------------------------------------------------------------


async def test_list_prs_via_ls_remote(local_remote_project) -> None:
    project_id, _, head_sha = local_remote_project
    async with session_scope() as session:
        service = PrService(session)
        listing = await service.list_open_prs(project_id)

    assert listing.source == "git"
    assert [pr.number for pr in listing.prs] == [3]
    pr = listing.prs[0]
    assert pr.head_sha == head_sha
    assert pr.base_ref is None
    assert pr.base_sha is None
    assert pr.source == "git"
    # Non-GitHub remote → the warning explains the limitation.
    assert listing.warning is not None
    assert "not a GitHub URL" in listing.warning


async def test_list_prs_no_remote(db, runtime, make_repo) -> None:
    repo = make_repo("isolated")
    async with session_scope() as session:
        project = await ProjectService(session).create(absolute_path=str(repo))
        project_id = project.id
    async with session_scope() as session:
        service = PrService(session)
        listing = await service.list_open_prs(project_id)
    assert listing.source == "none"
    assert listing.prs == []
    assert "no git remote" in (listing.warning or "")


# ---------------------------------------------------------------------------
# job creation with mode="pr"
# ---------------------------------------------------------------------------


async def test_pr_job_via_api_captures_immutable_shas(
    github_project, fake_ocr, monkeypatch
) -> None:
    project_id, _ = github_project

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PR_PAYLOAD)

    transport = _mock_transport(handler)
    monkeypatch.setattr(
        JobService,
        "_prs",
        lambda self: PrService(self.session, http_transport=transport),
    )

    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(project_id=project_id, mode="pr", pr_number=7)
        job_id = job.id

    async with session_scope() as session:
        from app.db import models

        job = await session.get(models.ReviewJob, job_id)
        assert job.mode == "pr"
        assert job.base_ref == "main"
        assert job.target_ref == "feature/prompts"
        snapshot = job.configuration_snapshot_json
        assert snapshot["base_sha"] == "e" * 40
        assert snapshot["target_sha"] == "f" * 40
        assert snapshot["refs"] == {
            "base_ref": "main",
            "target_ref": "feature/prompts",
            "commit_ref": None,
        }
        assert snapshot["context"]["mode"] == "pr"
        assert job.request_metadata_json["pr_number"] == 7
        argv = job.generated_command_json["argv"]
        assert "--from" in argv
        assert argv[argv.index("--from") + 1] == "e" * 40
        assert argv[argv.index("--to") + 1] == "f" * 40
        assert "--format" in argv and "json" in argv
        assert "--audience" in argv and "human" in argv
        # PR jobs run in a detached worktree, exactly like range jobs.
        assert job.worktree_path is None  # created at execution time
        assert str(job_id) in job.generated_command_json["cwd"]


async def test_pr_job_git_fallback_requires_explicit_base(
    local_remote_project, fake_ocr
) -> None:
    project_id, _, _ = local_remote_project
    async with session_scope() as session:
        service = JobService(session)
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.create(project_id=project_id, mode="pr", pr_number=3)
        assert "base" in str(excinfo.value).lower()
        assert excinfo.value.next_action is not None


async def test_pr_job_git_fallback_with_base_ref(
    local_remote_project, fake_ocr
) -> None:
    project_id, _, head_sha = local_remote_project
    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(
            project_id=project_id, mode="pr", pr_number=3, base_ref="main"
        )
        snapshot = job.configuration_snapshot_json
        assert job.mode == "pr"
        assert job.base_ref == "main"
        assert snapshot["target_sha"] == head_sha
        assert snapshot["base_sha"] == head_sha  # remote shares the same commit
        argv = job.generated_command_json["argv"]
        assert argv[argv.index("--from") + 1] == snapshot["base_sha"]
        assert argv[argv.index("--to") + 1] == head_sha


async def test_pr_job_missing_pr_number(github_project, fake_ocr) -> None:
    project_id, _ = github_project
    async with session_scope() as session:
        service = JobService(session)
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.create(project_id=project_id, mode="pr")
        assert excinfo.value.next_action is not None


async def test_pr_job_unknown_number(github_project, fake_ocr, monkeypatch) -> None:
    project_id, _ = github_project

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PR_PAYLOAD)

    transport = _mock_transport(handler)
    monkeypatch.setattr(
        JobService,
        "_prs",
        lambda self: PrService(self.session, http_transport=transport),
    )
    async with session_scope() as session:
        service = JobService(session)
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.create(project_id=project_id, mode="pr", pr_number=99)
        assert "#99" in str(excinfo.value)


async def test_pr_job_without_remote_rejected(db, runtime, make_repo, fake_ocr) -> None:
    repo = make_repo("noremote")
    async with session_scope() as session:
        project = await ProjectService(session).create(absolute_path=str(repo))
        project_id = project.id
    async with session_scope() as session:
        service = JobService(session)
        with pytest.raises(ValidationFailedError) as excinfo:
            await service.create(project_id=project_id, mode="pr", pr_number=1)
        assert "no git remote" in str(excinfo.value)
        assert excinfo.value.next_action is not None


# ---------------------------------------------------------------------------
# route: GET /api/v1/projects/{id}/pull-requests
# ---------------------------------------------------------------------------


@pytest.fixture()
async def client(settings, fake_ocr, runtime):
    import asyncio

    from app.main import create_app

    app = create_app(settings)
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def _lifespan_runner() -> None:
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    lifespan_task = asyncio.create_task(_lifespan_runner())
    await ready.wait()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            await c.get("/api/v1/health")
            yield c
    finally:
        stop.set()
        await asyncio.wait_for(lifespan_task, timeout=10)


async def test_pull_requests_route_returns_envelope(
    client, local_remote_project
) -> None:
    project_id, _, head_sha = local_remote_project
    response = await client.get(f"/api/v1/projects/{project_id}/pull-requests")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "git"
    assert body["warning"] is not None
    assert body["prs"] == [
        {
            "number": 3,
            "title": None,
            "head_ref": None,
            "head_sha": head_sha,
            "base_ref": None,
            "base_sha": None,
            "author": None,
            "updated_at": None,
            "source": "git",
        }
    ]


async def test_pull_requests_route_404_for_unknown_project(client) -> None:
    response = await client.get("/api/v1/projects/nope/pull-requests")
    assert response.status_code == 404


async def test_pr_job_executes_like_range(local_remote_project, fake_ocr, make_worker) -> None:
    """The execution path treats PR jobs like range jobs (detached worktree)."""

    import asyncio

    from app.db import models

    project_id, _, _ = local_remote_project
    async with session_scope() as session:
        service = JobService(session)
        job = await service.create(
            project_id=project_id, mode="pr", pr_number=3, base_ref="main"
        )
        job_id = job.id
    worker = make_worker()
    await worker.drain()

    deadline = asyncio.get_event_loop().time() + 15.0
    status = None
    while asyncio.get_event_loop().time() < deadline:
        async with session_scope() as session:
            job = await session.get(models.ReviewJob, job_id)
            status = job.status
            command = job.generated_command_json
        if status in {"completed", "completed_with_warnings", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert status in {"completed", "completed_with_warnings"}
    # The command ran in a detached worktree (removed after the job finished).
    assert "worktrees" in str(command["cwd"]).replace("\\", "/")

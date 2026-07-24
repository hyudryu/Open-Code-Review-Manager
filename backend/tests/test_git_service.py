"""GitService tests against real temporary git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.security import RefValidationError
from app.git.service import (
    GitService,
    RefNotFoundError,
    RepoValidationError,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


# --- validate_repo ------------------------------------------------------------


async def test_validate_repo_success(git_service: GitService, repo: Path) -> None:
    info = await git_service.validate_repo(repo)
    assert info.path == repo.resolve()
    assert info.current_branch == "main"
    assert not info.is_detached
    assert not info.is_dirty
    assert info.git_common_dir.name == ".git"


async def test_validate_repo_rejects_missing(git_service: GitService, tmp_path: Path) -> None:
    with pytest.raises(RepoValidationError):
        await git_service.validate_repo(tmp_path / "missing")


async def test_validate_repo_rejects_non_repo(git_service: GitService, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RepoValidationError) as exc:
        await git_service.validate_repo(plain)
    assert exc.value.reason == "not_worktree"


async def test_validate_repo_rejects_bare(git_service: GitService, tmp_path: Path, repo: Path) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo), str(bare)],
        capture_output=True, check=True,
    )
    with pytest.raises(RepoValidationError) as exc:
        await git_service.validate_repo(bare)
    assert exc.value.reason == "bare"


async def test_validate_repo_rejects_duplicate(git_service: GitService, repo: Path) -> None:
    with pytest.raises(RepoValidationError) as exc:
        await git_service.validate_repo(
            repo, existing_paths={str(repo.resolve())}
        )
    assert exc.value.reason == "duplicate"


async def test_validate_repo_rejects_outside_allowed_roots(
    git_service: GitService, tmp_path: Path
) -> None:
    # allowed_roots is [tmp_path]; a repo in a sibling directory is outside.
    sibling = tmp_path.parent / (tmp_path.name + "-outside")
    sibling.mkdir(exist_ok=True)
    try:
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=sibling, capture_output=True, check=True
        )
        with pytest.raises(RepoValidationError) as exc:
            await git_service.validate_repo(sibling)
        assert exc.value.reason == "outside_allowed_roots"
    finally:
        import shutil

        shutil.rmtree(sibling, ignore_errors=True)


async def test_validate_repo_dirty_and_detached(git_service: GitService, repo: Path) -> None:
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", sha)
    info = await git_service.validate_repo(repo)
    assert info.is_dirty
    assert info.is_detached
    assert info.current_branch is None


# --- scan_folder ---------------------------------------------------------------


async def test_scan_folder_finds_nested_repos(git_service: GitService, make_repo, tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    (parent / "a").mkdir(parents=True)
    (parent / "b" / "inner").mkdir(parents=True)
    make_repo("parent/a")
    make_repo("parent/b/inner")
    result = await git_service.scan_folder(parent, depth=3)
    paths = {r.path.name for r in result.repos}
    assert paths == {"a", "inner"}


async def test_scan_folder_respects_depth(git_service: GitService, make_repo, tmp_path: Path) -> None:
    deep = tmp_path / "deep"
    (deep / "l1" / "l2" / "l3").mkdir(parents=True)
    make_repo("deep/l1/l2/l3")
    shallow = await git_service.scan_folder(deep, depth=1)
    assert shallow.repos == []
    deeper = await git_service.scan_folder(deep, depth=3)
    assert len(deeper.repos) == 1


async def test_scan_folder_skips_excluded_dirs(git_service: GitService, make_repo, tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "node_modules" / "pkg").mkdir(parents=True)
    make_repo("root/node_modules/pkg")
    result = await git_service.scan_folder(root, depth=3)
    assert result.repos == []


async def test_scan_folder_detects_worktree_git_file(
    git_service: GitService, repo: Path, tmp_path: Path
) -> None:
    wt = tmp_path / "linked-worktree"
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "worktree", "add", "--detach", str(wt), sha)
    result = await git_service.scan_folder(tmp_path, depth=1)
    names = {r.path.name: r for r in result.repos}
    assert "linked-worktree" in names
    assert names["linked-worktree"].has_git_file


async def test_scan_folder_marks_registered(
    git_service: GitService, repo: Path, tmp_path: Path
) -> None:
    result = await git_service.scan_folder(
        tmp_path, depth=1, existing_paths={str(repo.resolve())}
    )
    marked = [r for r in result.repos if r.path == repo.resolve()]
    assert marked and marked[0].already_registered


# --- refresh_branches ------------------------------------------------------------


async def test_refresh_branches_kinds_and_current(git_service: GitService, repo: Path) -> None:
    _git(repo, "branch", "feature/x")
    _git(repo, "tag", "v1.0")
    # Fake a remote ref.
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    entries, fetch_error = await git_service.refresh_branches(repo)
    assert fetch_error is None
    by_ref = {e.full_ref: e for e in entries}

    local = by_ref["refs/heads/main"]
    assert local.kind == "local" and local.is_current and local.is_default
    feature = by_ref["refs/heads/feature/x"]
    assert feature.kind == "local" and not feature.is_current
    remote = by_ref["refs/remotes/origin/main"]
    assert remote.kind == "remote" and remote.remote_name == "origin"
    assert remote.is_default
    tag = by_ref["refs/tags/v1.0"]
    assert tag.kind == "tag"
    for entry in entries:
        assert len(entry.commit_sha) == 40
        assert entry.commit_timestamp is not None


def test_parse_for_each_ref_unit(git_service: GitService) -> None:
    output = (
        "refs/heads/main|aabbccdd00112233445566778899001122334455|initial|2026-07-20T10:00:00+00:00\n"
        "refs/remotes/origin/dev|bbccdd0011223344556677889900112233445566|dev work|2026-07-21T11:00:00+02:00\n"
        "refs/tags/v2|ccddee001122334455667788990011223344556677|release|\n"
    )
    entries = GitService.parse_for_each_ref(output)
    assert len(entries) == 3
    assert entries[0].kind == "local" and entries[0].name == "main"
    assert entries[0].commit_timestamp is not None
    assert entries[1].kind == "remote" and entries[1].remote_name == "origin"
    assert entries[1].name == "dev"
    assert entries[2].kind == "tag" and entries[2].commit_timestamp is None


async def test_failed_fetch_keeps_local_refs(git_service: GitService, repo: Path) -> None:
    # No remote configured: fetch --all succeeds trivially, so simulate a
    # failing remote instead.
    _git(repo, "remote", "add", "origin", str(repo / "does-not-matter"))
    _git(repo, "remote", "set-url", "origin", "/nonexistent/remote.git")
    entries, fetch_error = await git_service.refresh_branches(repo, fetch=True)
    assert fetch_error is not None
    assert any(e.full_ref == "refs/heads/main" for e in entries)


# --- resolve_ref ------------------------------------------------------------------


async def test_resolve_ref_branch_tag_sha(git_service: GitService, repo: Path) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    assert await git_service.resolve_ref(repo, "main") == head
    _git(repo, "tag", "v9")
    assert await git_service.resolve_ref(repo, "v9") == head
    assert await git_service.resolve_ref(repo, head) == head


async def test_resolve_ref_unknown(git_service: GitService, repo: Path) -> None:
    with pytest.raises(RefNotFoundError):
        await git_service.resolve_ref(repo, "no-such-branch")


async def test_resolve_ref_rejects_option_injection(git_service: GitService, repo: Path) -> None:
    with pytest.raises(RefValidationError):
        await git_service.resolve_ref(repo, "--upload-pack=touch /tmp/pwn")


# --- worktrees ----------------------------------------------------------------------


async def test_worktree_lifecycle(git_service: GitService, repo: Path, tmp_path: Path) -> None:
    sha = await git_service.resolve_ref(repo, "main")
    wt = tmp_path / "wt-job-1"
    await git_service.add_detached_worktree(repo, wt, sha)
    assert (wt / ".git").is_file()
    assert (wt / "hello.py").is_file()

    entries = await git_service.list_worktrees(repo)
    assert any(e.path.name == "wt-job-1" and e.is_detached for e in entries)

    await git_service.remove_worktree(repo, wt)
    assert not wt.exists()
    await git_service.prune_worktrees(repo)


async def test_git_version_detected(git_service: GitService) -> None:
    version = await git_service.version()
    assert version and version[0].isdigit()

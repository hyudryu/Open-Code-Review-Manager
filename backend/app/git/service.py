"""Git integration behind a single service (SPEC §5, §6, §11, §38 rule 5).

All git invocations use ``asyncio.create_subprocess_exec`` argv arrays —
never shell strings, never ``shell=True``. User-supplied refs are validated
and placed after ``--end-of-options`` where supported.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import (
    PathSecurityError,
    RefValidationError,
    enforce_allowed_roots,
    normalize_path,
    validate_git_ref,
)

logger = get_logger(__name__)

#: Directories skipped during folder scans (SPEC §4).
DEFAULT_EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "target",
        "vendor",
        ".git",
        ".cache",
        ".next",
        ".nuxt",
        "coverage",
    }
)

FOR_EACH_REF_FORMAT = "%(refname)|%(objectname)|%(subject)|%(committerdate:iso-strict)"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GitError(RuntimeError):
    """Base error carrying sanitized git stderr."""

    def __init__(self, message: str, *, stderr: str = "", returncode: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class GitNotFoundError(GitError):
    pass


class GitTimeoutError(GitError):
    pass


class RepoValidationError(GitError):
    def __init__(self, reason: str, message: str, *, stderr: str = ""):
        super().__init__(message, stderr=stderr)
        self.reason = reason  # machine-readable: missing/not_worktree/bare/duplicate/outside_allowed_roots


class RefNotFoundError(GitError):
    pass


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class RepoInfo:
    """Outcome of :meth:`GitService.validate_repo` (SPEC §5)."""

    path: Path  # resolved top-level work tree
    git_common_dir: Path
    current_branch: str | None  # None when HEAD is detached
    is_detached: bool
    is_dirty: bool
    remotes: dict[str, str]  # remote name -> fetch url
    remote_name: str | None  # preferred remote ("origin" when present)
    remote_url: str | None
    default_branch: str | None


@dataclass(slots=True)
class ScannedRepo:
    path: Path  # resolved top-level
    has_git_file: bool  # worktree-style .git file vs .git directory
    already_registered: bool = False


@dataclass(slots=True)
class ScanResult:
    root: Path
    repos: list[ScannedRepo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BranchEntry:
    """One parsed ``git for-each-ref`` row (SPEC §6)."""

    name: str
    full_ref: str
    kind: str  # local | remote | tag
    remote_name: str | None
    commit_sha: str
    commit_subject: str
    commit_timestamp: datetime | None
    is_default: bool = False
    is_current: bool = False


@dataclass(slots=True)
class WorktreeEntry:
    path: Path
    head: str | None
    branch: str | None  # None when detached
    is_detached: bool
    is_bare: bool
    is_prunable: bool


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GitService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._executable: str | None = None

    # -- executable ---------------------------------------------------------

    def find_executable(self) -> str | None:
        """Locate the git binary (custom path first, then PATH)."""

        if self._executable:
            return self._executable
        custom = self._settings.git_executable
        if custom:
            candidate = normalize_path(custom)
            if candidate.is_file():
                self._executable = str(candidate)
                return self._executable
        for name in ("git", "git.exe"):
            found = shutil.which(name)
            if found:
                self._executable = found
                return found
        return None

    def _require_executable(self) -> str:
        exe = self.find_executable()
        if exe is None:
            raise GitNotFoundError(
                "git executable not found; install Git or configure a custom path"
            )
        return exe

    # -- subprocess ----------------------------------------------------------

    @staticmethod
    def build_safe_env() -> dict[str, str]:
        """Environment for git subprocesses: non-interactive, no inherited
        repo state (GIT_DIR/GIT_WORK_TREE/etc. are stripped)."""

        env = dict(os.environ)
        for var in list(env):
            # Keep GIT_CEILING_DIRECTORIES (a discovery *limiter* used by
            # sandboxed/test environments); strip all other repo state.
            if var.startswith("GIT_") and var not in {
                "GIT_SSL_NO_VERIFY",
                "GIT_CEILING_DIRECTORIES",
            }:
                env.pop(var)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        env["SSH_ASKPASS"] = ""
        env["GCM_INTERACTIVE"] = "never"
        return env

    async def run(
        self,
        args: list[str],
        *,
        cwd: Path | str | None = None,
        timeout: float | None = None,
    ) -> GitResult:
        """Run git with an argv array; raise on timeout, return on any exit."""

        exe = self._require_executable()
        effective_timeout = timeout or self._settings.git_timeout_seconds
        try:
            proc = await asyncio.create_subprocess_exec(
                exe,
                *args,
                cwd=str(cwd) if cwd else None,
                env=self.build_safe_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise GitError(f"failed to start git: {exc}") from exc
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GitTimeoutError(
                f"git {' '.join(args[:2])} timed out after {effective_timeout:.0f}s"
            ) from exc
        return GitResult(
            returncode=proc.returncode or 0,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )

    async def version(self) -> str | None:
        result = await self.run(["version"], timeout=10)
        if result.returncode != 0:
            return None
        return result.stdout.strip().removeprefix("git version").strip()

    # -- repo validation ------------------------------------------------------

    async def validate_repo(
        self,
        path: str | Path,
        *,
        existing_paths: set[str] | None = None,
        enforce_roots: bool | None = None,
    ) -> RepoInfo:
        """Validate a repository for registration (SPEC §5).

        Rejects: missing paths, non-worktrees, bare repositories, duplicates
        (by resolved top-level, case-normalized), and — when path restrictions
        are enabled — top-levels outside the configured allowed roots.
        """

        try:
            resolved = normalize_path(path, must_exist=True)
        except PathSecurityError as exc:
            raise RepoValidationError("missing", str(exc)) from exc
        if not resolved.is_dir():
            raise RepoValidationError("missing", f"not a directory: {resolved}")

        enforce = (
            self._settings.path_restrictions_enabled if enforce_roots is None else enforce_roots
        )

        async def _git(args: list[str], what: str) -> GitResult:
            result = await self.run(args, cwd=resolved)
            if result.returncode != 0:
                raise RepoValidationError(
                    "not_worktree",
                    f"git {what} failed for {resolved}",
                    stderr=result.stderr.strip()[:500],
                )
            return result

        inside = await self.run(
            ["rev-parse", "--is-inside-work-tree"], cwd=resolved
        )
        # Bare check first: inside a bare repo --is-inside-work-tree exits 0
        # and prints "false", which must surface as "bare", not "not_worktree".
        bare = await self.run(["rev-parse", "--is-bare-repository"], cwd=resolved)
        if bare.returncode == 0 and bare.stdout.strip() == "true":
            raise RepoValidationError(
                "bare", f"bare repositories cannot be reviewed: {resolved}"
            )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise RepoValidationError(
                "not_worktree",
                f"not a git work tree: {resolved}",
                stderr=inside.stderr.strip()[:500],
            )

        top = await _git(["rev-parse", "--show-toplevel"], "rev-parse --show-toplevel")
        top_level = normalize_path(top.stdout.strip(), must_exist=True)

        if enforce:
            try:
                enforce_allowed_roots(top_level, list(self._settings.allowed_roots))
            except PathSecurityError as exc:
                raise RepoValidationError("outside_allowed_roots", str(exc)) from exc

        normcase_top = os.path.normcase(str(top_level))
        if existing_paths and normcase_top in {
            os.path.normcase(p) for p in existing_paths
        }:
            raise RepoValidationError(
                "duplicate", f"repository already registered: {top_level}"
            )

        common = await _git(
            ["rev-parse", "--git-common-dir"], "rev-parse --git-common-dir"
        )
        common_raw = common.stdout.strip()
        common_dir = Path(common_raw)
        if not common_dir.is_absolute():
            common_dir = (top_level / common_dir).resolve()

        remotes = await self._parse_remotes(top_level)
        remote_name = "origin" if "origin" in remotes else next(iter(remotes), None)
        remote_url = remotes.get(remote_name) if remote_name else None

        branch_result = await self.run(
            ["symbolic-ref", "--short", "HEAD"], cwd=top_level
        )
        is_detached = branch_result.returncode != 0
        current_branch = None if is_detached else branch_result.stdout.strip()

        status = await self.run(["status", "--porcelain"], cwd=top_level)
        is_dirty = bool(status.stdout.strip()) if status.returncode == 0 else False

        default_branch = await self._detect_default_branch(top_level, remote_name)

        return RepoInfo(
            path=top_level,
            git_common_dir=common_dir,
            current_branch=current_branch,
            is_detached=is_detached,
            is_dirty=is_dirty,
            remotes=remotes,
            remote_name=remote_name,
            remote_url=remote_url,
            default_branch=default_branch,
        )

    async def _parse_remotes(self, cwd: Path) -> dict[str, str]:
        result = await self.run(["remote", "-v"], cwd=cwd)
        remotes: dict[str, str] = {}
        if result.returncode != 0:
            return remotes
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "(fetch)":
                remotes.setdefault(parts[0], parts[1])
        return remotes

    async def _detect_default_branch(
        self, cwd: Path, remote_name: str | None
    ) -> str | None:
        """Default branch from ``refs/remotes/<remote>/HEAD`` when present."""

        if not remote_name:
            return None
        result = await self.run(
            ["symbolic-ref", f"refs/remotes/{remote_name}/HEAD"], cwd=cwd
        )
        if result.returncode != 0:
            return None
        prefix = f"refs/remotes/{remote_name}/"
        ref = result.stdout.strip()
        return ref.removeprefix(prefix) if ref.startswith(prefix) else None

    # -- folder scanning -------------------------------------------------------

    async def scan_folder(
        self,
        path: str | Path,
        *,
        depth: int = 2,
        excluded_names: frozenset[str] = DEFAULT_EXCLUDED_DIR_NAMES,
        existing_paths: set[str] | None = None,
    ) -> ScanResult:
        """Depth-limited, symlink-loop-safe repository discovery (SPEC §4).

        Detects both ``.git`` directories and worktree ``.git`` files, then
        resolves each candidate's real top-level via git and deduplicates.
        Filesystem walking runs in a worker thread to keep the loop free.
        """

        root = normalize_path(path, must_exist=True)
        if not root.is_dir():
            raise PathSecurityError(f"not a directory: {root}")
        registered = {os.path.normcase(p) for p in (existing_paths or set())}

        candidates, errors = await asyncio.to_thread(
            self._walk_for_git_markers, root, depth, excluded_names
        )

        seen: set[str] = set()
        repos: list[ScannedRepo] = []
        for candidate, has_git_file in candidates:
            result = await self.run(
                ["rev-parse", "--show-toplevel"], cwd=candidate
            )
            if result.returncode != 0:
                errors.append(
                    f"{candidate}: not a usable work tree ({result.stderr.strip()[:200]})"
                )
                continue
            try:
                top = normalize_path(result.stdout.strip(), must_exist=True)
            except PathSecurityError:
                continue
            key = os.path.normcase(str(top))
            if key in seen:
                continue
            seen.add(key)
            repos.append(
                ScannedRepo(
                    path=top,
                    has_git_file=has_git_file,
                    already_registered=key in registered,
                )
            )
        return ScanResult(root=root, repos=repos, errors=errors)

    def _walk_for_git_markers(
        self,
        root: Path,
        depth: int,
        excluded_names: frozenset[str],
    ) -> tuple[list[tuple[Path, bool]], list[str]]:
        """Sync BFS over directories without following symlinked dirs.

        Returns ``(candidates, errors)`` where a candidate is
        ``(directory, has_git_file)``.
        """

        candidates: list[tuple[Path, bool]] = []
        errors: list[str] = []
        visited: set[tuple[int, int] | str] = set()

        def _identity(p: Path) -> tuple[int, int] | str:
            try:
                st = p.stat()
                return (st.st_dev, st.st_ino)
            except OSError:
                return str(p)

        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue:
            current, level = queue.pop(0)
            ident = _identity(current)
            if ident in visited:
                continue
            visited.add(ident)

            git_marker = current / ".git"
            try:
                if git_marker.is_dir():
                    candidates.append((current, False))
                    continue  # do not descend into repository internals
                if git_marker.is_file():
                    candidates.append((current, True))
                    continue
            except OSError:
                continue

            if level >= depth:
                continue
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.name in excluded_names:
                                continue
                            # follow_symlinks=False: never recurse into a
                            # symlinked directory → loop-safe by construction.
                            if entry.is_dir(follow_symlinks=False):
                                queue.append((Path(entry.path), level + 1))
                        except OSError:
                            continue
            except PermissionError:
                errors.append(f"{current}: permission denied")
            except OSError as exc:
                errors.append(f"{current}: {exc}")
        return candidates, errors

    # -- branches ---------------------------------------------------------------

    @staticmethod
    def parse_for_each_ref(output: str) -> list[BranchEntry]:
        """Parse ``for-each-ref`` output into branch entries (pure function)."""

        entries: list[BranchEntry] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            full_ref, sha, subject, date_str = parts
            if full_ref.startswith("refs/heads/"):
                kind = "local"
                name = full_ref[len("refs/heads/"):]
                remote_name = None
            elif full_ref.startswith("refs/remotes/"):
                kind = "remote"
                rest = full_ref[len("refs/remotes/"):]
                remote_name, _, name = rest.partition("/")
                if not name:  # e.g. refs/remotes/origin (unusual)
                    continue
            elif full_ref.startswith("refs/tags/"):
                kind = "tag"
                name = full_ref[len("refs/tags/"):]
                remote_name = None
            else:
                continue
            timestamp: datetime | None = None
            if date_str.strip():
                try:
                    timestamp = datetime.fromisoformat(date_str.strip())
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                except ValueError:
                    timestamp = None
            entries.append(
                BranchEntry(
                    name=name,
                    full_ref=full_ref,
                    kind=kind,
                    remote_name=remote_name,
                    commit_sha=sha.strip(),
                    commit_subject=subject,
                    commit_timestamp=timestamp,
                )
            )
        return entries

    async def refresh_branches(
        self,
        path: str | Path,
        *,
        fetch: bool = False,
        prune: bool = False,
    ) -> tuple[list[BranchEntry], str | None]:
        """Collect branch cache rows (SPEC §6).

        Returns ``(entries, fetch_error)``. A failed fetch never prevents
        local refs from being returned, so the caller can keep the existing
        cache semantics of §6 ("a failed fetch must not erase the cache").
        """

        repo = normalize_path(path, must_exist=True)
        fetch_error: str | None = None
        if fetch:
            args = ["fetch", "--all"] + (["--prune"] if prune else [])
            result = await self.run(
                args, cwd=repo, timeout=self._settings.git_fetch_timeout_seconds
            )
            if result.returncode != 0:
                fetch_error = result.stderr.strip()[:500] or "git fetch failed"

        result = await self.run(
            [
                "for-each-ref",
                f"--format={FOR_EACH_REF_FORMAT}",
                "refs/heads",
                "refs/remotes",
                "refs/tags",
            ],
            cwd=repo,
        )
        if result.returncode != 0:
            raise GitError(
                f"git for-each-ref failed for {repo}",
                stderr=result.stderr.strip()[:500],
                returncode=result.returncode,
            )
        entries = self.parse_for_each_ref(result.stdout)

        current = await self.run(["symbolic-ref", "--short", "HEAD"], cwd=repo)
        current_branch = current.stdout.strip() if current.returncode == 0 else None
        for entry in entries:
            if entry.kind == "local" and entry.name == current_branch:
                entry.is_current = True

        default_remote_branch = await self._detect_default_branch(
            repo, "origin" if any(e.remote_name == "origin" for e in entries) else None
        )
        if default_remote_branch:
            for entry in entries:
                if (
                    entry.kind == "remote"
                    and entry.name == default_remote_branch
                    and entry.remote_name == "origin"
                ):
                    entry.is_default = True
                if entry.kind == "local" and entry.name == default_remote_branch:
                    entry.is_default = True
        return entries, fetch_error

    # -- refs -------------------------------------------------------------------

    async def resolve_ref(
        self, path: str | Path, ref: str, *, must_be_commit: bool = True
    ) -> str:
        """Resolve ``ref`` to a commit SHA via ``rev-parse --verify``.

        The ref is validated first and passed after ``--end-of-options``
        (SPEC §27 Git Security).
        """

        validated = validate_git_ref(ref)
        repo = normalize_path(path, must_exist=True)
        spec = f"{validated}^{{commit}}" if must_be_commit else validated
        result = await self.run(
            ["rev-parse", "--verify", "--end-of-options", spec], cwd=repo
        )
        if result.returncode != 0:
            raise RefNotFoundError(
                f"could not resolve ref {ref!r} in {repo}",
                stderr=result.stderr.strip()[:300],
                returncode=result.returncode,
            )
        return result.stdout.strip().splitlines()[0]

    # -- worktrees ----------------------------------------------------------------

    async def add_detached_worktree(
        self, repo_path: str | Path, worktree_path: str | Path, commit_sha: str
    ) -> Path:
        """Create a detached worktree at an immutable commit (SPEC §11)."""

        repo = normalize_path(repo_path, must_exist=True)
        target = normalize_path(worktree_path)
        validate_git_ref(commit_sha)
        result = await self.run(
            ["worktree", "add", "--detach", str(target), commit_sha],
            cwd=repo,
            timeout=self._settings.git_timeout_seconds,
        )
        if result.returncode != 0:
            raise GitError(
                f"failed to create worktree at {target}",
                stderr=result.stderr.strip()[:500],
                returncode=result.returncode,
            )
        return target

    async def remove_worktree(
        self, repo_path: str | Path, worktree_path: str | Path, *, force: bool = False
    ) -> None:
        """Remove a worktree. Only used for app-created worktrees."""

        repo = normalize_path(repo_path, must_exist=True)
        target = normalize_path(worktree_path)
        args = ["worktree", "remove"] + (["--force"] if force else []) + [str(target)]
        result = await self.run(args, cwd=repo)
        if result.returncode != 0:
            raise GitError(
                f"failed to remove worktree {target}",
                stderr=result.stderr.strip()[:500],
                returncode=result.returncode,
            )

    async def prune_worktrees(self, repo_path: str | Path) -> None:
        repo = normalize_path(repo_path, must_exist=True)
        result = await self.run(["worktree", "prune"], cwd=repo)
        if result.returncode != 0:
            raise GitError(
                f"git worktree prune failed for {repo}",
                stderr=result.stderr.strip()[:500],
                returncode=result.returncode,
            )

    async def list_worktrees(self, repo_path: str | Path) -> list[WorktreeEntry]:
        """Parse ``git worktree list --porcelain`` (startup recovery uses this
        to detect orphan app-created worktrees)."""

        repo = normalize_path(repo_path, must_exist=True)
        result = await self.run(["worktree", "list", "--porcelain"], cwd=repo)
        if result.returncode != 0:
            raise GitError(
                f"git worktree list failed for {repo}",
                stderr=result.stderr.strip()[:500],
                returncode=result.returncode,
            )
        entries: list[WorktreeEntry] = []
        current: dict[str, object] = {}
        for line in result.stdout.splitlines() + [""]:
            if line.startswith("worktree "):
                if current.get("path"):
                    entries.append(self._wt_entry(current))
                current = {"path": line[len("worktree "):], "detached": False,
                           "bare": False, "prunable": False}
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                current["branch"] = line[len("branch "):]
            elif line == "detached":
                current["detached"] = True
            elif line == "bare":
                current["bare"] = True
            elif line.startswith("prunable"):
                current["prunable"] = True
            elif line == "" and current.get("path"):
                entries.append(self._wt_entry(current))
                current = {}
        return entries

    @staticmethod
    def _wt_entry(raw: dict[str, object]) -> WorktreeEntry:
        return WorktreeEntry(
            path=Path(str(raw["path"])),
            head=raw.get("head") if isinstance(raw.get("head"), str) else None,
            branch=raw.get("branch") if isinstance(raw.get("branch"), str) else None,
            is_detached=bool(raw.get("detached")),
            is_bare=bool(raw.get("bare")),
            is_prunable=bool(raw.get("prunable")),
        )

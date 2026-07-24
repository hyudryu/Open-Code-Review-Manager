"""Pull request discovery for PR review jobs (SPEC §29 error style).

GitHub projects resolve open PRs through the REST API; every project falls
back to ``git ls-remote <remote> refs/pull/*/head`` which yields PR numbers
and head SHAs but no base information (the UI then asks for a base branch).
The optional token comes from ``OCR_CC_GITHUB_TOKEN`` and is never logged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.db import models
from app.git.service import GitError
from app.services.deps import ServiceBase
from app.services.errors import NotFoundError, ValidationFailedError

GITHUB_API = "https://api.github.com"
USER_AGENT = "ocr-control-center"
TOKEN_ENV_VAR = "OCR_CC_GITHUB_TOKEN"

# https://github.com/owner/repo(.git), ssh://git@github.com/owner/repo(.git)
_HTTPS_RE = re.compile(
    r"^(?:https?|ssh)://(?:git@)?github\.com[:/]"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
# git@github.com:owner/repo(.git)
_SCP_RE = re.compile(
    r"^git@github\.com:(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

_LS_REMOTE_RE = re.compile(r"^(?P<sha>[0-9a-f]{40})\trefs/pull/(?P<number>\d+)/head$")


def parse_github_remote(url: str | None) -> tuple[str, str] | None:
    """Return ``(owner, repo)`` for GitHub remotes, else ``None``."""

    if not url:
        return None
    candidate = url.strip()
    for pattern in (_HTTPS_RE, _SCP_RE):
        match = pattern.match(candidate)
        if match:
            return match.group("owner"), match.group("repo")
    return None


@dataclass(slots=True)
class PullRequestEntry:
    number: int
    title: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    base_ref: str | None = None
    base_sha: str | None = None
    author: str | None = None
    updated_at: datetime | None = None
    source: str = "git"  # api | git


@dataclass(slots=True)
class PullRequestList:
    prs: list[PullRequestEntry] = field(default_factory=list)
    source: str = "none"  # api | git | none
    warning: str | None = None


class PrService(ServiceBase):
    def __init__(self, session, *, http_transport: httpx.AsyncBaseTransport | None = None, **kwargs) -> None:
        super().__init__(session, **kwargs)
        self._http_transport = http_transport

    # ------------------------------------------------------------------
    # listing
    # ------------------------------------------------------------------

    async def list_open_prs(self, project_id: str) -> PullRequestList:
        project = await self.session.get(models.Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        return await self.list_for_project(project)

    async def list_for_project(self, project: models.Project) -> PullRequestList:
        remote_url = project.remote_url
        remote = project.remote_name or remote_url
        if not remote:
            return PullRequestList(
                source="none",
                warning=(
                    "This project has no git remote, so pull requests cannot be "
                    "listed. Use a range review with explicit refs instead."
                ),
            )

        github = parse_github_remote(remote_url)
        api_error: str | None = None
        if github is not None:
            try:
                prs = await self._list_via_api(*github)
                return PullRequestList(prs=prs, source="api")
            except Exception as exc:  # network/HTTP/parse — degrade, don't fail
                api_error = self._describe_api_error(exc)

        fallback = await self._list_via_ls_remote(project.absolute_path, remote)
        if api_error:
            fallback.warning = (
                f"GitHub API unavailable ({api_error}); fell back to "
                "`git ls-remote refs/pull/*/head`, which only provides PR "
                "numbers and head SHAs — pick a base branch manually."
            )
        elif github is None:
            fallback.warning = (
                "The remote is not a GitHub URL. PRs were discovered via "
                "`git ls-remote refs/pull/*/head`; if the host does not publish "
                "pull refs, use a range review with explicit refs instead."
            )
        if not fallback.prs and fallback.warning is None and fallback.source != "none":
            fallback.warning = "No open pull requests found."
        return fallback

    # ------------------------------------------------------------------
    # resolution (job creation)
    # ------------------------------------------------------------------

    async def resolve_pr(
        self, project: models.Project, pr_number: int
    ) -> PullRequestEntry:
        """Resolve one PR for immutable snapshot capture at queue time."""

        listing = await self.list_for_project(project)
        for pr in listing.prs:
            if pr.number == pr_number:
                return pr
        raise ValidationFailedError(
            f"Pull request #{pr_number} was not found.",
            detail=listing.warning,
            next_action="Refresh the pull request list and pick an open PR.",
        )

    # ------------------------------------------------------------------
    # GitHub API
    # ------------------------------------------------------------------

    async def _list_via_api(self, owner: str, repo: str) -> list[PullRequestEntry]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get(TOKEN_ENV_VAR, "").strip()
        if token:  # never logged, never persisted
            headers["Authorization"] = f"Bearer {token}"
        timeout = httpx.Timeout(15.0)
        owns = self._http_transport is None
        client = httpx.AsyncClient(
            timeout=timeout, transport=self._http_transport, follow_redirects=False
        )
        try:
            response = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
                params={"state": "open", "per_page": "50"},
                headers=headers,
            )
        finally:
            if owns:
                await client.aclose()
        if response.status_code != 200:
            raise GitHubApiError(response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubApiError(response.status_code) from exc
        if not isinstance(payload, list):
            raise GitHubApiError(response.status_code)
        return [self._map_api_pr(item) for item in payload if isinstance(item, dict)]

    @staticmethod
    def _map_api_pr(item: dict) -> PullRequestEntry:
        head = item.get("head") or {}
        base = item.get("base") or {}
        user = item.get("user") or {}
        updated_raw = item.get("updated_at")
        updated: datetime | None = None
        if isinstance(updated_raw, str):
            try:
                updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
            except ValueError:
                updated = None
        return PullRequestEntry(
            number=int(item.get("number") or 0),
            title=item.get("title"),
            head_ref=head.get("ref"),
            head_sha=head.get("sha"),
            base_ref=base.get("ref"),
            base_sha=base.get("sha"),
            author=user.get("login"),
            updated_at=updated,
            source="api",
        )

    @staticmethod
    def _describe_api_error(exc: Exception) -> str:
        if isinstance(exc, GitHubApiError):
            if exc.status_code in {403, 429}:
                return (
                    f"rate limited or forbidden (HTTP {exc.status_code}) — set "
                    f"{TOKEN_ENV_VAR} or try again later"
                )
            if exc.status_code == 404:
                return (
                    "repository not found or private without a token (HTTP 404) — "
                    f"set {TOKEN_ENV_VAR} if the repo is private"
                )
            return f"HTTP {exc.status_code}"
        if isinstance(exc, httpx.TimeoutException):
            return "request timed out"
        return "network error"

    # ------------------------------------------------------------------
    # git fallback
    # ------------------------------------------------------------------

    async def _list_via_ls_remote(self, repo_path: str, remote: str) -> PullRequestList:
        try:
            result = await self.git.run(
                ["ls-remote", remote, "refs/pull/*/head"],
                cwd=repo_path,
                timeout=self.settings.git_timeout_seconds,
            )
        except GitError as exc:
            return PullRequestList(
                source="none",
                warning=f"`git ls-remote` failed: {exc.stderr or exc}",
            )
        if result.returncode != 0:
            return PullRequestList(
                source="none",
                warning=(
                    "`git ls-remote` failed: "
                    f"{result.stderr.strip()[:300] or 'unknown error'}"
                ),
            )
        prs = parse_ls_remote_output(result.stdout)
        return PullRequestList(prs=prs, source="git")


def parse_ls_remote_output(output: str) -> list[PullRequestEntry]:
    """Parse ``git ls-remote <remote> refs/pull/*/head`` output (pure)."""

    prs: list[PullRequestEntry] = []
    for line in output.splitlines():
        match = _LS_REMOTE_RE.match(line.strip())
        if match:
            prs.append(
                PullRequestEntry(
                    number=int(match.group("number")),
                    head_sha=match.group("sha"),
                    source="git",
                )
            )
    prs.sort(key=lambda pr: pr.number)
    return prs


class GitHubApiError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"GitHub API returned HTTP {status_code}")
        self.status_code = status_code

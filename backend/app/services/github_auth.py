"""GitHub CLI account discovery and switching without exposing credentials."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass


GITHUB_HOST = "github.com"


class GitHubAuthError(RuntimeError):
    """A safe, user-actionable GitHub CLI failure."""


@dataclass(slots=True)
class GitHubAccount:
    login: str
    active: bool
    state: str


@dataclass(slots=True)
class GitHubAuthStatus:
    accounts: list[GitHubAccount]
    error: str | None = None


class GitHubAuthService:
    """Uses the user's existing ``gh`` keychain configuration.

    Tokens are deliberately only returned internally for an HTTP request and
    are never serialized, persisted, or included in an exception.
    """

    async def status(self) -> GitHubAuthStatus:
        try:
            stdout = await self._run_gh("auth", "status", "--hostname", GITHUB_HOST, "--json", "hosts")
            payload = json.loads(stdout)
        except (GitHubAuthError, json.JSONDecodeError):
            return GitHubAuthStatus(accounts=[], error="GitHub CLI authentication is unavailable. Run `gh auth login` and try again.")

        raw_accounts = payload.get("hosts", {}).get(GITHUB_HOST, []) if isinstance(payload, dict) else []
        accounts = [
            GitHubAccount(login=item["login"], active=bool(item.get("active")), state=str(item.get("state", "unknown")))
            for item in raw_accounts
            if isinstance(item, dict) and isinstance(item.get("login"), str)
        ]
        return GitHubAuthStatus(accounts=accounts)

    async def switch(self, login: str) -> GitHubAuthStatus:
        status = await self.status()
        known = next((account for account in status.accounts if account.login == login), None)
        if known is None:
            raise GitHubAuthError("That GitHub account is not available in the GitHub CLI keychain.")
        if known.state != "success":
            raise GitHubAuthError("That GitHub account needs to be authenticated again in the GitHub CLI.")
        if not known.active:
            await self._run_gh("auth", "switch", "--hostname", GITHUB_HOST, "--user", login)
        return await self.status()

    async def active_token(self) -> str | None:
        """Return the active CLI token only for in-memory API authentication."""

        try:
            token = await self._run_gh("auth", "token", "--hostname", GITHUB_HOST)
        except GitHubAuthError:
            return None
        return token.strip() or None

    async def _run_gh(self, *args: str) -> str:
        executable = shutil.which("gh") or shutil.which("gh.exe")
        if executable is None:
            raise GitHubAuthError("GitHub CLI is not installed.")
        env = dict(os.environ)
        env["GH_PROMPT_DISABLED"] = "1"
        try:
            proc = await asyncio.create_subprocess_exec(
                executable, *args, env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        except (OSError, TimeoutError) as exc:
            raise GitHubAuthError("GitHub CLI could not be contacted.") from exc
        if proc.returncode != 0:
            raise GitHubAuthError("GitHub CLI authentication command failed.")
        return stdout.decode("utf-8", errors="replace")

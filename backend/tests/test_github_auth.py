"""GitHub CLI keychain account discovery and switching."""

from __future__ import annotations

import pytest

from app.services.github_auth import GitHubAuthError, GitHubAuthService


class FakeGitHubAuth(GitHubAuthService):
    def __init__(self) -> None:
        self.active = "account-a"
        self.calls: list[tuple[str, ...]] = []

    async def _run_gh(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("auth", "status"):
            return (
                '{"hosts":{"github.com":['
                f'{{"login":"account-a","active":{str(self.active == "account-a").lower()},"state":"success"}},'
                f'{{"login":"account-b","active":{str(self.active == "account-b").lower()},"state":"success"}}'
                ']}}'
            )
        if args[:2] == ("auth", "switch"):
            self.active = args[-1]
            return ""
        if args[:2] == ("auth", "token"):
            return "not-exposed-token\n"
        raise AssertionError(args)


async def test_status_lists_active_and_keychain_accounts() -> None:
    auth = FakeGitHubAuth()
    status = await auth.status()

    assert status.error is None
    assert [(item.login, item.active) for item in status.accounts] == [
        ("account-a", True),
        ("account-b", False),
    ]


async def test_switch_changes_active_account() -> None:
    auth = FakeGitHubAuth()
    status = await auth.switch("account-b")

    assert [(item.login, item.active) for item in status.accounts] == [
        ("account-a", False),
        ("account-b", True),
    ]
    assert ("auth", "switch", "--hostname", "github.com", "--user", "account-b") in auth.calls


async def test_switch_rejects_an_unknown_account() -> None:
    with pytest.raises(GitHubAuthError, match="not available"):
        await FakeGitHubAuth().switch("missing")


async def test_active_token_is_internal_only() -> None:
    assert await FakeGitHubAuth().active_token() == "not-exposed-token"

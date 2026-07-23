"""Security primitives: path safety, git ref validation, argument parsing,
redaction helpers, and CSRF tokens (SPEC §27, §38).

Nothing in this module executes commands; it produces validated values that
callers pass to subprocess argv arrays.
"""

from __future__ import annotations

import re
import secrets as _secrets
import shlex
from pathlib import Path

from app.core.logging import REDACTED, redact_text

# ---------------------------------------------------------------------------
# Path security
# ---------------------------------------------------------------------------


class PathSecurityError(ValueError):
    """Raised when a path fails a security check."""


def normalize_path(raw: str | Path, *, must_exist: bool = False) -> Path:
    """Expand ``~``, resolve symlinks/relatives, reject null bytes.

    ``must_exist=False`` still resolves as much of the path as exists so
    authorization checks always see a canonical, symlink-free absolute path.
    """

    text = str(raw)
    if "\x00" in text:
        raise PathSecurityError("path contains a null byte")
    path = Path(text).expanduser()
    try:
        resolved = path.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathSecurityError(f"path does not exist: {text}") from exc
    except (OSError, RuntimeError) as exc:
        raise PathSecurityError(f"cannot resolve path {text!r}: {exc}") from exc
    return resolved


def is_within(path: Path, root: Path) -> bool:
    """True when ``path`` equals ``root`` or lives underneath it."""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def enforce_allowed_roots(path: Path, allowed_roots: list[Path]) -> Path:
    """Reject ``path`` when restrictions apply and it escapes every root.

    An empty ``allowed_roots`` list means "unrestricted" (the default for a
    local-first tool); callers gate on ``path_restrictions_enabled``.
    """

    if not allowed_roots:
        return path
    normalized_roots = [normalize_path(r) for r in allowed_roots]
    if any(is_within(path, root) for root in normalized_roots):
        return path
    raise PathSecurityError(
        f"path {path} is outside the configured allowed roots"
    )


# ---------------------------------------------------------------------------
# Git ref validation
# ---------------------------------------------------------------------------

_MAX_REF_LENGTH = 256


class RefValidationError(ValueError):
    pass


def validate_git_ref(ref: str) -> str:
    """Validate a user-supplied git ref.

    Rejects empty refs, leading ``-`` (option injection), whitespace/control
    characters, ``..`` sequences, and refs over the length limit. The ref is
    otherwise passed through verbatim; callers must still place it after
    ``--end-of-options`` and verify it with ``git rev-parse --verify``.
    """

    if not ref or not ref.strip():
        raise RefValidationError("git ref is empty")
    if len(ref) > _MAX_REF_LENGTH:
        raise RefValidationError("git ref exceeds maximum length")
    if ref != ref.strip():
        raise RefValidationError("git ref has leading/trailing whitespace")
    if ref.startswith("-"):
        raise RefValidationError("git ref must not start with '-'")
    if "\x00" in ref:
        raise RefValidationError("git ref contains a null byte")
    if re.search(r"[\x00-\x1f\x7f]", ref):
        raise RefValidationError("git ref contains control characters")
    if ".." in ref:
        raise RefValidationError("git ref must not contain '..'")
    if re.search(r"[~^:?*\[\]\\ ]", ref):
        raise RefValidationError("git ref contains illegal characters")
    if ref.endswith("/") or ref.endswith(".") or ref.endswith(".lock"):
        raise RefValidationError("git ref has an illegal suffix")
    if ref.startswith("/") or ref.startswith("."):
        raise RefValidationError("git ref has an illegal prefix")
    if "@{" in ref:
        raise RefValidationError("git ref must not contain '@{'")
    return ref


def end_of_options_args(*refs: str) -> list[str]:
    """Return ``[--end-of-options, ref...]`` after validating each ref."""

    return ["--end-of-options", *(validate_git_ref(r) for r in refs)]


# ---------------------------------------------------------------------------
# Additional-arguments parsing (SPEC §8)
# ---------------------------------------------------------------------------

#: Shell metacharacters that must never appear in expert additional args.
#: argv arrays are not shell-interpreted, but rejecting these prevents users
#: from believing shell semantics apply and blocks accidental control ops.
SHELL_METACHARACTERS = set(";&|><`$\\\n\r")

#: Flags the control plane always owns; users may not override them via the
#: additional-arguments field.
CONTROL_PLANE_OWNED_FLAGS: frozenset[str] = frozenset(
    {
        "--repo",
        "--from",
        "--to",
        "--commit",
        "-c",
        "--format",
        "-f",
        "--audience",
        "--resume",
        "--preview",
        "-p",
        "--background",
        "-b",
        "--background-file",
        "-B",
        "--model",
        "--concurrency",
        "--timeout",
        "--max-tools",
        "--max-git-procs",
        "--rule",
        "--exclude",
        "--tools",
        # planning patch flags (Stage 4) — profile-owned
        "--plan-mode",
        "--plan-threshold",
        "--max-tokens",
        "--template",
    }
)


class AdditionalArgsError(ValueError):
    pass


def parse_additional_arguments(raw: str | None) -> list[str]:
    """Split an expert additional-arguments string into a safe argv list.

    Rejects empty tokens, shell metacharacters, control characters, and any
    flag owned by the control plane. Returns ``[]`` for blank input.
    """

    if not raw or not raw.strip():
        return []
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise AdditionalArgsError(f"cannot parse additional arguments: {exc}") from exc
    for token in tokens:
        if not token:
            raise AdditionalArgsError("empty argument token")
        if any(ch in SHELL_METACHARACTERS or ord(ch) < 0x20 for ch in token):
            raise AdditionalArgsError(
                f"argument {token!r} contains shell metacharacters or control characters"
            )
        flag = token.split("=", 1)[0]
        if flag in CONTROL_PLANE_OWNED_FLAGS:
            raise AdditionalArgsError(
                f"argument {token!r} conflicts with a control-plane-owned flag"
            )
    return tokens


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

#: Environment variable names whose values are secrets and must be redacted
#: in previews, logs, metadata.json, and exports.
SECRET_ENV_KEYS: frozenset[str] = frozenset(
    {
        "OCR_LLM_TOKEN",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    }
)


def redact_environment(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` with secret values replaced for display."""

    return {
        key: (REDACTED if key in SECRET_ENV_KEYS and value else value)
        for key, value in env.items()
    }


__all__ = [
    "AdditionalArgsError",
    "CONTROL_PLANE_OWNED_FLAGS",
    "PathSecurityError",
    "REDACTED",
    "RefValidationError",
    "SECRET_ENV_KEYS",
    "SHELL_METACHARACTERS",
    "end_of_options_args",
    "enforce_allowed_roots",
    "is_within",
    "normalize_path",
    "parse_additional_arguments",
    "redact_environment",
    "redact_text",
    "validate_git_ref",
    "generate_csrf_token",
]


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def generate_csrf_token() -> str:
    """Anti-CSRF token for state-changing local requests (SPEC §27)."""

    return _secrets.token_urlsafe(32)

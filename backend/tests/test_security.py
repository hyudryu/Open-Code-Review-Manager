"""Path normalization, ref validation, additional-args, redaction, CSRF."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.security import (
    AdditionalArgsError,
    PathSecurityError,
    RefValidationError,
    end_of_options_args,
    enforce_allowed_roots,
    generate_csrf_token,
    is_within,
    normalize_path,
    parse_additional_arguments,
    redact_environment,
    validate_git_ref,
)

# --- path normalization -----------------------------------------------------


def test_normalize_rejects_null_bytes() -> None:
    with pytest.raises(PathSecurityError):
        normalize_path("C:/foo/\x00bar")


def test_normalize_resolves_relative(tmp_path: Path) -> None:
    target = tmp_path / "a" / ".." / "b"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    assert normalize_path(target) == (tmp_path / "b").resolve()


def test_normalize_expands_user() -> None:
    home = Path.home().resolve()
    assert normalize_path("~/x").parent == home


def test_normalize_missing_strict(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityError):
        normalize_path(tmp_path / "nope", must_exist=True)


def test_enforce_allowed_roots_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sneaky = root / ".." / "outside"
    with pytest.raises(PathSecurityError):
        enforce_allowed_roots(normalize_path(sneaky), [root])


def test_enforce_allowed_roots_accepts_inside(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    inner = root / "proj"
    inner.mkdir(parents=True)
    assert enforce_allowed_roots(inner, [root]) == inner.resolve()


def test_symlink_resolved_before_check(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    assert normalize_path(link) == real.resolve()
    assert is_within(normalize_path(link / "."), real)


# --- git ref validation ------------------------------------------------------


@pytest.mark.parametrize("ref", ["main", "feature/auth-2", "v1.2.3", "HEAD",
                                 "a" * 40, "refs/heads/main"])
def test_valid_refs(ref: str) -> None:
    assert validate_git_ref(ref) == ref


@pytest.mark.parametrize(
    "ref",
    [
        "--upload-pack=evil",   # option injection
        "-c",
        "",
        "   ",
        "..",
        "main..evil",
        "feature branch",        # whitespace
        "ref~1",                 # tilde
        "ref^{commit}",          # caret
        "bad:ref",
        "wild*card",
        "quest?ion",
        "back\\slash",
        "trailing/",
        ".leading",
        "trailing.lock",
        "has@{0}",
        "ctl\x01char",
        "x" * 300,
    ],
)
def test_invalid_refs(ref: str) -> None:
    with pytest.raises(RefValidationError):
        validate_git_ref(ref)


def test_end_of_options_args() -> None:
    args = end_of_options_args("main", "v1.0")
    assert args == ["--end-of-options", "main", "v1.0"]
    with pytest.raises(RefValidationError):
        end_of_options_args("-rf")


# --- additional arguments parsing -------------------------------------------


def test_parse_additional_args_basic() -> None:
    assert parse_additional_arguments("  ") == []
    assert parse_additional_arguments("--verbose --level 3") == [
        "--verbose",
        "--level",
        "3",
    ]


def test_parse_additional_args_quotes() -> None:
    assert parse_additional_arguments('--note "hello world"') == [
        "--note",
        "hello world",
    ]


@pytest.mark.parametrize("raw", ["--foo; rm -rf /", "a && b", "x | y", "in > out",
                                 "a`b`c", "$(whoami)"])
def test_parse_additional_args_rejects_metacharacters(raw: str) -> None:
    with pytest.raises(AdditionalArgsError):
        parse_additional_arguments(raw)


def test_parse_additional_args_rejects_backslash_quoted() -> None:
    # Quoting preserves a literal backslash, which is still rejected.
    with pytest.raises(AdditionalArgsError):
        parse_additional_arguments('"back\\slash"')


@pytest.mark.parametrize(
    "raw",
    ["--format text", "-f json", "--audience human", "--repo /tmp/x",
     "--from main", "--commit abc", "--format=json", "--resume s1",
     "--model gpt", "--plan-mode always", "--template /t"],
)
def test_parse_additional_args_rejects_owned_flags(raw: str) -> None:
    with pytest.raises(AdditionalArgsError):
        parse_additional_arguments(raw)


# --- redaction / csrf ---------------------------------------------------------


def test_redact_environment() -> None:
    env = {"OCR_LLM_TOKEN": "sk-secret", "OCR_LLM_URL": "http://x", "EMPTY": ""}
    redacted = redact_environment(env)
    assert redacted["OCR_LLM_TOKEN"] == "***REDACTED***"
    assert redacted["OCR_LLM_URL"] == "http://x"
    assert redacted["EMPTY"] == ""


def test_csrf_tokens_unique() -> None:
    a, b = generate_csrf_token(), generate_csrf_token()
    assert a != b and len(a) >= 32

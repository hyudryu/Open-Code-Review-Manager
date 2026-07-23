"""SecretStore: references, env resolution, in-memory fallback, redaction."""

from __future__ import annotations

import pytest

from app.core.logging import redact_text, redactor
from app.core.secrets import (
    EnvSecretStore,
    InMemorySecretStore,
    SecretStoreError,
    is_secret_reference,
    make_env_reference,
    make_keyring_reference,
)


async def test_inmemory_roundtrip() -> None:
    store = InMemorySecretStore()
    ref = await store.set("provider/openai", "sk-test-12345")
    assert ref == make_keyring_reference("provider/openai")
    assert is_secret_reference(ref)
    assert await store.get(ref) == "sk-test-12345"
    await store.delete(ref)
    assert await store.get(ref) is None


async def test_env_reference_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TEST_TOKEN", "env-secret-999")
    store = EnvSecretStore()
    ref = make_env_reference("MY_TEST_TOKEN")
    assert is_secret_reference(ref)
    assert await store.get(ref) == "env-secret-999"
    assert await store.get(make_env_reference("MISSING_VAR_XYZ")) is None
    with pytest.raises(SecretStoreError):
        await store.set("x", "y")


async def test_inmemory_resolves_env_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALLBACK_TOKEN", "fallback-secret")
    store = InMemorySecretStore()
    assert await store.get("env:FALLBACK_TOKEN") == "fallback-secret"


async def test_combined_store_gets_redacted_from_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemorySecretStore()
    ref = await store.set("p", "supersecret-value-123")
    value = await store.get(ref)
    assert value == "supersecret-value-123"
    # Registered with the global redactor.
    assert "supersecret-value-123" not in redact_text("token=supersecret-value-123 ok")
    assert "***REDACTED***" in redact_text("leak: supersecret-value-123")


def test_non_reference_strings() -> None:
    assert not is_secret_reference("plain-string")
    assert not is_secret_reference(None)
    assert not is_secret_reference("")


def test_redact_text_key_value_pattern() -> None:
    text = "OCR_LLM_TOKEN=abc123xyz other=ok"
    redacted = redact_text(text)
    assert "abc123xyz" not in redacted
    assert "other=ok" in redacted


def test_redactor_ignores_short_values() -> None:
    redactor.register("abc")  # too short; would over-redact
    assert redactor.redact("abc def") == "abc def"

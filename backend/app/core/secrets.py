"""Credential storage abstraction (SPEC §9 "Credential Storage", §38 rule 7).

Database rows only ever store a *reference* string:

- ``keyring:<name>`` — value stored in the OS credential store
  (Windows Credential Manager / macOS Keychain / Secret Service) under the
  service name ``ocr-control-center``.
- ``env:<VAR_NAME>`` — value read from a process environment variable
  (for headless deployments).

The in-memory fallback store exists for tests and for hosts without a working
keyring backend; it logs a loud warning because it is not durable.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from app.core.logging import get_logger, redactor

SERVICE_NAME = "ocr-control-center"

KEYRING_PREFIX = "keyring:"
ENV_PREFIX = "env:"

logger = get_logger(__name__)


def make_keyring_reference(name: str) -> str:
    return f"{KEYRING_PREFIX}{name}"


def make_env_reference(var_name: str) -> str:
    return f"{ENV_PREFIX}{var_name}"


def is_secret_reference(value: str | None) -> bool:
    return bool(value) and (
        value.startswith(KEYRING_PREFIX) or value.startswith(ENV_PREFIX)
    )


class SecretStoreError(RuntimeError):
    pass


class SecretStore(ABC):
    """Resolves and persists credential values behind references."""

    @abstractmethod
    async def set(self, name: str, value: str) -> str:
        """Store ``value`` under ``name`` and return its reference string."""

    @abstractmethod
    async def get(self, reference: str) -> str | None:
        """Resolve a reference to its secret value (``None`` if missing)."""

    @abstractmethod
    async def delete(self, reference: str) -> None:
        """Remove the stored secret backing ``reference`` (best effort)."""


class KeyringSecretStore(SecretStore):
    """OS-native credential storage via the ``keyring`` package."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service_name = service_name

    def _keyring(self):
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - dependency present
            raise SecretStoreError("keyring package is not available") from exc
        return keyring

    async def set(self, name: str, value: str) -> str:
        try:
            self._keyring().set_password(self._service_name, name, value)
        except Exception as exc:
            raise SecretStoreError(
                f"failed to store credential in OS keyring: {type(exc).__name__}"
            ) from exc
        redactor.register(value)
        return make_keyring_reference(name)

    async def get(self, reference: str) -> str | None:
        if not reference.startswith(KEYRING_PREFIX):
            raise SecretStoreError(f"not a keyring reference: {reference!r}")
        name = reference[len(KEYRING_PREFIX):]
        try:
            value = self._keyring().get_password(self._service_name, name)
        except Exception as exc:
            raise SecretStoreError(
                f"failed to read credential from OS keyring: {type(exc).__name__}"
            ) from exc
        redactor.register(value)
        return value

    async def delete(self, reference: str) -> None:
        if not reference.startswith(KEYRING_PREFIX):
            return
        name = reference[len(KEYRING_PREFIX):]
        try:
            self._keyring().delete_password(self._service_name, name)
        except Exception:
            # Deletion is best effort; the entry may not exist.
            pass


class EnvSecretStore(SecretStore):
    """Read-only store resolving ``env:VAR`` references from the environment."""

    async def set(self, name: str, value: str) -> str:  # pragma: no cover
        raise SecretStoreError(
            "env secret store is read-only; set the environment variable instead"
        )

    async def get(self, reference: str) -> str | None:
        if not reference.startswith(ENV_PREFIX):
            raise SecretStoreError(f"not an env reference: {reference!r}")
        value = os.environ.get(reference[len(ENV_PREFIX):])
        redactor.register(value)
        return value

    async def delete(self, reference: str) -> None:
        return  # nothing to delete


class InMemorySecretStore(SecretStore):
    """Non-durable fallback for tests and hosts without a keyring backend."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        logger.warning(
            "using_in_memory_secret_store",
            detail="credentials will NOT persist; configure an OS keyring or env: references",
        )

    async def set(self, name: str, value: str) -> str:
        self._values[name] = value
        redactor.register(value)
        return make_keyring_reference(name)

    async def get(self, reference: str) -> str | None:
        if reference.startswith(KEYRING_PREFIX):
            value = self._values.get(reference[len(KEYRING_PREFIX):])
        elif reference.startswith(ENV_PREFIX):
            value = os.environ.get(reference[len(ENV_PREFIX):])
        else:
            value = None
        redactor.register(value)
        return value

    async def delete(self, reference: str) -> None:
        if reference.startswith(KEYRING_PREFIX):
            self._values.pop(reference[len(KEYRING_PREFIX):], None)


class CompositeSecretStore(SecretStore):
    """Dispatches by reference prefix; ``set`` always writes to keyring."""

    def __init__(self, keyring_store: SecretStore | None = None) -> None:
        self._keyring = keyring_store or KeyringSecretStore()
        self._env = EnvSecretStore()

    async def set(self, name: str, value: str) -> str:
        return await self._keyring.set(name, value)

    async def get(self, reference: str) -> str | None:
        if reference.startswith(ENV_PREFIX):
            return await self._env.get(reference)
        return await self._keyring.get(reference)

    async def delete(self, reference: str) -> None:
        if reference.startswith(KEYRING_PREFIX):
            await self._keyring.delete(reference)


_default_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    """Process-wide store. Falls back to in-memory if keyring is unusable."""

    global _default_store
    if _default_store is None:
        try:
            store = CompositeSecretStore()
            # Probe the backend; some Linux hosts have no Secret Service.
            import keyring

            keyring.get_keyring()
            _default_store = store
        except Exception:
            _default_store = InMemorySecretStore()
    return _default_store


def set_secret_store(store: SecretStore) -> None:
    """Override the process-wide store (used by tests)."""

    global _default_store
    _default_store = store

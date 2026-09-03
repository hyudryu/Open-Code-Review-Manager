"""OCR self-update: runs ``npm i -g @alibaba-group/open-code-review``.

The OCR CLI is a globally installed npm package, so "update" means re-running
its npm install in place and force re-probing the adapter afterwards (npm
replaces the shim and package files at the same paths, so the cached binary
path stays valid).

npm's ``.cmd`` shims cannot be exec'd directly on Windows, so the shim is
resolved to its underlying ``npm-cli.js`` (same unwrapping the adapter uses
for the ``ocr`` binary) with a ``cmd /c`` fallback for unrecognized shims.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger, redact_text
from app.ocr.adapter import OCRAdapter

logger = get_logger(__name__)

OCR_NPM_PACKAGE = "@alibaba-group/open-code-review"
INSTALL_COMMAND = f"npm i -g {OCR_NPM_PACKAGE}"

_IS_WINDOWS = os.name == "nt"


class OCRUpdateError(RuntimeError):
    """Raised when the npm install fails or cannot be attempted."""


async def latest_npm_version() -> str | None:
    """Latest published version of the OCR package from the npm registry.

    Returns ``None`` when the registry cannot be reached — callers treat that
    as "unknown", never as an update failure.
    """

    from httpx import AsyncClient, Timeout

    url = f"https://registry.npmjs.org/{OCR_NPM_PACKAGE}/latest"
    try:
        async with AsyncClient(timeout=Timeout(5.0)) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json().get("version")
    except Exception as exc:  # noqa: BLE001 — registry reachability is best-effort
        logger.warning("npm_registry_lookup_failed", error=str(exc))
        return None


def npm_install_argv() -> list[str]:
    """Argv array that runs ``npm install -g <package>`` on this platform.

    Raises :class:`OCRUpdateError` when npm is not on PATH.
    """

    npm = shutil.which("npm")
    if not npm:
        raise OCRUpdateError(
            "npm was not found on PATH. Install Node.js, then retry the update."
        )
    install = ["install", "-g", OCR_NPM_PACKAGE]
    if _IS_WINDOWS:
        # npm.CMD cannot be exec'd directly; unwrap the standard npm shim to
        # its npm-cli.js (long-lived node process, no cmd.exe wrapper).
        unwrapped = OCRAdapter._windows_npm_shim_argv(npm)
        if unwrapped:
            return [*unwrapped, *install]
        return ["cmd", "/c", npm, *install]
    return [npm, *install]


class OCRUpdateService:
    """Single-flight runner for the npm global install."""

    def __init__(self, adapter: OCRAdapter) -> None:
        self._adapter = adapter
        self._lock = asyncio.Lock()

    @property
    def in_progress(self) -> bool:
        return self._lock.locked()

    async def update(self) -> dict[str, Any]:
        """Install the latest OCR release and re-probe the binary.

        Returns a summary dict with ``previous_version``,
        ``current_version``, ``latest_version``, and ``update_available``.
        Raises :class:`OCRUpdateError` when the install fails.
        """

        async with self._lock:
            settings = get_settings()
            status_before = await self._adapter.detect()
            previous_version = status_before.version

            argv = npm_install_argv()
            logger.info("ocr_update_started", argv=argv[:-1])
            start = time.monotonic()
            rc, stdout, stderr = await self._run_install(
                argv, timeout=settings.ocr_update_timeout_seconds
            )
            elapsed = time.monotonic() - start
            if rc != 0:
                detail = redact_text((stderr or stdout).strip())[-800:]
                raise OCRUpdateError(
                    detail or f"npm install exited with code {rc}"
                )

            status_after = await self._adapter.detect(force=True)
            current_version = status_after.version
            latest = await latest_npm_version()
            from app.ocr.version import is_newer

            update_available = bool(
                current_version and latest and is_newer(current_version, latest)
            )
            logger.info(
                "ocr_update_finished",
                previous_version=previous_version,
                current_version=current_version,
                elapsed_seconds=round(elapsed, 1),
            )
            return {
                "ok": True,
                "previous_version": previous_version,
                "current_version": current_version,
                "latest_version": latest,
                "update_available": update_available,
                "message": (
                    f"Updated OpenCodeReview to {current_version}"
                    if current_version
                    else "npm install completed"
                ),
            }

    async def _run_install(
        self, argv: list[str], *, timeout: float
    ) -> tuple[int, str, str]:
        """Run the npm install argv array with a timeout; never raises."""

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return (-1, "", f"{type(exc).__name__}: {exc}")
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return (-1, "", f"npm install timed out after {timeout:.0f}s")
        return (
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
        )

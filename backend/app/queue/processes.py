"""Cross-platform process-tree termination (SPEC §12 Cancellation, §27).

POSIX jobs are spawned with ``start_new_session=True`` so the whole process
group can be signalled; Windows uses ``taskkill /T`` (argv array, no shell).
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from app.core.logging import get_logger

logger = get_logger(__name__)

IS_WINDOWS = sys.platform.startswith("win")


async def terminate_process_tree(
    proc: asyncio.subprocess.Process, *, grace_seconds: float
) -> None:
    """Gracefully terminate then force-kill a subprocess tree.

    1. Graceful signal (SIGTERM to the group / ``taskkill /T`` on Windows).
    2. Wait up to ``grace_seconds``.
    3. Force kill (SIGKILL to the group / ``taskkill /F /T``).
    """

    if proc.returncode is not None:
        return
    pid = proc.pid

    if IS_WINDOWS:
        # taskkill without /F sends WM_CLOSE; console processes may ignore it,
        # so the graceful phase is short and we always escalate.
        await _taskkill(pid, force=False)
    else:
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except ProcessLookupError:
                return

    try:
        await asyncio.wait_for(proc.wait(), timeout=max(grace_seconds, 0.1))
        return
    except TimeoutError:
        pass

    logger.warning("process_grace_expired_force_killing", pid=pid)
    if IS_WINDOWS:
        await _taskkill(pid, force=True)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                return
    try:
        await asyncio.wait_for(proc.wait(), timeout=10)
    except TimeoutError:  # pragma: no cover - extremely unusual
        logger.error("process_refused_to_die", pid=pid)


async def _taskkill(pid: int, *, force: bool) -> None:
    args = ["taskkill", "/PID", str(pid), "/T"] + (["/F"] if force else [])
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
    except (OSError, TimeoutError) as exc:  # pragma: no cover - defensive
        logger.warning("taskkill_failed", pid=pid, error=str(exc))

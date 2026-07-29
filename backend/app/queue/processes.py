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


def pid_alive(pid: int | None) -> bool:
    """Return whether *pid* still identifies a running process."""

    if pid is None or pid <= 0:
        return False
    if IS_WINDOWS:
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int, *, kernel32=None) -> bool:
    """Check liveness with Win32 handles instead of unsupported signal 0."""

    import ctypes
    from ctypes import wintypes

    injected = kernel32 is not None
    if kernel32 is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    open_process = kernel32.OpenProcess
    wait_for_single_object = kernel32.WaitForSingleObject
    close_handle = kernel32.CloseHandle
    if not injected:
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait_for_single_object.restype = wintypes.DWORD
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

    synchronize = 0x00100000
    handle = open_process(synchronize, False, pid)
    if not handle:
        error = kernel32.last_error if injected else ctypes.get_last_error()
        if error in {87, 1168}:  # invalid parameter / not found
            return False
        # Access denied (and unknown inspection failures) must not let the
        # reaper silently kill a potentially healthy review.
        return True

    try:
        status = wait_for_single_object(handle, 0)
        if status == 0x00000102:  # WAIT_TIMEOUT: process has not exited
            return True
        if status == 0x00000000:  # WAIT_OBJECT_0: process is signalled/exited
            return False
        return True  # WAIT_FAILED or unexpected inspection result
    finally:
        close_handle(handle)


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

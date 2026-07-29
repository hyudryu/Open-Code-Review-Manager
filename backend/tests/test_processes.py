"""Cross-platform process liveness and data-directory ownership tests."""

from __future__ import annotations

import os

import pytest

import app.queue.processes as processes
from app.core.instance_lock import DataDirectoryLock, InstanceAlreadyRunningError


class _FakeKernel32:
    def __init__(self, *, handle=123, wait_status=0x102, last_error=0) -> None:
        self.handle = handle
        self.wait_status = wait_status
        self.last_error = last_error
        self.closed: list[int] = []

    def OpenProcess(self, _access, _inherit, _pid):
        return self.handle

    def WaitForSingleObject(self, _handle, _milliseconds):
        return self.wait_status

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.mark.parametrize(
    ("wait_status", "expected"),
    [(0x102, True), (0x00000000, False), (0xFFFFFFFF, True)],
)
def test_windows_pid_alive_uses_process_wait_state(wait_status, expected) -> None:
    kernel32 = _FakeKernel32(wait_status=wait_status)
    assert processes._windows_pid_alive(42, kernel32=kernel32) is expected
    assert kernel32.closed == [123]


@pytest.mark.parametrize(
    ("last_error", "expected"),
    [(87, False), (1168, False), (5, True), (999, True)],
)
def test_windows_pid_alive_handles_open_process_errors(last_error, expected) -> None:
    kernel32 = _FakeKernel32(handle=0, last_error=last_error)
    assert processes._windows_pid_alive(42, kernel32=kernel32) is expected
    assert kernel32.closed == []


@pytest.mark.skipif(os.name != "nt", reason="requires Win32 process handles")
def test_windows_pid_alive_integration() -> None:
    assert processes._windows_pid_alive(os.getpid()) is True
    assert processes._windows_pid_alive(2_147_483_647) is False


def test_data_directory_lock_rejects_second_backend(tmp_path) -> None:
    first = DataDirectoryLock(tmp_path)
    second = DataDirectoryLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()

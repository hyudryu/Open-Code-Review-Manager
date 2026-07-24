"""Server-side blocking wait for job terminal states (SPEC §13, §14).

Shared by the MCP ``ocr_get_job`` tool and ``GET /api/v1/jobs/{id}`` so
agents and HTTP clients can long-poll server-side instead of running a
client polling loop. Fully async: subscribes to the in-process event bus,
wakes on terminal events, and re-checks the database on a periodic safety
interval. No DB session, transaction, or connection is held while waiting —
a fresh short session re-reads the status after each wakeup.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.db import models
from app.db.session import get_session_factory
from app.queue.bus import get_event_bus
from app.queue.service import TERMINAL_STATUSES

logger = get_logger(__name__)

#: Bounds for caller-supplied timeouts (seconds).
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 300

#: Safety-net re-check interval in case a bus event is missed (seconds).
RECHECK_INTERVAL_SECONDS = 5.0

#: Event types that always imply a terminal job state (SPEC §14).
_TERMINAL_EVENT_TYPES = frozenset({"job.completed", "job.failed", "job.cancelled"})


def clamp_timeout(timeout_seconds: int | None) -> int:
    """Clamp a caller-supplied timeout into the supported range."""

    if timeout_seconds is None:
        return DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(MAX_TIMEOUT_SECONDS, int(timeout_seconds)))


def _is_terminal_event(event: dict[str, Any]) -> bool:
    event_type = event.get("type")
    if event_type in _TERMINAL_EVENT_TYPES:
        return True
    if event_type == "job.status":
        payload = event.get("payload") or {}
        return payload.get("to") in TERMINAL_STATUSES
    return False


async def _current_status(job_id: str) -> str | None:
    """Read the job's status in a fresh short session (None = job gone)."""

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(models.ReviewJob, job_id)
        return job.status if job is not None else None


async def wait_for_job_terminal(
    job_id: str, timeout_seconds: int | None = None
) -> bool:
    """Block (async) until ``job_id`` reaches a terminal status or times out.

    Returns ``True`` when the job is terminal, ``False`` when the timeout
    elapsed (or the job disappeared). Already-terminal jobs return
    immediately. Cancellation of the caller's task cleanly unsubscribes
    from the event bus — no leaked subscriptions.
    """

    timeout = clamp_timeout(timeout_seconds)
    status = await _current_status(job_id)
    if status is None:
        return False
    if status in TERMINAL_STATUSES:
        return True

    bus = get_event_bus()
    queue: asyncio.Queue = bus.subscribe(job_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=min(RECHECK_INTERVAL_SECONDS, remaining)
                )
            except TimeoutError:
                # Safety-net wakeup: re-check the DB in case an event was
                # missed; cheap insurance, still fully async.
                pass
            else:
                # Non-terminal events (progress, log lines) don't justify a
                # DB hit — go back to sleep.
                if not _is_terminal_event(event):
                    continue
            status = await _current_status(job_id)
            if status is None:
                return False
            if status in TERMINAL_STATUSES:
                return True
    finally:
        bus.unsubscribe(queue, job_id)

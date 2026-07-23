"""In-process async event bus for SSE fan-out (SPEC §14).

Events are *persisted first* as JobEvent rows, then published here so live
subscribers receive them. Reconnecting clients replay from the database via
``Last-Event-ID`` and only rely on the bus for events after connect.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

#: Bounded per-subscriber buffer (SPEC §28 "Bounded in-memory event buffers").
MAX_QUEUE_SIZE = 256


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._wildcard: set[asyncio.Queue] = set()

    def subscribe(self, job_id: str | None = None) -> asyncio.Queue:
        """Subscribe to one job's events (or all jobs when ``job_id=None``)."""

        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        if job_id is None:
            self._wildcard.add(queue)
        else:
            self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, job_id: str | None = None) -> None:
        if job_id is None:
            self._wildcard.discard(queue)
            for queues in self._subscribers.values():
                queues.discard(queue)
        else:
            queues = self._subscribers.get(job_id)
            if queues is not None:
                queues.discard(queue)
                if not queues:
                    self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, event: dict[str, Any]) -> None:
        """Fan out an event; drops for slow subscribers rather than blocking."""

        targets = set(self._subscribers.get(job_id, ())) | self._wildcard
        for queue in targets:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("event_bus_subscriber_lagged", job_id=job_id)


#: Process-wide bus (replaced by tests via ``set_event_bus``).
_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


def set_event_bus(bus: EventBus) -> None:
    global _bus
    _bus = bus

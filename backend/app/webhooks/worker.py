"""Webhook delivery worker: asyncio task draining due deliveries."""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.webhooks.service import WebhookService

logger = get_logger(__name__)


class WebhookWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(4)

    def notify(self) -> None:
        self._wake.set()

    async def run_once(self) -> int:
        """Deliver all currently-due deliveries (deterministic for tests)."""

        factory = get_session_factory()
        delivered = 0
        while True:
            async with factory() as session:
                service = WebhookService(session, settings=self.settings)
                due = await service.due_deliveries(limit=5)
                if not due:
                    return delivered
                for delivery in due:
                    try:
                        await service.deliver(delivery)
                        delivered += 1
                    except Exception:
                        logger.exception(
                            "webhook_delivery_error", delivery_id=delivery.id
                        )
                await session.commit()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("webhook_worker_error")
            self._wake.clear()
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=max(self.settings.webhook_poll_seconds, 0.5),
                )
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()
            self._task = None


_current: WebhookWorker | None = None


def set_current_webhook_worker(worker: WebhookWorker | None) -> None:
    global _current
    _current = worker


def get_current_webhook_worker() -> WebhookWorker | None:
    return _current

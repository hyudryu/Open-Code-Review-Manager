"""QueueWorker: asyncio dispatcher enforcing concurrency limits (SPEC §12).

One long-lived task scans for runnable queued jobs and spawns
:meth:`JobRunner.run_job` tasks while respecting the global worker count,
per-project limits, and per-provider limits. ``drain``/``run_once`` are
public so tests can drive the worker deterministically.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.secrets import SecretStore
from app.db import models
from app.db.session import get_session_factory
from app.git.service import GitService
from app.ocr.adapter import OCRAdapter
from app.queue.runner import JobRunner
from app.queue.service import QueueService, WebhookDispatcher

logger = get_logger(__name__)


class QueueWorker:
    def __init__(
        self,
        settings: Settings,
        git: GitService,
        adapter: OCRAdapter,
        secrets: SecretStore,
        *,
        webhook_dispatcher: WebhookDispatcher | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        self.settings = settings
        self.runner = JobRunner(
            settings, git, adapter, secrets, webhook_dispatcher=webhook_dispatcher
        )
        self._git = git
        self._adapter = adapter
        self._secrets = secrets
        self._webhook_dispatcher = webhook_dispatcher
        self.poll_seconds = poll_seconds
        self._tasks: dict[str, asyncio.Task] = {}
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # limits
    # ------------------------------------------------------------------

    async def _limits(self) -> tuple[int, int, int]:
        """(global, per_project, per_provider) — AppSettings override config."""

        factory = get_session_factory()
        async with factory() as session:
            keys = [
                "queue.global_concurrency",
                "queue.per_project_concurrency",
                "queue.per_provider_concurrency",
            ]
            result = await session.execute(
                select(models.AppSetting).where(models.AppSetting.key.in_(keys))
            )
            values = {row.key: row.value_json for row in result.scalars()}
        def _int(key: str, default: int) -> int:
            try:
                return max(1, int(values.get(key) or default))
            except (TypeError, ValueError):
                return default

        return (
            _int("queue.global_concurrency", self.settings.global_concurrency),
            _int("queue.per_project_concurrency", self.settings.per_project_concurrency),
            _int(
                "queue.per_provider_concurrency",
                self.settings.default_provider_concurrency,
            ),
        )

    async def _is_paused(self) -> bool:
        factory = get_session_factory()
        async with factory() as session:
            queue = QueueService(session, settings=self.settings)
            return await queue.is_queue_paused()

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self) -> int:
        """Spawn runner tasks for as many queued jobs as limits allow."""

        if self._stop.is_set() or await self._is_paused():
            return 0
        global_limit, per_project, per_provider = await self._limits()
        capacity = global_limit - self.runner.active_count
        if capacity <= 0:
            return 0

        factory = get_session_factory()
        async with factory() as session:
            queue = QueueService(session, settings=self.settings)
            candidates = await queue.next_runnable(limit=50)

        spawned = 0
        for job in candidates:
            if capacity <= 0:
                break
            if job.id in self._tasks:
                continue
            if self.runner.active_for_project(job.project_id) >= per_project:
                continue
            provider_key = (
                (job.configuration_snapshot_json or {}).get("provider") or {}
            ).get("id") or "none"
            if self.runner.active_for_provider(provider_key) >= per_provider:
                continue
            task = asyncio.create_task(self._run_guarded(job.id))
            self._tasks[job.id] = task
            task.add_done_callback(lambda _t, jid=job.id: self._tasks.pop(jid, None))
            capacity -= 1
            spawned += 1
        return spawned

    async def _run_guarded(self, job_id: str) -> None:
        try:
            await self.runner.run_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("job_runner_unhandled_error", job_id=job_id)
        finally:
            self._wake.set()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def notify(self) -> None:
        """Wake the dispatch loop (called after enqueue/cancel/completion)."""

        self._wake.set()

    async def run_once(self) -> int:
        """One dispatch pass (deterministic driver for tests)."""

        return await self._dispatch()

    async def drain(self) -> None:
        """Dispatch and wait until no job is active and none is dispatchable."""

        while True:
            await self._dispatch()
            if not self._tasks:
                # Nothing running; one more pass to be sure nothing appeared.
                if await self._dispatch() == 0:
                    return
            current = list(self._tasks.values())
            if current:
                await asyncio.gather(*current, return_exceptions=True)

    async def start(self) -> None:
        if self._loop_task is not None:
            return
        self._stop.clear()
        self._loop_task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._dispatch()
            except Exception:
                logger.exception("queue_dispatch_error")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._loop_task is not None:
            try:
                await asyncio.wait_for(self._loop_task, timeout=5)
            except TimeoutError:
                self._loop_task.cancel()
            self._loop_task = None
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    # ------------------------------------------------------------------
    # cancellation bridge (QueueService -> runner)
    # ------------------------------------------------------------------

    async def cancel_handler(self, job_id: str) -> None:
        await self.runner.request_cancel(job_id)

    @property
    def active_job_ids(self) -> list[str]:
        return list(self._tasks)


_current: QueueWorker | None = None


def set_current_worker(worker: QueueWorker | None) -> None:
    global _current
    _current = worker


def get_current_worker() -> QueueWorker | None:
    return _current

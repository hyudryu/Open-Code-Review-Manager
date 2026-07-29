"""QueueWorker: asyncio dispatcher enforcing concurrency limits (SPEC §12).

One long-lived task scans for runnable queued jobs and spawns
:meth:`JobRunner.run_job` tasks while respecting the global worker count,
per-project limits, and per-provider limits. ``drain``/``run_once`` are
public so tests can drive the worker deterministically.

A second long-lived task (the *reaper*) periodically scans for jobs stuck
in ``running`` or ``preparing`` whose runner task has been lost (e.g. after
a hard server kill). It checks whether the OCR subprocess PID is still
alive and enforces a maximum runtime, transitioning stale jobs to
``failed`` so they don't block the queue forever.
"""

from __future__ import annotations

import asyncio
import time
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


def _pid_alive(pid: int | None) -> bool:
    """Check whether a process PID is still running (cross-platform)."""

    if pid is None:
        return False
    import os
    import signal

    try:
        os.kill(pid, 0)  # signal 0 = existence check, no actual signal sent
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it — treat as alive
    except OSError:
        return False
    return True


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
        self._reaper_task: asyncio.Task | None = None

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

        # Check both dispatched tasks AND the database for active jobs.
        # self._tasks tracks asyncio tasks we spawned, but a job can be
        # active in the DB (preparing/running) even if its task briefly
        # left self._tasks (e.g. quick failure + retry). The DB is the
        # source of truth for what's actually consuming capacity.
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(models.ReviewJob).where(
                    models.ReviewJob.status.in_(["preparing", "running", "cancelling"])
                )
            )
            db_active = list(result.scalars())
            db_active_ids = {j.id for j in db_active}
            db_active_projects = {j.project_id for j in db_active}

            # Capacity = global limit - max(tracked tasks, DB active jobs)
            active_count = max(len(self._tasks), len(db_active_ids))
            capacity = global_limit - active_count
            if capacity <= 0:
                return 0

            queue = QueueService(session, settings=self.settings)
            candidates = await queue.next_runnable(limit=50)

        spawned = 0
        for job in candidates:
            if capacity <= 0:
                break
            if job.id in self._tasks or job.id in db_active_ids:
                continue
            # Check both runner tracking and DB for per-project limits.
            project_active = self.runner.active_for_project(job.project_id)
            db_project_count = sum(1 for j in db_active if j.project_id == job.project_id)
            if max(project_active, db_project_count) >= per_project:
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
    # stale-job reaper (watchdog)
    # ------------------------------------------------------------------

    async def reap_once(self) -> int:
        """Scan for jobs stuck in running/preparing whose runner task is gone.

        Checks two conditions for each stale job:
        1. Process PID is set but no longer alive → ``process_died``
           (only for jobs in 'running' state, and only after a grace period
           to avoid killing jobs whose process is just starting)
        2. Runtime exceeded ``ocr_process_timeout_seconds`` → ``process_timeout``

        Only jobs NOT in ``self._tasks`` are considered — actively-managed
        jobs are handled by the runner's own timeout logic.

        Returns the number of jobs transitioned to ``failed``.
        """

        from datetime import datetime, timezone

        factory = get_session_factory()
        reaped = 0
        grace_period = 120.0  # 2-minute grace before checking PID liveness
        async with factory() as session:
            result = await session.execute(
                select(models.ReviewJob).where(
                    models.ReviewJob.status.in_(["running", "preparing"])
                )
            )
            stale_jobs = list(result.scalars())

            for job in stale_jobs:
                # Skip jobs that still have an active runner task.
                if job.id in self._tasks:
                    continue

                pid = job.process_id
                started = job.started_at
                timeout = self.settings.ocr_process_timeout_seconds

                # Condition 1: running job with a dead PID.
                # Only check 'running' jobs (not 'preparing' — those may not
                # have a PID yet). Require a grace period since start to avoid
                # killing jobs whose subprocess is still spinning up.
                if (
                    job.status == "running"
                    and pid is not None
                    and started
                ):
                    started_dt = started if isinstance(started, datetime) else datetime.fromisoformat(str(started))
                    if started_dt.tzinfo is None:
                        started_dt = started_dt.replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()
                    if elapsed > grace_period and not _pid_alive(pid):
                        logger.warning(
                            "reaper_process_died",
                            job_id=job.id,
                            pid=pid,
                            elapsed=elapsed,
                        )
                        queue = QueueService(session, settings=self.settings)
                        try:
                            await queue.transition(
                                job,
                                "failed",
                                message=f"OCR process exited unexpectedly (PID {pid} no longer exists after {elapsed:.0f}s).",
                                error_code="process_died",
                            )
                            job.process_id = None
                            reaped += 1
                        except Exception:
                            logger.exception("reaper_transition_failed", job_id=job.id)
                        continue

                # Condition 2: runtime exceeded the process timeout.
                if started:
                    started_dt = started if isinstance(started, datetime) else datetime.fromisoformat(str(started))
                    if started_dt.tzinfo is None:
                        started_dt = started_dt.replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - started_dt).total_seconds()
                    if elapsed > timeout:
                        logger.warning(
                            "reaper_process_timeout",
                            job_id=job.id,
                            elapsed=elapsed,
                            timeout=timeout,
                        )
                        queue = QueueService(session, settings=self.settings)
                        try:
                            await queue.transition(
                                job,
                                "failed",
                                message=f"OCR process exceeded the {timeout:.0f}s timeout (ran for {elapsed:.0f}s).",
                                error_code="process_timeout",
                            )
                            job.process_id = None
                            reaped += 1
                        except Exception:
                            logger.exception("reaper_transition_failed", job_id=job.id)

            if reaped:
                await session.commit()
        return reaped

    async def _reaper_loop(self) -> None:
        """Periodically scan for and clean up stale running/preparing jobs."""

        interval = self.settings.reaper_interval_seconds
        while not self._stop.is_set():
            try:
                count = await self.reap_once()
                if count:
                    logger.info("reaper_cleaned_stale_jobs", count=count)
                    self._wake.set()  # wake dispatcher — capacity may have freed up
            except Exception:
                logger.exception("reaper_loop_error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                pass

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
        self._reaper_task = asyncio.create_task(self._reaper_loop())

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
        if self._reaper_task is not None:
            try:
                await asyncio.wait_for(self._reaper_task, timeout=5)
            except TimeoutError:
                self._reaper_task.cancel()
            self._reaper_task = None
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

"""QueueService: durable queue state machine + ordering (SPEC §12-13, §38.6).

Every status change goes through :meth:`QueueService.transition`, which
rejects invalid transitions and persists a ``job.status`` JobEvent on every
accepted one. Ordering is ``priority DESC, manual_position ASC, queued_at
ASC``; manual reordering rewrites positions transactionally.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select, update

from app.core.logging import get_logger
from app.db import models
from app.queue.bus import get_event_bus
from app.services.deps import ServiceBase
from app.services.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationFailedError,
)

logger = get_logger(__name__)

#: SPEC §13 allowed transitions. Retry/resume create NEW jobs, so terminal
#: states never transition back within the same row.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"preparing", "cancelled"}),
    "preparing": frozenset({"running", "failed", "cancelled", "cancelling", "interrupted"}),
    "running": frozenset(
        {"completed", "completed_with_warnings", "failed", "cancelling", "interrupted"}
    ),
    "cancelling": frozenset({"cancelled", "failed", "interrupted"}),
    "completed": frozenset(),
    "completed_with_warnings": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "interrupted": frozenset(),
}

TERMINAL_STATUSES = frozenset(
    {"completed", "completed_with_warnings", "failed", "cancelled", "interrupted"}
)
ACTIVE_STATUSES = frozenset({"queued", "preparing", "running", "cancelling"})

#: job.status -> webhook event name (None = no webhook for this status).
WEBHOOK_EVENT_BY_STATUS: dict[str, str | None] = {
    "queued": "review.queued",
    "preparing": "review.started",
    "running": None,
    "cancelling": None,
    "completed": "review.completed",
    "completed_with_warnings": "review.completed_with_warnings",
    "failed": "review.failed",
    "cancelled": "review.cancelled",
    "interrupted": None,
}

QUEUE_PAUSED_SETTING = "queue.paused"

#: Async callback invoked (same session) when a transition maps to a webhook
#: event; signature: (session, job, event_type) -> None.
WebhookDispatcher = Callable[[Any, models.ReviewJob, str], Awaitable[None]]
#: Async callback asking the runner to cancel an active job's process.
CancelHandler = Callable[[str], Awaitable[None]]


class QueueService(ServiceBase):
    def __init__(self, session, **kwargs: Any) -> None:
        super().__init__(session, **kwargs)
        self.webhook_dispatcher: WebhookDispatcher | None = None
        self.cancel_handler: CancelHandler | None = None

    # ------------------------------------------------------------------
    # state machine
    # ------------------------------------------------------------------

    async def transition(
        self,
        job: models.ReviewJob,
        target: str,
        *,
        message: str | None = None,
        error_code: str | None = None,
        payload: dict[str, Any] | None = None,
        event_type: str = "job.status",
    ) -> models.JobEvent:
        """Move ``job`` to ``target``; reject invalid transitions (SPEC §13)."""

        allowed = ALLOWED_TRANSITIONS.get(job.status, frozenset())
        if target not in allowed:
            raise InvalidTransitionError(job.id, job.status, target)

        now = datetime.now(timezone.utc)
        previous = job.status
        job.status = target
        if message is not None:
            job.status_message = message
        if target == "running" and job.started_at is None:
            job.started_at = now
        if target == "cancelling" and job.cancel_requested_at is None:
            job.cancel_requested_at = now
        if target in TERMINAL_STATUSES:
            job.completed_at = now
            job.process_id = None
        if error_code is not None and target in TERMINAL_STATUSES:
            job.error_code = error_code

        event_payload: dict[str, Any] = {
            "from": previous,
            "to": target,
            "message": message,
            **(payload or {}),
        }
        event = models.JobEvent(
            job_id=job.id, event_type=event_type, payload_json=event_payload
        )
        self.session.add(event)
        await self.session.flush()

        get_event_bus().publish(
            job.id,
            {"id": event.id, "type": event_type, "payload": event_payload},
        )

        webhook_event = WEBHOOK_EVENT_BY_STATUS.get(target)
        if webhook_event and self.webhook_dispatcher is not None:
            await self.webhook_dispatcher(self.session, job, webhook_event)

        logger.info(
            "job_transition", job_id=job.id, previous=previous, target=target
        )
        return event

    async def emit_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        persist: bool = True,
    ) -> models.JobEvent | None:
        """Persist + publish a non-status job event (SPEC §14)."""

        event: models.JobEvent | None = None
        event_id: int | None = None
        if persist:
            event = models.JobEvent(
                job_id=job_id, event_type=event_type, payload_json=payload
            )
            self.session.add(event)
            await self.session.flush()
            event_id = event.id
        get_event_bus().publish(
            job_id, {"id": event_id, "type": event_type, "payload": payload or {}}
        )
        return event

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    async def get_job(self, job_id: str) -> models.ReviewJob:
        job = await self.session.get(models.ReviewJob, job_id)
        if job is None:
            raise NotFoundError("Review job", job_id)
        return job

    @staticmethod
    def _queue_order(stmt):
        return stmt.order_by(
            models.ReviewJob.priority.desc(),
            models.ReviewJob.manual_position.asc().nulls_last(),
            models.ReviewJob.queued_at.asc(),
        )

    async def list_queue(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        active_only: bool = False,
    ) -> list[models.ReviewJob]:
        stmt = select(models.ReviewJob)
        if status:
            stmt = stmt.where(models.ReviewJob.status == status)
        if project_id:
            stmt = stmt.where(models.ReviewJob.project_id == project_id)
        if source:
            stmt = stmt.where(models.ReviewJob.source == source)
        if active_only:
            stmt = stmt.where(models.ReviewJob.status.in_(sorted(ACTIVE_STATUSES)))
        stmt = self._queue_order(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def next_runnable(self, *, limit: int) -> list[models.ReviewJob]:
        stmt = self._queue_order(
            select(models.ReviewJob).where(
                models.ReviewJob.status == "queued",
                models.ReviewJob.paused.is_(False),
            )
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def queue_position(self, job: models.ReviewJob) -> int | None:
        """1-based position among waiting jobs (None when not queued)."""

        if job.status != "queued":
            return None
        queued = await self.next_runnable(limit=10_000)
        for index, candidate in enumerate(queued, start=1):
            if candidate.id == job.id:
                return index
        return None

    # ------------------------------------------------------------------
    # enqueue + ordering
    # ------------------------------------------------------------------

    async def enqueue(self, job: models.ReviewJob) -> models.ReviewJob:
        """Assign a monotonically increasing manual position (FIFO tie-break)."""

        if job.manual_position is None:
            result = await self.session.execute(
                select(func.max(models.ReviewJob.manual_position))
            )
            job.manual_position = (result.scalar() or 0) + 1
        result = await self.session.execute(
            select(func.count(models.ReviewJob.id)).where(
                models.ReviewJob.status == "queued", models.ReviewJob.id != job.id
            )
        )
        job.queue_position = result.scalar_one() + 1
        await self.session.flush()
        return job

    async def _queued_in_priority(self, job: models.ReviewJob) -> list[models.ReviewJob]:
        stmt = self._queue_order(
            select(models.ReviewJob).where(
                models.ReviewJob.status == "queued",
                models.ReviewJob.priority == job.priority,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def move(self, job_id: str, action: str) -> models.ReviewJob:
        """Manual reorder: ``top`` | ``up`` | ``down`` (transactional).

        Reassigns manual_position for the whole same-priority queued group so
        the stored order exactly matches the requested one.
        """

        if action not in {"top", "up", "down"}:
            raise ValidationFailedError(
                f"Unknown move action '{action}'.",
                detail="Supported actions: top, up, down.",
            )
        job = await self.get_job(job_id)
        if job.status != "queued":
            raise ConflictError(
                "Only queued jobs can be reordered.",
                detail=f"Job is currently '{job.status}'.",
                next_action="Wait for the job to finish or cancel it.",
            )
        group = await self._queued_in_priority(job)
        ids = [j.id for j in group]
        try:
            index = ids.index(job.id)
        except ValueError:  # pragma: no cover - defensive
            return job

        if action == "top":
            group.insert(0, group.pop(index))
        elif action == "up" and index > 0:
            group[index - 1], group[index] = group[index], group[index - 1]
        elif action == "down" and index < len(group) - 1:
            group[index + 1], group[index] = group[index], group[index + 1]
        else:
            return job  # already at the boundary — no-op

        for position, member in enumerate(group, start=1):
            member.manual_position = position
        await self.session.flush()
        job.queue_position = await self.queue_position(job)
        await self.session.flush()
        return job

    async def reorder(self, ordered_job_ids: list[str]) -> list[models.ReviewJob]:
        """Bulk transactional reorder of queued jobs (SPEC §12)."""

        queued = await self.list_queue(status="queued")
        queued_by_id = {j.id: j for j in queued}
        unknown = [jid for jid in ordered_job_ids if jid not in queued_by_id]
        if unknown:
            raise ValidationFailedError(
                "Reorder list contains jobs that are not queued.",
                detail=f"Unknown or non-queued job ids: {unknown}",
            )
        by_priority: dict[int, list[str]] = {}
        for job in queued:
            by_priority.setdefault(job.priority, [])
        requested = {jid: i for i, jid in enumerate(ordered_job_ids)}
        for priority, members in by_priority.items():
            ordered = sorted(
                members,
                key=lambda j: (
                    requested.get(j.id, len(requested)),
                    j.manual_position if j.manual_position is not None else 1 << 30,
                    j.queued_at,
                ),
            )
            for position, member in enumerate(ordered, start=1):
                member.manual_position = position
        await self.session.flush()
        return await self.list_queue(status="queued")

    # ------------------------------------------------------------------
    # pause / resume
    # ------------------------------------------------------------------

    async def pause_job(self, job_id: str) -> models.ReviewJob:
        job = await self.get_job(job_id)
        if job.status != "queued":
            raise ConflictError(
                "Only queued jobs can be paused.",
                detail=f"Job is currently '{job.status}'.",
            )
        job.paused = True
        await self.session.flush()
        return job

    async def resume_job(self, job_id: str) -> models.ReviewJob:
        job = await self.get_job(job_id)
        if job.status != "queued":
            raise ConflictError(
                "Only queued jobs can be resumed.",
                detail=f"Job is currently '{job.status}'.",
            )
        job.paused = False
        await self.session.flush()
        return job

    async def is_queue_paused(self) -> bool:
        setting = await self.session.get(models.AppSetting, QUEUE_PAUSED_SETTING)
        return bool(setting and setting.value_json)

    async def set_queue_paused(self, paused: bool) -> None:
        setting = await self.session.get(models.AppSetting, QUEUE_PAUSED_SETTING)
        if setting is None:
            setting = models.AppSetting(key=QUEUE_PAUSED_SETTING, value_json=paused)
            self.session.add(setting)
        else:
            setting.value_json = paused
        await self.session.flush()

    # ------------------------------------------------------------------
    # cancel + clear
    # ------------------------------------------------------------------

    async def cancel(self, job_id: str) -> models.ReviewJob:
        """Cancel a queued or active job (SPEC §12 Cancellation)."""

        job = await self.get_job(job_id)
        if job.status == "queued":
            await self.transition(job, "cancelled", message="Cancelled while queued.")
            return job
        if job.status in {"preparing", "running"}:
            await self.transition(job, "cancelling", message="Cancellation requested.")
            if self.cancel_handler is not None:
                await self.cancel_handler(job.id)
            return job
        if job.status == "cancelling":
            return job  # idempotent
        raise ConflictError(
            "This job can no longer be cancelled.",
            detail=f"Job is already '{job.status}'.",
        )

    async def clear_completed(self) -> int:
        """Remove terminal jobs from the queue. Returns the deleted count."""

        result = await self.session.execute(
            select(models.ReviewJob).where(
                models.ReviewJob.status.in_(sorted(TERMINAL_STATUSES))
            )
        )
        jobs = list(result.scalars())
        for job in jobs:
            await self.session.delete(job)
        await self.session.flush()
        return len(jobs)

    async def recount_positions(self) -> None:
        """Rewrite queue_position for queued jobs (display helper)."""

        queued = await self.list_queue(status="queued")
        await self.session.execute(
            update(models.ReviewJob)
            .where(models.ReviewJob.status != "queued")
            .values(queue_position=None)
        )
        for position, job in enumerate(queued, start=1):
            job.queue_position = position
        await self.session.flush()

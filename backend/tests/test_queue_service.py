"""QueueService: ordering, state machine, transactional reorder (SPEC §12-13)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import models
from app.db.session import session_scope
from app.queue.service import QueueService
from app.services.errors import ConflictError, InvalidTransitionError


async def _make_job(session, project_id: str, *, priority: int = 50, status: str = "queued") -> models.ReviewJob:
    job = models.ReviewJob(
        project_id=project_id,
        mode="commit",
        commit_ref="HEAD",
        priority=priority,
        status=status,
        configuration_snapshot_json={"provider": None, "model": None},
        generated_command_json={"argv": ["ocr", "review"]},
    )
    session.add(job)
    await session.flush()
    queue = QueueService(session)
    await queue.enqueue(job)
    return job


async def test_state_machine_rejects_invalid_transitions(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        with pytest.raises(InvalidTransitionError):
            await queue.transition(job, "completed")  # queued -/-> completed
        with pytest.raises(InvalidTransitionError):
            await queue.transition(job, "running")  # queued -/-> running


async def test_state_machine_valid_path_emits_events(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        await queue.transition(job, "preparing")
        await queue.transition(job, "running")
        await queue.transition(job, "completed")
        assert job.started_at is not None
        assert job.completed_at is not None
    async with session_scope() as session:
        result = await session.execute(
            select(models.JobEvent).where(models.JobEvent.job_id == job.id)
        )
        events = list(result.scalars())
        assert len(events) == 3
        assert all(e.event_type == "job.status" for e in events)
        assert events[0].payload_json["to"] == "preparing"
        assert events[-1].payload_json == {
            "from": "running",
            "to": "completed",
            "message": None,
        }


async def test_terminal_states_cannot_transition(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        await queue.transition(job, "cancelled")
        with pytest.raises(InvalidTransitionError):
            await queue.transition(job, "queued")


async def test_queue_ordering_priority_then_manual_position(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        low = await _make_job(session, project_id, priority=10)
        high = await _make_job(session, project_id, priority=90)
        mid = await _make_job(session, project_id, priority=50)
        queue = QueueService(session)
        ordered = await queue.list_queue(status="queued")
        assert [j.id for j in ordered] == [high.id, mid.id, low.id]


async def test_move_top_up_down_is_transactional(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        a = await _make_job(session, project_id)
        b = await _make_job(session, project_id)
        c = await _make_job(session, project_id)
        queue = QueueService(session)

        await queue.move(c.id, "top")
        ordered = await queue.list_queue(status="queued")
        assert [j.id for j in ordered] == [c.id, a.id, b.id]

        await queue.move(b.id, "up")
        ordered = await queue.list_queue(status="queued")
        assert [j.id for j in ordered] == [c.id, b.id, a.id]

        await queue.move(c.id, "down")
        ordered = await queue.list_queue(status="queued")
        assert [j.id for j in ordered] == [b.id, c.id, a.id]

        # Boundaries are no-ops.
        await queue.move(b.id, "up")
        ordered = await queue.list_queue(status="queued")
        assert [j.id for j in ordered] == [b.id, c.id, a.id]


async def test_move_rejects_non_queued(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        await queue.transition(job, "preparing")
        with pytest.raises(ConflictError):
            await queue.move(job.id, "top")


async def test_pause_job_and_queue(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)

        await queue.pause_job(job.id)
        assert job.paused is True
        runnable = await queue.next_runnable(limit=10)
        assert runnable == []

        await queue.resume_job(job.id)
        runnable = await queue.next_runnable(limit=10)
        assert [j.id for j in runnable] == [job.id]

        assert await queue.is_queue_paused() is False
        await queue.set_queue_paused(True)
        assert await queue.is_queue_paused() is True


async def test_cancel_queued_job(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        await queue.cancel(job.id)
        assert job.status == "cancelled"
        assert job.completed_at is not None


async def test_clear_completed(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        job = await _make_job(session, project_id)
        queue = QueueService(session)
        await queue.transition(job, "cancelled")
        removed = await queue.clear_completed()
        assert removed == 1
        assert await session.get(models.ReviewJob, job.id) is None


async def test_queue_position(project) -> None:
    project_id, _ = project
    async with session_scope() as session:
        a = await _make_job(session, project_id)
        b = await _make_job(session, project_id)
        queue = QueueService(session)
        assert await queue.queue_position(a) == 1
        assert await queue.queue_position(b) == 2
        await queue.transition(a, "preparing")
        assert await queue.queue_position(a) is None
        assert await queue.queue_position(b) == 1

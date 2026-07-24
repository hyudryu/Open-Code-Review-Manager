"""Queue routes (SPEC §19 Queue)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_db, job_service
from app.queue.service import QueueService
from app.schemas.jobs import JobOut, QueueReorderRequest, QueueStateOut
from app.services.jobs import JobService

router = APIRouter(prefix="/queue", tags=["queue"])


def _queue(db, service: JobService) -> QueueService:
    return service._queue()


@router.get("", response_model=QueueStateOut)
async def queue_state(service: JobService = Depends(job_service)):
    queue = service._queue()
    jobs = await queue.list_queue(active_only=True)
    return QueueStateOut(
        paused=await queue.is_queue_paused(),
        jobs=[JobOut.model_validate(j) for j in jobs],
    )


@router.post("/pause", response_model=QueueStateOut)
async def pause_queue(service: JobService = Depends(job_service)):
    queue = service._queue()
    await queue.set_queue_paused(True)
    jobs = await queue.list_queue(active_only=True)
    return QueueStateOut(paused=True, jobs=[JobOut.model_validate(j) for j in jobs])


@router.post("/resume", response_model=QueueStateOut)
async def resume_queue(service: JobService = Depends(job_service)):
    queue = service._queue()
    await queue.set_queue_paused(False)
    from app.queue.worker import get_current_worker

    worker = get_current_worker()
    if worker is not None:
        worker.notify()
    jobs = await queue.list_queue(active_only=True)
    return QueueStateOut(paused=False, jobs=[JobOut.model_validate(j) for j in jobs])


@router.post("/reorder", response_model=list[JobOut])
async def reorder_queue(
    payload: QueueReorderRequest, service: JobService = Depends(job_service)
):
    queue = service._queue()
    jobs = await queue.reorder(payload.job_ids)
    return [JobOut.model_validate(j) for j in jobs]


@router.post("/clear-completed")
async def clear_completed(service: JobService = Depends(job_service)):
    queue = service._queue()
    removed = await queue.clear_completed()
    return {"removed": removed}

"""Job routes incl. SSE event stream (SPEC §14, §19 Jobs)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import finding_service, get_db, job_service
from app.db import models
from app.db.session import get_session_factory
from app.queue.bus import get_event_bus
from app.queue.service import TERMINAL_STATUSES
from app.schemas.common import Page
from app.schemas.jobs import (
    FindingOut,
    FindingUpdate,
    JobCreate,
    JobMoveRequest,
    JobOut,
    JobPreviewOut,
    JobPreviewRequest,
    JobRetryRequest,
    JobUpdate,
    LogOut,
    SessionOut,
)
from app.services.errors import NotFoundError
from app.services.findings import FindingService
from app.services.jobs import EXPORT_FORMATS, JobService
from app.services.waits import wait_for_job_terminal

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _findings_count(db, job_id: str) -> int:
    result = await db.execute(
        select(func.count(models.Finding.id)).where(models.Finding.job_id == job_id)
    )
    return int(result.scalar_one())


async def _with_counts(service: JobService, jobs: list[models.ReviewJob]) -> list[JobOut]:
    out: list[JobOut] = []
    for job in jobs:
        data = JobOut.model_validate(job)
        data.findings_count = await _findings_count(service.session, job.id)
        out.append(data)
    return out


@router.get("", response_model=Page[JobOut])
async def list_jobs(
    status: str | None = None,
    project_id: str | None = None,
    source: str | None = None,
    provider_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: JobService = Depends(job_service),
):
    jobs, total = await service.list(
        status=status,
        project_id=project_id,
        source=source,
        provider_id=provider_id,
        limit=limit,
        offset=offset,
    )
    return Page[JobOut](
        items=await _with_counts(service, jobs), total=total, limit=limit, offset=offset
    )


@router.post("", response_model=JobOut, status_code=201)
async def create_job(
    payload: JobCreate, service: JobService = Depends(job_service)
):
    job = await service.create(**payload.model_dump(), source="web")
    return JobOut.model_validate(job)


@router.post("/preview", response_model=JobPreviewOut)
async def preview_job(
    payload: JobPreviewRequest, service: JobService = Depends(job_service)
):
    result = await service.preview(**payload.model_dump())
    return JobPreviewOut(**result.model_dump())


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    wait_for_terminal: bool = Query(default=False),
    timeout_seconds: int = Query(default=300, ge=1, le=600),
    service: JobService = Depends(job_service),
):
    """Job detail. With ``wait_for_terminal=true`` this long-polls
    server-side until a terminal status or the timeout (SPEC §13/§14)."""

    job = await service.get(job_id)
    if wait_for_terminal and job.status not in TERMINAL_STATUSES:
        # Release the request-scoped connection while waiting; re-read after.
        await service.session.rollback()
        await wait_for_job_terminal(job_id, timeout_seconds)
        factory = get_session_factory()
        async with factory() as session:
            job = await JobService(session).get(job_id)
            data = JobOut.model_validate(job)
            data.findings_count = await _findings_count(session, job.id)
            return data
    data = JobOut.model_validate(job)
    data.findings_count = await _findings_count(service.session, job.id)
    return data


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: str,
    payload: JobUpdate,
    service: JobService = Depends(job_service),
):
    job = await service.get(job_id)
    if payload.priority is not None and job.status == "queued":
        job.priority = payload.priority
        await service.session.flush()
    return JobOut.model_validate(job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, service: JobService = Depends(job_service)):
    await service.delete(job_id)
    return Response(status_code=204)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str, service: JobService = Depends(job_service)):
    return JobOut.model_validate(await service.cancel(job_id))


@router.post("/{job_id}/retry", response_model=JobOut, status_code=201)
async def retry_job(
    job_id: str,
    payload: JobRetryRequest | None = None,
    service: JobService = Depends(job_service),
):
    fields = payload.model_dump() if payload else {}
    return JobOut.model_validate(await service.retry(job_id, **fields))


@router.post("/{job_id}/resume", response_model=JobOut, status_code=201)
async def resume_job(job_id: str, service: JobService = Depends(job_service)):
    return JobOut.model_validate(await service.resume(job_id))


@router.post("/{job_id}/duplicate", response_model=JobOut, status_code=201)
async def duplicate_job(job_id: str, service: JobService = Depends(job_service)):
    return JobOut.model_validate(await service.duplicate(job_id))


@router.post("/{job_id}/move", response_model=JobOut)
async def move_job(
    job_id: str,
    payload: JobMoveRequest,
    service: JobService = Depends(job_service),
):
    return JobOut.model_validate(await service.move(job_id, payload.action))


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(job_id: str, service: JobService = Depends(job_service)):
    queue = service._queue()
    return JobOut.model_validate(await queue.pause_job(job_id))


@router.post("/{job_id}/resume-paused", response_model=JobOut)
async def resume_paused_job(job_id: str, service: JobService = Depends(job_service)):
    queue = service._queue()
    return JobOut.model_validate(await queue.resume_job(job_id))


# --- SSE (SPEC §14) ----------------------------------------------------------


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    db=Depends(get_db),
):
    """SSE stream: persisted replay by Last-Event-ID, then live bus events."""

    job = await db.get(models.ReviewJob, job_id)
    if job is None:
        raise NotFoundError("Review job", job_id)

    last_event_id = request.headers.get("last-event-id") or request.query_params.get(
        "lastEventId"
    )
    try:
        after_id = int(last_event_id) if last_event_id else 0
    except ValueError:
        after_id = 0

    bus = get_event_bus()
    queue: asyncio.Queue = bus.subscribe(job_id)

    TERMINAL_EVENT_TYPES = {"job.completed", "job.failed", "job.cancelled"}
    TERMINAL_STATUSES = {
        "completed", "completed_with_warnings", "failed", "cancelled", "interrupted"
    }

    def _is_terminal(event_type: str | None, payload: dict | None) -> bool:
        if event_type in TERMINAL_EVENT_TYPES:
            return True
        if event_type == "job.status" and payload:
            return payload.get("to") in TERMINAL_STATUSES
        return False

    async def stream():
        try:
            # 1. Replay persisted events the client has not seen yet.
            saw_terminal = False
            factory = get_session_factory()
            async with factory() as session:
                stmt = (
                    select(models.JobEvent)
                    .where(
                        models.JobEvent.job_id == job_id,
                        models.JobEvent.id > after_id,
                    )
                    .order_by(models.JobEvent.id)
                    .limit(1000)
                )
                result = await session.execute(stmt)
                for event in result.scalars():
                    payload = event.payload_json or {}
                    saw_terminal = saw_terminal or _is_terminal(
                        event.event_type, payload
                    )
                    yield {
                        "id": str(event.id),
                        "event": event.event_type,
                        "data": json.dumps(payload, ensure_ascii=False),
                    }
                current_status = (
                    await session.get(models.ReviewJob, job_id)
                ).status
            # A finished job's stream closes after replay — reconnecting
            # clients always converge instead of holding a dead connection.
            if saw_terminal or current_status in TERMINAL_STATUSES:
                return
            # 2. Live events from the bus with keepalive comments.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"comment": "keepalive"}
                    continue
                yield {
                    "id": str(event.get("id")) if event.get("id") else None,
                    "event": event.get("type", "message"),
                    "data": json.dumps(event.get("payload") or {}, ensure_ascii=False),
                }
                if _is_terminal(event.get("type"), event.get("payload")):
                    return
        finally:
            bus.unsubscribe(queue, job_id)

    return EventSourceResponse(stream())


# --- job sub-resources --------------------------------------------------------


@router.get("/{job_id}/events/history", response_model=list[dict[str, Any]])
async def job_event_history(
    job_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
):
    job = await db.get(models.ReviewJob, job_id)
    if job is None:
        raise NotFoundError("Review job", job_id)
    stmt = (
        select(models.JobEvent)
        .where(models.JobEvent.job_id == job_id)
        .order_by(models.JobEvent.id)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "payload": e.payload_json,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars()
    ]


@router.get("/{job_id}/findings", response_model=Page[FindingOut])
async def list_findings(
    job_id: str,
    user_state: str | None = None,
    path: str | None = None,
    include_reasoning: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: FindingService = Depends(finding_service),
):
    findings, total = await service.list_for_job(
        job_id, user_state=user_state, path=path, limit=limit, offset=offset
    )
    items = [FindingOut.model_validate(f) for f in findings]
    if not include_reasoning:
        # Reasoning is opt-in only (SPEC §38.15).
        for item in items:
            item.thinking = None
    return Page[FindingOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}/findings/{finding_id}", response_model=FindingOut)
async def get_finding(
    job_id: str,
    finding_id: str,
    include_reasoning: bool = Query(default=False),
    service: FindingService = Depends(finding_service),
):
    finding = await service.get(finding_id)
    if finding.job_id != job_id:
        raise NotFoundError("Finding", finding_id)
    data = FindingOut.model_validate(finding)
    if not include_reasoning:
        data.thinking = None
    return data


@router.patch("/{job_id}/findings/{finding_id}", response_model=FindingOut)
async def update_finding(
    job_id: str,
    finding_id: str,
    payload: FindingUpdate,
    service: FindingService = Depends(finding_service),
):
    finding = await service.get(finding_id)
    if finding.job_id != job_id:
        raise NotFoundError("Finding", finding_id)
    updated = await service.update(
        finding_id, **payload.model_dump(exclude_unset=True)
    )
    data = FindingOut.model_validate(updated)
    data.thinking = None  # mutations never leak reasoning (SPEC §38.15)
    return data


@router.get("/{job_id}/warnings", response_model=list[dict[str, Any]])
async def list_warnings(job_id: str, service: JobService = Depends(job_service)):
    job = await service.get(job_id)
    return job.warnings_json or []


@router.get("/{job_id}/logs", response_model=LogOut)
async def job_logs(
    job_id: str,
    stream: str = Query(default="stdout", pattern="^(stdout|stderr)$"),
    tail_bytes: int = Query(default=64_000, ge=1, le=1_000_000),
    service: JobService = Depends(job_service),
):
    return await service.read_log(job_id, stream, tail_bytes=tail_bytes)


@router.get("/{job_id}/session", response_model=SessionOut)
async def job_session(
    job_id: str,
    q: str | None = Query(default=None, max_length=500),
    task_type: str | None = Query(default=None, max_length=100),
    file: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: JobService = Depends(job_service),
):
    return await service.read_session(
        job_id, limit=limit, offset=offset, q=q, task_type=task_type, file=file
    )


@router.get("/{job_id}/export")
async def export_job(
    job_id: str,
    format: str = Query(default="md"),
    include_reasoning: bool = False,
    service: JobService = Depends(job_service),
):
    content, media_type, filename = await service.export(
        job_id, format, include_reasoning=include_reasoning
    )
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

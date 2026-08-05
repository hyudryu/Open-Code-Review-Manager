"""Server-side job ETA estimation: progress + remaining time + poll interval.

Session-scoped helpers live in :class:`EtaService`; the math itself is in the
pure, DB-free helpers below so it can be unit-tested directly. The MCP job
tools (``ocr_get_job`` / ``ocr_get_job_results``) and the REST job-detail
endpoint attach the produced ``{progress, eta_seconds, eta,
poll_interval_seconds}`` dict to their responses so an agent knows how long to
wait before polling again.

Estimates are derived only from data already in the DB — no extra persistence
and no changes to the OCR process:

- Running jobs blend their own observed pace (``elapsed / completed_files``)
  with a historical per-file average learned from recent completed jobs, so
  the estimate self-corrects as files complete.
- Queued jobs extrapolate from ``active-running-remaining + (position-1) *
  avg_runtime + avg_runtime`` using recent completed jobs.
- Terminal jobs report 0 and ask the caller to stop polling.

Anything we cannot time (a running job with no inventory yet, or a queued job
with no server history) returns ``eta_seconds=None`` with a conservative
``poll_interval_seconds`` so the agent still paces itself.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db import models
from app.queue.service import TERMINAL_STATUSES
from app.services.deps import ServiceBase

#: How much the historical per-file average is trusted as pseudo-observations
#: before the job's own pace has been seen (fewer completed files → the
#: historical average dominates; more completions → the job's own pace wins).
HISTORICAL_PRIOR_WEIGHT = 3

#: Suggested poll-interval bounds for jobs we can time (seconds).
_MIN_POLL_SECONDS = 5
_MAX_POLL_SECONDS = 30
#: Fallback interval when the remaining time is unknown (seconds).
_RUNNING_UNKNOWN_POLL_SECONDS = 5
_QUEUED_UNKNOWN_POLL_SECONDS = 10

#: How many recent completed jobs inform the historical timing averages.
_HISTORY_LIMIT = 30


def progress_percent(
    completed_files: int, total_files: int | None
) -> float | None:
    """Completion percentage (0–100, one decimal) or ``None`` if unknown."""

    if not total_files or total_files <= 0:
        return None
    if completed_files <= 0:
        return 0.0
    return min(100.0, round(completed_files / total_files * 100.0, 1))


def blend_pace(
    observed_per_file: float,
    historical_per_file: float | None,
    completed_files: int,
) -> float:
    """Blend a job's own observed pace with the historical per-file average.

    The historical average counts as ``HISTORICAL_PRIOR_WEIGHT`` pseudo-
    observations; the observed pace counts one-for-one per completion, so the
    blended estimate converges to the job's true pace as files complete.
    """

    if historical_per_file is None or historical_per_file <= 0:
        return observed_per_file
    if completed_files <= 0:
        return historical_per_file
    return (
        historical_per_file * HISTORICAL_PRIOR_WEIGHT
        + observed_per_file * completed_files
    ) / (HISTORICAL_PRIOR_WEIGHT + completed_files)


def running_eta_seconds(
    *,
    total_files: int | None,
    completed_files: int,
    elapsed_seconds: float,
    historical_per_file: float | None = None,
) -> float | None:
    """Estimated seconds remaining for a running job (``None`` = unknown).

    Requires a known inventory. A job with at least one completed file blends
    its own observed pace with the historical average; a job that has not
    completed any file yet falls back to the historical per-file average so
    the estimate is stable from the start (mirroring the frontend). Returns 0
    once every file has completed.
    """

    if total_files is None or total_files <= 0:
        return None
    remaining = total_files - completed_files
    if remaining <= 0:
        return 0.0
    if completed_files <= 0 or elapsed_seconds <= 0:
        # No observed pace yet — fall back to the historical-only estimate
        # (matches estimateActiveJobETA on the frontend). Unknown when there
        # is no history to lean on either.
        if historical_per_file is not None and historical_per_file > 0:
            return remaining * historical_per_file
        return None
    observed = elapsed_seconds / completed_files
    blended = blend_pace(observed, historical_per_file, completed_files)
    return remaining * blended


def format_eta(eta_seconds: float | None) -> str | None:
    """Human-readable ETA string (``"about 3 min"``) or ``None``."""

    if eta_seconds is None:
        return None
    if eta_seconds <= 0:
        return "now"
    seconds = int(math.ceil(eta_seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"about {hours} h {minutes} min"
    if minutes:
        return f"about {minutes} min"
    return f"about {seconds} s"


def poll_interval_seconds(eta_seconds: float | None, *, running: bool) -> int:
    """Suggested seconds to wait before polling again, bucketed and bounded.

    ``eta_seconds=0`` (already done) → 0. A known ETA is polled at a bounded
    fraction of the remaining time; an unknown ETA falls back to a conservative
    status-specific interval.
    """

    if eta_seconds is not None and eta_seconds <= 0:
        return 0
    if eta_seconds is None:
        return (
            _RUNNING_UNKNOWN_POLL_SECONDS if running else _QUEUED_UNKNOWN_POLL_SECONDS
        )
    suggested = max(
        _MIN_POLL_SECONDS,
        min(_MAX_POLL_SECONDS, math.ceil(eta_seconds / 4)),
    )
    return int(suggested)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive UTC; normalize to timezone-aware UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _elapsed_seconds(job: models.ReviewJob, now: datetime | None = None) -> float:
    """Seconds since the job started (0 when it hasn't started yet)."""

    if job.started_at is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return (now - _as_utc(job.started_at)).total_seconds()


class EtaService(ServiceBase):
    """Computes the job-detail ETA block from DB state (progress + history)."""

    async def _read_progress(self, job_id: str) -> dict[str, Any]:
        """Reconstruct progress from persisted inventory/file_completed events."""

        stmt = (
            select(models.JobEvent)
            .where(
                models.JobEvent.job_id == job_id,
                models.JobEvent.event_type.in_(
                    ["job.inventory", "job.file_completed", "job.file_started"]
                ),
            )
            .order_by(models.JobEvent.id)
        )
        result = await self.session.execute(stmt)
        total_files: int | None = None
        # Whether ``total_files`` came from a real ``job.inventory`` event.
        # The started-files fallback below is only a live denominator for
        # percent; it must NOT be trusted as the ETA denominator, or a review
        # that never received an inventory would be estimated as a 1-file job.
        has_real_inventory = False
        completed_files = 0
        seen_completed: set[str] = set()
        # job.file_started drives the live denominator when OCR 1.8+ emits no
        # explicit inventory and reviewable-count is unknown.
        started_files = 0
        for event in result.scalars():
            payload = event.payload_json or {}
            if event.event_type == "job.inventory":
                count = payload.get("total_files")
                if isinstance(count, int) and count > 0:
                    total_files = count
                    has_real_inventory = True
            elif event.event_type == "job.file_started":
                started_files += 1
            elif event.event_type == "job.file_completed":
                path = payload.get("file")
                if path:
                    if path not in seen_completed:
                        seen_completed.add(path)
                        completed_files += 1
                else:
                    completed_files += 1
        if total_files is None and started_files:
            total_files = started_files
        return {
            "total_files": total_files,
            "completed_files": completed_files,
            "percent": progress_percent(completed_files, total_files),
            "has_real_inventory": has_real_inventory,
        }

    async def _history_stats(self) -> dict[str, Any]:
        """Per-file and per-job timing averages from recent completed jobs."""

        stmt = (
            select(models.ReviewJob)
            .where(
                models.ReviewJob.status.in_(sorted(TERMINAL_STATUSES)),
                models.ReviewJob.started_at.is_not(None),
                models.ReviewJob.completed_at.is_not(None),
            )
            .order_by(models.ReviewJob.completed_at.desc())
            .limit(_HISTORY_LIMIT)
        )
        result = await self.session.execute(stmt)
        runtimes: list[float] = []
        per_files: list[float] = []
        for job in result.scalars():
            try:
                runtime_s = (
                    _as_utc(job.completed_at) - _as_utc(job.started_at)
                ).total_seconds()
            except TypeError:  # pragma: no cover - defensive
                continue
            if runtime_s <= 0:
                continue
            runtimes.append(runtime_s)
            summary = job.result_summary_json or {}
            files = summary.get("files_reviewed") or 0
            if files and files > 0:
                per_files.append(runtime_s / files)
        return {
            "count": len(runtimes),
            "avg_runtime_s": (sum(runtimes) / len(runtimes)) if runtimes else None,
            "avg_per_file_s": (sum(per_files) / len(per_files)) if per_files else None,
        }

    async def _active_remaining_seconds(
        self, historical_per_file: float | None
    ) -> float:
        """Total remaining time of jobs currently preparing/running."""

        stmt = select(models.ReviewJob).where(
            models.ReviewJob.status.in_(["preparing", "running"])
        )
        result = await self.session.execute(stmt)
        total = 0.0
        for job in result.scalars():
            progress = await self._read_progress(job.id)
            # Only a real inventory is a trustworthy ETA denominator; a
            # started-only job (no job.inventory) stays unknown so it cannot
            # drag the queued estimate down toward ~one file of work.
            if not progress["has_real_inventory"]:
                continue
            remaining = running_eta_seconds(
                total_files=progress["total_files"],
                completed_files=progress["completed_files"],
                elapsed_seconds=_elapsed_seconds(job),
                historical_per_file=historical_per_file,
            )
            if remaining is not None and remaining > 0:
                total += remaining
        return total

    async def _queued_eta(
        self, job: models.ReviewJob
    ) -> tuple[float | None, int]:
        """ETA for a waiting job: active wait + queued-ahead + own run."""

        history = await self._history_stats()
        if history["avg_runtime_s"] is None:
            return None, _QUEUED_UNKNOWN_POLL_SECONDS
        active_remaining = await self._active_remaining_seconds(
            history["avg_per_file_s"]
        )
        position = job.queue_position or 1
        jobs_ahead = max(0, position - 1)
        eta = active_remaining + jobs_ahead * history["avg_runtime_s"] + history[
            "avg_runtime_s"
        ]
        return int(math.ceil(eta)), poll_interval_seconds(eta, running=False)

    async def describe(self, job: models.ReviewJob) -> dict[str, Any]:
        """Return the ``{progress, eta_seconds, eta, poll_interval_seconds}`` block."""

        progress = await self._read_progress(job.id)

        if job.status in TERMINAL_STATUSES:
            return {
                "progress": progress,
                "eta_seconds": 0,
                "eta": format_eta(0),
                "poll_interval_seconds": 0,
            }

        if job.status == "queued":
            eta_seconds, poll = await self._queued_eta(job)
            return {
                "progress": progress,
                "eta_seconds": eta_seconds,
                "eta": format_eta(eta_seconds),
                "poll_interval_seconds": poll,
            }

        # preparing / running / cancelling — pace from this job's own progress.
        elapsed_seconds = _elapsed_seconds(job)
        history = await self._history_stats()
        # Only a real ``job.inventory`` total is a safe ETA denominator. Without
        # one, ``total_files`` is a synthetic started-count that would make the
        # historical fallback report ~one file of ETA; keep those jobs unknown.
        eta_total_files = (
            progress["total_files"] if progress["has_real_inventory"] else None
        )
        eta_seconds = running_eta_seconds(
            total_files=eta_total_files,
            completed_files=progress["completed_files"],
            elapsed_seconds=elapsed_seconds,
            historical_per_file=history["avg_per_file_s"],
        )
        return {
            "progress": progress,
            "eta_seconds": (
                int(math.ceil(eta_seconds)) if eta_seconds is not None else None
            ),
            "eta": format_eta(eta_seconds),
            "poll_interval_seconds": poll_interval_seconds(eta_seconds, running=True),
        }
